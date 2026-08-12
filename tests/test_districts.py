import pytest

from vrdb import districts, reader, schema
from tests.conftest import DISTRICT_HEADER, DISTRICT_ROWS, build_xlsx


def test_iter_rows_returns_header_then_data(districts_xlsx):
    rows = list(districts.iter_rows(districts_xlsx))
    assert rows[0] == DISTRICT_HEADER
    assert len(rows) == 11  # header + 10 district rows


def test_all_empty_rows_are_skipped(districts_xlsx):
    # the fixture appends 3 fully blank <row> elements after a 5-row gap
    rows = list(districts.iter_rows(districts_xlsx))
    assert all(any(cell for cell in r) for r in rows)


def test_declared_dimension_is_not_trusted(tmp_path):
    # The real workbook declares A1:H237379 but holds 231,537 data rows.
    path = build_xlsx(
        tmp_path / "d.xlsx", DISTRICT_HEADER,
        [["AD", "Adams", "Fire", "F1", "FIRE 1", "311", "LIND", "311.1"]],
        blank_rows=50, row_gap=100,
    )
    assert len(list(districts.iter_rows(path))) == 2


def test_shared_strings_resolve(districts_xlsx):
    rows = list(districts.iter_rows(districts_xlsx))
    assert rows[1][4] == "FIRE DISTRICT NO. 8"


def test_absent_cells_become_empty_strings(tmp_path):
    path = build_xlsx(
        tmp_path / "d.xlsx", DISTRICT_HEADER,
        [["AD", "", "Fire", "", "FIRE 1", "311", "", "311.1"]],
    )
    assert list(districts.iter_rows(path))[1] == [
        "AD", "", "Fire", "", "FIRE 1", "311", "", "311.1"
    ]


def test_cells_without_an_r_attribute_are_positional(tmp_path):
    """OOXML lets a cell omit r=; it then sits after the previous cell.

    Passing the missing attribute straight into _column_index raised TypeError,
    not the diagnosable ValueError. Pyright could not see it because typeshed
    types ET.iterparse as Iterator[tuple[str, Any]].
    """
    path = build_xlsx(
        tmp_path / "no_refs.xlsx", DISTRICT_HEADER, DISTRICT_ROWS, omit_refs=True
    )
    rows = list(districts.iter_rows(path))
    assert rows[0] == DISTRICT_HEADER
    assert rows[1] == DISTRICT_ROWS[0]
    assert len(rows) == 11


def test_malformed_cell_reference_raises_a_diagnosable_error():
    with pytest.raises(ValueError, match="malformed cell reference"):
        districts._column_index("1A")


def test_iter_batches_yields_coerced_rows(districts_xlsx):
    stats = reader.ReadStats()
    rows = [
        r
        for b in districts.iter_batches(
            districts_xlsx, schema.DISTRICTS_PRECINCTS, stats=stats
        )
        for r in b
    ]
    assert len(rows) == 10
    assert stats.rows == 10
    assert rows[0][0] == "AD"


def test_content_past_the_last_column_is_counted_and_skipped(tmp_path):
    """A ninth populated column means the workbook layout changed.

    `if index >= width: continue` used to discard that cell in silence, and
    stats.malformed was never incremented by this reader at all, so
    check_no_malformed_rows reported a PASS that could not fail.
    """
    wide = list(DISTRICT_ROWS[0]) + ["SURPRISE"]
    path = build_xlsx(
        tmp_path / "wide.xlsx", DISTRICT_HEADER, [wide] + DISTRICT_ROWS[1:]
    )
    stats = reader.ReadStats()
    rows = [
        r
        for b in districts.iter_batches(
            path, schema.DISTRICTS_PRECINCTS, stats=stats
        )
        for r in b
    ]
    assert stats.malformed == 1
    assert stats.malformed_examples == [(2, 9)]  # sheet row 2, 9 populated columns
    assert stats.rows == 9
    assert len(rows) == 9


def test_an_empty_cell_past_the_last_column_is_not_malformed(tmp_path):
    """Only content counts. A trailing empty cell is not a layout change."""
    padded = list(DISTRICT_ROWS[0]) + [""]
    path = build_xlsx(tmp_path / "padded.xlsx", DISTRICT_HEADER, [padded])
    stats = reader.ReadStats()
    rows = [
        r
        for b in districts.iter_batches(
            path, schema.DISTRICTS_PRECINCTS, stats=stats
        )
        for r in b
    ]
    assert stats.malformed == 0
    assert len(rows) == 1


def test_all_empty_rows_are_skipped_without_counting_as_malformed(districts_xlsx):
    """The real workbook holds 2,249 of these by design."""
    stats = reader.ReadStats()
    list(districts.iter_batches(districts_xlsx, schema.DISTRICTS_PRECINCTS, stats=stats))
    assert stats.malformed == 0
    assert stats.rows == 10


def test_every_precinctpart_format_survives_unmodified(districts_xlsx):
    rows = [
        r
        for b in districts.iter_batches(districts_xlsx, schema.DISTRICTS_PRECINCTS)
        for r in b
    ]
    parts = {r[7] for r in rows}
    assert {"311.1", "5639.1", "0417.22", "0600.919", "2401.A",
            "175-3", "12-A", "202-01", "2169"} <= parts


def test_reordered_header_raises(tmp_path):
    """A swapped column pair used to load silently.

    check_districts_join only exercises (CountyCode, PrecinctPart), so
    swapping DistrictName and PrecinctName passed every check at full join
    coverage while every district filter returned the wrong voters.
    """
    swapped = list(DISTRICT_HEADER)
    name, precinct = swapped.index("DistrictName"), swapped.index("PrecinctName")
    swapped[name], swapped[precinct] = swapped[precinct], swapped[name]
    path = build_xlsx(tmp_path / "swapped.xlsx", swapped, DISTRICT_ROWS)

    with pytest.raises(reader.HeaderMismatch) as excinfo:
        list(districts.iter_batches(path, schema.DISTRICTS_PRECINCTS))
    assert "DistrictName" in str(excinfo.value)


def test_missing_column_in_header_raises(tmp_path):
    renamed = list(DISTRICT_HEADER)
    renamed[7] = "PrecinctPartId"
    path = build_xlsx(tmp_path / "renamed.xlsx", renamed, DISTRICT_ROWS)
    with pytest.raises(reader.HeaderMismatch):
        list(districts.iter_batches(path, schema.DISTRICTS_PRECINCTS))


def test_empty_workbook_yields_nothing(tmp_path):
    path = build_xlsx(tmp_path / "empty.xlsx", DISTRICT_HEADER, [])
    assert list(districts.iter_batches(path, schema.DISTRICTS_PRECINCTS)) == []


def test_batching(districts_xlsx):
    batches = list(
        districts.iter_batches(
            districts_xlsx, schema.DISTRICTS_PRECINCTS, batch_size=3
        )
    )
    assert [len(b) for b in batches] == [3, 3, 3, 1]
