import sqlite3
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import vrdb_export


def test_end_to_end(tmp_path, extract_dir, capsys):
    out = tmp_path / "out"
    out.mkdir()
    # The fixture deliberately holds one voter with a blank PrecinctPart, so
    # it joins at 90% by design. Lower the floor so this exercises the
    # all-checks-pass path that the real 99.999% extract takes.
    code = vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--parquet", "--join-floor", "0.5"]
    )
    assert code == 0

    db = out / "vrdb_20260803.sqlite"
    assert db.exists()
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM voters").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM voting_history").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM districts_precincts").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM ref_county").fetchone()[0] == 39

    assert pq.read_table(out / "voters_20260803.parquet").num_rows == 10
    assert pq.read_table(out / "voting_history_20260803.parquet").num_rows == 5
    assert pq.read_table(out / "districts_precincts_20260803.parquet").num_rows == 10

    assert "ALL CHECKS PASSED" in capsys.readouterr().out


def test_refuses_to_clobber(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    (out / "vrdb_20260803.sqlite").write_text("existing")
    with pytest.raises(SystemExit) as excinfo:
        vrdb_export.main([str(extract_dir), "--out", str(out)])
    assert excinfo.value.code == 2


def test_force_overwrites(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    (out / "vrdb_20260803.sqlite").write_text("existing")
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--force", "--join-floor", "0.5"]
    ) == 0


def test_outputs_default_to_the_source_folder(extract_dir):
    """`out_dir = found.vrdb.parent` is what keeps voter data out of the repo.

    Every other CLI test passes --out, so nothing exercised the default. The
    extract_dir fixture lives under tmp_path, so this writes there.
    """
    assert vrdb_export.main([str(extract_dir), "--parquet", "--join-floor", "0.5"]) == 0
    for name in (
        "vrdb_20260803.sqlite",
        "voters_20260803.parquet",
        "voting_history_20260803.parquet",
        "districts_precincts_20260803.parquet",
    ):
        assert (extract_dir / name).exists(), name
        assert not (Path.cwd() / name).exists(), f"{name} landed in the repo"


def test_default_writes_sqlite_only(tmp_path, extract_dir):
    """Parquet is opt-in. Most runs want the database and nothing else.

    The fixture joins at 90% by design, so an all-pass run needs the floor
    lowered. Without asserting the code, this returned 1 unnoticed.
    """
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--join-floor", "0.5"]
    ) == 0
    assert (out / "vrdb_20260803.sqlite").exists()
    assert not list(out.glob("*.parquet"))


def test_parquet_adds_to_the_database_rather_than_replacing_it(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--parquet", "--join-floor", "0.5"]
    ) == 0
    assert (out / "vrdb_20260803.sqlite").exists()
    assert len(list(out.glob("*.parquet"))) == 3


def test_parquet_only_skips_the_database(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out), "--parquet-only"]) == 0
    assert not (out / "vrdb_20260803.sqlite").exists()
    assert (out / "voters_20260803.parquet").exists()


def test_the_sqlite_flag_is_gone(tmp_path, extract_dir):
    """It would now mean the same as passing nothing, so it is not accepted."""
    with pytest.raises(SystemExit) as excinfo:
        vrdb_export.main([str(extract_dir), "--out", str(tmp_path), "--sqlite"])
    assert excinfo.value.code == 2


def test_sqlite_and_parquet_hold_the_same_rows(tmp_path, extract_dir):
    """Both outputs having 10 rows does not prove they hold the same 10."""
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--parquet", "--join-floor", "0.5"]
    ) == 0
    conn = sqlite3.connect(out / "vrdb_20260803.sqlite")

    db_voters = {r[0] for r in conn.execute("SELECT StateVoterID FROM voters")}
    pq_voters = set(
        pq.read_table(out / "voters_20260803.parquet", columns=["StateVoterID"])
        .column("StateVoterID")
        .to_pylist()
    )
    assert len(db_voters) == 10
    assert db_voters == pq_voters

    db_history = {r[0] for r in conn.execute("SELECT VoterHistoryID FROM voting_history")}
    pq_history = set(
        pq.read_table(
            out / "voting_history_20260803.parquet", columns=["VoterHistoryID"]
        )
        .column("VoterHistoryID")
        .to_pylist()
    )
    assert len(db_history) == 5
    assert db_history == pq_history
    conn.close()


def test_parquet_row_count_is_verified_against_sqlite(tmp_path, extract_dir, capsys):
    """Nothing else looks at the Parquet output in any mode."""
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--parquet", "--join-floor", "0.5"]
    ) == 0
    captured = capsys.readouterr().out
    assert "PASS  voters: parquet matches sqlite: sqlite 10 vs parquet 10" in captured
    assert "PASS  voting_history: parquet matches sqlite" in captured


def test_parquet_only_reports_that_no_checks_ran(tmp_path, extract_dir, capsys):
    """Verification needs the database, so --parquet alone runs zero checks."""
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out), "--parquet-only"]) == 0
    captured = capsys.readouterr().out
    assert "NO CHECKS RUN" in captured
    assert "ALL CHECKS PASSED" not in captured


def test_skip_verify_reports_that_no_checks_ran(tmp_path, extract_dir, capsys):
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--skip-verify"]
    ) == 0
    captured = capsys.readouterr().out
    assert "NO CHECKS RUN" in captured
    assert "ALL CHECKS PASSED" not in captured


def test_missing_extract_is_a_message_not_a_traceback(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert vrdb_export.main([str(empty), "--out", str(tmp_path / "out")]) == 2
    assert "no *VRDB_Extract.txt" in capsys.readouterr().err


def test_ambiguous_extract_is_a_message_not_a_traceback(tmp_path, extract_dir, capsys):
    (extract_dir / "20260401_VRDB_Extract.txt").write_bytes(b"")
    assert vrdb_export.main([str(extract_dir), "--out", str(tmp_path / "out")]) == 2
    assert "Keep one extract per folder" in capsys.readouterr().err


def test_optional_files_missing_is_a_warning(tmp_path, extract_dir, capsys):
    (extract_dir / "2026-08-03_Districts-Precincts.xlsx").unlink()
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 0
    assert "no districts" in capsys.readouterr().out.lower()


def test_undecodable_byte_reports_encoding_guidance(tmp_path, extract_dir, capsys):
    # 0x81 is unassigned in CP1252
    target = extract_dir / "20260803_VRDB_Extract.txt"
    target.write_bytes(target.read_bytes().replace(b"NORTHCUTT", b"NORTH\x81UTT"))
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 1
    assert "--encoding latin-1" in capsys.readouterr().err
    assert not (out / "vrdb_20260803.sqlite").exists()


def test_undecodable_byte_past_a_chunk_boundary_reports_the_true_offset(
    tmp_path, extract_dir, capsys
):
    """The reader decodes 1 MiB chunks, so a raw error.start is chunk-relative.

    test_undecodable_byte_reports_encoding_guidance passes only because its
    fixture is under 1 MiB and never crosses a boundary.
    """
    target = extract_dir / "20260803_VRDB_Extract.txt"
    header, _, rest = target.read_bytes().partition(b"\r\n")
    body = bytearray(header + b"\r\n" + rest * 900)
    assert len(body) > (1 << 20)
    offset = (1 << 20) + 500
    body[offset] = 0x81  # unassigned in CP1252
    target.write_bytes(bytes(body))

    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert f"offset {offset}" in err
    assert "offset 500 " not in err  # the chunk-relative answer


def test_default_join_floor_still_fails_the_90_percent_fixture(tmp_path, extract_dir, capsys):
    """--join-floor must not weaken the production default.

    Without an explicit floor the fixture's 90% coverage is below
    verify.JOIN_COVERAGE_FLOOR, so the run must report a failure and exit 1.
    """
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 1
    captured = capsys.readouterr().out
    assert "SOME CHECKS FAILED" in captured
    assert "90.0%" in captured


def test_malformed_rows_fail_verification(tmp_path, extract_dir, capsys):
    """A skipped row must fail the run, not just print a warning."""
    target = extract_dir / "20260803_VRDB_Extract.txt"
    target.write_bytes(
        target.read_bytes() + "9000011|SHORT|ROW\r\n9000012|ALSO|SHORT\r\n".encode("cp1252")
    )
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--join-floor", "0.5"]
    ) == 1
    captured = capsys.readouterr().out
    assert "FAIL  voters: no malformed rows" in captured
    assert "2 row(s) skipped" in captured
    # The row count still passes: the source holds 12 rows, the database holds
    # 10, and the 2 skipped rows account for the difference exactly.
    assert "PASS  voters: row count" in captured
    assert "SOME CHECKS FAILED" in captured


def test_row_count_catches_a_load_that_stopped_early(
    tmp_path, extract_dir, capsys, monkeypatch
):
    """The row count is checked against an independent re-read of the source.

    Fed the reader's own accepted-row tally instead, this check reported
    "source 4 vs database 4" and passed: the database holds every row the
    reader counted, and the reader counted only the rows it got to, so both
    sides agree no matter how much of the file went unread.

    The sample check does catch a truncation this severe, and on this 10-row
    fixture it catches every truncation, because the sampler reads a small file
    whole. At real scale it is 200 random rows out of 5.5M, so a load that lost
    the last few thousand rows would slip past it around 96 times in 100. The
    row count is the check that cannot miss it.
    """
    real = vrdb_export.reader.iter_batches

    def stops_after_one_batch(path, table, **kwargs):
        for batch in real(path, table, **kwargs):
            yield batch
            return

    monkeypatch.setattr(vrdb_export.reader, "iter_batches", stops_after_one_batch)
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--batch", "4", "--join-floor", "0.5"]
    ) == 1
    captured = capsys.readouterr().out
    assert "FAIL  voters: row count: source 10 vs database 4" in captured
    assert "SOME CHECKS FAILED" in captured


def test_districts_row_count_catches_a_load_that_stopped_early(
    tmp_path, extract_dir, capsys, monkeypatch
):
    """The workbook is counted by a second parse, not by the loader's tally.

    The join floor is set low enough here that coverage still passes, so the
    row count is the only thing standing between a half-loaded districts table
    and a clean bill of health.
    """
    real = vrdb_export.districts.iter_batches

    def stops_after_one_batch(path, table, **kwargs):
        for batch in real(path, table, **kwargs):
            yield batch
            return

    monkeypatch.setattr(vrdb_export.districts, "iter_batches", stops_after_one_batch)
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--batch", "4", "--join-floor", "0.2"]
    ) == 1
    captured = capsys.readouterr().out
    assert "FAIL  districts_precincts: row count: source 10 vs database 4" in captured
    assert "PASS  districts join coverage" in captured


def test_a_changed_source_header_is_a_message_not_a_traceback(
    tmp_path, extract_dir, capsys
):
    """The SOS renaming a column must not end the run in a stack trace.

    HeaderMismatch is the loader refusing to guess, which is correct, but it
    was the one expected failure that reached the user as a traceback.
    """
    target = extract_dir / "20260803_VRDB_Extract.txt"
    target.write_bytes(target.read_bytes().replace(b"Birthyear", b"YearofBirth", 1))
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "YearofBirth" in err
    assert not (out / "vrdb_20260803.sqlite").exists()


def test_leaves_alone_outputs_for_tables_it_is_not_writing(tmp_path, extract_dir):
    """A missing optional source must not endanger that table's earlier output.

    An earlier run wrote districts_precincts_20260803.parquet. This run has no
    districts file, so it must neither refuse over that path nor delete it.
    """
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "districts_precincts_20260803.parquet"
    stale.write_bytes(b"from an earlier complete run")
    (extract_dir / "2026-08-03_Districts-Precincts.xlsx").unlink()

    assert vrdb_export.main([str(extract_dir), "--out", str(out), "--parquet"]) == 0
    assert stale.read_bytes() == b"from an earlier complete run"


def test_force_does_not_delete_an_untouched_table_output(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "districts_precincts_20260803.parquet"
    stale.write_bytes(b"from an earlier complete run")
    (extract_dir / "2026-08-03_Districts-Precincts.xlsx").unlink()

    assert vrdb_export.main([str(extract_dir), "--out", str(out), "--force", "--parquet"]) == 0
    assert stale.read_bytes() == b"from an earlier complete run"


def test_partial_output_is_removed_on_failure(tmp_path, extract_dir, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(vrdb_export.sqlite_out, "create_indexes", explode)
    with pytest.raises(RuntimeError):
        vrdb_export.main([str(extract_dir), "--out", str(out)])
    assert not (out / "vrdb_20260803.sqlite").exists()
