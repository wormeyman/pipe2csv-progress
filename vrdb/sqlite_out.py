"""SQLite output.

Bulk-load pragmas are safe here because the database is a disposable derivative
of the source extract: if a load is interrupted the file is deleted and rebuilt.
Indexes are created after the inserts, never before.
"""

import sqlite3

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
