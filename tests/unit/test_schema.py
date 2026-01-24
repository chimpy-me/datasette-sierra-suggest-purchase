"""Unit tests for database schema and initialization."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


def test_poc_schema_creation():
    """Test that the POC schema can be created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        conn = sqlite3.connect(db_path)
        try:
            # Apply POC schema
            conn.executescript("""
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

                CREATE INDEX IF NOT EXISTS idx_requests_status_created
                    ON purchase_requests(status, created_ts);
                CREATE INDEX IF NOT EXISTS idx_requests_patron_created
                    ON purchase_requests(patron_record_id, created_ts);
            """)
            conn.commit()

            # Verify table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='purchase_requests'"
            )
            assert cursor.fetchone() is not None

            # Test inserting a row
            conn.execute(
                """
                INSERT INTO purchase_requests
                    (request_id, created_ts, patron_record_id, raw_query, status)
                VALUES ('test123', '2024-01-01T00:00:00Z', 12345, 'Test Book', 'new')
                """
            )
            conn.commit()

            # Verify the row
            cursor = conn.execute("SELECT * FROM purchase_requests WHERE request_id = 'test123'")
            row = cursor.fetchone()
            assert row is not None
            assert row[3] == "Test Book"  # raw_query

        finally:
            conn.close()


def test_status_constraint():
    """Test that status CHECK constraint works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        conn = sqlite3.connect(db_path)
        try:
            conn.executescript("""
                CREATE TABLE purchase_requests (
                    request_id TEXT PRIMARY KEY,
                    created_ts TEXT NOT NULL,
                    patron_record_id INTEGER NOT NULL,
                    raw_query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
                );
            """)
            conn.commit()

            # Valid status should work
            conn.execute(
                "INSERT INTO purchase_requests VALUES ('1', '2024-01-01', 1, 'test', 'new')"
            )
            conn.execute(
                "INSERT INTO purchase_requests VALUES ('2', '2024-01-01', 1, 'test', 'ordered')"
            )
            conn.commit()

            # Invalid status should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO purchase_requests VALUES ('3', '2024-01-01', 1, 'test', 'invalid_status')"
                )

        finally:
            conn.close()
