#!/usr/bin/env python3
"""Initialize the suggest-a-purchase database with all migrations."""

import argparse
import sqlite3
from pathlib import Path

# Base schema (version 1) - the original POC schema
BASE_SCHEMA = """
-- Base schema v1: Core purchase_requests table

CREATE TABLE IF NOT EXISTS purchase_requests (
    request_id TEXT PRIMARY KEY,
    created_ts TEXT NOT NULL,
    patron_record_id INTEGER NOT NULL,
    raw_query TEXT NOT NULL,
    format_preference TEXT,
    patron_notes TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    staff_notes TEXT,
    updated_ts TEXT,

    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_requests_status_created
    ON purchase_requests(status, created_ts);

CREATE INDEX IF NOT EXISTS idx_requests_patron_created
    ON purchase_requests(patron_record_id, created_ts);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_ts TEXT NOT NULL
);

-- Record base schema as version 1
INSERT OR IGNORE INTO schema_migrations (version, applied_ts)
    VALUES (1, datetime('now'));
"""


def init_db(db_path: Path, run_migrations: bool = True) -> None:
    """Create the database with base schema and optionally run migrations."""
    print(f"Initializing database: {db_path}")

    # Create with base schema
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(BASE_SCHEMA)
        conn.commit()
        print("  Base schema (v1) created.")
    finally:
        conn.close()

    # Run any additional migrations
    if run_migrations:
        print("Running migrations...")
        from datasette_suggest_purchase.migrations import run_migrations as do_migrations

        applied = do_migrations(db_path, verbose=True)
        if applied:
            print(f"Applied {len(applied)} migration(s).")

    # Show final state
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT version, applied_ts FROM schema_migrations ORDER BY version"
        )
        print("\nSchema versions:")
        for row in cursor:
            print(f"  v{row[0]} applied at {row[1]}")

        # Show table list
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
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
    parser.add_argument(
        "--no-migrations",
        action="store_true",
        help="Skip running migrations (base schema only)",
    )
    args = parser.parse_args()

    init_db(args.db, run_migrations=not args.no_migrations)


if __name__ == "__main__":
    main()
