"""Tests for suggest-a-bot schema and migrations."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


def create_test_db() -> Path:
    """Create a test database with full schema."""
    # Import here to avoid issues if package not installed
    from datasette_suggest_purchase.migrations import run_migrations

    fd, path = tempfile.mkstemp(suffix=".db")
    db_path = Path(path)

    # Create base schema
    conn = sqlite3.connect(db_path)
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

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_ts TEXT NOT NULL
        );

        INSERT OR IGNORE INTO schema_migrations (version, applied_ts)
            VALUES (1, datetime('now'));
    """)
    conn.commit()
    conn.close()

    # Run migrations
    run_migrations(db_path, verbose=False)

    return db_path


class TestBotSchema:
    """Test the bot-related schema additions."""

    def test_request_events_table_exists(self):
        """request_events table should be created by migration."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='request_events'"
            )
            assert cursor.fetchone() is not None
        finally:
            db_path.unlink()

    def test_bot_runs_table_exists(self):
        """bot_runs table should be created by migration."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_runs'"
            )
            assert cursor.fetchone() is not None
        finally:
            db_path.unlink()

    def test_purchase_requests_has_bot_columns(self):
        """purchase_requests should have bot-related columns."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("PRAGMA table_info(purchase_requests)")
            columns = {row[1] for row in cursor.fetchall()}

            expected_columns = {
                "bot_status",
                "bot_processed_ts",
                "bot_error",
                "catalog_match",
                "catalog_holdings_json",
                "catalog_checked_ts",
                "consortium_available",
                "consortium_sources_json",
                "consortium_checked_ts",
                "refined_title",
                "refined_author",
                "refined_isbn",
                "authority_source",
                "refinement_confidence",
                "bot_assessment_json",
                "bot_notes",
                "bot_action",
                "bot_action_ts",
            }

            for col in expected_columns:
                assert col in columns, f"Missing column: {col}"
        finally:
            db_path.unlink()

    def test_bot_status_constraint(self):
        """bot_status should only accept valid values."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)

            # Valid status should work
            conn.execute("""
                INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, bot_status)
                VALUES ('test1', '2024-01-01', 12345, 'test query', 'pending')
            """)
            conn.commit()

            # Invalid status should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, bot_status)
                    VALUES ('test2', '2024-01-01', 12345, 'test query', 'invalid_status')
                """)
        finally:
            db_path.unlink()

    def test_catalog_match_constraint(self):
        """catalog_match should only accept valid values or NULL."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)

            # NULL should work (default)
            conn.execute("""
                INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query)
                VALUES ('test1', '2024-01-01', 12345, 'test query')
            """)
            conn.commit()

            # Valid value should work
            conn.execute("""
                INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, catalog_match)
                VALUES ('test2', '2024-01-01', 12345, 'test query', 'exact')
            """)
            conn.commit()

            # Invalid value should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, catalog_match)
                    VALUES ('test3', '2024-01-01', 12345, 'test query', 'invalid')
                """)
        finally:
            db_path.unlink()

    def test_event_type_constraint(self):
        """request_events event_type should only accept valid values."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)

            # First create a request to reference
            conn.execute("""
                INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query)
                VALUES ('req1', '2024-01-01', 12345, 'test query')
            """)
            conn.commit()

            # Valid event type should work
            conn.execute("""
                INSERT INTO request_events (event_id, request_id, ts, actor_id, event_type)
                VALUES ('evt1', 'req1', '2024-01-01', 'bot:suggest-a-bot', 'bot_started')
            """)
            conn.commit()

            # Invalid event type should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO request_events (event_id, request_id, ts, actor_id, event_type)
                    VALUES ('evt2', 'req1', '2024-01-01', 'bot:suggest-a-bot', 'invalid_type')
                """)
        finally:
            db_path.unlink()

    def test_bot_runs_status_constraint(self):
        """bot_runs status should only accept valid values."""
        db_path = create_test_db()
        try:
            conn = sqlite3.connect(db_path)

            # Valid status should work
            conn.execute("""
                INSERT INTO bot_runs (run_id, started_ts, status)
                VALUES ('run1', '2024-01-01', 'running')
            """)
            conn.commit()

            # Invalid status should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO bot_runs (run_id, started_ts, status)
                    VALUES ('run2', '2024-01-01', 'invalid_status')
                """)
        finally:
            db_path.unlink()


class TestMigrationRunner:
    """Test the migration runner itself."""

    def test_migrations_are_idempotent(self):
        """Running migrations multiple times should not fail."""
        from datasette_suggest_purchase.migrations import run_migrations

        db_path = create_test_db()
        try:
            # Run migrations again - should not fail
            applied = run_migrations(db_path, verbose=False)
            assert applied == []  # Nothing new to apply
        finally:
            db_path.unlink()

    def test_get_current_version(self):
        """Should report correct schema version."""
        from datasette_suggest_purchase.migrations import get_current_version

        db_path = create_test_db()
        try:
            version = get_current_version(db_path)
            assert version == 2  # Base (1) + migration 0002
        finally:
            db_path.unlink()
