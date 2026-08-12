from vrdb import schema


def test_voters_has_33_columns_in_source_order():
    """The full tuple, transcribed from the extract's own header row.

    Spot-checking positions 0, 5 and 32 let a swap of two untested middle
    columns through, and the supposed integration guard is circular:
    tests/conftest.py builds its fixture header FROM these names, so
    reader.HeaderMismatch can never catch a schema-side swap.
    """
    assert len(schema.VOTERS.columns) == 33
    assert schema.VOTERS.column_names == (
        "StateVoterID",
        "FName",
        "MName",
        "LName",
        "NameSuffix",
        "Birthyear",
        "Gender",
        "RegStNum",
        "RegStFrac",
        "RegStName",
        "RegStType",
        "RegUnitType",
        "RegStPreDirection",
        "RegStPostDirection",
        "RegStUnitNum",
        "RegCity",
        "RegState",
        "RegZipCode",
        "CountyCode",
        "PrecinctCode",
        "PrecinctPart",
        "LegislativeDistrict",
        "CongressionalDistrict",
        "Mail1",
        "Mail2",
        "Mail3",
        "MailCity",
        "MailZip",
        "MailState",
        "MailCountry",
        "Registrationdate",
        "LastVoted",
        "StatusCode",
    )


def test_voting_history_column_order_follows_file_not_pdf():
    assert schema.VOTING_HISTORY.column_names == (
        "VoterHistoryID",
        "CountyCode",
        "CountyCode_Voting",
        "StateVoterID",
        "ElectionDate",
    )


def test_districts_has_8_text_columns():
    assert len(schema.DISTRICTS_PRECINCTS.columns) == 8
    assert all(c.kind == schema.KIND_TEXT for c in schema.DISTRICTS_PRECINCTS.columns)
    assert schema.DISTRICTS_PRECINCTS.primary_key is None


def test_primary_keys():
    voters_key = schema.VOTERS.primary_key
    history_key = schema.VOTING_HISTORY.primary_key
    assert voters_key is not None and voters_key.name == "StateVoterID"
    assert history_key is not None and history_key.name == "VoterHistoryID"


def test_identifier_columns_stay_text():
    kinds = {c.name: c.kind for c in schema.VOTERS.columns}
    # 23,093 rows hold values like "123A"
    assert kinds["RegStNum"] == schema.KIND_TEXT
    # 56,139 rows hold ZIP+4
    assert kinds["RegZipCode"] == schema.KIND_TEXT
    # leading zeros and letter suffixes are significant
    assert kinds["PrecinctCode"] == schema.KIND_TEXT
    assert kinds["PrecinctPart"] == schema.KIND_TEXT


def test_numeric_and_date_columns():
    kinds = {c.name: c.kind for c in schema.VOTERS.columns}
    assert kinds["Birthyear"] == schema.KIND_INT
    assert kinds["LegislativeDistrict"] == schema.KIND_INT
    assert kinds["CongressionalDistrict"] == schema.KIND_INT
    assert kinds["Registrationdate"] == schema.KIND_DATE
    assert kinds["LastVoted"] == schema.KIND_DATE
    assert schema.VOTING_HISTORY.columns[4].kind == schema.KIND_DATE


def test_every_column_has_a_known_kind():
    for table in schema.ALL_TABLES:
        for column in table.columns:
            assert schema.sqlite_type(column.kind) in {"INTEGER", "TEXT"}


def test_no_redundant_statevoterid_index():
    # StateVoterID is INTEGER PRIMARY KEY, so it is the rowid already
    names = {i.name for i in schema.VOTERS.indexes}
    assert "idx_voters_statevoterid" not in names


def test_indexes_reference_real_columns():
    for table in schema.ALL_TABLES:
        valid = set(table.column_names)
        for index in table.indexes:
            assert set(index.columns) <= valid, (table.name, index.name)


def test_index_names_are_globally_unique():
    seen = [i.name for t in schema.ALL_TABLES for i in t.indexes]
    assert len(seen) == len(set(seen))


def test_districts_join_index_exists():
    both = {i.columns for i in schema.VOTERS.indexes}
    assert ("CountyCode", "PrecinctPart") in both
    dp = {i.columns for i in schema.DISTRICTS_PRECINCTS.indexes}
    assert ("CountyCode", "PrecinctPart") in dp


def test_reference_code_tables():
    assert len(schema.COUNTY_CODES) == 39
    assert schema.COUNTY_CODES["KI"] == "King"
    assert schema.COUNTY_CODES["GY"] == "Grays Harbor"
    assert set(schema.GENDER_CODES) == {"M", "F", "U", "O"}
    assert "Pending - Primary Only Voter" in schema.STATUS_CODES
