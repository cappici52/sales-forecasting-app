r"""Copy the legacy local SQLite data to an empty, migrated PostgreSQL database.

Run from backend/: .\.venv\Scripts\python.exe scripts\copy_sqlite_to_postgres.py
Add --execute after checking the counts. SQLite and model files are never modified.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import sqlite3
import sys

from sqlalchemy import Date, DateTime, Boolean, create_engine, func, insert, select, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401 - register ORM tables
from app.config import settings
from app.database import Base


TABLES = ("organizations", "users", "sales_records", "model_runs", "forecast_snapshots")


def source_rows(connection: sqlite3.Connection, name: str) -> list[dict]:
    table = Base.metadata.tables[name]
    connection.row_factory = sqlite3.Row
    rows = []
    for source in connection.execute(f'SELECT * FROM "{name}" ORDER BY id'):
        item = {}
        for column in table.columns:
            value = source[column.name]
            if value is not None and isinstance(column.type, DateTime):
                value = datetime.fromisoformat(value)
            elif value is not None and isinstance(column.type, Date):
                value = date.fromisoformat(value)
            elif value is not None and isinstance(column.type, Boolean):
                value = bool(value)
            item[column.name] = value
        rows.append(item)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Copy into the empty PostgreSQL database")
    args = parser.parse_args()
    source_path = Path(__file__).resolve().parents[1] / "projecta1.db"
    if not source_path.is_file():
        raise SystemExit(f"SQLite source not found: {source_path}")
    url = make_url(settings.database_url)
    if not url.drivername.startswith("postgresql") or not url.database or url.database.endswith("_test"):
        raise SystemExit("DATABASE_URL must point to the main PostgreSQL database")

    with closing(sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)) as source:
        source.execute("PRAGMA query_only=ON")
        data = {name: source_rows(source, name) for name in TABLES}

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as destination:
            if destination.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "0001_initial":
                raise RuntimeError("PostgreSQL migration is not at 0001_initial")
            existing = {name: destination.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
                        for name in TABLES}
            if any(existing.values()):
                raise RuntimeError(f"Destination is not empty; refusing to copy: {existing}")
            print("SQLite source:", {name: len(rows) for name, rows in data.items()})
            print("PostgreSQL destination:", existing)
            if not args.execute:
                print("Dry run only. Re-run with --execute to copy data.")
                return

            for name in TABLES:
                table = Base.metadata.tables[name]
                for start in range(0, len(data[name]), 500):
                    destination.execute(insert(table), data[name][start:start + 500])
                if data[name]:
                    # Explicit SQLite IDs require advancing PostgreSQL identity sequences.
                    destination.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                        f"(SELECT max(id) FROM {name}), true)"
                    ))
                copied = destination.scalar(select(func.count()).select_from(table))
                if copied != len(data[name]):
                    raise RuntimeError(f"Count mismatch for {name}: {copied} != {len(data[name])}")
            print("Copied and verified:", {name: len(rows) for name, rows in data.items()})
            print("Active login sessions were intentionally not copied; sign in again.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
