# pipe2csv-progress
Two tools for working with Washington voter registry (VRDB) extracts. `to_csv_progress.py` converts a large, pipe-delimited export that uses `<br>` for line breaks into standard RFC 4180 CSV, fast, with accurate progress, ETA, and proper quoting for commas inside fields. `vrdb_export.py` loads a full monthly extract into a typed, indexed SQLite database and a set of Parquet files - see [below](#vrdb_exportpy---load-an-extract-into-sqlite-and-parquet).

- Streams input in a single pass
- Handles Windows-1252 (smart quotes) by default
- Normalizes `<br>` and `<br/>` to newlines
- Writes UTF-8 CSV with correct quoting
- Shows rows processed, rate, percent, and ETA
- No external Python dependencies

## Quick start

`python3 to_csv_progress.py INPUT.txt OUTPUT.csv`

Examples:

Default: CP1252 -> UTF-8 CSV

`python3 to_csv_progress.py 20250701_VRDB_Extract.txt voters.csv`

More frequent progress updates

`python3 to_csv_progress.py 20250701_VRDB_Extract.txt voters.csv --tick 20000`

Different source encoding (if needed)

`python3 to_csv_progress.py 20250701_VRDB_Extract.txt voters.csv --encoding latin-1`

Larger read chunks for slightly higher throughput

`python3 to_csv_progress.py 20250701_VRDB_Extract.txt voters.csv --chunk 2097152`

## Why this script

Many county/state exports use pipes as field separators and `<br>` as row delimiters, and often encode as Windows-1252. This tool:
- Converts `<br>` to real newlines
- Parses pipes safely (fields may contain commas)
- Outputs a clean UTF-8 CSV that standard tools can import

## Usage details

positional arguments:

`inp`                  Input text file (pipe-delimited, line breaks)

`out`                  Output CSV file (UTF-8)

options:

`--encoding`           Source encoding (default: cp1252)

`--tick`               Print progress every N rows (default: 100000)

`--chunk`              Read chunk size in bytes (default: 1048576)

## Sanity checks

`wc -l voters.csv          # expect N+1 lines (including header)`

`head -1 voters.csv`

`tail -1 voters.csv`

## vrdb_export.py - load an extract into SQLite and Parquet

Builds a typed, indexed SQLite database and a set of Parquet files from a
monthly Washington VRDB extract.

### Setup

```bash
uv venv --python 3.14
uv pip install -e ".[notebook,dev]"
bash scripts/install-hooks.sh
```

The third line is not optional. Git does not track hooks or filter
configuration, so the two protections that keep voter data out of the notebook
live in `.git/` and have to be installed once per clone. See
[Data protection](#data-protection).

### Type checking

```bash
.venv/bin/pyright
```

Standard mode, configured in `pyrightconfig.json`. It is what caught the
unguarded `table.primary_key` dereference in `verify.py`.

### Usage

```bash
.venv/bin/python vrdb_export.py /path/to/08.2026.WA
```

It finds the three files by pattern (`*VRDB_Extract.txt`,
`*Voting_History*.txt`, `*Districts-Precincts.xlsx`), preferring the `.txt`
source over a previously converted `.csv`. Run it with no arguments to be
prompted for the folder. Only the VRDB file is required; a missing history or
districts file is a warning, and the table it would have populated is simply
skipped.

Outputs are named from the extract date and land in the source folder by
default: `vrdb_20260803.sqlite`, `voters_20260803.parquet`,
`voting_history_20260803.parquet`, `districts_precincts_20260803.parquet`.
Re-running is idempotent; it refuses to overwrite an existing output unless
you pass `--force`, and if a run fails partway it deletes whatever partial
outputs it had already started writing.

Options:

| Option | Effect |
|---|---|
| `--out DIR` | Output directory (default: the source folder) |
| `--sqlite` | Write only SQLite |
| `--parquet` | Write only Parquet |
| `--force` | Overwrite existing outputs |
| `--skip-verify` | Skip the post-load verification pass |
| `--encoding ENCODING` | Source encoding (default: `cp1252`) |
| `--tick TICK` | Progress interval, in rows (default: 100000) |
| `--batch BATCH` | Rows per batch (default: 50000) |
| `--join-floor JOIN_FLOOR` | Minimum share of voters that must join to a district row before the check fails (default 0.95). The 2026-08 extract measures 0.999986. Lower it only to investigate an extract whose `PrecinctPart` format changed. |

### Verification

Unless you pass `--skip-verify`, the run re-checks its own output and exits 1
if anything fails. Per table it checks that no row was skipped as malformed,
that the row count is right, that the primary key is unique, that the Parquet
file holds as many rows as SQLite, and - for the two pipe-delimited tables -
that 200 rows re-read at random offsets from the source match the database
field for field. It finishes by reporting what share of voters join to a
district row.

Two of those deserve spelling out, because the obvious implementation of each
is a check that cannot fail:

- **The row count comes from re-reading the source**, not from the loader's own
  tally of rows it accepted. Given that tally, the check compares the loader to
  itself: a load that stopped early leaves a database holding exactly the rows
  the reader counted, so both sides agree no matter how much of the file went
  unread. Re-counting costs 1.1s on the 765 MB voters file and 0.4s on voting
  history. The workbook has no equivalent cheap re-count, so
  `districts_precincts` is still counted against the loader's tally.
- **Malformed rows fail the run**, rather than only printing a warning. A row
  the reader skipped for a wrong field count is invisible to every other check,
  since it never reaches the accepted-row tally in the first place. For the
  workbook, "malformed" means a row with content in a column past `PrecinctPart`
  - a shape change that would otherwise load its first eight columns in silence.

### Performance

Measured on the real 2026-08 extract, on an M-series Mac:

- Full run (SQLite + Parquet, all three files): 91 seconds.
- Row counts: `voters` 5,573,822; `voting_history` 5,234,497;
  `districts_precincts` 231,537.
- Output sizes: SQLite 1,959.2 MB; `voters_20260803.parquet` 149.9 MB;
  `voting_history_20260803.parquet` 41.2 MB;
  `districts_precincts_20260803.parquet` 0.8 MB.
- The 773.3 MB source text becomes a 149.9 MB Parquet file, about 5.2x smaller.
- Verification: 0 malformed rows, 0 coercion warnings, districts join coverage
  99.9986% (5,573,743 of 5,573,822 voters).

The pipe-delimited reader (`vrdb/reader.py`) holds constant memory regardless
of file size - measured flat at 37.959 MB peak from 300k through 1.2M rows
read, because it streams the file in chunks and never materializes more than
one batch at a time. The xlsx reader (`vrdb/districts.py`) does not have that
property: it calls `element.clear()` on each row after reading it, which frees
the row's cell content but does not detach the now-empty `<row>` stub from its
parent, so memory grows linearly with row count - tens of MB across the
workbook's roughly 233,787 row elements. That workbook is small enough (231,537
data rows) for this not to matter in practice, but it is not the same
constant-memory design as the text reader.

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
leading zeros and merges distinct precincts across counties. Matched
literally, it joins 99.9986% of voters to a district row (5,573,743 of
5,573,822 in the 2026-08 extract).

### Data protection

VRDB extracts and everything derived from them are regulated under
RCW 29A.08.720 and RCW 29A.08.740. The data may be used for political purposes
but never for commercial advertising or solicitation; misuse is a class C
felony. **This repository is public.** Outputs contain this regulated data:
they default to the source data folder and must never be committed.

`.gitignore` covers the data file types:

- outputs and sources: `*.sqlite`, `*.sqlite3`, `*.db`, `*.parquet`, `*.txt`,
  `*.csv`, `*.xlsx`, `*.xls`, `*.zip`
- SQLite sidecars: `*.sqlite-wal`, `*.sqlite-shm`, `*.sqlite-journal`, and the
  same three suffixes on `*.sqlite3` and `*.db`. Any GUI that opens an output
  database with `PRAGMA journal_mode=WAL` (TablePlus, DB Browser) writes
  `vrdb_20260803.sqlite-wal` and `-shm` beside it, holding raw page data from
  the regulated tables. `*.sqlite` does not match those names.
- `.superpowers/`, the development ledger

`.gitignore` cannot protect the notebook, because `notebooks/vrdb_explore.ipynb`
is tracked on purpose. A notebook's rendered output is stored inside the
`.ipynb` file, so a cell that displayed voter data stays in version control
until that output is explicitly cleared, even though the code that produced it
looks harmless. Two things stand in the way, and `bash scripts/install-hooks.sh`
installs both:

- an **nbstripout clean filter**, wired up through `.gitattributes`, which
  strips outputs and execution counts as the file is staged
- a **pre-commit hook**, `scripts/pre-commit`, which inspects the staged blob
  of every `.ipynb` and refuses the commit if any code cell still has outputs
  or a non-null `execution_count`

Hooks and filter configuration live in `.git/`, which git does not track, so
**both are local-only and must be installed per clone**. The hook checks what
would actually be committed rather than the working tree, so it still fires on
a clone where the filter was never installed. `scripts/pre-commit` itself is
tracked, so the check travels with the repository even though its installation
does not.
