import os
import time

import pytest

from vrdb import discover


def test_discovers_all_three(extract_dir):
    found = discover.discover(extract_dir)
    voting_history = found.voting_history
    districts = found.districts
    assert found.vrdb.name == "20260803_VRDB_Extract.txt"
    assert (
        voting_history is not None
        and voting_history.name == "2025-2026_Voting_History_20260601.txt"
    )
    assert (
        districts is not None
        and districts.name == "2026-08-03_Districts-Precincts.xlsx"
    )
    assert found.extract_date == "20260803"


def test_a_sibling_csv_never_wins(extract_dir):
    (extract_dir / "20260803_VRDB_Extract.csv").write_text("x")
    assert discover.discover(extract_dir).vrdb.suffix == ".txt"


def test_a_converted_csv_is_not_discovered(tmp_path):
    """A .csv is the one thing the reader cannot read: it splits on "|" only.

    Discovery used to fall back to *VRDB_Extract.csv when no .txt was present.
    That found a file iter_batches then rejected with HeaderMismatch, which
    main() did not catch, so the run ended in a traceback. A real folder like
    this holds a comma-delimited derivative of a source file that is now gone.
    """
    (tmp_path / "20250701_VRDB_Extract.csv").write_text("x")
    with pytest.raises(discover.MissingExtract, match=r"VRDB_Extract\.txt"):
        discover.discover(tmp_path)


def test_optional_files_may_be_absent(extract_dir):
    (extract_dir / "2025-2026_Voting_History_20260601.txt").unlink()
    (extract_dir / "2026-08-03_Districts-Precincts.xlsx").unlink()
    found = discover.discover(extract_dir)
    assert found.voting_history is None
    assert found.districts is None


def test_missing_vrdb_raises(tmp_path):
    with pytest.raises(discover.MissingExtract):
        discover.discover(tmp_path)


def test_extract_date_from_filename(tmp_path):
    path = tmp_path / "20260803_VRDB_Extract.txt"
    path.write_text("x")
    assert discover.extract_date_from(path) == "20260803"


def test_extract_date_falls_back_to_mtime(tmp_path):
    path = tmp_path / "VRDB_Extract.txt"
    path.write_text("x")
    stamp = time.mktime((2026, 3, 14, 12, 0, 0, 0, 0, -1))
    os.utime(path, (stamp, stamp))
    assert discover.extract_date_from(path) == "20260314"


def test_extract_date_skips_a_match_that_is_not_a_real_date(tmp_path):
    # "2025-2026" matches the pattern but means month 20, day 26
    path = tmp_path / "2025-2026_Voting_History_20260601.txt"
    path.write_text("x")
    assert discover.extract_date_from(path) == "20260601"


def test_two_vrdb_extracts_raise_rather_than_pick_one(extract_dir):
    (extract_dir / "20260401_VRDB_Extract.txt").write_text("x")
    with pytest.raises(discover.AmbiguousExtract) as excinfo:
        discover.discover(extract_dir)
    message = str(excinfo.value)
    assert "20260401_VRDB_Extract.txt" in message
    assert "20260803_VRDB_Extract.txt" in message


def test_two_history_files_also_raise(extract_dir):
    (extract_dir / "2023-2024_Voting_History_20240601.txt").write_text("x")
    with pytest.raises(discover.AmbiguousExtract):
        discover.discover(extract_dir)
