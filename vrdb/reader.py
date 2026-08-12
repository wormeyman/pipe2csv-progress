"""Streaming reader for the SOS pipe-delimited extracts.

The files are CP1252, CRLF, pipe-delimited, with a header row. CP1252 matters:
real rows contain byte 0x92, a right single quote in CP1252 but an unassigned
control character in Latin-1.

Older extracts used literal <br> markers instead of line breaks, so those are
normalized too. The 2026-08 extract contains none.
"""

import codecs
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vrdb import schema

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


class HeaderMismatch(Exception):
    """The file's header does not match the expected table."""


@dataclass
class ReadStats:
    rows: int = 0
    malformed: int = 0
    malformed_examples: list[tuple[int, int]] = field(default_factory=list)
    coerced_null: dict[str, int] = field(default_factory=dict)


def coerce(value: str, kind: str):
    """Convert one raw field to its stored form, or None.

    Empty and whitespace-only fields become NULL. This folds away the Gender
    column's single-space value, which would otherwise be its own GROUP BY
    bucket.
    """
    value = value.strip()
    if not value:
        return None
    if kind == schema.KIND_TEXT:
        return value
    if kind == schema.KIND_INT:
        try:
            return int(value)
        except ValueError:
            return None
    if kind == schema.KIND_DATE:
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    raise ValueError(f"unknown column kind: {kind!r}")


def _decode_chunk(decoder, chunk: bytes, base: int, *, final: bool = False) -> str:
    """Decode one chunk (or flush the tail with `final=True`).

    A stateless `bytes.decode(encoding)` per chunk is only safe for
    single-byte codecs: a multi-byte character straddling a chunk boundary
    would split into two chunks, each individually invalid, and raise a
    spurious `UnicodeDecodeError`. `decoder` is a stateful incremental
    decoder, which buffers a partial trailing sequence and completes it on
    the next call instead.

    That statefulness changes what `error.start` means on failure: it indexes
    into `error.object`, which for a stateful decoder is whatever bytes were
    already buffered from a prior call followed by this call's new bytes -
    not `chunk` alone. `base` is the file offset where `chunk` begins (or,
    for the final flush, the file's total byte count so far); subtracting the
    buffered byte count backs the reported offset out to where those bytes
    actually sit in the file.
    """
    pending = len(getattr(decoder, "buffer", b""))
    try:
        return decoder.decode(chunk, final)
    except UnicodeDecodeError as error:
        file_base = base - pending
        # `object` holds the buffered-plus-new bytes that were being decoded,
        # so the offending byte is `object[start]`, not `chunk[start]`.
        reason = f"{error.reason} (byte 0x{error.object[error.start]:02x})"
        raise UnicodeDecodeError(
            error.encoding,
            error.object,
            error.start + file_base,
            error.end + file_base,
            reason,
        ) from None


def _logical_lines(path: Path, encoding: str, chunk_size: int = 1 << 20):
    """Yield (line, bytes_read) for each non-empty logical line."""
    bytes_read = 0
    decoder = codecs.getincrementaldecoder(encoding)()
    with open(path, "rb") as handle:
        carry = ""
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            base = bytes_read
            bytes_read += len(chunk)
            decoded = _decode_chunk(decoder, chunk, base)
            carry = _BR.sub("\n", carry + decoded)
            *lines, carry = carry.split("\n")
            for line in lines:
                line = line.rstrip("\r")
                if line:
                    yield line, bytes_read
        # Flush any sequence the decoder held back waiting for more bytes
        # that will never arrive. A genuinely truncated multi-byte sequence
        # at end of file must raise here rather than being silently dropped.
        final_text = _decode_chunk(decoder, b"", bytes_read, final=True)
        carry = _BR.sub("\n", carry + final_text)
        carry = carry.rstrip("\r\n")
        if carry:
            yield carry, bytes_read


def read_header(path: Path, encoding: str = "cp1252") -> list[str]:
    for line, _ in _logical_lines(path, encoding):
        return [c.strip() for c in line.split("|")]
    return []


def iter_batches(
    path,
    table: schema.Table,
    *,
    encoding: str = "cp1252",
    batch_size: int = 50_000,
    stats: ReadStats | None = None,
    progress=None,
):
    """Yield lists of coerced rows, one list per batch.

    Rows whose field count does not match the table are counted in `stats` and
    skipped rather than aborting the load.
    """
    path = Path(path)
    stats = stats if stats is not None else ReadStats()
    kinds = [c.kind for c in table.columns]
    names = list(table.column_names)
    width = len(names)

    lines = _logical_lines(path, encoding)
    try:
        header_line, _ = next(lines)
    except StopIteration:
        return
    header = [c.strip() for c in header_line.split("|")]
    if header != names:
        raise HeaderMismatch(
            f"{path.name}: expected columns {names}, found {header}"
        )

    batch = []
    line_no = 1
    for line, bytes_read in lines:
        line_no += 1
        fields = line.split("|")
        if len(fields) != width:
            stats.malformed += 1
            if len(stats.malformed_examples) < 10:
                stats.malformed_examples.append((line_no, len(fields)))
            continue
        row = []
        for name, kind, raw in zip(names, kinds, fields):
            value = coerce(raw, kind)
            if value is None and raw.strip() and kind != schema.KIND_TEXT:
                stats.coerced_null[name] = stats.coerced_null.get(name, 0) + 1
            row.append(value)
        batch.append(row)
        stats.rows += 1
        if len(batch) >= batch_size:
            yield batch
            batch = []
        if progress is not None:
            progress.update(stats.rows, bytes_read)
    if batch:
        yield batch
