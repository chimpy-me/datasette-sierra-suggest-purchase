#!/usr/bin/env python3
"""Initialize the POC database schema for suggest-a-purchase."""

import argparse
import sqlite3
from pathlib import Path

POC_SCHEMA = """
-- POC schema: single table (Option A from architectural review)
-- This is intentionally minimal for the 2-day demo.

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

-- Schema version tracking (for future migrations)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_ts TEXT NOT NULL
);

-- Record that we've applied the initial schema
INSERT OR IGNORE INTO schema_migrations (version, applied_ts)
    VALUES (1, datetime('now'));
"""


def init_db(db_path: Path) -> None:
    """Create the database with the POC schema."""
    print(f"Initializing database: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(POC_SCHEMA)
        conn.commit()
        print("Schema created successfully.")

        # Verify
        cursor = conn.execute(
            "SELECT version, applied_ts FROM schema_migrations ORDER BY version"
        )
        for row in cursor:
            print(f"  Migration v{row[0]} applied at {row[1]}")
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
