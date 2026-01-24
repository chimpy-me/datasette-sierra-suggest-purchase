"""
Database migration utilities for datasette-suggest-purchase.

Migrations are numbered SQL files in this directory (e.g., 0002_description.sql).
They are applied in order based on the numeric prefix.
"""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent


def get_migration_files() -> list[tuple[int, Path]]:
    """Get all migration files sorted by version number."""
    migrations = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            version = int(match.group(1))
            migrations.append((version, path))
    return sorted(migrations, key=lambda x: x[0])


def get_applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Get the set of already-applied migration versions."""
    try:
        cursor = conn.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return set()


def apply_migration(conn: sqlite3.Connection, version: int, path: Path) -> None:
    """Apply a single migration file."""
    sql = path.read_text()
    now = datetime.now(UTC).isoformat()

    # Execute the migration
    conn.executescript(sql)

    # Record that we applied it
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_ts) VALUES (?, ?)",
        (version, now),
    )
    conn.commit()


def run_migrations(db_path: Path, verbose: bool = True) -> list[int]:
    """
    Run all pending migrations on the database.

    Returns list of versions that were applied.
    """
    conn = sqlite3.connect(db_path)
    applied = []

    try:
        # Ensure schema_migrations table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_ts TEXT NOT NULL
            )
        """)
        conn.commit()

        already_applied = get_applied_versions(conn)
        migrations = get_migration_files()

        for version, path in migrations:
            if version in already_applied:
                if verbose:
                    print(f"  Skipping migration {version} (already applied)")
                continue

            if verbose:
                print(f"  Applying migration {version}: {path.name}")

            apply_migration(conn, version, path)
            applied.append(version)

        if verbose and not applied:
            print("  No new migrations to apply.")

    finally:
        conn.close()

    return applied


def get_current_version(db_path: Path) -> int:
    """Get the current schema version."""
    if not db_path.exists():
        return 0

    conn = sqlite3.connect(db_path)
    try:
        applied = get_applied_versions(conn)
        return max(applied) if applied else 0
    finally:
        conn.close()
