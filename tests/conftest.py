import zipfile
from pathlib import Path

import pytest

from vrdb import schema

VOTER_HEADER = "|".join(schema.VOTERS.column_names)

# Each row is a list of 33 fields. Invented data only.
VOTER_ROWS = [
    # 0: ordinary Adams County row, dotted PrecinctPart
    ["9000001", "AVERY", "LEE", "NORTHCUTT", "", "1970", "F", "220", "", "7TH",
     "ST", "", "E", "", "", "LIND", "WA", "99341", "AD", "311", "311.1", "9",
     "5", "PO BOX 104", "", "", "LIND", "99341", "WA", "", "2018-05-01",
     "2025-11-04", "Active"],
    # 1: CP1252 high bytes - 0xC9 in RENEE, 0x92 right single quote in O'BRIEN
    ["9000002", "TESSA", "RENÉE", "O’BRIEN", "", "2001", "F", "27306",
     "", "1005", "PR", "", "S", "SE", "", "KENNEWICK", "WA", "99338", "BE",
     "5639", "5639.1", "8", "4", "", "", "", "", "", "", "", "2019-01-27",
     "2024-11-05", "Active"],
    # 2: non-integer RegStNum, ZIP+4, whitespace-only Gender, blank Birthyear
    ["9000003", "MARLO", "", "FENNIMORE", "JR", "", " ", "123A", "1/2",
     "CEDARBROOK", "LN", "APT", "", "N", "4B", "SPOKANE", "WA", "99201-4417",
     "SP", "0417", "0417.22", "3", "5", "", "", "", "", "", "", "", "1996-06-14",
     "", "Inactive"],
    # 3: King County - leading zeros in both PrecinctCode and PrecinctPart
    ["9000004", "ODELL", "RAY", "VANTASSEL", "", "1955", "M", "1400", "",
     "PINE", "AVE", "", "", "", "", "SEATTLE", "WA", "98101", "KI", "0600",
     "0600.919", "43", "7", "", "", "", "", "", "", "", "2004-03-02",
     "2026-02-10", "Active"],
    # 4: Jefferson - letter-suffixed PrecinctPart
    ["9000005", "BIRDIE", "", "HALVORSEN", "", "1988", "U", "77", "", "QUILCENE",
     "RD", "", "", "", "", "PORT TOWNSEND", "WA", "98368", "JE", "2401",
     "2401.A", "24", "6", "", "", "", "", "", "", "", "2012-08-19",
     "2025-08-05", "Active"],
    # 5: Chelan - hyphenated PrecinctPart, PrecinctCode keeps its leading zero
    ["9000006", "CASIMIR", "P", "DRUMHELLER", "", "1949", "M", "8", "",
     "ORCHARD", "WAY", "", "", "", "", "WENATCHEE", "WA", "98801", "CH", "0175",
     "175-3", "12", "8", "", "", "", "", "", "", "", "1988-10-01", "2025-11-04",
     "Active"],
    # 6: San Juan - hyphen plus letter
    ["9000007", "PERPETUA", "", "SWANBERG", "III", "1962", "O", "5", "",
     "HARBOR", "ST", "", "", "", "", "FRIDAY HARBOR", "WA", "98250", "SJ",
     "0012", "12-A", "40", "2", "", "", "", "", "", "", "", "2001-05-05",
     "2026-04-28", "Pending - Primary Only Voter"],
    # 7: Skamania - zero-padded hyphenated part
    ["9000008", "THADDEUS", "O", "KLICKITAT", "", "1993", "M", "42", "",
     "WIND RIVER", "HWY", "", "", "", "", "CARSON", "WA", "98610", "SM", "202",
     "202-01", "14", "3", "", "", "", "", "", "", "", "2015-02-02",
     "2025-04-22", "Active"],
    # 8: Pierce - PrecinctPart identical to a bare number
    ["9000009", "LURLINE", "", "PUYALLUP", "", "1979", "F", "1600", "",
     "MERIDIAN", "AVE", "", "", "E", "", "TACOMA", "WA", "98404", "PI", "2169",
     "2169", "27", "6", "", "", "", "", "", "", "", "2009-09-09", "2025-02-11",
     "Inactive"],
    # 9: blank PrecinctPart, so it cannot join to districts
    ["9000010", "EULALIE", "", "WHITMARSH", "", "1944", "F", "1", "", "MAIN",
     "ST", "", "", "", "", "YAKIMA", "WA", "98901", "YA", "", "", "15", "4",
     "", "", "", "", "", "", "", "1975-01-20", "", "Active"],
]

HISTORY_HEADER = "|".join(schema.VOTING_HISTORY.column_names)
HISTORY_ROWS = [
    ["800000001", "AD", "AD", "9000001", "2025-11-04"],
    ["800000002", "BE", "BE", "9000002", "2024-11-05"],
    ["800000003", "KI", "KI", "9000004", "2026-02-10"],
    ["800000004", "KI", "PI", "9000004", "2025-11-04"],
    ["800000005", "JE", "JE", "9000005", "2025-08-05"],
]

DISTRICT_HEADER = [
    "CountyCode", "County", "DistrictType", "DistrictCode", "DistrictName",
    "PrecinctCode", "PrecinctName", "PrecinctPart",
]
DISTRICT_ROWS = [
    ["AD", "Adams", "Fire", "FIR010008", "FIRE DISTRICT NO. 8", "311",
     "LIND CITY", "311.1"],
    ["AD", "Adams", "Cemetery", "CEM010001", "CEMETERY DISTRICT 1", "311",
     "LIND CITY", "311.1"],
    ["BE", "Benton", "School", "SCH030017", "SCHOOL DISTRICT 17", "5639",
     "KENNEWICK 39", "5639.1"],
    ["SP", "Spokane", "Library", "LIB320002", "LIBRARY DISTRICT 2", "0417",
     "SPOKANE 417", "0417.22"],
    ["KI", "King", "Port", "POR170001", "PORT OF SEATTLE", "0600",
     "SEATTLE 600", "0600.919"],
    ["JE", "Jefferson", "Fire", "FIR160001", "FIRE DISTRICT NO. 1", "2401",
     "QUILCENE", "2401.A"],
    ["CH", "Chelan", "Cemetery", "CEM040001", "CEMETERY DISTRICT NO. 1", "0175",
     "175", "175-3"],
    ["SJ", "San Juan", "Port", "POR280001", "PORT OF FRIDAY HARBOR", "0012",
     "12", "12-A"],
    ["SM", "Skamania", "School", "SCH300002", "SCHOOL DISTRICT 2", "202",
     "CARSON", "202-01"],
    ["PI", "Pierce", "Fire", "FIR270008", "FIRE DISTRICT NO. 8", "2169",
     "TACOMA 2169", "2169"],
]


def _write_pipe_file(path: Path, header: str, rows) -> Path:
    """Write a CP1252, CRLF, pipe-delimited file the way the SOS ships them."""
    body = "\r\n".join([header] + ["|".join(r) for r in rows]) + "\r\n"
    path.write_bytes(body.encode("cp1252"))
    return path


@pytest.fixture
def vrdb_txt(tmp_path: Path) -> Path:
    return _write_pipe_file(
        tmp_path / "20260803_VRDB_Extract.txt", VOTER_HEADER, VOTER_ROWS
    )


@pytest.fixture
def history_txt(tmp_path: Path) -> Path:
    return _write_pipe_file(
        tmp_path / "2025-2026_Voting_History_20260601.txt",
        HISTORY_HEADER,
        HISTORY_ROWS,
    )


def _cell_xml(ref: str, value: str, shared: dict, *, omit_ref: bool = False) -> str:
    attribute = "" if omit_ref else f' r="{ref}"'
    if value == "":
        return f"<c{attribute}/>"
    idx = shared.setdefault(value, len(shared))
    return f'<c{attribute} t="s"><v>{idx}</v></c>'


def build_xlsx(path: Path, header, rows, *, blank_rows: int = 0, row_gap: int = 0,
               omit_refs: bool = False) -> Path:
    """Build a minimal xlsx.

    `blank_rows` appends fully empty <row> elements, and `row_gap` skips that
    many row numbers before them, reproducing the two quirks in the real
    Districts-Precincts workbook. `omit_refs` drops the r= attribute from every
    cell, which OOXML permits and some streaming writers do.
    """
    shared: dict[str, int] = {}
    xml_rows = []
    for r_index, row in enumerate([header] + list(rows), start=1):
        cells = "".join(
            _cell_xml(f"{chr(ord('A') + c)}{r_index}", v, shared, omit_ref=omit_refs)
            for c, v in enumerate(row)
        )
        xml_rows.append(f'<row r="{r_index}">{cells}</row>')

    next_row = len(rows) + 2 + row_gap
    for i in range(blank_rows):
        xml_rows.append(f'<row r="{next_row + i}"/>')

    last_row = next_row + blank_rows
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:H{last_row}"/>'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        "</worksheet>"
    )
    ordered = sorted(shared.items(), key=lambda kv: kv[1])
    strings = "".join(f"<si><t>{v}</t></si>" for v, _ in ordered)
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(ordered)}" uniqueCount="{len(ordered)}">{strings}</sst>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "</sheets></workbook>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", shared_xml)
    return path


@pytest.fixture
def districts_xlsx(tmp_path: Path) -> Path:
    return build_xlsx(
        tmp_path / "2026-08-03_Districts-Precincts.xlsx",
        DISTRICT_HEADER,
        DISTRICT_ROWS,
        blank_rows=3,
        row_gap=5,
    )


@pytest.fixture
def extract_dir(vrdb_txt: Path, history_txt: Path, districts_xlsx: Path) -> Path:
    """A folder holding all three files, as an extract ships."""
    return vrdb_txt.parent
