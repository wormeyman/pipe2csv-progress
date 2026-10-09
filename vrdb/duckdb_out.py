"""DuckDB views over the Parquet output, for browsing in TablePlus.

This is the only module that imports duckdb. It writes vrdb_YYYYMMDD.duckdb
beside the Parquet files: one view per table, named by table rather than by
date, so a saved TablePlus filter on `voters` still works next month. Each view
reads its Parquet file live, so the file holds no voter rows. It also carries
the three small lookup tables, schema.REF_TABLES.
Paths in it are absolute, because TablePlus opens it from its own working
directory.

It also writes "Open vrdb_YYYYMMDD.duckdb in TablePlus.app" to double-click.
TablePlus does not claim .duckdb files, and no app claims the duckdb:// link
scheme, so the launcher hands the link to TablePlus by name.

    python vrdb_export.py /path/to/10.2026.WA     # every export writes the views
    python -m vrdb.duckdb_out /path/to/10.2026.WA  # views for a folder exported before that
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

import duckdb

from vrdb import schema

TABLES = ("voters", "voting_history", "districts_precincts")
_PARQUET = re.compile(r"^(?P<table>[a-z_]+)_(?P<date>\d{8})\.parquet$")


def views_path(out_dir: Path, extract_date: str) -> Path:
    return out_dir / f"vrdb_{extract_date}.duckdb"


def launcher_path(views: Path) -> Path:
    return views.with_name(f"Open {views.name} in TablePlus.app")


def _quote(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def write_views(path: Path, parquet: dict[str, Path]) -> Path:
    """One view per table over its Parquet file, plus the small lookup tables,
    through a temp file so a viewer never opens a half-written one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as conn:
        for table, source in parquet.items():
            conn.execute(f'CREATE VIEW "{table}" AS SELECT * FROM read_parquet({_quote(source)})')
        for name, (key, value), mapping in schema.REF_TABLES:
            conn.execute(f'CREATE TABLE "{name}" ({key} VARCHAR PRIMARY KEY, {value} VARCHAR)')
            conn.executemany(f'INSERT INTO "{name}" VALUES (?, ?)', sorted(mapping.items()))
    tmp.replace(path)
    return path


def tableplus_url(path: Path) -> str:
    """A TablePlus connection link for the views file."""
    query = urlencode({"statusColor": "007F3D", "env": "", "name": path.stem, "tLSMode": 0,
                       "usePrivateKey": "false", "safeModeLevel": 0, "advancedSafeModeLevel": 0,
                       "driverVersion": 0, "lazyload": "false"})
    return f"duckdb://@{quote(str(path), safe='')}/{path.name}?{query}"


def launcher_script(url: str) -> str:
    literal = url.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "open -a TablePlus " & quoted form of "{literal}"'


def write_launcher(views: Path) -> Path | None:
    """Compile the double-click launcher. None where there is no osacompile (not macOS)."""
    if shutil.which("osacompile") is None:
        return None
    app = launcher_path(views)
    tmp = app.with_name(app.name + ".tmp.app")
    shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(["osacompile", "-o", str(tmp), "-e", launcher_script(tableplus_url(views))],
                   check=True)
    shutil.rmtree(app, ignore_errors=True)
    tmp.rename(app)
    return app


def find_parquet(folder: Path) -> tuple[str, dict[str, Path]]:
    """The newest extract date that has a voters file, and its table files."""
    by_date: dict[str, dict[str, Path]] = {}
    for path in folder.iterdir():
        match = _PARQUET.match(path.name)
        if match and match["table"] in TABLES:
            by_date.setdefault(match["date"], {})[match["table"]] = path
    dates = sorted(d for d, files in by_date.items() if "voters" in files)
    if not dates:
        raise FileNotFoundError(f"no voters_YYYYMMDD.parquet in {folder}")
    found = by_date[dates[-1]]
    return dates[-1], {t: found[t] for t in TABLES if t in found}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write DuckDB views over a folder's VRDB Parquet files.")
    parser.add_argument("folder", help="Folder holding the Parquet files")
    parser.add_argument("--no-launcher", action="store_true", help="Skip the TablePlus launcher app")
    args = parser.parse_args(argv)
    folder = Path(args.folder).expanduser()
    try:
        extract_date, parquet = find_parquet(folder)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    views = write_views(views_path(folder, extract_date), parquet)
    print(f"Wrote {views} ({views.stat().st_size / 1e3:.0f} KB): {', '.join(parquet)}")
    if not args.no_launcher and (app := write_launcher(views)) is not None:
        print(f"Wrote {app.name}, to double-click")
    return 0


if __name__ == "__main__":
    sys.exit(main())
