import pytest

from vrdb import districts, reader, schema, sqlite_out, verify
from tests.conftest import VOTER_HEADER, VOTER_ROWS


def _loaded(tmp_path, vrdb_txt, districts_xlsx=None):
    conn = sqlite_out.connect(tmp_path / "t.sqlite")
    sqlite_out.create_table(conn, schema.VOTERS)
    sqlite_out.insert_batches(
        conn, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    sqlite_out.create_indexes(conn, schema.VOTERS)
    if districts_xlsx is not None:
        sqlite_out.create_table(conn, schema.DISTRICTS_PRECINCTS)
        sqlite_out.insert_batches(
            conn,
            schema.DISTRICTS_PRECINCTS,
            districts.iter_batches(districts_xlsx, schema.DISTRICTS_PRECINCTS),
        )
        sqlite_out.create_indexes(conn, schema.DISTRICTS_PRECINCTS)
    return conn


def test_count_source_rows_excludes_header(vrdb_txt):
    assert verify.count_source_rows(vrdb_txt) == 10


def test_count_workbook_rows_excludes_header(districts_xlsx):
    """The workbook needs its own counter; count_source_rows splits on "|"."""
    assert verify.count_workbook_rows(districts_xlsx) == 10


def test_row_count_passes(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    assert verify.check_row_count(conn, schema.VOTERS, 10).passed


def test_row_count_fails_when_rows_are_missing(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    conn.execute("DELETE FROM voters WHERE StateVoterID = 9000001")
    conn.commit()
    result = verify.check_row_count(conn, schema.VOTERS, 10)
    assert not result.passed
    assert "9" in result.detail


def test_row_count_accounts_for_rows_skipped_as_malformed(tmp_path, vrdb_txt):
    """The source count is taken from the source, so it includes skipped rows.

    Only rows the reader accepted reach the database, so the two sides differ
    by exactly the malformed count and that difference is not a failure.
    """
    conn = _loaded(tmp_path, vrdb_txt)
    assert verify.check_row_count(conn, schema.VOTERS, 12, skipped=2).passed


def test_row_count_fails_when_skipped_rows_do_not_explain_the_gap(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    result = verify.check_row_count(conn, schema.VOTERS, 12, skipped=1)
    assert not result.passed
    assert "source 12" in result.detail


def test_primary_key_uniqueness(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    assert verify.check_primary_key_unique(conn, schema.VOTERS).passed


def test_no_malformed_rows_passes_on_a_clean_read():
    stats = reader.ReadStats(rows=10)
    result = verify.check_no_malformed_rows(schema.VOTERS, stats)
    assert result.passed
    assert "0 skipped" in result.detail


def test_no_malformed_rows_fails_and_names_the_lines():
    """The row count cannot catch this: stats.rows already excludes them."""
    stats = reader.ReadStats(rows=10, malformed=3, malformed_examples=[(4, 32), (7, 34)])
    result = verify.check_no_malformed_rows(schema.VOTERS, stats)
    assert not result.passed
    assert "3 row(s) skipped" in result.detail
    assert "line 4 has 32 fields" in result.detail


def test_parquet_matches_sqlite():
    assert verify.check_parquet_matches_sqlite(schema.VOTERS, 10, 10).passed
    mismatch = verify.check_parquet_matches_sqlite(schema.VOTERS, 10, 9)
    assert not mismatch.passed
    assert "sqlite 10 vs parquet 9" in mismatch.detail


def test_sample_matches_source(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    result = verify.check_sample_against_source(
        conn, schema.VOTERS, vrdb_txt, count=10
    )
    assert result.passed, result.detail
    # Without this, a sampler that compared nothing at all would also pass.
    assert "compared 10 rows" in result.detail


def test_sample_works_on_a_br_delimited_extract(tmp_path):
    """Older extracts use <br> instead of CRLF, and reader.py supports them.

    Read raw, such a file is one giant physical line, every candidate fails the
    width check, and the sampler returns nothing.
    """
    path = tmp_path / "old_VRDB_Extract.txt"
    body = "<br>".join([VOTER_HEADER] + ["|".join(r) for r in VOTER_ROWS]) + "<br>"
    path.write_bytes(body.encode("cp1252"))

    sample = verify.sample_source_rows(path, schema.VOTERS, count=10)
    assert len(sample) == 10

    conn = _loaded(tmp_path, path)
    result = verify.check_sample_against_source(conn, schema.VOTERS, path, count=10)
    assert result.passed, result.detail
    assert "compared 10 rows" in result.detail


def test_sample_fails_when_nothing_could_be_sampled(tmp_path):
    """An empty sample means the check did not run, not that it passed."""
    path = tmp_path / "header_only.txt"
    path.write_bytes((VOTER_HEADER + "\r\n").encode("cp1252"))

    conn = sqlite_out.connect(tmp_path / "t.sqlite")
    sqlite_out.create_table(conn, schema.VOTERS)

    assert verify.sample_source_rows(path, schema.VOTERS) == []
    result = verify.check_sample_against_source(conn, schema.VOTERS, path)
    assert not result.passed
    assert "did not run" in result.detail


def test_sample_detects_a_corrupted_cell(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    conn.execute("UPDATE voters SET LName = 'WRONG' WHERE StateVoterID = 9000001")
    conn.commit()
    result = verify.check_sample_against_source(
        conn, schema.VOTERS, vrdb_txt, count=10
    )
    assert not result.passed
    assert "LName" in result.detail


def test_sample_detects_a_missing_row(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    conn.execute("DELETE FROM voters WHERE StateVoterID = 9000005")
    conn.commit()
    result = verify.check_sample_against_source(
        conn, schema.VOTERS, vrdb_txt, count=10
    )
    assert not result.passed


def test_districts_join_coverage(tmp_path, vrdb_txt, districts_xlsx):
    conn = _loaded(tmp_path, vrdb_txt, districts_xlsx)
    # 9 of the 10 fixture voters have a matching district row; one has a blank
    # PrecinctPart and cannot match
    result = verify.check_districts_join(conn, floor=0.5)
    assert "90.0%" in result.detail
    assert result.passed


def test_districts_join_fails_below_the_floor(tmp_path, vrdb_txt, districts_xlsx):
    conn = _loaded(tmp_path, vrdb_txt, districts_xlsx)
    # the production floor is 0.95 and the fixture sits at 0.90
    assert verify.JOIN_COVERAGE_FLOOR == 0.95
    assert not verify.check_districts_join(conn).passed


def test_sample_against_source_rejects_a_table_without_a_primary_key(
    tmp_path, vrdb_txt, districts_xlsx
):
    conn = _loaded(tmp_path, vrdb_txt, districts_xlsx)
    with pytest.raises(ValueError, match="no primary key"):
        verify.check_sample_against_source(
            conn, schema.DISTRICTS_PRECINCTS, districts_xlsx
        )
