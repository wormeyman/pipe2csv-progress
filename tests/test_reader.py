import pytest

from vrdb import reader, schema


def test_coerce_blank_and_whitespace_become_null():
    assert reader.coerce("", schema.KIND_TEXT) is None
    assert reader.coerce("   ", schema.KIND_TEXT) is None
    assert reader.coerce(" ", schema.KIND_TEXT) is None


def test_coerce_strips_surrounding_whitespace():
    assert reader.coerce("  LIND  ", schema.KIND_TEXT) == "LIND"


def test_coerce_int():
    assert reader.coerce("1970", schema.KIND_INT) == 1970
    assert reader.coerce("", schema.KIND_INT) is None
    assert reader.coerce("19x0", schema.KIND_INT) is None


def test_coerce_date_keeps_iso_string():
    assert reader.coerce("2025-11-04", schema.KIND_DATE) == "2025-11-04"
    assert reader.coerce("", schema.KIND_DATE) is None
    assert reader.coerce("11/04/2025", schema.KIND_DATE) is None
    assert reader.coerce("2025-13-99", schema.KIND_DATE) is None


def test_read_header(vrdb_txt):
    assert reader.read_header(vrdb_txt) == list(schema.VOTERS.column_names)


def test_iter_batches_reads_every_row(vrdb_txt):
    stats = reader.ReadStats()
    rows = [r for batch in reader.iter_batches(vrdb_txt, schema.VOTERS, stats=stats) for r in batch]
    assert len(rows) == 10
    assert stats.rows == 10
    assert stats.malformed == 0


def test_batching_respects_batch_size(vrdb_txt):
    batches = list(reader.iter_batches(vrdb_txt, schema.VOTERS, batch_size=4))
    assert [len(b) for b in batches] == [4, 4, 2]


def test_cp1252_high_bytes_decode_correctly(vrdb_txt):
    rows = [r for b in reader.iter_batches(vrdb_txt, schema.VOTERS) for r in b]
    names = {r[0]: (r[2], r[3]) for r in rows}
    # byte 0xC9 and byte 0x92; latin-1 would turn 0x92 into a control character
    assert names[9000002] == ("RENÉE", "O’BRIEN")


def test_identifier_columns_survive_as_strings(vrdb_txt):
    rows = {r[0]: r for b in reader.iter_batches(vrdb_txt, schema.VOTERS) for r in b}
    cols = list(schema.VOTERS.column_names)
    reg_st_num = cols.index("RegStNum")
    zip_code = cols.index("RegZipCode")
    precinct = cols.index("PrecinctCode")
    part = cols.index("PrecinctPart")
    assert rows[9000003][reg_st_num] == "123A"
    assert rows[9000003][zip_code] == "99201-4417"
    assert rows[9000004][precinct] == "0600"
    assert rows[9000004][part] == "0600.919"
    assert rows[9000006][part] == "175-3"
    assert rows[9000007][part] == "12-A"
    assert rows[9000008][part] == "202-01"
    assert rows[9000009][part] == "2169"


def test_blank_birthyear_and_whitespace_gender_become_null(vrdb_txt):
    stats = reader.ReadStats()
    rows = {r[0]: r for b in reader.iter_batches(vrdb_txt, schema.VOTERS, stats=stats) for r in b}
    cols = list(schema.VOTERS.column_names)
    assert rows[9000003][cols.index("Birthyear")] is None
    assert rows[9000003][cols.index("Gender")] is None  # was a single space
    # An empty field is a normal NULL, not a coercion failure, so nothing is
    # counted. Both bad Birthyear values in the real 2026-08 extract are empty.
    assert stats.coerced_null == {}


def test_unparseable_value_is_counted_separately_from_blank(tmp_path):
    header = "|".join(schema.VOTING_HISTORY.column_names)
    path = tmp_path / "h.txt"
    path.write_bytes(
        ("\r\n".join([header, "1|AD|AD|notanumber|13/40/2025", "2|AD|AD||"]) + "\r\n")
        .encode("cp1252")
    )
    stats = reader.ReadStats()
    rows = [r for b in reader.iter_batches(path, schema.VOTING_HISTORY, stats=stats) for r in b]
    assert rows[0][3] is None and rows[0][4] is None  # unparseable -> NULL
    assert rows[1][3] is None and rows[1][4] is None  # blank -> NULL
    # only the unparseable row is counted, not the blank one
    assert stats.coerced_null == {"StateVoterID": 1, "ElectionDate": 1}


def test_malformed_row_is_counted_and_skipped(tmp_path):
    header = "|".join(schema.VOTING_HISTORY.column_names)
    body = "\r\n".join([
        header,
        "1|AD|AD|9000001|2025-11-04",
        "2|AD|AD|9000002",              # too few fields
        "3|AD|AD|9000003|2025-11-04",
    ]) + "\r\n"
    path = tmp_path / "h.txt"
    path.write_bytes(body.encode("cp1252"))

    stats = reader.ReadStats()
    rows = [r for b in reader.iter_batches(path, schema.VOTING_HISTORY, stats=stats) for r in b]
    assert len(rows) == 2
    assert stats.malformed == 1
    assert stats.malformed_examples == [(3, 4)]  # line 3 had 4 fields


def test_header_mismatch_raises(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"Wrong|Header\r\n1|2\r\n")
    with pytest.raises(reader.HeaderMismatch) as excinfo:
        list(reader.iter_batches(path, schema.VOTING_HISTORY))
    assert "VoterHistoryID" in str(excinfo.value)


def test_undecodable_byte_raises(tmp_path):
    path = tmp_path / "bad.txt"
    # 0x81 is unassigned in CP1252
    path.write_bytes(
        "|".join(schema.VOTING_HISTORY.column_names).encode("cp1252")
        + b"\r\n1|AD|AD|\x81|2025-11-04\r\n"
    )
    with pytest.raises(UnicodeDecodeError):
        list(reader.iter_batches(path, schema.VOTING_HISTORY))


def test_br_markers_are_normalized_for_older_extracts(tmp_path):
    header = "|".join(schema.VOTING_HISTORY.column_names)
    path = tmp_path / "old.txt"
    path.write_bytes(
        (header + "<br>1|AD|AD|9000001|2025-11-04<br/>2|AD|AD|9000002|2025-08-05<br>")
        .encode("cp1252")
    )
    rows = [r for b in reader.iter_batches(path, schema.VOTING_HISTORY) for r in b]
    assert len(rows) == 2


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 4, 5, 7, 11])
def test_line_splitting_survives_every_chunk_boundary(tmp_path, chunk_size):
    """<br>, <br/> and \\r\\n must split identically at any chunk boundary.

    carry and chunk are substituted and split together, so a tag straddling a
    read boundary is retained rather than half-matched. The default chunk is
    1 MiB, which no fixture can reach, so this drives _logical_lines directly -
    the same sanctioned coupling verify.py already relies on.
    """
    header = "|".join(schema.VOTING_HISTORY.column_names)
    body = (
        header + "<br>"
        + "1|AD|AD|9000001|2025-11-04<br/>"
        + "2|BE|BE|9000002|2025-08-05\r\n"
        + "3|KI|KI|9000003|2026-02-10<br>"
        + "4|JE|JE|9000004|2026-04-28\r\n"
    )
    path = tmp_path / "mixed.txt"
    path.write_bytes(body.encode("cp1252"))

    expected = [line for line, _ in reader._logical_lines(path, "cp1252")]
    assert len(expected) == 5  # header plus 4 data rows, no empties

    actual = [
        line
        for line, _ in reader._logical_lines(path, "cp1252", chunk_size=chunk_size)
    ]
    assert actual == expected


def test_undecodable_byte_past_a_chunk_boundary_reports_the_file_offset(tmp_path):
    """error.start comes back chunk-relative from bytes.decode().

    Reported unadjusted it is short by one full chunk for every chunk already
    read, so on the real 773 MB extract it can point up to 772 MB too early.
    """
    path = tmp_path / "bad.txt"
    header = "|".join(schema.VOTING_HISTORY.column_names).encode("cp1252")
    filler = b"1|AD|AD|9000001|2025-11-04\r\n" * 40
    body = bytearray(header + b"\r\n" + filler)
    offset = 300  # sits in the fifth 64-byte chunk, not the first
    body[offset] = 0x81  # unassigned in CP1252
    path.write_bytes(bytes(body))

    with pytest.raises(UnicodeDecodeError) as excinfo:
        list(reader._logical_lines(path, "cp1252", chunk_size=64))
    assert excinfo.value.start == offset
    assert excinfo.value.end == offset + 1
    assert "0x81" in str(excinfo.value)


@pytest.mark.parametrize("split_offset", [3, 4, 5, 6, 7])
def test_utf8_multibyte_characters_survive_a_chunk_boundary(tmp_path, split_offset):
    """A multi-byte UTF-8 character split across two chunks must decode intact.

    `chunk.decode(encoding)` per chunk is only safe for single-byte codecs; a
    stateless decode of each chunk independently would raise a spurious
    UnicodeDecodeError here because half of 'e' (2 bytes) or the em dash (3
    bytes) is, on its own, not valid UTF-8. `split_offset` walks the boundary
    through every byte of both sequences: 3-4 splits 'e', 5-7 splits the em
    dash.
    """
    marker = "café—shop"  # 'e' is 2 UTF-8 bytes, the em dash is 3
    prefix = "x" * 400
    suffix = "y" * 400
    line = prefix + marker + suffix
    body = (line + "\r\n").encode("utf-8")
    path = tmp_path / "utf8.txt"
    path.write_bytes(body)

    marker_start = len(prefix.encode("utf-8"))
    chunk_size = marker_start + split_offset  # lands inside the multi-byte run
    assert chunk_size < len(body)  # the file really does span more than one chunk

    lines = [
        text
        for text, _ in reader._logical_lines(path, "utf-8", chunk_size=chunk_size)
    ]
    assert lines == [line]


def test_truncated_utf8_sequence_at_eof_raises(tmp_path):
    """A file that ends mid-character must raise, not silently drop the byte.

    The incremental decoder buffers an incomplete trailing sequence hoping
    more bytes will complete it. `decoder.decode(b"", final=True)` after the
    read loop is what forces that buffered fragment to be judged: without it
    the truncated 'e' below would simply vanish rather than raising.
    """
    path = tmp_path / "truncated.txt"
    body = "1|AD|AD|9000001|2025-11-04\r\ncaf".encode("utf-8") + b"\xc3"  # 'e' minus its 2nd byte
    path.write_bytes(body)

    with pytest.raises(UnicodeDecodeError) as excinfo:
        list(reader._logical_lines(path, "utf-8"))
    assert excinfo.value.start == len(body) - 1
    assert "0xc3" in str(excinfo.value)


def test_cp1252_high_bytes_survive_every_chunk_size(tmp_path):
    """CP1252 is single-byte, so a chunk boundary can never split a character.

    Confirms the switch to an incremental decoder left that guarantee intact:
    byte 0xC9 and byte 0x92 decode correctly no matter where the boundary
    falls, including chunk sizes tiny enough to land right next to either
    byte.
    """
    line = "RENÉE|O’BRIEN"
    body = (line + "\r\n").encode("cp1252")
    path = tmp_path / "cp1252.txt"
    path.write_bytes(body)

    for chunk_size in range(1, len(body) + 1):
        lines = [
            text
            for text, _ in reader._logical_lines(path, "cp1252", chunk_size=chunk_size)
        ]
        assert lines == [line]
