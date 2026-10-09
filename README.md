# pipe2csv-progress
Two tools for working with Washington voter registry (VRDB) extracts. `to_csv_progress.py` converts a large, pipe-delimited export that uses `<br>` for line breaks into standard RFC 4180 CSV, fast, with accurate progress, ETA, and proper quoting for commas inside fields. `vrdb_export.py` loads a full monthly extract into typed Parquet files with DuckDB views for browsing in TablePlus, and optionally a SQLite database - see [below](#vrdb_exportpy---load-an-extract-into-parquet).

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

## vrdb_export.py - load an extract into Parquet

Builds typed Parquet files from a monthly Washington VRDB extract, with a small
DuckDB file of views over them for browsing in TablePlus. Pass `--sqlite` to
also build a typed, indexed SQLite database, about 10 times the size.

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
`*Voting_History*.txt`, `*Districts-Precincts.xlsx`). Run it with no arguments
to be prompted for the folder. Only the VRDB file is required; a missing
history or districts file is a warning, and the table it would have populated
is simply skipped.

It reads the original pipe-delimited export and nothing else. A `.csv` you
converted earlier - with `to_csv_progress.py`, say - is comma-delimited, and
the reader splits on `|` only, so such a file is deliberately not discovered
rather than found and then rejected. If a folder holds two files matching one
pattern, or a header whose columns have been renamed or reordered, the run
stops with a message naming the problem instead of loading a guess.

Outputs are named from the extract date and land in the source folder by
default. A plain run writes `voters_20261001.parquet`,
`voting_history_20261001.parquet` and `districts_precincts_20261001.parquet`,
the views file `vrdb_20261001.duckdb`, and on a Mac a launcher app to
double-click (see [Browsing in TablePlus](#browsing-in-tableplus)). With
`--sqlite` you also get `vrdb_20261001.sqlite`, from the same read pass.
Re-running is idempotent; it refuses to overwrite an existing output unless
you pass `--force`, and if a run fails partway it deletes whatever partial
outputs it had already started writing.

Options:

| Option | Effect |
|---|---|
| `--out DIR` | Output directory (default: the source folder) |
| `--sqlite` | Also build the SQLite database, about 10 times the size of the Parquet files |
| `--force` | Overwrite existing outputs |
| `--skip-verify` | Skip the post-load verification pass |
| `--encoding ENCODING` | Source encoding (default: `cp1252`) |
| `--tick TICK` | Progress interval, in rows (default: 100000) |
| `--batch BATCH` | Rows per batch (default: 50000) |
| `--join-floor JOIN_FLOOR` | Minimum share of voters that must join to a district row before the check fails (default 0.95). The 2026-08 extract measures 0.999986. Lower it only to investigate an extract whose `PrecinctPart` format changed. |

### Verification

Unless you pass `--skip-verify`, the run re-checks its own output and exits 1
if anything fails. Per table it checks that no row was skipped as malformed,
that the row count is right, that the primary key is unique, and - for the two
pipe-delimited tables - that 200 rows re-read at random offsets from the source
match the output field for field. Every check reads the Parquet files through
the DuckDB views, so the default run is fully checked with no database. With
`--sqlite` it also checks that SQLite holds as many rows as each Parquet file,
since the two writers share one read pass. It finishes by reporting what share
of voters join to a district row.

Two of those deserve spelling out, because the obvious implementation of each
is a check that cannot fail:

- **The row count comes from re-reading the source**, not from the loader's own
  tally of rows it accepted. Given that tally, the check compares the loader to
  itself: a load that stopped early leaves a database holding exactly the rows
  the reader counted, so both sides agree no matter how much of the file went
  unread. Re-counting costs 1.1s on the 765 MB voters file, 0.4s on voting
  history and 2.4s to parse the workbook a second time - about 4 seconds on a
  94-second run.
- **Malformed rows fail the run**, rather than only printing a warning. A row
  the reader skipped for a wrong field count is invisible to every other check,
  since it never reaches the accepted-row tally in the first place. For the
  workbook, "malformed" means a row with content in a column past `PrecinctPart`
  - a shape change that would otherwise load its first eight columns in silence.

### Performance

The default run on the real 2026-10 extract, on an M-series Mac: 39.9
seconds, every check passed, 5,593,488 voters. Its outputs are the three
Parquet files (170.1 MB) and the views file (1.8 MB). The same extract with
`--sqlite` took 86.8 seconds and added a 1,770.1 MB database.

Measured earlier on the real 2026-08 extract, when SQLite was the default:

- Full run writing both SQLite and Parquet for all three files: 91 seconds.
- Row counts: `voters` 5,573,822; `voting_history` 5,234,497;
  `districts_precincts` 231,537.
- Output sizes: SQLite 1,959.2 MB; `voters_20260803.parquet` 149.9 MB;
  `voting_history_20260803.parquet` 41.2 MB;
  `districts_precincts_20260803.parquet` 0.8 MB.
- The 773.3 MB source text becomes a 149.9 MB Parquet file, about 5.2x smaller.
- Verification: 0 malformed rows, 0 coercion warnings, districts join coverage
  99.9986% (5,573,743 of 5,573,822 voters).

Back then, skipping Parquet was worth roughly 11%. The 2026-04 extract, same machine, same
5.5M voters: 83.2 seconds writing SQLite alone against 93.8 seconds writing both.
Most of that is in the voters pass, which reads at 161k rows/s writing SQLite
alone and 123k rows/s feeding both writers from the shared read.

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

### Browsing in TablePlus

Parquet is far smaller than the database. On the 2026-10 extract the three
Parquet files total 170.1 MB against 1,770.1 MB of SQLite. DuckDB browses them
without a copy, through `vrdb_20261001.duckdb`, which every run writes beside
them. For a folder exported before views existed:

```bash
.venv/bin/python -m vrdb.duckdb_out /path/to/10.2026.WA
```

The views file holds three views, `voters`, `voting_history` and
`districts_precincts`, plus the lookup tables `ref_county`, `ref_gender` and
`ref_status`. The views hold no rows: each reads its Parquet file live. The
file is 1.8 MB, almost all of it DuckDB's fixed storage for the three small
tables. The views are named by table, not by date, so a saved TablePlus filter
still works on next month's extract.

TablePlus 27 has DuckDB 1.5.6 built in, and `pyproject.toml` pins the same
version. TablePlus does not open `.duckdb` files on a double-click (Tad
does), so the run also writes `Open vrdb_20261001.duckdb in TablePlus.app`.
Double-click that. It runs `open -a TablePlus` on a `duckdb://` connection
link, since no app claims that link scheme by itself.

The views file and the launcher hold file paths, not voters, but both are
gitignored with the rest of the outputs.

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
- DuckDB views and their launcher: `*.duckdb`, `*.duckdb.tmp`, `*.duckdb.wal`
  and `Open *.duckdb in TablePlus.app/`. They hold file paths and the lookup
  tables, not voters, but they name the extract files.
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
