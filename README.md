# pipe2csv-progress
Convert large, pipe-delimited voter registry exports that use `<br>` for line breaks into standard RFC 4180 CSV, fast, with accurate progress, ETA, and proper quoting for commas inside fields.

- Streams input in a single pass
- Handles Windows-1252 (smart quotes) by default
- Normalizes `<br>` and `<br/>` to newlines
- Writes UTF-8 CSV with correct quoting
- Shows rows processed, rate, percent, and ETA
- No external Python dependencies

## Quick start

`python3 to_csv_progress_pct.py INPUT.txt OUTPUT.csv`

Examples:

Default: CP1252 -> UTF-8 CSV
`python3 to_csv_progress_pct.py 20250701_VRDB_Extract.txt voters.csv`
More frequent progress updates
`python3 to_csv_progress_pct.py 20250701_VRDB_Extract.txt voters.csv --tick 20000`
Different source encoding (if needed)
`python3 to_csv_progress_pct.py 20250701_VRDB_Extract.txt voters.csv --encoding latin-1`
Larger read chunks for slightly higher throughput
`python3 to_csv_progress_pct.py 20250701_VRDB_Extract.txt voters.csv --chunk 2097152`

## Why this script

Many county/state exports use pipes as field separators and `<br>` as row delimiters, and often encode as Windows-1252. This tool:
- Converts `<br>` to real newlines
- Parses pipes safely (fields may contain commas)
- Outputs a clean UTF-8 CSV that standard tools can import

## Usage details

positional arguments:
inp                  Input text file (pipe-delimited, 
 line breaks)
out                  Output CSV file (UTF-8)
options:
--encoding           Source encoding (default: cp1252)
--tick               Print progress every N rows (default: 100000)
--chunk              Read chunk size in bytes (default: 1048576)

## Sanity checks

wc -l voters.csv          # expect N+1 lines (including header)
head -1 voters.csv
tail -1 voters.csv