#!/usr/bin/env python3
"""Purge old purchase requests and events for retention compliance."""

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def purge(db_path: Path, days: int) -> int:
    """Delete purchase_requests and request_events older than N days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT request_id FROM purchase_requests WHERE created_ts < ?",
            (cutoff_iso,),
        )
        request_ids = [row[0] for row in cursor.fetchall()]
        if not request_ids:
            return 0

        conn.execute(
            "DELETE FROM request_events WHERE request_id IN ({})".format(
                ",".join("?" * len(request_ids))
            ),
            request_ids,
        )
        conn.execute(
            "DELETE FROM purchase_requests WHERE request_id IN ({})".format(
                ",".join("?" * len(request_ids))
            ),
            request_ids,
        )
        conn.commit()
        return len(request_ids)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge old purchase requests")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("suggest_purchase.db"),
        help="Path to the SQLite database file (default: suggest_purchase.db)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Delete requests older than this many days (default: 365)",
    )
    args = parser.parse_args()

    deleted = purge(args.db, args.days)
    print(f"Deleted {deleted} request(s) older than {args.days} days")


if __name__ == "__main__":
    main()
