"""DuckDB views over the Parquet output, for browsing in TablePlus.

The views file holds no voter rows, only views that read the Parquet files
live. Every test builds made-up extracts in tmp_path.
"""

import subprocess
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import vrdb_export
from vrdb import duckdb_out, schema

REPO = Path(__file__).resolve().parents[1]


def _parquet(path: Path, ids: list[str]) -> Path:
    pq.write_table(pa.table({"StateVoterID": ids}), path)
    return path


def test_views_are_named_by_table_and_read_the_parquet_live(tmp_path):
    voters = _parquet(tmp_path / "voters_20261001.parquet", ["WA1", "WA2"])
    out = duckdb_out.write_views(tmp_path / "vrdb_20261001.duckdb", {"voters": voters})
    with duckdb.connect(str(out), read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM voters").fetchone() == (2,)
    _parquet(voters, ["WA1"])
    with duckdb.connect(str(out), read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM voters").fetchone() == (1,)


def test_views_work_from_another_working_directory(tmp_path, monkeypatch):
    """TablePlus opens the file from its own working directory."""
    voters = _parquet(tmp_path / "voters_20261001.parquet", ["WA1"])
    out = duckdb_out.write_views(tmp_path / "vrdb_20261001.duckdb", {"voters": voters})
    monkeypatch.chdir("/")
    with duckdb.connect(str(out), read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM voters").fetchone() == (1,)


def test_the_cli_writes_views_over_every_table(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    code = vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--join-floor", "0.5"]
    )
    assert code == 0
    with duckdb.connect(str(out / "vrdb_20260803.duckdb"), read_only=True) as conn:
        counts = {
            name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()
            for name in ("voters", "voting_history", "districts_precincts")
        }
    assert counts == {"voters": (10,), "voting_history": (5,), "districts_precincts": (10,)}


def test_views_for_parquet_already_written(tmp_path, extract_dir):
    """`python -m vrdb.duckdb_out FOLDER` for a folder exported before views existed."""
    out = tmp_path / "out"
    out.mkdir()
    assert vrdb_export.main(
        [str(extract_dir), "--out", str(out), "--join-floor", "0.5"]
    ) == 0
    (out / "vrdb_20260803.duckdb").unlink()
    assert duckdb_out.main([str(out), "--no-launcher"]) == 0
    with duckdb.connect(str(out / "vrdb_20260803.duckdb"), read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM voters").fetchone() == (10,)


def test_a_folder_with_no_parquet_is_a_message(tmp_path, capsys):
    assert duckdb_out.main([str(tmp_path), "--no-launcher"]) == 2
    assert "no voters_YYYYMMDD.parquet" in capsys.readouterr().err


def test_the_tableplus_link_encodes_the_whole_path():
    url = duckdb_out.tableplus_url(Path("/Users/me/10.2026 WA/vrdb_20261001.duckdb"))
    assert url.startswith(
        "duckdb://@%2FUsers%2Fme%2F10.2026%20WA%2Fvrdb_20261001.duckdb/vrdb_20261001.duckdb?"
    )


def test_the_launcher_hands_the_link_to_tableplus_by_name():
    """`open <link>` fails: no app claims duckdb://. `open -a TablePlus <link>` works."""
    assert duckdb_out.launcher_script('duckdb://@%2Fa"b/x?n=1') == (
        'do shell script "open -a TablePlus " & quoted form of "duckdb://@%2Fa\\"b/x?n=1"'
    )


@pytest.mark.parametrize("name", [
    "vrdb_20261001.duckdb", "vrdb_20261001.duckdb.wal", "vrdb_20261001.duckdb.tmp",
    "Open vrdb_20261001.duckdb in TablePlus.app/Contents/Info.plist",
])
def test_views_outputs_are_gitignored(name):
    """The views file holds paths, not voters, but it is regulated-data adjacent."""
    hit = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO)
    assert hit.returncode == 0, name


def test_the_views_file_carries_the_lookup_tables(tmp_path):
    """They lived only in SQLite, so dropping the database would have lost them."""
    voters = _parquet(tmp_path / "voters_20261001.parquet", ["WA1"])
    out = duckdb_out.write_views(tmp_path / "vrdb_20261001.duckdb", {"voters": voters})
    with duckdb.connect(str(out), read_only=True) as conn:
        for name, _columns, mapping in schema.REF_TABLES:
            rows = conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
            assert rows == sorted(mapping.items()), name
    assert [name for name, _, _ in schema.REF_TABLES] == ["ref_county", "ref_gender", "ref_status"]
