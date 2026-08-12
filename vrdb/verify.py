"""Post-load verification against the source files.

The sample check deliberately re-reads and re-parses the source rather than
comparing against anything held in memory from the load. The previous
generation of this tool compared the database to the DataFrame it had just
written from, so a parse bug would have matched itself.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from vrdb import districts, reader, schema

# Voters below this join rate mean the PrecinctPart format changed and district
# filtering is silently broken. The 2026-08 extract measures 99.999%.
JOIN_COVERAGE_FLOOR = 0.95


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def count_source_rows(path, encoding: str = "cp1252") -> int:
    """Count data rows, excluding the header."""
    total = -1
    for _ in reader._logical_lines(Path(path), encoding):
        total += 1
    return max(total, 0)


def count_workbook_rows(path) -> int:
    """Count the workbook's data rows by parsing the sheet a second time.

    The workbook needs its own counter because count_source_rows splits text on
    "|". Rows skipped for holding content past the last column are added back:
    like a malformed text line, they are in the source and cannot be in the
    database, and check_no_malformed_rows is what fails on them.
    """
    stats = reader.ReadStats()
    total = -1  # the header row
    for _ in districts.iter_rows(path, stats=stats):
        total += 1
    return max(total + stats.malformed, 0)


def check_row_count(conn, table: schema.Table, expected: int, *,
                    skipped: int = 0) -> CheckResult:
    """Compare the database against a count taken from the source itself.

    `expected` must come from re-reading the source, not from the loader's own
    tally of the rows it accepted. Given that tally this check compares the
    loader to itself: a load that stopped early leaves a database holding
    exactly the rows the reader counted, so both sides agree and nothing fails.

    `skipped` is the malformed-row count. Those rows are in the source total
    and cannot be in the database, so they are not a shortfall here;
    check_no_malformed_rows is what fails on them.
    """
    actual = conn.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
    detail = f"source {expected:,} vs database {actual:,}"
    if skipped:
        detail = f"{detail} plus {skipped:,} skipped"
    return CheckResult(
        f"{table.name}: row count",
        actual + skipped == expected,
        detail,
    )


def check_no_malformed_rows(table: schema.Table, stats: reader.ReadStats) -> CheckResult:
    """Fail if the reader skipped any row for having the wrong field count.

    check_row_count compares the database to `stats.rows`, which is the reader's
    own tally of the rows it accepted. A malformed row never reaches that
    counter: reader.iter_batches counts it in `stats.malformed` and continues
    before `stats.rows` is incremented. So a row dropped at parse time matches
    on both sides of every other check and is otherwise invisible. This is the
    check that sees it, and the spec requires a nonzero count to fail
    verification rather than only print a warning.
    """
    if not stats.malformed:
        return CheckResult(f"{table.name}: no malformed rows", True, "0 skipped")
    detail = f"{stats.malformed:,} row(s) skipped for a wrong field count"
    examples = ", ".join(
        f"line {line_no} has {count} fields"
        for line_no, count in stats.malformed_examples[:3]
    )
    if examples:
        detail = f"{detail}: {examples}"
    return CheckResult(f"{table.name}: no malformed rows", False, detail)


def check_primary_key_unique(conn, table: schema.Table) -> CheckResult:
    key = table.primary_key
    if key is None:
        return CheckResult(f"{table.name}: primary key", True, "no primary key")
    total, distinct = conn.execute(
        f'SELECT COUNT(*), COUNT(DISTINCT "{key.name}") FROM "{table.name}"'
    ).fetchone()
    return CheckResult(
        f"{table.name}: {key.name} unique",
        total == distinct,
        f"{total:,} rows, {distinct:,} distinct",
    )


def check_parquet_matches_sqlite(table: schema.Table, sqlite_rows: int,
                                 parquet_rows: int) -> CheckResult:
    """Assert the two outputs of one shared read pass agree on row count.

    Nothing else looks at the Parquet file. The tee in vrdb_export.py feeds both
    writers from the same batches, so a divergence means one writer dropped a
    batch, and the closing summary would report the Parquet number as if it were
    the whole run's.
    """
    return CheckResult(
        f"{table.name}: parquet matches sqlite",
        sqlite_rows == parquet_rows,
        f"sqlite {sqlite_rows:,} vs parquet {parquet_rows:,}",
    )


def sample_source_rows(path, table: schema.Table, *, count: int = 200,
                       encoding: str = "cp1252", seed: int = 0) -> list[list]:
    """Re-parse `count` rows read from random byte offsets in the source.

    Seeking to random offsets keeps this O(count) instead of re-reading the
    whole 773 MB file.
    """
    path = Path(path)
    size = path.stat().st_size
    kinds = [c.kind for c in table.columns]
    width = len(kinds)
    rng = random.Random(seed)
    rows = []
    seen = set()

    # A small file is cheaper and more predictable to read whole than to sample
    # by seeking. This is also what test fixtures hit.
    #
    # It goes through reader._logical_lines rather than handle.readline() so it
    # splits lines by the loader's rules, not by raw \n. An older extract that
    # separates rows with <br> instead of CRLF is one giant physical line: read
    # raw, every candidate fails the width check and the sampler returns
    # nothing, which used to make the whole check pass vacuously. This is the
    # same deliberate coupling count_source_rows already has.
    if size < 1 << 20:
        lines = [line for line, _ in reader._logical_lines(path, encoding)]
        candidates = [ln for ln in lines[1:] if len(ln.split("|")) == width]
        rng.shuffle(candidates)
        return [
            [reader.coerce(v, k) for v, k in zip(line.split("|"), kinds)]
            for line in candidates[:count]
        ]

    with open(path, "rb") as handle:
        header_len = len(handle.readline())
        if size <= header_len:
            return []
        for _ in range(count * 20):
            if len(rows) >= count:
                break
            handle.seek(rng.randrange(header_len, size))
            handle.readline()  # discard the partial line
            raw = handle.readline()
            if not raw:
                handle.seek(header_len)
                raw = handle.readline()
            line = raw.decode(encoding).rstrip("\r\n")
            fields = line.split("|")
            if len(fields) != width or line in seen:
                continue
            seen.add(line)
            rows.append([reader.coerce(v, k) for v, k in zip(fields, kinds)])
    return rows


def check_sample_against_source(conn, table: schema.Table, path, *, count: int = 200,
                                encoding: str = "cp1252", seed: int = 0) -> CheckResult:
    key = table.primary_key
    if key is None:
        raise ValueError(f"{table.name} has no primary key to sample against")
    names = list(table.column_names)
    key_index = names.index(key.name)
    columns = ", ".join(f'"{c}"' for c in names)
    sample = sample_source_rows(path, table, count=count, encoding=encoding, seed=seed)
    if not sample:
        # An empty sample means the check did not run, which is not the same
        # thing as the check passing. Reporting it as a pass is how a sampler
        # that could not split the file into rows stayed invisible.
        return CheckResult(
            f"{table.name}: sample matches source",
            False,
            f"no rows could be sampled from {Path(path).name}; the check did not run",
        )
    problems = []
    for expected in sample:
        found = conn.execute(
            f'SELECT {columns} FROM "{table.name}" WHERE "{key.name}" = ?',
            (expected[key_index],),
        ).fetchone()
        if found is None:
            problems.append(f"{key.name}={expected[key_index]} missing from database")
            continue
        for name, want, got in zip(names, expected, found):
            if want != got:
                problems.append(
                    f"{key.name}={expected[key_index]} {name}: "
                    f"source {want!r} vs database {got!r}"
                )
    detail = f"compared {len(sample)} rows re-read from source"
    if problems:
        detail = f"{len(problems)} mismatch(es): " + "; ".join(problems[:5])
    return CheckResult(f"{table.name}: sample matches source", not problems, detail)


def check_districts_join(conn, *, floor: float = JOIN_COVERAGE_FLOOR) -> CheckResult:
    """Report what share of voters join to a district row.

    A drop here means the PrecinctPart format changed between extracts and
    district filtering would silently return nothing.
    """
    total = conn.execute("SELECT COUNT(*) FROM voters").fetchone()[0]
    if not total:
        return CheckResult("districts join coverage", False, "no voters loaded")
    matched = conn.execute(
        """
        SELECT COUNT(*) FROM voters v WHERE EXISTS (
            SELECT 1 FROM districts_precincts d
            WHERE d.CountyCode = v.CountyCode AND d.PrecinctPart = v.PrecinctPart
        )
        """
    ).fetchone()[0]
    share = matched / total
    return CheckResult(
        "districts join coverage",
        share >= floor,
        f"{matched:,} of {total:,} voters join ({share * 100:.1f}%)",
    )
