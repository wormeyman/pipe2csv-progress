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

_DESCRIPTION = (
    __doc__ or "Load a Washington VRDB extract into SQLite and Parquet."
).splitlines()[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
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
    try:
        found = discover.discover(Path(folder).expanduser())
    except (discover.MissingExtract, discover.AmbiguousExtract) as error:
        # These messages already say what to do; only the traceback was wrong.
        print(error, file=sys.stderr)
        return 2

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
    # Rows the tee path actually inserted into SQLite, per table, so the two
    # outputs of a single shared pass can be checked against each other.
    sqlite_rows: dict[str, int] = {}

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
                assert conn is not None
                db = conn
                name = table.name
                sqlite_rows[name] = 0

                def tee():
                    for batch in make():
                        sqlite_rows[name] += sqlite_out.insert_batches(
                            db, table, [batch]
                        )
                        yield batch

                written[table.name] = parquet_out.write_batches(
                    paths[f"parquet:{table.name}"], table, tee()
                )
            elif want_sqlite:
                assert conn is not None
                db = conn
                written[table.name] = sqlite_out.insert_batches(db, table, make())
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
                table_stats = all_stats[table.name]
                # Before the row count, which reports skipped rows as expected
                # rather than as a shortfall.
                results.append(verify.check_no_malformed_rows(table, table_stats))
                # Counted by re-reading the source, not taken from the loader's
                # own tally, so a load that stopped early cannot satisfy it.
                # Measured at 1.1s for the 765 MB voters file, 0.4s for voting
                # history and 2.4s for the workbook's second parse.
                if table is schema.DISTRICTS_PRECINCTS:
                    source_rows = verify.count_workbook_rows(path)
                else:
                    source_rows = verify.count_source_rows(path, encoding=args.encoding)
                results.append(
                    verify.check_row_count(
                        conn, table, source_rows, skipped=table_stats.malformed
                    )
                )
                results.append(verify.check_primary_key_unique(conn, table))
                if table.name in sqlite_rows:
                    results.append(
                        verify.check_parquet_matches_sqlite(
                            table, sqlite_rows[table.name], written[table.name]
                        )
                    )
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
        if isinstance(error, reader.HeaderMismatch):
            # The loader refusing to guess at renamed or reordered columns is
            # an expected outcome, not a crash. Its message already names the
            # file and both column lists.
            print(error, file=sys.stderr)
            return 1
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
    if not results:
        # --skip-verify, or --parquet alone (verification needs the database).
        # An empty result list is not a clean bill of health.
        print("NO CHECKS RUN")
    else:
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
