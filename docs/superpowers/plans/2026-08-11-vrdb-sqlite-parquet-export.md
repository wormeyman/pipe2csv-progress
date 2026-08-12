# VRDB SQLite + Parquet Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load a monthly Washington VRDB extract (voters, voting history, districts-to-precincts) into one typed, indexed SQLite database and a matching set of Parquet files, with verification against the source.

**Architecture:** A `vrdb/` package split by responsibility: `schema.py` holds the single source of truth for columns, types and indexes and depends only on the stdlib; `reader.py` and `districts.py` turn source files into batches of coerced Python rows through an identical interface; `sqlite_out.py` and `parquet_out.py` consume batches and know nothing about parsing; `verify.py` re-reads the sources to check the outputs; `vrdb_export.py` wires them together. `to_csv_progress.py` is not touched.

**Tech Stack:** Python 3.14.6, pyarrow 25.0.1 (only runtime dependency), stdlib `sqlite3`, `zipfile` and `xml.etree.ElementTree` for xlsx, pytest for tests, pandas + jupyterlab for the notebook only.

**Spec:** `docs/superpowers/specs/2026-08-11-vrdb-sqlite-parquet-export-design.md`

## Global Constraints

- Python 3.14.6; create the venv with `uv venv`. Runtime dependency is `pyarrow==25.0.1` only. Notebook extra: `pandas==3.0.5`, `jupyterlab==4.6.3`, `matplotlib==3.11.1` (the age-distribution cell plots). Dev extra: `pytest`.
- `to_csv_progress.py` must not be modified. It stays stdlib-only.
- No package directory may be named `lib` - `.gitignore` already contains `lib/`.
- `schema.py` must not import pyarrow. Kind-to-Arrow mapping lives in `parquet_out.py`.
- **No real voter data in any test fixture or committed file.** Fixtures are generated at test time into `tmp_path` with invented names and IDs.
- This repo is public. Voter data outputs must never be committable.
- Source encoding is `cp1252`, not `latin-1`. Real rows contain byte `0x92` (`O'BRIEN` uses a right single quote) which is a right single quote in CP1252 but an unassigned control character in Latin-1.
- `PrecinctCode` and `PrecinctPart` are TEXT and are matched as literal strings. Never parse, normalize, or numerically cast them.
- Dates are stored as ISO `YYYY-MM-DD` TEXT in SQLite and as `date32` in Parquet.
- Empty and whitespace-only fields become NULL.
- Use hyphens, not em dashes or en dashes, in all files.
- Reader batch size default: 50,000 rows.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependency groups |
| `.gitignore` | Modified: exclude all voter-data file types |
| `vrdb/__init__.py` | Empty package marker |
| `vrdb/schema.py` | Column names, kinds, primary keys, index definitions, reference code tables. Stdlib only. |
| `vrdb/progress.py` | Rows/rate/percent/ETA reporter, matching `to_csv_progress.py` output style |
| `vrdb/reader.py` | Streaming CP1252 pipe-delimited reader, value coercion, read statistics |
| `vrdb/districts.py` | Streaming xlsx reader over `xl/worksheets/sheet1.xml` |
| `vrdb/sqlite_out.py` | Typed table creation, bulk insert, index creation, reference tables |
| `vrdb/parquet_out.py` | Kind-to-Arrow mapping, batch writing |
| `vrdb/discover.py` | Find the three files in a folder, derive the extract date |
| `vrdb/verify.py` | Post-load checks against the source files |
| `vrdb_export.py` | CLI entry point |
| `tests/conftest.py` | Generates synthetic fixtures into `tmp_path` |
| `tests/test_*.py` | One test module per `vrdb/` module |
| `notebooks/vrdb_explore.ipynb` | Starter analysis notebook |
| `README.md` | Modified: new tool section and data-protection notice |

---

### Task 1: Project scaffolding, venv, and data protection

**Files:**
- Create: `pyproject.toml`
- Create: `vrdb/__init__.py`
- Create: `tests/__init__.py`
- Modify: `.gitignore` (append a new section at end of file)

**Interfaces:**
- Consumes: nothing
- Produces: an installed venv at `.venv/`, an importable `vrdb` package, a working `pytest` command

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "vrdb-export"
version = "0.1.0"
description = "Load Washington VRDB extracts into SQLite and Parquet"
requires-python = ">=3.12"
dependencies = ["pyarrow==25.0.1"]

[project.optional-dependencies]
notebook = ["pandas==3.0.5", "jupyterlab==4.6.3", "matplotlib==3.11.1"]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["vrdb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the empty package markers**

Create `vrdb/__init__.py` and `tests/__init__.py`, both empty files.

- [ ] **Step 3: Create the venv and install**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
uv venv --python 3.14
uv pip install -e ".[notebook,dev]"
```

- [ ] **Step 4: Verify the venv works**

```bash
.venv/bin/python -c "import pyarrow, vrdb; print(pyarrow.__version__)"
```
Expected: `25.0.1`

- [ ] **Step 5: Append the data-protection section to `.gitignore`**

Append these lines to the end of the existing `.gitignore`:

```gitignore

# --- Voter data protection (RCW 29A.08.720 / 29A.08.740) ---
# This repo is public. VRDB extracts and anything derived from them are
# regulated data and must never be committed. Test fixtures are generated at
# test time into tmp_path, so nothing here needs an exception.
*.sqlite
*.sqlite3
*.db
*.parquet
*.txt
*.csv
*.xlsx
*.xls
*.zip
```

- [ ] **Step 6: Verify the ignore rules actually bite**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
touch /tmp/probe.sqlite && cp /tmp/probe.sqlite ./probe.sqlite
git check-ignore -v probe.sqlite
rm probe.sqlite
git status --short
```
Expected: `check-ignore` prints the matching `.gitignore` line; `git status --short` shows no untracked data file.

- [ ] **Step 7: Verify pytest runs**

```bash
.venv/bin/pytest -q
```
Expected: `no tests ran` (exit code 5). This confirms pytest is wired up.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml vrdb/__init__.py tests/__init__.py .gitignore
git commit -m "chore: scaffold vrdb package, venv config, and voter-data gitignore rules"
```

---

### Task 2: Schema definitions

**Files:**
- Create: `vrdb/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `KIND_TEXT = "text"`, `KIND_INT = "int"`, `KIND_DATE = "date"`
  - `Column(name: str, kind: str, primary_key: bool = False)` frozen dataclass
  - `Table(name: str, columns: tuple[Column, ...], indexes: tuple[Index, ...])` frozen dataclass, with properties `column_names -> tuple[str, ...]` and `primary_key -> Column | None`
  - `Index(name: str, columns: tuple[str, ...])` frozen dataclass
  - `VOTERS: Table`, `VOTING_HISTORY: Table`, `DISTRICTS_PRECINCTS: Table`
  - `ALL_TABLES: tuple[Table, ...]`
  - `sqlite_type(kind: str) -> str`
  - `COUNTY_CODES: dict[str, str]`, `GENDER_CODES: dict[str, str]`, `STATUS_CODES: dict[str, str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schema.py`:

```python
from vrdb import schema


def test_voters_has_33_columns_in_source_order():
    assert len(schema.VOTERS.columns) == 33
    assert schema.VOTERS.column_names[0] == "StateVoterID"
    assert schema.VOTERS.column_names[5] == "Birthyear"
    assert schema.VOTERS.column_names[32] == "StatusCode"


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
    assert schema.VOTERS.primary_key.name == "StateVoterID"
    assert schema.VOTING_HISTORY.primary_key.name == "VoterHistoryID"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schema.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.schema'`

- [ ] **Step 3: Write `vrdb/schema.py`**

```python
"""Single source of truth for VRDB table shapes.

Stdlib only on purpose: this module must stay importable without pyarrow so
the readers and SQLite writer can be tested independently. The kind-to-Arrow
mapping lives in parquet_out.py.

Column names and order follow the actual extract headers, not
"VRDB Database Fields 2.pdf", which is wrong in three places (see the design
spec).
"""

from dataclasses import dataclass

KIND_TEXT = "text"
KIND_INT = "int"
KIND_DATE = "date"

_SQLITE_TYPES = {KIND_TEXT: "TEXT", KIND_INT: "INTEGER", KIND_DATE: "TEXT"}


def sqlite_type(kind: str) -> str:
    """SQLite declared type for a column kind.

    Dates are TEXT: SQLite has no date type, and ISO YYYY-MM-DD strings sort
    and compare correctly with <, BETWEEN and date().
    """
    try:
        return _SQLITE_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown column kind: {kind!r}") from None


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    primary_key: bool = False


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    indexes: tuple[Index, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def primary_key(self) -> Column | None:
        for c in self.columns:
            if c.primary_key:
                return c
        return None


def _t(name: str) -> Column:
    return Column(name, KIND_TEXT)


VOTERS = Table(
    name="voters",
    columns=(
        Column("StateVoterID", KIND_INT, primary_key=True),
        _t("FName"),
        _t("MName"),
        _t("LName"),
        _t("NameSuffix"),
        Column("Birthyear", KIND_INT),
        _t("Gender"),
        _t("RegStNum"),  # 23,093 rows like "123A"
        _t("RegStFrac"),
        _t("RegStName"),
        _t("RegStType"),
        _t("RegUnitType"),
        _t("RegStPreDirection"),
        _t("RegStPostDirection"),
        _t("RegStUnitNum"),
        _t("RegCity"),
        _t("RegState"),
        _t("RegZipCode"),  # ZIP+4 present
        _t("CountyCode"),
        _t("PrecinctCode"),  # leading zeros significant
        _t("PrecinctPart"),  # format varies by county, match literally
        Column("LegislativeDistrict", KIND_INT),
        Column("CongressionalDistrict", KIND_INT),
        _t("Mail1"),
        _t("Mail2"),
        _t("Mail3"),  # always empty in the 2026-08 extract
        _t("MailCity"),
        _t("MailZip"),
        _t("MailState"),
        _t("MailCountry"),
        Column("Registrationdate", KIND_DATE),
        Column("LastVoted", KIND_DATE),
        _t("StatusCode"),
    ),
    indexes=(
        Index("idx_voters_county", ("CountyCode",)),
        Index("idx_voters_status", ("StatusCode",)),
        Index("idx_voters_precinct", ("CountyCode", "PrecinctCode")),
        Index("idx_voters_precinctpart", ("CountyCode", "PrecinctPart")),
        Index("idx_voters_legislative", ("LegislativeDistrict",)),
        Index("idx_voters_congressional", ("CongressionalDistrict",)),
        Index("idx_voters_lastvoted", ("LastVoted",)),
        Index("idx_voters_name", ("LName", "FName")),
    ),
)

VOTING_HISTORY = Table(
    name="voting_history",
    columns=(
        Column("VoterHistoryID", KIND_INT, primary_key=True),
        _t("CountyCode"),
        _t("CountyCode_Voting"),
        Column("StateVoterID", KIND_INT),
        Column("ElectionDate", KIND_DATE),
    ),
    indexes=(
        Index("idx_vh_statevoterid", ("StateVoterID",)),
        Index("idx_vh_electiondate", ("ElectionDate",)),
    ),
)

DISTRICTS_PRECINCTS = Table(
    name="districts_precincts",
    columns=(
        _t("CountyCode"),
        _t("County"),
        _t("DistrictType"),
        _t("DistrictCode"),
        _t("DistrictName"),
        _t("PrecinctCode"),
        _t("PrecinctName"),
        _t("PrecinctPart"),
    ),
    indexes=(
        Index("idx_dp_precinctpart", ("CountyCode", "PrecinctPart")),
        Index("idx_dp_districtname", ("DistrictName",)),
    ),
)

ALL_TABLES = (VOTERS, VOTING_HISTORY, DISTRICTS_PRECINCTS)

COUNTY_CODES = {
    "AD": "Adams", "AS": "Asotin", "BE": "Benton", "CH": "Chelan",
    "CM": "Clallam", "CR": "Clark", "CU": "Columbia", "CZ": "Cowlitz",
    "DG": "Douglas", "FE": "Ferry", "FR": "Franklin", "GA": "Garfield",
    "GR": "Grant", "GY": "Grays Harbor", "IS": "Island", "JE": "Jefferson",
    "KI": "King", "KP": "Kitsap", "KS": "Kittitas", "KT": "Klickitat",
    "LE": "Lewis", "LI": "Lincoln", "MA": "Mason", "OK": "Okanogan",
    "PA": "Pacific", "PE": "Pend Oreille", "PI": "Pierce", "SJ": "San Juan",
    "SK": "Skagit", "SM": "Skamania", "SN": "Snohomish", "SP": "Spokane",
    "ST": "Stevens", "TH": "Thurston", "WK": "Wahkiakum", "WL": "Walla Walla",
    "WM": "Whatcom", "WT": "Whitman", "YA": "Yakima",
}

GENDER_CODES = {
    "M": "Male",
    "F": "Female",
    "U": "Unknown/Not Provided",
    "O": "Other",
}

STATUS_CODES = {
    "Active": "",
    "Inactive": "See RCW 29A.08.620 for reasons a voter would be assigned inactive status",
    "Pending - Primary Only Voter": (
        "17 on the day of the primary but 18 on or before the following November "
        "general election; may vote in primaries only"
    ),
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_schema.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/schema.py tests/test_schema.py
git commit -m "feat: add VRDB schema definitions with types, indexes and code tables"
```

---

### Task 3: Progress reporter

**Files:**
- Create: `vrdb/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Progress(label: str, total_bytes: int | None, tick: int = 100_000, stream=sys.stderr, clock=time.monotonic)` with methods `update(rows: int, bytes_read: int) -> None` and `finish(rows: int) -> None`, and module function `human(n: float) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_progress.py`:

```python
import io

from vrdb.progress import Progress, human


def test_human_scales_units():
    assert human(950) == "950"
    assert human(1500) == "2K"
    assert human(2_500_000) == "2M"


def test_update_prints_only_on_tick_boundary():
    out = io.StringIO()
    clock = iter([0.0, 1.0, 2.0, 3.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.update(rows=50, bytes_read=100)
    assert out.getvalue() == ""
    p.update(rows=100, bytes_read=500)
    assert "rows=100" in out.getvalue()


def test_update_reports_percent_and_eta():
    out = io.StringIO()
    clock = iter([0.0, 10.0, 20.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.update(rows=100, bytes_read=250)
    line = out.getvalue()
    assert "25.0%" in line
    # 10s consumed 25%, so ~30s remain
    assert "ETA 00:00:30" in line


def test_unknown_total_bytes_omits_percent_and_eta():
    out = io.StringIO()
    clock = iter([0.0, 1.0, 2.0]).__next__
    p = Progress("voters", total_bytes=None, tick=100, stream=out, clock=clock)
    p.update(rows=100, bytes_read=0)
    line = out.getvalue()
    assert "%" not in line
    assert "ETA" not in line


def test_finish_reports_total_and_rate():
    out = io.StringIO()
    clock = iter([0.0, 4.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.finish(rows=2000)
    line = out.getvalue()
    assert "2,000" in line
    assert "500" in line  # 2000 rows / 4s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_progress.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.progress'`

- [ ] **Step 3: Write `vrdb/progress.py`**

```python
"""Progress reporting in the same style as to_csv_progress.py."""

import sys
import time


def human(n: float) -> str:
    for unit in ("", "K", "M", "B"):
        if abs(n) < 1000:
            return f"{n:.0f}{unit}"
        n /= 1000.0
    return f"{n:.1f}T"


class Progress:
    """Prints rows, rate, percent and ETA every `tick` rows.

    `clock` is injectable so tests do not depend on wall time.
    """

    def __init__(self, label, total_bytes=None, tick=100_000, stream=None, clock=time.monotonic):
        self.label = label
        self.total_bytes = total_bytes
        self.tick = tick
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock
        self.start = clock()
        self._next_tick = tick

    def _elapsed(self) -> float:
        return max(self.clock() - self.start, 1e-6)

    def update(self, rows: int, bytes_read: int) -> None:
        if rows < self._next_tick:
            return
        self._next_tick = ((rows // self.tick) + 1) * self.tick
        elapsed = self._elapsed()
        rate = rows / elapsed
        pct = eta = ""
        if self.total_bytes and bytes_read > 0:
            fraction = bytes_read / self.total_bytes
            pct = f" {fraction * 100:5.1f}%"
            remaining = max(elapsed / fraction - elapsed, 0)
            eta = (
                f" ETA {int(remaining // 3600):02d}:"
                f"{int((remaining % 3600) // 60):02d}:"
                f"{int(remaining % 60):02d}"
            )
        print(
            f"[{self.label}] rows={human(rows)} rate={rate:,.0f}/s{pct}{eta}",
            file=self.stream,
            flush=True,
        )

    def finish(self, rows: int) -> None:
        elapsed = self._elapsed()
        rate = rows / elapsed
        print(
            f"[{self.label}] done: {rows:,} rows in {elapsed:,.1f}s ({rate:,.0f}/s)",
            file=self.stream,
            flush=True,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_progress.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/progress.py tests/test_progress.py
git commit -m "feat: add progress reporter with rate, percent and ETA"
```

---

### Task 4: Synthetic test fixtures

**Files:**
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing
- Produces: pytest fixtures `vrdb_txt(tmp_path) -> Path`, `history_txt(tmp_path) -> Path`, `districts_xlsx(tmp_path) -> Path`, `extract_dir(tmp_path) -> Path`. All data is invented.

- [ ] **Step 1: Write `tests/conftest.py`**

Every name, ID and address below is invented. The shapes reproduce real edge cases: CRLF endings, CP1252 high bytes, empty and whitespace-only fields, a non-integer `RegStNum`, a ZIP+4, a leading-zero `PrecinctCode`, an unparseable `Birthyear`, and all seven `PrecinctPart` formats.

```python
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


def _cell_xml(ref: str, value: str, shared: dict) -> str:
    if value == "":
        return f'<c r="{ref}"/>'
    idx = shared.setdefault(value, len(shared))
    return f'<c r="{ref}" t="s"><v>{idx}</v></c>'


def build_xlsx(path: Path, header, rows, *, blank_rows: int = 0, row_gap: int = 0) -> Path:
    """Build a minimal xlsx.

    `blank_rows` appends fully empty <row> elements, and `row_gap` skips that
    many row numbers before them, reproducing the two quirks in the real
    Districts-Precincts workbook.
    """
    shared: dict[str, int] = {}
    xml_rows = []
    for r_index, row in enumerate([header] + list(rows), start=1):
        cells = "".join(
            _cell_xml(f"{chr(ord('A') + c)}{r_index}", v, shared)
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
```

- [ ] **Step 2: Verify the fixtures build**

Create a scratch check and run it, then delete it:

```bash
.venv/bin/python - <<'PY'
import tempfile, zipfile, pathlib, sys
sys.path.insert(0, "tests")
from conftest import _write_pipe_file, build_xlsx, VOTER_HEADER, VOTER_ROWS, DISTRICT_HEADER, DISTRICT_ROWS
d = pathlib.Path(tempfile.mkdtemp())
p = _write_pipe_file(d / "v.txt", VOTER_HEADER, VOTER_ROWS)
raw = p.read_bytes()
assert b"\r\n" in raw, "expected CRLF"
assert b"\x92" in raw, "expected CP1252 right single quote"
assert b"\xc9" in raw, "expected CP1252 E-acute"
assert raw.decode("cp1252").splitlines()[0].count("|") == 32
x = build_xlsx(d / "d.xlsx", DISTRICT_HEADER, DISTRICT_ROWS, blank_rows=3, row_gap=5)
with zipfile.ZipFile(x) as z:
    assert "xl/sharedStrings.xml" in z.namelist()
print("fixtures OK")
PY
```
Expected: `fixtures OK`

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add synthetic VRDB, history and xlsx fixtures with real-world edge cases"
```

---

### Task 5: Pipe-delimited streaming reader

**Files:**
- Create: `vrdb/reader.py`
- Test: `tests/test_reader.py`

**Interfaces:**
- Consumes: `vrdb.schema` (`Table`, `KIND_*`), `vrdb.progress.Progress`
- Produces:
  - `ReadStats` dataclass: `rows: int`, `malformed: int`, `malformed_examples: list[tuple[int, int]]`, `coerced_null: dict[str, int]`
  - `coerce(value: str, kind: str) -> str | int | None`
  - `read_header(path: Path, encoding: str = "cp1252") -> list[str]`
  - `iter_batches(path, table, *, encoding="cp1252", batch_size=50_000, stats=None, progress=None) -> Iterator[list[list]]`
  - `HeaderMismatch(Exception)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reader.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reader.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.reader'`

- [ ] **Step 3: Write `vrdb/reader.py`**

```python
"""Streaming reader for the SOS pipe-delimited extracts.

The files are CP1252, CRLF, pipe-delimited, with a header row. CP1252 matters:
real rows contain byte 0x92, a right single quote in CP1252 but an unassigned
control character in Latin-1.

Older extracts used literal <br> markers instead of line breaks, so those are
normalized too. The 2026-08 extract contains none.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vrdb import schema

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


class HeaderMismatch(Exception):
    """The file's header does not match the expected table."""


@dataclass
class ReadStats:
    rows: int = 0
    malformed: int = 0
    malformed_examples: list = field(default_factory=list)
    coerced_null: dict = field(default_factory=dict)


def coerce(value: str, kind: str):
    """Convert one raw field to its stored form, or None.

    Empty and whitespace-only fields become NULL. This folds away the Gender
    column's single-space value, which would otherwise be its own GROUP BY
    bucket.
    """
    value = value.strip()
    if not value:
        return None
    if kind == schema.KIND_TEXT:
        return value
    if kind == schema.KIND_INT:
        try:
            return int(value)
        except ValueError:
            return None
    if kind == schema.KIND_DATE:
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    raise ValueError(f"unknown column kind: {kind!r}")


def _logical_lines(path: Path, encoding: str, chunk_size: int = 1 << 20):
    """Yield (line, bytes_read) for each non-empty logical line."""
    bytes_read = 0
    with open(path, "rb") as handle:
        carry = ""
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            carry = _BR.sub("\n", carry + chunk.decode(encoding))
            *lines, carry = carry.split("\n")
            for line in lines:
                line = line.rstrip("\r")
                if line:
                    yield line, bytes_read
        carry = carry.rstrip("\r\n")
        if carry:
            yield carry, bytes_read


def read_header(path: Path, encoding: str = "cp1252") -> list[str]:
    for line, _ in _logical_lines(path, encoding):
        return [c.strip() for c in line.split("|")]
    return []


def iter_batches(
    path,
    table: schema.Table,
    *,
    encoding: str = "cp1252",
    batch_size: int = 50_000,
    stats: ReadStats | None = None,
    progress=None,
):
    """Yield lists of coerced rows, one list per batch.

    Rows whose field count does not match the table are counted in `stats` and
    skipped rather than aborting the load.
    """
    path = Path(path)
    stats = stats if stats is not None else ReadStats()
    kinds = [c.kind for c in table.columns]
    names = list(table.column_names)
    width = len(names)

    lines = _logical_lines(path, encoding)
    try:
        header_line, _ = next(lines)
    except StopIteration:
        return
    header = [c.strip() for c in header_line.split("|")]
    if header != names:
        raise HeaderMismatch(
            f"{path.name}: expected columns {names}, found {header}"
        )

    batch = []
    line_no = 1
    for line, bytes_read in lines:
        line_no += 1
        fields = line.split("|")
        if len(fields) != width:
            stats.malformed += 1
            if len(stats.malformed_examples) < 10:
                stats.malformed_examples.append((line_no, len(fields)))
            continue
        row = []
        for name, kind, raw in zip(names, kinds, fields):
            value = coerce(raw, kind)
            if value is None and raw.strip() and kind != schema.KIND_TEXT:
                stats.coerced_null[name] = stats.coerced_null.get(name, 0) + 1
            row.append(value)
        batch.append(row)
        stats.rows += 1
        if len(batch) >= batch_size:
            yield batch
            batch = []
        if progress is not None:
            progress.update(stats.rows, bytes_read)
    if batch:
        yield batch
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reader.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/reader.py tests/test_reader.py
git commit -m "feat: add streaming CP1252 pipe reader with coercion and read stats"
```

---

### Task 6: Districts xlsx reader

**Files:**
- Create: `vrdb/districts.py`
- Test: `tests/test_districts.py`

**Interfaces:**
- Consumes: `vrdb.schema`, `vrdb.reader.ReadStats`
- Produces:
  - `iter_rows(path) -> Iterator[list[str]]` - every non-empty sheet row including the header, cells as strings
  - `iter_batches(path, table, *, batch_size=50_000, stats=None, progress=None) -> Iterator[list[list]]` - same shape as `reader.iter_batches`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_districts.py`:

```python
from vrdb import districts, reader, schema
from tests.conftest import DISTRICT_HEADER, build_xlsx


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


def test_every_precinctpart_format_survives_unmodified(districts_xlsx):
    rows = [
        r
        for b in districts.iter_batches(districts_xlsx, schema.DISTRICTS_PRECINCTS)
        for r in b
    ]
    parts = {r[7] for r in rows}
    assert {"311.1", "5639.1", "0417.22", "0600.919", "2401.A",
            "175-3", "12-A", "202-01", "2169"} <= parts


def test_batching(districts_xlsx):
    batches = list(
        districts.iter_batches(
            districts_xlsx, schema.DISTRICTS_PRECINCTS, batch_size=3
        )
    )
    assert [len(b) for b in batches] == [3, 3, 3, 1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_districts.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.districts'`

- [ ] **Step 3: Write `vrdb/districts.py`**

```python
"""Streaming reader for the Districts-Precincts workbook.

Trust boundary: the input is a workbook the operator downloaded from the WA
Secretary of State and already opens in Excel, parsed locally. stdlib
ElementTree is fine for that. If this ever ingests workbooks from untrusted
senders, swap the import for defusedxml.ElementTree, which is a drop-in and
blocks entity-expansion attacks that stdlib ElementTree does not.

Stdlib only. The real workbook declares dimension A1:H237379 but holds 231,537
data rows: 3,592 row numbers have no element at all, and 2,249 of the elements
that do exist are entirely empty. Trusting `dimension`, or emitting one row per
<row> element, invents phantom all-null district rows. So: never read the
declared dimension, and skip rows where every cell is empty.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from vrdb import reader, schema

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL = re.compile(r"[A-Z]+")


def _column_index(ref: str) -> int:
    """'A1' -> 0, 'H12' -> 7, 'AA3' -> 26."""
    letters = _COL.match(ref).group(0)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in root]


def iter_rows(path, width: int = 8):
    """Yield each non-empty sheet row as a list of `width` strings."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        strings = _shared_strings(archive)
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            for _, element in ET.iterparse(sheet, events=("end",)):
                if element.tag != _NS + "row":
                    continue
                cells = [""] * width
                for cell in element.iter(_NS + "c"):
                    index = _column_index(cell.get("r"))
                    if index >= width:
                        continue
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(_NS + "t"))
                    else:
                        node = cell.find(_NS + "v")
                        if node is None or node.text is None:
                            value = ""
                        elif kind == "s":
                            value = strings[int(node.text)]
                        else:
                            value = node.text
                    cells[index] = value
                element.clear()
                if any(cells):
                    yield cells


def iter_batches(
    path,
    table: schema.Table = schema.DISTRICTS_PRECINCTS,
    *,
    batch_size: int = 50_000,
    stats: reader.ReadStats | None = None,
    progress=None,
):
    """Yield lists of coerced rows, matching reader.iter_batches."""
    stats = stats if stats is not None else reader.ReadStats()
    kinds = [c.kind for c in table.columns]
    width = len(kinds)

    rows = iter_rows(path, width=width)
    next(rows, None)  # discard the header

    batch = []
    for cells in rows:
        batch.append([reader.coerce(v, k) for v, k in zip(cells, kinds)])
        stats.rows += 1
        if len(batch) >= batch_size:
            yield batch
            batch = []
        if progress is not None:
            progress.update(stats.rows, 0)
    if batch:
        yield batch
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_districts.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/districts.py tests/test_districts.py
git commit -m "feat: add stdlib xlsx reader that skips phantom rows and gaps"
```

---

### Task 7: SQLite writer

**Files:**
- Create: `vrdb/sqlite_out.py`
- Test: `tests/test_sqlite_out.py`

**Interfaces:**
- Consumes: `vrdb.schema`
- Produces:
  - `connect(path, *, bulk=True) -> sqlite3.Connection`
  - `create_table(conn, table) -> None`
  - `insert_batches(conn, table, batches) -> int`
  - `create_indexes(conn, table) -> None`
  - `write_ref_tables(conn) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sqlite_out.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sqlite_out.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.sqlite_out'`

- [ ] **Step 3: Write `vrdb/sqlite_out.py`**

```python
"""SQLite output.

Bulk-load pragmas are safe here because the database is a disposable derivative
of the source extract: if a load is interrupted the file is deleted and rebuilt.
Indexes are created after the inserts, never before.
"""

import sqlite3
from pathlib import Path

from vrdb import schema


def connect(path, *, bulk: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    if bulk:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -262144")  # 256 MB
    return conn


def create_table(conn: sqlite3.Connection, table: schema.Table) -> None:
    parts = []
    for column in table.columns:
        declaration = f'"{column.name}" {schema.sqlite_type(column.kind)}'
        if column.primary_key:
            declaration += " PRIMARY KEY"
        parts.append(declaration)
    conn.execute(f'DROP TABLE IF EXISTS "{table.name}"')
    conn.execute(f'CREATE TABLE "{table.name}" ({", ".join(parts)})')
    conn.commit()


def insert_batches(conn: sqlite3.Connection, table: schema.Table, batches) -> int:
    columns = ", ".join(f'"{c}"' for c in table.column_names)
    placeholders = ", ".join("?" * len(table.columns))
    statement = f'INSERT INTO "{table.name}" ({columns}) VALUES ({placeholders})'
    written = 0
    for batch in batches:
        conn.executemany(statement, batch)
        conn.commit()
        written += len(batch)
    return written


def create_indexes(conn: sqlite3.Connection, table: schema.Table) -> None:
    for index in table.indexes:
        columns = ", ".join(f'"{c}"' for c in index.columns)
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "{index.name}" '
            f'ON "{table.name}" ({columns})'
        )
    conn.commit()


def write_ref_tables(conn: sqlite3.Connection) -> None:
    """Small lookup tables so queries can read 'King' instead of 'KI'."""
    specs = [
        ("ref_county", "code TEXT PRIMARY KEY, name TEXT", schema.COUNTY_CODES),
        ("ref_gender", "code TEXT PRIMARY KEY, name TEXT", schema.GENDER_CODES),
        ("ref_status", "code TEXT PRIMARY KEY, note TEXT", schema.STATUS_CODES),
    ]
    for name, columns, mapping in specs:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(f'CREATE TABLE "{name}" ({columns})')
        conn.executemany(
            f'INSERT INTO "{name}" VALUES (?, ?)', sorted(mapping.items())
        )
    conn.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sqlite_out.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/sqlite_out.py tests/test_sqlite_out.py
git commit -m "feat: add SQLite writer with typed tables, bulk pragmas and indexes"
```

---

### Task 8: Parquet writer

**Files:**
- Create: `vrdb/parquet_out.py`
- Test: `tests/test_parquet_out.py`

**Interfaces:**
- Consumes: `vrdb.schema`
- Produces:
  - `arrow_type(kind: str) -> pa.DataType`
  - `arrow_schema(table) -> pa.Schema`
  - `write_batches(path, table, batches, *, compression="zstd") -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parquet_out.py`:

```python
import datetime

import pyarrow as pa
import pyarrow.parquet as pq

from vrdb import parquet_out, reader, schema


def test_arrow_schema_types():
    fields = {f.name: f.type for f in parquet_out.arrow_schema(schema.VOTERS)}
    assert fields["StateVoterID"] == pa.int64()
    assert fields["Birthyear"] == pa.int64()
    assert fields["Registrationdate"] == pa.date32()
    assert fields["LastVoted"] == pa.date32()
    assert fields["RegZipCode"] == pa.string()
    assert fields["PrecinctPart"] == pa.string()


def test_write_and_read_back(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    n = parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    assert n == 10
    table = pq.read_table(out)
    assert table.num_rows == 10
    assert table.schema.field("Registrationdate").type == pa.date32()


def test_dates_arrive_as_real_dates(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    table = pq.read_table(out).to_pydict()
    index = table["StateVoterID"].index(9000001)
    assert table["Registrationdate"][index] == datetime.date(2018, 5, 1)


def test_nulls_survive(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    data = pq.read_table(out).to_pydict()
    index = data["StateVoterID"].index(9000003)
    assert data["Birthyear"][index] is None
    assert data["Gender"][index] is None
    assert data["LastVoted"][index] is None
    assert all(v is None for v in data["Mail3"])


def test_identifier_columns_stay_strings(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    data = pq.read_table(out).to_pydict()
    index = data["StateVoterID"].index(9000004)
    assert data["PrecinctCode"][index] == "0600"
    assert data["PrecinctPart"][index] == "0600.919"


def test_multiple_batches_produce_multiple_row_groups(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS, batch_size=4)
    )
    assert pq.ParquetFile(out).num_row_groups == 3
    assert pq.read_table(out).num_rows == 10


def test_empty_input_still_writes_a_valid_file(tmp_path):
    out = tmp_path / "empty.parquet"
    n = parquet_out.write_batches(out, schema.VOTERS, iter([]))
    assert n == 0
    assert pq.read_table(out).num_rows == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parquet_out.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.parquet_out'`

- [ ] **Step 3: Write `vrdb/parquet_out.py`**

```python
"""Parquet output.

This is the only module that imports pyarrow, so schema.py and the readers stay
testable without it. Dates are converted explicitly with date.fromisoformat
rather than relying on an Arrow string-to-date cast: the reader has already
validated the format, and an explicit conversion cannot silently reinterpret a
value.
"""

from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from vrdb import schema

_ARROW_TYPES = {
    schema.KIND_TEXT: pa.string(),
    schema.KIND_INT: pa.int64(),
    schema.KIND_DATE: pa.date32(),
}


def arrow_type(kind: str) -> pa.DataType:
    try:
        return _ARROW_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown column kind: {kind!r}") from None


def arrow_schema(table: schema.Table) -> pa.Schema:
    return pa.schema(
        [pa.field(c.name, arrow_type(c.kind)) for c in table.columns]
    )


def _to_arrow(batch, table: schema.Table) -> pa.Table:
    columns = []
    for position, column in enumerate(table.columns):
        values = [row[position] for row in batch]
        if column.kind == schema.KIND_DATE:
            values = [None if v is None else date.fromisoformat(v) for v in values]
        columns.append(pa.array(values, type=arrow_type(column.kind)))
    return pa.Table.from_arrays(columns, schema=arrow_schema(table))


def write_batches(path, table: schema.Table, batches, *, compression: str = "zstd") -> int:
    """Write batches to a Parquet file, one row group per batch."""
    written = 0
    writer = pq.ParquetWriter(
        str(path), arrow_schema(table), compression=compression, use_dictionary=True
    )
    try:
        for batch in batches:
            writer.write_table(_to_arrow(batch, table))
            written += len(batch)
    finally:
        writer.close()
    return written
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parquet_out.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/parquet_out.py tests/test_parquet_out.py
git commit -m "feat: add Parquet writer with date32 dates and zstd compression"
```

---

### Task 9: File discovery and extract date

**Files:**
- Create: `vrdb/discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ExtractFiles` frozen dataclass: `vrdb: Path`, `voting_history: Path | None`, `districts: Path | None`, `extract_date: str`
  - `extract_date_from(path: Path) -> str`
  - `discover(folder) -> ExtractFiles`
  - `MissingExtract(Exception)`
  - `AmbiguousExtract(Exception)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discover.py`:

```python
import os
import time

import pytest

from vrdb import discover


def test_discovers_all_three(extract_dir):
    found = discover.discover(extract_dir)
    assert found.vrdb.name == "20260803_VRDB_Extract.txt"
    assert found.voting_history.name == "2025-2026_Voting_History_20260601.txt"
    assert found.districts.name == "2026-08-03_Districts-Precincts.xlsx"
    assert found.extract_date == "20260803"


def test_prefers_txt_over_a_sibling_csv(extract_dir):
    (extract_dir / "20260803_VRDB_Extract.csv").write_text("x")
    assert discover.discover(extract_dir).vrdb.suffix == ".txt"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_discover.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.discover'`

- [ ] **Step 3: Write `vrdb/discover.py`**

```python
"""Locate the three files an extract ships with and derive its date."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


class MissingExtract(Exception):
    """No VRDB extract found in the folder."""


class AmbiguousExtract(Exception):
    """More than one file in the folder matches a pattern."""


@dataclass(frozen=True)
class ExtractFiles:
    vrdb: Path
    voting_history: Path | None
    districts: Path | None
    extract_date: str


def extract_date_from(path: Path) -> str:
    """YYYYMMDD from the filename, falling back to the file's mtime.

    Every match is validated as a real calendar date before it is accepted.
    Without that check the optional separator lets the pattern match straight
    across a year range: "2025-2026_Voting_History_20260601.txt" yields
    "20252026", meaning month 20 and day 26, instead of the real date later in
    the name.
    """
    for match in _DATE.finditer(path.name):
        stamp = "".join(match.groups())
        try:
            date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
        except ValueError:
            continue
        return stamp
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")


def _only(folder: Path, pattern: str) -> Path | None:
    """The single file matching `pattern`, or None.

    Refuses to choose when a folder holds more than one match. Picking the
    lexicographically first would silently load 20260401 over 20260803, and
    the run would produce correctly named output containing the wrong month.
    """
    matches = sorted(folder.glob(pattern))
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise AmbiguousExtract(
            f"{len(matches)} files in {folder} match {pattern}: {names}. "
            "Keep one extract per folder so the month loaded is never a guess."
        )
    return matches[0] if matches else None


def discover(folder) -> ExtractFiles:
    folder = Path(folder)
    # Prefer the .txt: it is the original CP1252 source. A sibling .csv is a
    # previously converted derivative.
    vrdb = _only(folder, "*VRDB_Extract.txt") or _only(folder, "*VRDB_Extract.csv")
    if vrdb is None:
        raise MissingExtract(f"no *VRDB_Extract.txt or .csv found in {folder}")
    return ExtractFiles(
        vrdb=vrdb,
        voting_history=_only(folder, "*Voting_History*.txt"),
        districts=_only(folder, "*Districts-Precincts.xlsx"),
        extract_date=extract_date_from(vrdb),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_discover.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/discover.py tests/test_discover.py
git commit -m "feat: add extract file discovery and date derivation"
```

---

### Task 10: Verification

**Files:**
- Create: `vrdb/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `vrdb.schema`, `vrdb.reader`
- Produces:
  - `CheckResult` dataclass: `name: str`, `passed: bool`, `detail: str`
  - `count_source_rows(path, encoding="cp1252") -> int`
  - `check_row_count(conn, table, expected) -> CheckResult`
  - `check_primary_key_unique(conn, table) -> CheckResult`
  - `sample_source_rows(path, table, *, count=200, encoding="cp1252", seed=0) -> list[list]`
  - `check_sample_against_source(conn, table, path, *, count=200, encoding="cp1252", seed=0) -> CheckResult`
  - `check_districts_join(conn) -> CheckResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_verify.py`:

```python
from vrdb import districts, reader, schema, sqlite_out, verify


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


def test_primary_key_uniqueness(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    assert verify.check_primary_key_unique(conn, schema.VOTERS).passed


def test_sample_matches_source(tmp_path, vrdb_txt):
    conn = _loaded(tmp_path, vrdb_txt)
    result = verify.check_sample_against_source(
        conn, schema.VOTERS, vrdb_txt, count=10
    )
    assert result.passed, result.detail


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_verify.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb.verify'`

- [ ] **Step 3: Write `vrdb/verify.py`**

```python
"""Post-load verification against the source files.

The sample check deliberately re-reads and re-parses the source rather than
comparing against anything held in memory from the load. The previous
generation of this tool compared the database to the DataFrame it had just
written from, so a parse bug would have matched itself.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from vrdb import reader, schema

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


def check_row_count(conn, table: schema.Table, expected: int) -> CheckResult:
    actual = conn.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
    return CheckResult(
        f"{table.name}: row count",
        actual == expected,
        f"source {expected:,} vs database {actual:,}",
    )


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
    if size < 1 << 20:
        with open(path, "rb") as handle:
            handle.readline()  # discard the header
            lines = [line.decode(encoding).rstrip("\r\n") for line in handle]
        candidates = [ln for ln in lines if ln and len(ln.split("|")) == width]
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
    names = list(table.column_names)
    key_index = names.index(key.name)
    columns = ", ".join(f'"{c}"' for c in names)
    sample = sample_source_rows(path, table, count=count, encoding=encoding, seed=seed)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_verify.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add vrdb/verify.py tests/test_verify.py
git commit -m "feat: add verification that re-reads the source to check the load"
```

---

### Task 11: CLI entry point

**Files:**
- Create: `vrdb_export.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: every `vrdb/` module
- Produces: `build_parser() -> argparse.ArgumentParser`, `output_paths(out_dir, extract_date, *, sqlite, parquet) -> dict[str, Path]`, `main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import sqlite3

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
        [str(extract_dir), "--out", str(out), "--join-floor", "0.5"]
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


def test_sqlite_only(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    vrdb_export.main([str(extract_dir), "--out", str(out), "--sqlite"])
    assert (out / "vrdb_20260803.sqlite").exists()
    assert not list(out.glob("*.parquet"))


def test_parquet_only(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    vrdb_export.main([str(extract_dir), "--out", str(out), "--parquet"])
    assert not (out / "vrdb_20260803.sqlite").exists()
    assert (out / "voters_20260803.parquet").exists()


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

    assert vrdb_export.main([str(extract_dir), "--out", str(out)]) == 0
    assert stale.read_bytes() == b"from an earlier complete run"


def test_force_does_not_delete_an_untouched_table_output(tmp_path, extract_dir):
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "districts_precincts_20260803.parquet"
    stale.write_bytes(b"from an earlier complete run")
    (extract_dir / "2026-08-03_Districts-Precincts.xlsx").unlink()

    assert vrdb_export.main([str(extract_dir), "--out", str(out), "--force"]) == 0
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'vrdb_export'`

- [ ] **Step 3: Write `vrdb_export.py`**

```python
#!/usr/bin/env python3
"""Load a Washington VRDB extract into SQLite and Parquet.

    python vrdb_export.py /path/to/08.2026.WA

Run with no arguments to be prompted for the folder.

The outputs contain regulated voter data (RCW 29A.08.720 and 29A.08.740). They
default to the source folder and must never be committed to version control.
"""

import argparse
import sys
import time
from pathlib import Path

from vrdb import discover, districts, parquet_out, progress, reader, schema, sqlite_out, verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", nargs="?", help="Folder holding the extract files")
    parser.add_argument("--out", help="Output directory (default: the source folder)")
    parser.add_argument("--sqlite", action="store_true", help="Write only SQLite")
    parser.add_argument("--parquet", action="store_true", help="Write only Parquet")
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--encoding", default="cp1252", help="Source encoding")
    parser.add_argument("--tick", type=int, default=100_000, help="Progress interval")
    parser.add_argument("--batch", type=int, default=50_000, help="Rows per batch")
    parser.add_argument(
        "--join-floor",
        type=float,
        default=verify.JOIN_COVERAGE_FLOOR,
        help=(
            "Minimum share of voters that must join to a district row before "
            f"the check fails (default {verify.JOIN_COVERAGE_FLOOR}). The "
            "2026-08 extract measures 0.99999. Lower it only to investigate an "
            "extract whose PrecinctPart format changed."
        ),
    )
    return parser


def output_paths(out_dir: Path, extract_date: str, tables, *, sqlite: bool,
                 parquet: bool) -> dict[str, Path]:
    """Output paths for the tables this run will actually write.

    Scoped to `tables`, not schema.ALL_TABLES. Naming a Parquet file for a
    table whose source was not discovered would make the run refuse to
    overwrite a file it never intended to touch, and with --force would delete
    a still-valid output from an earlier, more complete run.
    """
    paths = {}
    if sqlite:
        paths["sqlite"] = out_dir / f"vrdb_{extract_date}.sqlite"
    if parquet:
        for table in tables:
            paths[f"parquet:{table.name}"] = out_dir / f"{table.name}_{extract_date}.parquet"
    return paths


def _check_clobber(paths: dict, force: bool) -> None:
    existing = [p for p in paths.values() if p.exists()]
    if existing and not force:
        for path in existing:
            print(f"Refusing to overwrite {path}", file=sys.stderr)
        print("Pass --force to overwrite.", file=sys.stderr)
        raise SystemExit(2)
    for path in existing:
        path.unlink()


def _report(stats: reader.ReadStats, label: str) -> None:
    if stats.malformed:
        print(f"  WARNING {label}: {stats.malformed:,} malformed row(s) skipped")
        for line_no, count in stats.malformed_examples:
            print(f"    line {line_no}: {count} fields")
    for column, count in sorted(stats.coerced_null.items()):
        print(f"  note {label}: {count:,} unparseable value(s) in {column} stored as NULL")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    folder = args.folder or input("Paste the path to the extract folder: ").strip().strip("\"'")
    if not folder:
        print("No folder provided.", file=sys.stderr)
        return 1
    found = discover.discover(Path(folder).expanduser())

    want_sqlite = args.sqlite or not args.parquet
    want_parquet = args.parquet or not args.sqlite
    out_dir = Path(args.out).expanduser() if args.out else found.vrdb.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extract date: {found.extract_date}")
    print(f"VRDB:         {found.vrdb}")
    print(f"History:      {found.voting_history or '(none found)'}")
    print(f"Districts:    {found.districts or '(none found)'}")
    if found.voting_history is None:
        print("WARNING: no voting history file found; skipping that table.")
    if found.districts is None:
        print("WARNING: no districts file found; skipping that table.")
    print(f"Output:       {out_dir}\n")

    sources = [(schema.VOTERS, found.vrdb)]
    if found.voting_history is not None:
        sources.append((schema.VOTING_HISTORY, found.voting_history))
    if found.districts is not None:
        sources.append((schema.DISTRICTS_PRECINCTS, found.districts))

    # Built after `sources` so a table whose source is missing this run neither
    # blocks the run nor has its earlier output deleted by --force.
    paths = output_paths(
        out_dir, found.extract_date, [t for t, _ in sources],
        sqlite=want_sqlite, parquet=want_parquet,
    )
    _check_clobber(paths, args.force)

    started = time.monotonic()
    conn = sqlite_out.connect(paths["sqlite"]) if want_sqlite else None
    written = {}
    all_stats = {}

    try:
        if conn is not None:
            sqlite_out.write_ref_tables(conn)

        for table, path in sources:
            stats = reader.ReadStats()
            all_stats[table.name] = stats
            total_bytes = path.stat().st_size
            reporter = progress.Progress(
                table.name, total_bytes=total_bytes, tick=args.tick, stream=sys.stdout
            )
            if table is schema.DISTRICTS_PRECINCTS:
                make = lambda: districts.iter_batches(
                    path, table, batch_size=args.batch, stats=stats, progress=reporter
                )
            else:
                make = lambda: reader.iter_batches(
                    path, table, encoding=args.encoding,
                    batch_size=args.batch, stats=stats, progress=reporter,
                )

            if conn is not None:
                sqlite_out.create_table(conn, table)

            if want_sqlite and want_parquet:
                # One pass feeds both writers: tee the batches so the 773 MB
                # source file is read once, not twice.
                def tee():
                    for batch in make():
                        sqlite_out.insert_batches(conn, table, [batch])
                        yield batch

                written[table.name] = parquet_out.write_batches(
                    paths[f"parquet:{table.name}"], table, tee()
                )
            elif want_sqlite:
                written[table.name] = sqlite_out.insert_batches(conn, table, make())
            else:
                written[table.name] = parquet_out.write_batches(
                    paths[f"parquet:{table.name}"], table, make()
                )

            reporter.finish(written[table.name])
            _report(stats, table.name)

            if conn is not None:
                print(f"  creating indexes on {table.name}...")
                sqlite_out.create_indexes(conn, table)

        results = []
        if conn is not None and not args.skip_verify:
            print("\n--- Verification ---")
            for table, path in sources:
                results.append(verify.check_row_count(conn, table, all_stats[table.name].rows))
                results.append(verify.check_primary_key_unique(conn, table))
                if table.primary_key is not None and table is not schema.DISTRICTS_PRECINCTS:
                    results.append(
                        verify.check_sample_against_source(
                            conn, table, path, encoding=args.encoding
                        )
                    )
            if found.districts is not None:
                results.append(
                    verify.check_districts_join(conn, floor=args.join_floor)
                )
            for result in results:
                print(f"  {'PASS' if result.passed else 'FAIL'}  {result.name}: {result.detail}")
    except BaseException as error:
        if conn is not None:
            conn.close()
        for path in paths.values():
            path.unlink(missing_ok=True)
        print("\nRun failed; partial outputs deleted.", file=sys.stderr)
        if isinstance(error, UnicodeDecodeError):
            print(
                f"Could not decode byte at offset {error.start} as "
                f"{args.encoding}. Try --encoding latin-1.",
                file=sys.stderr,
            )
            return 1
        raise

    if conn is not None:
        conn.close()

    elapsed = time.monotonic() - started
    print(f"\n{'=' * 56}")
    failed = [r for r in results if not r.passed]
    print("SOME CHECKS FAILED" if failed else "ALL CHECKS PASSED")
    for name, count in written.items():
        print(f"  {name:<22} {count:>12,} rows")
    for path in paths.values():
        if path.exists():
            print(f"  {path.name:<22} {path.stat().st_size / 1e6:>9,.1f} MB")
    print(f"  {'elapsed':<22} {elapsed:>11,.1f}s")
    print(f"{'=' * 56}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: 11 passed

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass, 0 failures

- [ ] **Step 6: Commit**

```bash
git add vrdb_export.py tests/test_cli.py
git commit -m "feat: add vrdb_export CLI with single-pass dual output and verification"
```

---

### Task 12: Real-data run and measurement

**Files:**
- Modify: `docs/superpowers/specs/2026-08-11-vrdb-sqlite-parquet-export-design.md` (replace the estimates in "Performance expectations" with measurements)

**Interfaces:**
- Consumes: the finished CLI
- Produces: `/Users/ericjohnson/08.2026.WA/vrdb_20260803.sqlite` and three Parquet files; confirmed real-world numbers

**This task writes ~1.8 GB of regulated voter data to the source folder. It must not touch the repo.**

- [ ] **Step 1: Run the exporter against the real extract**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
time .venv/bin/python vrdb_export.py /Users/ericjohnson/08.2026.WA 2>&1 | tee /tmp/vrdb_run.log
```

Expected in the output:
- `voters` 5,573,822 rows
- `voting_history` 5,234,497 rows
- `districts_precincts` 231,537 rows
- 0 malformed rows
- **no** coercion warnings at all. The two rows with no `Birthyear` hold an
  empty field, not garbage, so they become NULL silently. A `note ... stored as NULL` line here means a
  value failed to parse and is worth investigating.
- `districts join coverage` reporting about 99.9%
- `ALL CHECKS PASSED`

- [ ] **Step 2: Confirm nothing landed in the repo**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
git status --short
ls -la /Users/ericjohnson/08.2026.WA/*.sqlite /Users/ericjohnson/08.2026.WA/*.parquet
```
Expected: `git status` is clean; the outputs exist only in the extract folder.

- [ ] **Step 3: Spot-check the loaded data**

```bash
sqlite3 /Users/ericjohnson/08.2026.WA/vrdb_20260803.sqlite <<'SQL'
SELECT COUNT(*) FROM voters;
SELECT StatusCode, COUNT(*) FROM voters GROUP BY 1;
SELECT typeof(StateVoterID), typeof(Birthyear), typeof(RegZipCode) FROM voters LIMIT 1;
SELECT PrecinctCode, PrecinctPart FROM voters WHERE CountyCode='KI' LIMIT 3;
SELECT LName FROM voters WHERE StateVoterID = 12298636;
SELECT COUNT(*) FROM voters v JOIN districts_precincts d
  ON d.CountyCode=v.CountyCode AND d.PrecinctPart=v.PrecinctPart
  WHERE d.DistrictName LIKE 'FIRE DISTRICT NO. 8%';
SQL
```

Expected: 5,573,822 voters; `Active` 5,136,428 / `Inactive` 426,134 / `Pending - Primary Only Voter` 11,260; types `integer|integer|text`; King County parts keep their leading zeros (`0600` / `0600.919`); voter 12298636's last name renders as `O'BRIEN` with a right single quote, proving CP1252 decoding held.

- [ ] **Step 4: Confirm the Parquet files read back**

```bash
.venv/bin/python - <<'PY'
import pyarrow.parquet as pq, pathlib
for p in sorted(pathlib.Path("/Users/ericjohnson/08.2026.WA").glob("*_20260803.parquet")):
    f = pq.ParquetFile(p)
    print(f"{p.name:<40} {f.metadata.num_rows:>10,} rows  {p.stat().st_size/1e6:>8,.1f} MB  {f.num_row_groups} row groups")
print(pq.read_table("/Users/ericjohnson/08.2026.WA/voters_20260803.parquet",
                    columns=["Registrationdate"]).schema)
PY
```
Expected: row counts match SQLite; `Registrationdate` is `date32[day]`.

- [ ] **Step 5: Replace the estimates in the spec with measurements**

In the design spec, rewrite the "Performance expectations" section: replace each "Estimates ... to be confirmed against real output" figure with the measured elapsed time, SQLite file size, and per-table Parquet sizes from steps 1 and 4. Keep the measured design-time figures (43s field-splitting pass, 11s bytes-only pass) as they are.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-11-vrdb-sqlite-parquet-export-design.md
git commit -m "docs: replace performance estimates with measurements from the 2026-08 extract"
```

---

### Task 13: Analysis notebook

**Files:**
- Create: `notebooks/vrdb_explore.ipynb`

**Interfaces:**
- Consumes: a database produced by `vrdb_export.py`
- Produces: nothing other code depends on

- [ ] **Step 1: Create the notebook**

Create `notebooks/vrdb_explore.ipynb` with the cells below. Use the `NotebookEdit` tool or write the JSON directly. Cell 1 is markdown; the rest are code.

**Markdown cell 1:**

```markdown
# Washington VRDB Explorer

Queries the SQLite database built by `vrdb_export.py`.

**This notebook reads regulated voter data.** Under RCW 29A.08.720 it may be
used for political purposes but never for commercial advertising or
solicitation; misuse is a class C felony under RCW 29A.08.740. Do not commit
this notebook with output cells populated, and do not commit the database.

Set `DB_PATH` below to your extract's database.
```

**Code cell 2 - connect:**

```python
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path("/Users/ericjohnson/08.2026.WA/vrdb_20260803.sqlite")
conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def q(sql, **params):
    return pd.read_sql_query(sql, conn, params=params)


q("""
  SELECT name, (SELECT COUNT(*) FROM sqlite_master m2
                WHERE m2.type='index' AND m2.tbl_name=m.name) AS indexes
  FROM sqlite_master m WHERE type='table' ORDER BY name
""")
```

**Code cell 3 - row counts:**

```python
pd.DataFrame(
    [(t, q(f"SELECT COUNT(*) n FROM {t}").n[0])
     for t in ("voters", "voting_history", "districts_precincts")],
    columns=["table", "rows"],
)
```

**Code cell 4 - registrations by county:**

```python
q("""
  SELECT c.name AS county, COUNT(*) AS voters,
         SUM(v.StatusCode = 'Active') AS active,
         SUM(v.StatusCode = 'Inactive') AS inactive
  FROM voters v JOIN ref_county c ON c.code = v.CountyCode
  GROUP BY c.name ORDER BY voters DESC
""")
```

**Code cell 5 - age distribution:**

```python
ages = q("""
  SELECT (Birthyear / 10) * 10 AS decade, COUNT(*) AS voters
  FROM voters WHERE Birthyear IS NOT NULL
  GROUP BY decade ORDER BY decade
""")
ages.plot.bar(x="decade", y="voters", legend=False, title="Voters by birth decade")
```

**Code cell 6 - turnout per election:**

```python
q("""
  SELECT h.ElectionDate,
         COUNT(*) AS ballots,
         ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM voters), 1) AS pct_of_extract
  FROM voting_history h
  GROUP BY h.ElectionDate ORDER BY h.ElectionDate
""")
```

**Code cell 7 - voters who skipped the last general:**

```python
q("""
  SELECT c.name AS county, COUNT(*) AS never_voted_2025_general
  FROM voters v JOIN ref_county c ON c.code = v.CountyCode
  WHERE v.StatusCode = 'Active' AND NOT EXISTS (
      SELECT 1 FROM voting_history h
      WHERE h.StateVoterID = v.StateVoterID AND h.ElectionDate = '2025-11-04'
  )
  GROUP BY c.name ORDER BY never_voted_2025_general DESC LIMIT 15
""")
```

**Markdown cell 8:**

```markdown
## Filter voters to one district

This replaces the manual procedure in `Filtering the VRDB in Excel.pdf`: no
dropdown, no copy-paste. The join is on the literal `(CountyCode, PrecinctPart)`
string, which matches 99.999% of voters. Never cast `PrecinctPart` to a number:
the format varies by county (`311.1`, `0600.919`, `2401.A`, `175-3`, `12-A`,
`202-01`, `2169`) and casting would destroy leading zeros and merge distinct
precincts across counties.
```

**Code cell 9 - list districts:**

```python
q("""
  SELECT DistrictType, COUNT(DISTINCT DistrictName) AS districts
  FROM districts_precincts GROUP BY DistrictType ORDER BY districts DESC
""")
```

**Code cell 10 - the district filter:**

```python
DISTRICT = "FIRE DISTRICT NO. 8"

q("""
  SELECT v.StateVoterID, v.FName, v.LName, v.RegCity, v.PrecinctPart,
         v.StatusCode, v.LastVoted
  FROM voters v
  JOIN districts_precincts d
    ON d.CountyCode = v.CountyCode AND d.PrecinctPart = v.PrecinctPart
  WHERE d.DistrictName = :district AND v.StatusCode = 'Active'
  ORDER BY v.LName, v.FName
  LIMIT 50
""", district=DISTRICT)
```

**Code cell 11 - the same question against Parquet:**

```python
import pyarrow.parquet as pq

voters_pq = pq.read_table(
    DB_PATH.with_name("voters_20260803.parquet"),
    columns=["StateVoterID", "CountyCode", "PrecinctPart", "StatusCode", "Registrationdate"],
)
print(voters_pq.num_rows, "rows")
print(voters_pq.schema.field("Registrationdate").type)
voters_pq.slice(0, 5).to_pandas()
```

- [ ] **Step 2: Run the notebook end to end**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
.venv/bin/jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=600 \
  --output /tmp/vrdb_explore_executed.ipynb notebooks/vrdb_explore.ipynb
```
Expected: completes with no exception.

- [ ] **Step 3: Clear all outputs before committing**

Executed output cells would embed real voter names in a file destined for a public repo.

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
.venv/bin/jupyter nbconvert --clear-output --inplace notebooks/vrdb_explore.ipynb
grep -ci 'execution_count": [1-9]' notebooks/vrdb_explore.ipynb || echo "outputs cleared"
```
Expected: `outputs cleared`

- [ ] **Step 4: Confirm no voter data is staged**

```bash
git add notebooks/vrdb_explore.ipynb
git diff --cached --stat
.venv/bin/python -c "
import json
nb = json.load(open('notebooks/vrdb_explore.ipynb'))
assert all(not c.get('outputs') for c in nb['cells']), 'notebook still has outputs'
print('clean')
"
```
Expected: `clean`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add VRDB analysis notebook with district-filter recipe"
```

---

### Task 14: README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything built above
- Produces: nothing other code depends on

- [ ] **Step 1: Rewrite the README top matter**

Keep the existing `to_csv_progress.py` documentation intact. Change the opening line to describe both tools, and note that `to_csv_progress_pct.py` in the existing examples should read `to_csv_progress.py` to match the actual filename.

- [ ] **Step 2: Add the new tool section**

Append to `README.md`:

````markdown
## vrdb_export.py - load an extract into SQLite and Parquet

Builds a typed, indexed SQLite database and a set of Parquet files from a
monthly Washington VRDB extract.

### Setup

```bash
uv venv --python 3.14
uv pip install -e ".[notebook,dev]"
```

### Usage

```bash
.venv/bin/python vrdb_export.py /path/to/08.2026.WA
```

It finds the three files by pattern (`*VRDB_Extract.txt`,
`*Voting_History*.txt`, `*Districts-Precincts.xlsx`), preferring the `.txt`
source over a previously converted `.csv`. Run it with no arguments to be
prompted for the folder. Only the VRDB file is required; a missing history or
districts file is a warning.

Outputs are named from the extract date and land in the source folder:
`vrdb_20260803.sqlite`, `voters_20260803.parquet`,
`voting_history_20260803.parquet`, `districts_precincts_20260803.parquet`.
Re-running is idempotent; it refuses to overwrite unless you pass `--force`.

Options: `--sqlite` / `--parquet` to write just one, `--out DIR`, `--force`,
`--skip-verify`, `--encoding`, `--tick`, `--batch`, `--join-floor`.

### Tables

| Table | Grain | Primary key |
|---|---|---|
| `voters` | one row per registered voter | `StateVoterID` |
| `voting_history` | one row per voter per election | `VoterHistoryID` |
| `districts_precincts` | one row per district-to-precinct-part pair | none |
| `ref_county`, `ref_gender`, `ref_status` | code lookups from the SOS docs | code |

Join voters to their elections on `StateVoterID`. Join voters to districts on
`(CountyCode, PrecinctPart)`.

### Two things the source documentation gets wrong

`VRDB Database Fields 2.pdf` disagrees with the files it describes:

- It calls VRDB column 6 `YearofBirth`. The header says `Birthyear`.
- It lists the voting-history columns as
  `CountyCode | CountyCode_Voting | StateVoterID | ElectionDate | VotingHistoryID`.
  The real header is
  `VoterHistoryID | CountyCode | CountyCode_Voting | StateVoterID | ElectionDate` -
  the ID is first, and it is spelled `VoterHistoryID`. The PDF's own example
  line contradicts its own table.

### Why some columns are TEXT

`RegStNum`, `RegZipCode`, `PrecinctCode` and `PrecinctPart` look numeric and are
not:

- 23,093 `RegStNum` values are like `123A`.
- 56,139 `RegZipCode` values are ZIP+4.
- `PrecinctCode` leading zeros are significant (`0600`).
- `PrecinctPart` format varies by county: `311.1` (Adams), `0600.919` (King),
  `2401.A` (Jefferson), `175-3` (Chelan), `12-A` (San Juan), `202-01`
  (Skamania), `2169` (Pierce).

Match `PrecinctPart` as a literal string. Casting it to a number destroys
leading zeros and merges distinct precincts across counties. Matched literally,
it joins 99.999% of voters to a district row.

### Data protection

VRDB extracts and everything derived from them are regulated under
RCW 29A.08.720 and RCW 29A.08.740. The data may be used for political purposes
but never for commercial advertising or solicitation; misuse is a class C
felony. **This repository is public.** Outputs default to the source data
folder, `.gitignore` excludes every relevant file type, and the notebook must be
committed with its output cells cleared.
````

- [ ] **Step 3: Verify the documented commands actually work**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
.venv/bin/python vrdb_export.py --help
```
Expected: usage text listing every option named in the README.

- [ ] **Step 4: Run the full suite one last time**

```bash
.venv/bin/pytest -q
git status --short
```
Expected: all tests pass; no data files staged or untracked.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document vrdb_export, the schema, and the data-protection rules"
```

---

### Task 15: Pyright standard mode

**Files:**
- Create: `pyrightconfig.json`
- Modify: `pyproject.toml` (dev extra)
- Modify: `vrdb/districts.py` (`_column_index`)
- Modify: `vrdb/verify.py` (`check_sample_against_source`)
- Modify: `vrdb/reader.py` (`ReadStats` field annotations)
- Modify: `vrdb_export.py` (parser description)
- Modify: `tests/test_schema.py` (`test_primary_keys`)

**Interfaces:**
- Consumes: every module built above
- Produces: a `pyright` dev dependency and a clean type-check

Pyright standard mode was run against this branch during Task 6 and found
three errors in shipped code plus one real latent bug in the planned
`verify.py`. This task adds the tool and fixes what it finds. All four fixes
below are known in advance; the point of the task is to institutionalize the
check, not to discover them.

- [ ] **Step 1: Add the dev dependency and config**

In `pyproject.toml`, change the dev extra to:

```toml
dev = ["pytest>=8", "pyright>=1.1.411"]
```

Create `pyrightconfig.json`:

```json
{
  "include": ["vrdb", "tests", "vrdb_export.py", "to_csv_progress.py"],
  "typeCheckingMode": "standard",
  "reportUnusedImport": "error",
  "pythonVersion": "3.14",
  "pythonPlatform": "Darwin",
  "venvPath": ".",
  "venv": ".venv"
}
```

Then install: `uv pip install -e ".[notebook,dev]"`

Strict mode was evaluated and rejected. Measured on this codebase with all
modules present: standard reports 10 errors, all real; strict reports 408, of
which 386 are annotation debt (`reportUnknownMemberType` 108,
`reportUnknownVariableType` 91, `reportUnknownArgumentType` 80,
`reportUnknownParameterType` 57, `reportMissingParameterType` 50). Strict's
only unique real finding is an unused `Path` import in `sqlite_out.py`, which
`reportUnusedImport` above captures on its own. Strict would also flag
`verify.py`'s deliberate use of `reader._logical_lines`, emit two
`reportMissingTypeStubs` for pyarrow, and produce 9 errors in
`to_csv_progress.py`, which must not be modified.

- [ ] **Step 2: Run Pyright and confirm it reproduces the known errors**

Run: `.venv/bin/pyright`
Expected: 11 errors - 8 `reportOptionalMemberAccess` (`tests/test_schema.py`
x2, `vrdb/districts.py` x1, `vrdb/verify.py` x4, `vrdb_export.py` x1), 2
`reportArgumentType` in `vrdb_export.py` where a `Connection | None` reaches
`insert_batches`, and 1 `reportUnusedImport` for `Path` in
`vrdb/sqlite_out.py`. If the count differs, reconcile before continuing rather
than adjusting the config to match.

- [ ] **Step 3: Write a failing test for the real bug**

`check_sample_against_source` dereferences `table.primary_key` four times
without a guard, so calling it on `DISTRICTS_PRECINCTS` (which has no primary
key) raises `AttributeError`. Add to `tests/test_verify.py`:

```python
def test_sample_against_source_rejects_a_table_without_a_primary_key(
    tmp_path, vrdb_txt, districts_xlsx
):
    conn = _loaded(tmp_path, vrdb_txt, districts_xlsx)
    with pytest.raises(ValueError, match="no primary key"):
        verify.check_sample_against_source(
            conn, schema.DISTRICTS_PRECINCTS, districts_xlsx
        )
```

- [ ] **Step 4: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_verify.py -k primary_key -v`
Expected: FAIL with `AttributeError: 'NoneType' object has no attribute 'name'`
- proving the bug is real and not hypothetical.

- [ ] **Step 5: Apply the four fixes**

In `vrdb/verify.py`, at the top of `check_sample_against_source`, replace
`key = table.primary_key` with:

```python
    key = table.primary_key
    if key is None:
        raise ValueError(f"{table.name} has no primary key to sample against")
```

In `vrdb/districts.py`, replace the body of `_column_index`'s first line:

```python
def _column_index(ref: str) -> int:
    """'A1' -> 0, 'H12' -> 7, 'AA3' -> 26."""
    match = _COL.match(ref)
    if match is None:
        raise ValueError(f"malformed cell reference: {ref!r}")
    letters = match.group(0)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1
```

In `vrdb/reader.py`, give `ReadStats` its type arguments so downstream
inference works:

```python
@dataclass
class ReadStats:
    rows: int = 0
    malformed: int = 0
    malformed_examples: list[tuple[int, int]] = field(default_factory=list)
    coerced_null: dict[str, int] = field(default_factory=dict)
```

In `vrdb_export.py`, `__doc__` is `str | None` and is `None` under `python -OO`.
Add a module-level constant after the docstring and use it:

```python
_DESCRIPTION = (
    __doc__ or "Load a Washington VRDB extract into SQLite and Parquet."
).splitlines()[0]
```

and in `build_parser`, change `argparse.ArgumentParser(description=__doc__.splitlines()[0])`
to `argparse.ArgumentParser(description=_DESCRIPTION)`.

In `vrdb/sqlite_out.py`, delete the unused `from pathlib import Path`.

In `vrdb_export.py`, the two `Connection | None` errors are not provable by
narrowing, because `conn` is non-None exactly when `want_sqlite` is true and
Pyright cannot see that invariant. Make it explicit instead of suppressing it:
inside the `if want_sqlite and want_parquet:` branch, bind a local
`db = conn` immediately after `assert conn is not None`, and have `tee()` call
`sqlite_out.insert_batches(db, table, [batch])`. Do the same for the
`elif want_sqlite:` branch. The assert documents the invariant the surrounding
control flow already guarantees.

In `tests/test_schema.py`, rewrite `test_primary_keys` so it narrows before
dereferencing:

```python
def test_primary_keys():
    voters_key = schema.VOTERS.primary_key
    history_key = schema.VOTING_HISTORY.primary_key
    assert voters_key is not None and voters_key.name == "StateVoterID"
    assert history_key is not None and history_key.name == "VoterHistoryID"
```

- [ ] **Step 6: Confirm Pyright is clean and nothing regressed**

```bash
cd /Users/ericjohnson/GitHub/pipe2csv-progress
.venv/bin/pyright
.venv/bin/pytest -q
```
Expected: `0 errors, 0 warnings, 0 informations`, and the full suite passes with
one more test than before.

- [ ] **Step 7: Document it in the README**

Add to the README's setup section:

````markdown
### Type checking

```bash
.venv/bin/pyright
```

Standard mode, configured in `pyrightconfig.json`. It is what caught the
unguarded `table.primary_key` dereference in `verify.py`.
````

- [ ] **Step 8: Commit**

```bash
git add pyrightconfig.json pyproject.toml vrdb/ tests/ vrdb_export.py README.md
git commit -m "feat: add Pyright standard mode and fix the Optional derefs it found"
```

---

## Self-Review

**Spec coverage:** Every spec section maps to a task. Architecture and file
layout, Task 1. Schema, types, indexes and reference tables, Task 2. Progress
reporting, Task 3. Fixtures for the testing section, Task 4. The pipe reader
including CP1252, null handling and malformed rows, Task 5. The xlsx reader
including phantom rows and row-number gaps, Task 6. SQLite output with bulk
pragmas and post-insert indexes, Task 7. Parquet with date32 and zstd, Task 8.
Discovery and output naming, Task 9. All six verification checks, Task 10. CLI,
error handling and partial-output cleanup, Task 11. Performance measurement,
Task 12. Notebook, Task 13. Data protection lands in Task 1 (`.gitignore`),
Task 12 (repo-clean check), Task 13 (cleared outputs) and Task 14 (README).

**Type consistency:** `iter_batches` has the same signature in `reader.py` and
`districts.py`, so `sqlite_out` and `parquet_out` consume either. `ReadStats` is
defined once in `reader.py` and reused by `districts.py`. `coerce` is defined
once and used by `reader.py`, `districts.py` and `verify.py`. `CheckResult`
fields (`name`, `passed`, `detail`) are read identically in `verify.py` and
`vrdb_export.py`. `Table.column_names`, `Table.primary_key`, `Index.name` and
`Index.columns` are used consistently in Tasks 2, 7, 8, 10 and 11.

**Known coupling:** `verify.count_source_rows` calls `reader._logical_lines`, a
private function. This is deliberate: both need identical line-splitting rules,
and duplicating the logic would let the count and the load disagree.
