#!/usr/bin/env python3
"""Initialize the suggest-a-purchase database with all migrations."""

import argparse
import sqlite3
from pathlib import Path

from datasette_suggest_purchase.migrations import run_migrations


def init_db(db_path: Path) -> None:
    """Create the database with all migrations applied."""
    print(f"Initializing database: {db_path}")

    # Run all migrations (creates DB if needed)
    print("Running migrations...")
    applied = run_migrations(db_path, verbose=True)
    if applied:
        print(f"Applied {len(applied)} migration(s): {applied}")

    # Show final state
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT version, applied_ts FROM schema_migrations ORDER BY version")
        print("\nSchema versions:")
        for row in cursor:
            print(f"  v{row[0]} applied at {row[1]}")

        # Show table list
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor if not row[0].startswith("sqlite_")]
        print(f"\nTables: {', '.join(tables)}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize suggest-a-purchase database")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("suggest_purchase.db"),
        help="Path to the SQLite database file (default: suggest_purchase.db)",
    )
    args = parser.parse_args()

    init_db(args.db)


if __name__ == "__main__":
    main()
