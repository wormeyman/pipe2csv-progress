"""Parquet output.

This is the only module that imports pyarrow, so schema.py and the readers stay
testable without it. Dates are converted explicitly with date.fromisoformat
rather than relying on an Arrow string-to-date cast: the reader has already
validated the format, and an explicit conversion cannot silently reinterpret a
value.
"""

from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from vrdb import schema

_ARROW_TYPES = {
    schema.KIND_TEXT: pa.string(),
    schema.KIND_INT: pa.int64(),
    schema.KIND_DATE: pa.date32(),
}


def arrow_type(kind: str) -> pa.DataType:
    try:
        return _ARROW_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown column kind: {kind!r}") from None


def arrow_schema(table: schema.Table) -> pa.Schema:
    return pa.schema(
        [pa.field(c.name, arrow_type(c.kind)) for c in table.columns]
    )


def _to_arrow(batch, table: schema.Table) -> pa.Table:
    columns = []
    for position, column in enumerate(table.columns):
        values = [row[position] for row in batch]
        if column.kind == schema.KIND_DATE:
            values = [None if v is None else date.fromisoformat(v) for v in values]
        columns.append(pa.array(values, type=arrow_type(column.kind)))
    return pa.Table.from_arrays(columns, schema=arrow_schema(table))


def write_batches(path, table: schema.Table, batches, *, compression: str = "zstd") -> int:
    """Write batches to a Parquet file, one row group per batch."""
    written = 0
    writer = pq.ParquetWriter(
        str(path), arrow_schema(table), compression=compression, use_dictionary=True
    )
    try:
        for batch in batches:
            writer.write_table(_to_arrow(batch, table))
            written += len(batch)
    finally:
        writer.close()
    return written
