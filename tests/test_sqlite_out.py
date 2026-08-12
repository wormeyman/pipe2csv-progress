import sqlite3

import pytest

from vrdb import districts, reader, schema, sqlite_out


def _load(path, vrdb_txt):
    conn = sqlite_out.connect(path)
    sqlite_out.create_table(conn, schema.VOTERS)
    n = sqlite_out.insert_batches(
        conn, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    sqlite_out.create_indexes(conn, schema.VOTERS)
    return conn, n


def test_declared_types_match_schema(tmp_path, vrdb_txt):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    declared = {
        row[1]: row[2]
        for row in conn.execute("PRAGMA table_info(voters)").fetchall()
    }
    assert declared["StateVoterID"] == "INTEGER"
    assert declared["Birthyear"] == "INTEGER"
    assert declared["LegislativeDistrict"] == "INTEGER"
    assert declared["RegStNum"] == "TEXT"
    assert declared["RegZipCode"] == "TEXT"
    assert declared["PrecinctPart"] == "TEXT"
    assert declared["Registrationdate"] == "TEXT"


def test_statevoterid_is_the_primary_key(tmp_path, vrdb_txt):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    pk = [r[1] for r in conn.execute("PRAGMA table_info(voters)") if r[5]]
    assert pk == ["StateVoterID"]


def test_all_rows_land(tmp_path, vrdb_txt):
    conn, n = _load(tmp_path / "t.sqlite", vrdb_txt)
    assert n == 10
    assert conn.execute("SELECT COUNT(*) FROM voters").fetchone()[0] == 10


def test_values_keep_their_types(tmp_path, vrdb_txt):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    row = conn.execute(
        "SELECT typeof(StateVoterID), typeof(Birthyear), typeof(RegZipCode),"
        " typeof(PrecinctCode) FROM voters WHERE StateVoterID = 9000003"
    ).fetchone()
    assert row == ("integer", "null", "text", "text")
    part = conn.execute(
        "SELECT PrecinctCode FROM voters WHERE StateVoterID = 9000004"
    ).fetchone()[0]
    assert part == "0600"  # leading zero survived


def test_indexes_are_created(tmp_path, vrdb_txt):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
    }
    assert names == {i.name for i in schema.VOTERS.indexes}


def test_duplicate_primary_key_is_rejected(tmp_path, vrdb_txt):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    dupe = [[9000001] + [None] * 32]
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_out.insert_batches(conn, schema.VOTERS, iter([dupe]))


def test_ref_tables(tmp_path):
    conn = sqlite_out.connect(tmp_path / "t.sqlite")
    sqlite_out.write_ref_tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM ref_county").fetchone()[0] == 39
    assert conn.execute(
        "SELECT name FROM ref_county WHERE code = 'KI'"
    ).fetchone()[0] == "King"
    assert conn.execute("SELECT COUNT(*) FROM ref_gender").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM ref_status").fetchone()[0] == 3


def test_districts_join_returns_voters(tmp_path, vrdb_txt, districts_xlsx):
    conn, _ = _load(tmp_path / "t.sqlite", vrdb_txt)
    sqlite_out.create_table(conn, schema.DISTRICTS_PRECINCTS)
    sqlite_out.insert_batches(
        conn,
        schema.DISTRICTS_PRECINCTS,
        districts.iter_batches(districts_xlsx, schema.DISTRICTS_PRECINCTS),
    )
    sqlite_out.create_indexes(conn, schema.DISTRICTS_PRECINCTS)
    rows = conn.execute(
        """
        SELECT v.LName FROM voters v
        JOIN districts_precincts d
          ON d.CountyCode = v.CountyCode AND d.PrecinctPart = v.PrecinctPart
        WHERE d.DistrictName = 'FIRE DISTRICT NO. 8'
        ORDER BY v.LName
        """
    ).fetchall()
    # Adams 311.1 and Pierce 2169 both belong to a district of that name
    assert [r[0] for r in rows] == ["NORTHCUTT", "PUYALLUP"]
