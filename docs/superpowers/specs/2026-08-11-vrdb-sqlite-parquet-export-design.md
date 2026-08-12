# VRDB SQLite + Parquet Export - Design

Date: 2026-08-11
Status: Approved for planning
Repo: `wormeyman/pipe2csv-progress` (public)

## Purpose

Turn a monthly Washington State Voter Registration Database (VRDB) extract into a
typed, indexed SQLite database and a set of Parquet files, so the data can be
queried in TablePlus, from SQL, or from a notebook instead of being filtered by
hand in Excel.

The existing `to_csv_progress.py` converts one pipe-delimited file to CSV. This
adds a second, separate tool that loads all three files an extract ships with
into one queryable database.

## Source data

Measured against `/Users/ericjohnson/08.2026.WA/` on 2026-08-11 by scanning every
row of both text files and every row of the workbook.

| File | Size | Data rows | Shape |
|---|---|---|---|
| `20260803_VRDB_Extract.txt` | 773 MB | 5,573,822 | 33 columns, pipe-delimited, CRLF, CP1252 |
| `2025-2026_Voting_History_20260601.txt` | 190 MB | 5,234,497 | 5 columns, same format |
| `2026-08-03_Districts-Precincts.xlsx` | 9 MB | 231,537 | 8 columns, single sheet |

The workbook's declared `dimension` is `A1:H237379`, which overstates the data.
The sheet holds 233,787 `<row>` elements, of which 2,249 are entirely empty, and
3,592 row numbers in the declared range have no element at all. Only 231,538
rows carry any value, one of which is the header. A loader that trusts
`dimension`, or that emits a row for every `<row>` element, produces 2,249 phantom
all-null district rows. The reader must skip rows where every cell is empty.

Three PDFs ship alongside: field definitions, an Excel how-to, and the RCW
29A.08.740 use restrictions.

### Corrections to `VRDB Database Fields 2.pdf`

The shipped documentation disagrees with the shipped data in three places. The
data wins.

1. The PDF lists VRDB column 6 as `YearofBirth`. The file header says
   `Birthyear`.
2. The PDF's voting-history field table lists the columns as
   `CountyCode | CountyCode_Voting | StateVoterID | ElectionDate | VotingHistoryID`.
   The real header is
   `VoterHistoryID | CountyCode | CountyCode_Voting | StateVoterID | ElectionDate`.
   The ID column is first, not last, and it is spelled `VoterHistoryID`. The
   PDF's own example line contradicts its own table.
3. The PDF's Districts-to-Precincts example shows `PrecinctPart` as a bare `1`
   or `3`. The real workbook uses the same dotted form the VRDB uses
   (`212.1`, `0093.235`). This matters because it is the join key.

### Measured data facts

These drive every typing decision below.

- Zero malformed rows. All 5,573,822 VRDB rows have exactly 33 fields; all
  5,234,497 history rows have exactly 5.
- `StateVoterID`: all integers, zero duplicates across 5,573,822 rows.
- `VoterHistoryID`: all integers, zero duplicates across 5,234,497 rows.
- `Registrationdate`, `LastVoted`, `ElectionDate`: 100% valid `YYYY-MM-DD`.
  Registration spans 1904-10-16 to 2026-11-12 (future-dated rows exist).
  LastVoted spans 1900-01-01 to 2026-08-04.
- `Birthyear`: 4-digit, range 1900-2009. Exactly 2 rows out of 5.5M have no
  birth year, and both hold an empty field rather than an unparseable one, so
  they become NULL without a warning.
- `RegStNum` is **not** an integer: 23,093 rows hold values like `123A`.
- `RegZipCode` is **not** an integer: 5,517,563 are 5-char, 56,139 are ZIP+4
  (10 char), 116 are 9-char, 4 are empty.
- `Mail3` is empty in 100% of rows. `RegStFrac` is 99.9% empty, `NameSuffix`
  98% empty.
- `Gender` holds `M`, `F`, `U`, `O`, empty, and a single-space string.
- `StatusCode` holds exactly three values: `Active`, `Inactive`,
  `Pending - Primary Only Voter`. The PDF calls the third "Primary Only Voter".
- 319 rows contain non-ASCII bytes; all decode cleanly as CP1252.
- No `<br>` markers appear anywhere in this extract. Lines are plain CRLF.
- Voting history covers 6 elections across all 39 counties: 2025-02-11 (526,930),
  2025-04-22 (570,558), 2025-08-05 (1,251,616), 2025-11-04 (1,988,870),
  2026-02-10 (768,827), 2026-04-28 (127,696).
- The districts workbook holds 13,734 distinct `(CountyCode, PrecinctPart)`
  pairs across 231,537 rows, so each precinct-part belongs to roughly 17
  overlapping districts.

### The districts join, verified

Joining voters to districts on `(CountyCode, PrecinctPart)` matches
**5,573,743 of 5,573,822 voters, or 99.999%**. Of the 79 misses, 77 are voters
whose source `PrecinctPart` is blank. This was measured, not assumed, and it is
what makes district filtering a single SQL join rather than the Excel dropdown
procedure the SOS how-to describes.

### `PrecinctPart` format varies by county

The dotted `311.1` form is the majority but not the rule. Sampled from both
files, which agree with each other county by county:

| County | `PrecinctCode` | `PrecinctPart` |
|---|---|---|
| AD Adams | `311` | `311.1` |
| KI King | `0600` | `0600.919` |
| JE Jefferson | `2401` | `2401.A` |
| CH Chelan | `0175` | `175-3` |
| SJ San Juan | `0012` | `12-A` |
| SM Skamania | `202` | `202-01` |
| PI Pierce | `2169` | `2169` |

17,035 workbook rows, all from CH, JE, PI, SJ, and SM, use a non-dotted form.
Leading zeros appear in `PrecinctCode` but are stripped in `PrecinctPart` for
some counties, and letter suffixes appear in others.

The consequence for implementation: **join on the literal `PrecinctPart` string
and never derive, normalize, parse, or numerically cast it.** Treating it as a
decimal number would collapse `0600.919`, silently merge San Juan's `22` with
Pierce's, and destroy the leading zeros. Both columns stay TEXT. The 99.999%
match rate is exactly what confirms literal string matching is correct.

## Prior art

`/Users/ericjohnson/04.2026.WA/vrdbtosqlite.py` loaded the April extract into
`vrdb_20260414_101330.sqlite` (1.478 GB, 5,514,920 rows, `voters` table).

Carried forward:

- The `voters` table name.
- The index set, which was tuned for browsing in TablePlus.
- Output written beside the source file, not into the repo.
- A verification pass and a closing summary with row count, DB size, and timing.

Changed, with reasons:

1. **It was not actually streaming.** It read in 500K-row chunks, then called
   `pd.concat(chunks, ignore_index=True)`, materializing all 5.5M rows as one
   all-string DataFrame before writing. Peak memory ran to several GB and the
   batched `to_sql` loop only sliced memory. The new reader holds one batch at a
   time.
2. **`StateVoterID` was TEXT with its own index.** It is a verified-unique
   integer, so it becomes `INTEGER PRIMARY KEY`. It then *is* the rowid,
   `idx_statevoterid` disappears, and the join to `voting_history` gets much
   faster.
3. **`Birthyear` was TEXT**, so `WHERE Birthyear < 1950` compared strings. It
   becomes INTEGER.
4. Verification compared the database against the in-memory DataFrame, which
   cannot detect a parse error because both sides came from the same parse. The
   new check re-reads the source file.
5. It loaded only the VRDB. Voting history and districts were never imported.
6. It required pandas. The exporter now needs only pyarrow.

## Scope

In scope:

- Load all three files into one SQLite database.
- Write one Parquet file per table.
- A starter analysis notebook.
- A virtualenv in the repo.
- Harden `.gitignore` against voter data.

Out of scope:

- Any change to `to_csv_progress.py`. It stays dependency-free.
- Cross-month diffing, geocoding, party affiliation (not in the source), or any
  mailing or outreach feature.

## Architecture

```
pipe2csv-progress/
├── to_csv_progress.py          # unchanged, stdlib only
├── vrdb_export.py              # CLI entry point
├── vrdb/
│   ├── __init__.py
│   ├── schema.py               # column names, types, code tables, index defs
│   ├── reader.py               # streaming CP1252 pipe reader + progress/ETA
│   ├── districts.py            # streaming xlsx reader, stdlib only
│   ├── sqlite_out.py           # typed table creation, batch insert, indexes
│   ├── parquet_out.py          # pyarrow batch writer
│   └── verify.py               # post-load checks against the source files
├── notebooks/vrdb_explore.ipynb
├── docs/superpowers/specs/
├── tests/
├── pyproject.toml
└── .venv/                      # gitignored
```

Each module has one job and a small interface:

- `schema.py` is data, not logic. It owns the single source of truth for column
  names, SQLite types, Arrow types, and index definitions. Everything else reads
  from it, so adding a column is a one-file change.
- `reader.py` yields batches of typed rows from a pipe-delimited CP1252 file. It
  knows nothing about SQLite or Parquet. It reports progress the way
  `to_csv_progress.py` does: rows, rate, percent, ETA.
- `districts.py` yields batches from the workbook with the same interface as
  `reader.py`, so writers cannot tell the two apart.
- `sqlite_out.py` and `parquet_out.py` each consume batches and know nothing
  about parsing.
- `verify.py` re-opens the source files and checks the outputs against them.

The xlsx reader uses `zipfile` plus `xml.etree.ElementTree.iterparse` against
`xl/worksheets/sheet1.xml` and `xl/sharedStrings.xml`. This was prototyped
during design and read the sheet in about two seconds, so openpyxl is not a
dependency. It resolves shared strings, tolerates absent cells and gaps in row
numbering, and skips all-empty rows.

## Data flow

```
source file -> reader batches -> [ sqlite_out ] -> vrdb_YYYYMMDD.sqlite
                              -> [ parquet_out ] -> <table>_YYYYMMDD.parquet
                                                 -> verify against source
```

One pass per source file feeds both writers, so the 773 MB VRDB file is read
once, not twice.

## Schema

### `voters` (5,573,822 rows)

| Column | Type | Note |
|---|---|---|
| StateVoterID | INTEGER PRIMARY KEY | verified unique |
| FName, MName, LName, NameSuffix | TEXT | |
| Birthyear | INTEGER | 2 unparseable rows become NULL |
| Gender | TEXT | whitespace-only normalized to NULL |
| RegStNum | TEXT | 23,093 non-integer values |
| RegStFrac, RegStName, RegStType, RegUnitType | TEXT | |
| RegStPreDirection, RegStPostDirection, RegStUnitNum | TEXT | |
| RegCity, RegState | TEXT | |
| RegZipCode | TEXT | ZIP+4 present |
| CountyCode | TEXT | |
| PrecinctCode, PrecinctPart | TEXT | leading zeros are significant (`0093`) |
| LegislativeDistrict | INTEGER | |
| CongressionalDistrict | INTEGER | |
| Mail1, Mail2, Mail3 | TEXT | Mail3 is always NULL |
| MailCity, MailZip, MailState, MailCountry | TEXT | |
| Registrationdate | TEXT | ISO `YYYY-MM-DD` |
| LastVoted | TEXT | ISO `YYYY-MM-DD` |
| StatusCode | TEXT | |

Dates stay ISO TEXT. SQLite has no date type, and ISO strings sort and compare
correctly with `<`, `BETWEEN`, and `date()`. Parquet gets real `date32` columns.

### `voting_history` (5,234,497 rows)

| Column | Type |
|---|---|
| VoterHistoryID | INTEGER PRIMARY KEY |
| CountyCode | TEXT |
| CountyCode_Voting | TEXT |
| StateVoterID | INTEGER |
| ElectionDate | TEXT (ISO) |

Column order follows the file, not the PDF.

### `districts_precincts` (231,537 rows)

| Column | Type |
|---|---|
| CountyCode, County | TEXT |
| DistrictType, DistrictCode, DistrictName | TEXT |
| PrecinctCode, PrecinctName, PrecinctPart | TEXT |

No primary key; the grain is a district-to-precinct-part pair.

### Reference tables

`schema.py` also emits three small lookup tables from the SOS documentation, so
queries can read `Adams` instead of `AD` without a hardcoded CASE statement:

- `ref_county` - 39 code-to-name rows
- `ref_gender` - `M`/`F`/`U`/`O`
- `ref_status` - the three `StatusCode` values with their RCW notes

### Indexes

On `voters`: `CountyCode`; `StatusCode`; `(CountyCode, PrecinctCode)`;
`LegislativeDistrict`; `CongressionalDistrict`; `LastVoted`; `(LName, FName)`;
and `(CountyCode, PrecinctPart)` for the districts join. `idx_statevoterid` is
dropped as redundant against the new primary key.

On `voting_history`: `StateVoterID`; `ElectionDate`.

On `districts_precincts`: `(CountyCode, PrecinctPart)`; `DistrictName`.

## CLI

```
python vrdb_export.py [FOLDER] [options]
```

Given a folder, it discovers the three files by pattern:

| Role | Pattern | Preference |
|---|---|---|
| VRDB | `*VRDB_Extract.txt` | prefer `.txt` over a sibling `.csv` |
| Voting history | `*Voting_History*.txt` | |
| Districts | `*Districts-Precincts.xlsx` | |

Run with no arguments, it prompts for the folder, matching the
`vrdbtosqlite.py` habit. Options:

- `--sqlite` / `--parquet` / both (default: both)
- `--out DIR` (default: the source folder)
- `--force` to overwrite existing outputs
- `--skip-verify`
- `--tick N` progress interval, matching `to_csv_progress.py`
- `--encoding` (default `cp1252`)
- `--batch N` rows per batch handed to the writers (default 50,000)
- `--join-floor F` minimum share of voters that must join to a district row
  before that check fails (default 0.95; the 2026-08 extract measures 0.99999).
  Lower it only to investigate an extract whose `PrecinctPart` format changed.

A missing history or districts file is a warning, not an error; the VRDB file is
required.

## Output naming

Named from the extract date parsed out of the VRDB filename
(`20260803_VRDB_Extract.txt` gives `20260803`), falling back to the file's
modification date if the name has no date:

- `vrdb_20260803.sqlite`
- `voters_20260803.parquet`
- `voting_history_20260803.parquet`
- `districts_precincts_20260803.parquet`

Written to the source folder. Re-running is idempotent, and the filename says
which extract it came from. If a target exists, the tool errors out and names
the file unless `--force` is passed.

## Null handling

An empty or whitespace-only field becomes NULL. This matches what pandas did
implicitly last time, keeps `WHERE MName IS NULL` correct, and folds away the
`Gender` single-space value that would otherwise appear as its own GROUP BY
bucket. Every column is nullable except the two primary keys.

## Error handling

- **Row with the wrong field count**: count it, log the first 10 with line
  numbers, keep going, and report the total at the end. A nonzero count fails
  verification. Zero occur in the current extract.
- **Unparseable integer or date**: store NULL, count it, report per column. An
  empty field is a normal NULL and is not counted, so a reported count always
  means a value was present but malformed. The 2026-08 extract produces no
  such counts.
- **Undecodable byte**: fail loudly with the byte offset and suggest
  `--encoding latin-1`, the same guidance `to_csv_progress.py` gives.
- **Output exists**: refuse and name the file unless `--force`.
- **Missing optional source file**: warn, skip that table, continue.
- **Interrupted run**: SQLite work happens in a transaction per batch, and the
  partial file is deleted on an unhandled exception so a half-loaded database is
  never left looking complete.

SQLite writes use `PRAGMA journal_mode=OFF`, `synchronous=OFF`, and a large
`cache_size` during the load, since the output is disposable and rebuildable.
Indexes are created after the inserts, not before.

## Verification

Extends the prior art's check so it validates the parse rather than only the
write.

1. **No malformed rows** per table. A row whose field count does not match the
   table is skipped at parse time and is not counted in the reader's row tally,
   so it is invisible to the row count below. This check reports the number
   skipped and the first few offending line numbers, and a nonzero count fails
   verification.
2. Row count per table.
3. Primary key uniqueness on `voters` and `voting_history`.
4. **Parquet against SQLite**: when both outputs are written they come from one
   shared read pass, so their row counts must agree. Nothing else looks at the
   Parquet file.
5. **Source re-read**: pick 200 random rows in the VRDB file, re-parse them
   independently, and compare every field against the database row with that
   `StateVoterID`. The previous script compared the database to the in-memory
   DataFrame, so a parse bug would have matched itself. An empty sample fails:
   it means the check did not run, which is not the same as passing.
6. Districts join coverage reported as a percentage, so a future extract that
   changes the `PrecinctPart` format shows up immediately instead of silently
   returning empty district filters.
7. Null-coercion counts printed per column.

Closing summary: rows per table, output sizes, elapsed time, and pass, fail, or
`NO CHECKS RUN` when the run was `--skip-verify` or Parquet-only.

An earlier draft of this list also called for the first and last 25 rows to be
compared field-by-field, as the previous generation of the tool did. That was
dropped in favor of the 200-row random sample in item 5, which is strictly
stronger: the first and last rows of a file are the two places a streaming
parser is least likely to get wrong, while a random sample can land anywhere,
including on the CP1252 and ZIP+4 rows that the fixed positions would never
reach.

## Notebook

`notebooks/vrdb_explore.ipynb`, connecting to the SQLite file with stdlib
`sqlite3` and displaying results with pandas:

1. Connect, list tables, show row counts and the schema.
2. Registrations by county, joined to `ref_county` for readable names.
3. Age distribution from `Birthyear`, bucketed by decade.
4. Turnout per election across the six 2025-2026 elections, as a share of the
   voters present in the extract.
5. Active versus inactive breakdown by county.
6. The district filter: pick a `DistrictName`, join through
   `districts_precincts` on `(CountyCode, PrecinctPart)`, return the voters. This
   replaces the manual Excel dropdown procedure in
   `Filtering the VRDB in Excel.pdf`.
7. A Parquet cell showing the same query against the Parquet files for anyone
   who prefers them.

## Environment

`.venv/` in the repo root, created with `uv venv`. Verified to resolve on the
installed Python 3.14.6:

- Runtime: `pyarrow==25.0.1`
- Notebook extra: `pandas==3.0.5`, `jupyterlab==4.6.3`, `matplotlib==3.11.1`
  (pulls `numpy==2.5.2`)
- Dev extra: `pytest`

`pyproject.toml` declares these with optional-dependency groups so the exporter
alone stays a one-package install.

## Testing

Unit tests over small fixtures committed to the repo. **No real voter data in
any fixture** - fixtures are hand-written rows with invented names and IDs that
reproduce the shapes found in the real file:

- Reader: CRLF handling, CP1252 high bytes, empty and whitespace-only fields,
  a wrong-field-count row, a `<br>` variant for older extracts.
- Types: `123A` in `RegStNum` stays text; ZIP+4 stays text; a bad `Birthyear`
  becomes NULL; leading-zero `PrecinctCode` survives.
- Schema: every column in `schema.py` has a SQLite type and an Arrow type.
- SQLite writer: types land as declared; indexes exist; primary key rejects a
  duplicate.
- Parquet writer: round-trips a batch; dates arrive as `date32`.
- Districts reader: shared-string resolution, absent cells, gaps in row
  numbering, all-empty rows skipped, and every `PrecinctPart` form in the table
  above (`311.1`, `0600.919`, `2401.A`, `175-3`, `12-A`, `202-01`, `2169`)
  surviving as an unmodified string.
- Verify: a deliberately corrupted database fails each check.

An end-to-end test runs the CLI against a ~100-row synthetic extract and asserts
both outputs and a clean verification.

## Data protection

`wormeyman/pipe2csv-progress` is a public repository, and RCW 29A.08.740 makes
misuse of this data a class C felony. The current `.gitignore` does not exclude
`*.csv`, `*.txt`, `*.db`, `*.sqlite`, or `*.parquet`.

Required changes:

- Add `*.sqlite`, `*.sqlite3`, `*.db`, `*.parquet`, `*.csv`, `*.txt`, `*.xlsx`
  to `.gitignore`, with a `!` exception for the small synthetic test fixtures
  and any documentation text the repo needs.
- Default all output to the source data folder, never the repo.
- A README section stating that outputs contain regulated voter data, that they
  must stay out of version control, and summarizing the RCW 29A.08.720 and
  29A.08.740 restrictions: no commercial or solicitation use, political use
  permitted.

Note that `.gitignore` already contains `lib/`, so no package directory may be
named `lib`.

Three more protections were added after the whole-branch review, because file
type patterns turned out not to be enough:

- `*.sqlite` does not match the `-wal`, `-shm` and `-journal` sidecars that any
  GUI opening an output database with `PRAGMA journal_mode=WAL` leaves beside
  it, and those hold raw page data from the regulated tables. Those three
  suffixes are now covered on `*.sqlite`, `*.sqlite3` and `*.db`.
- `notebooks/vrdb_explore.ipynb` is tracked on purpose, so `.gitignore` cannot
  protect it, and its rendered output would carry real records. An nbstripout
  clean filter and a tracked `scripts/pre-commit` hook both guard it; the hook
  inspects the staged blob, so it still fires where the filter is not
  installed. Both are local-only and are installed by
  `scripts/install-hooks.sh`.
- The registration number is part of the regulated record under
  RCW 29A.08.720(2), so no real `StateVoterID` appears anywhere in this
  repository, including in these design documents.

## Performance expectations

Measured during design: a pure-Python pass that splits all 5,573,822 VRDB rows
into fields takes about 43 seconds, and a bytes-only pass takes about 11
seconds. The districts workbook parses in about 2 seconds.

Measured against the 2026-08-03 extract (5,573,822 voters, 5,234,497 history
rows, 231,537 district-precinct rows), full run including verification:

- VRDB to SQLite plus Parquet, including indexes: 47.1s (118,434 rows/s)
- Voting history: 11.6s (451,375 rows/s)
- Districts: 3.2s (72,035 rows/s)
- Verification (row counts, PK uniqueness, 200-row source re-read per table,
  districts join coverage): included in the total below
- Total elapsed, load plus verify: 91.2s (`time` reported 1m31.3s real,
  1m20.4s user, 5.6s sys)
- SQLite output: 1,959.2 MB for all three tables plus indexes (the April
  VRDB-only database was 1.478 GB; this one adds voting_history and
  districts_precincts plus their indexes)
- Parquet output with zstd and dictionary encoding:
  - `voters_20260803.parquet`: 149.9 MB (112 row groups)
  - `voting_history_20260803.parquet`: 41.2 MB (105 row groups)
  - `districts_precincts_20260803.parquet`: 0.8 MB (5 row groups)

Memory stayed flat at one batch, unlike the prior script's multi-GB peak.

## README

Add a section covering the new tool: what it produces, the discovery and CLI
usage, the schema and join keys, the documentation corrections above, the
99.999% join measurement, and the data-protection notice.
