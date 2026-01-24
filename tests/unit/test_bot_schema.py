"""Tests for suggest-a-bot schema and migrations."""

import sqlite3

import pytest


class TestBotSchema:
    """Test the bot-related schema additions."""

    def test_request_events_table_exists(self, db_path):
        """request_events table should be created by migration."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='request_events'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_bot_runs_table_exists(self, db_path):
        """bot_runs table should be created by migration."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_runs'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_purchase_requests_has_bot_columns(self, db_path):
        """purchase_requests should have bot-related columns."""
        conn = sqlite3.connect(db_path)
        try:
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
            conn.close()

    def test_bot_status_constraint(self, db_path):
        """bot_status should only accept valid values."""
        conn = sqlite3.connect(db_path)
        try:
            # Valid status should work
            conn.execute("""
                INSERT INTO purchase_requests
                    (request_id, created_ts, patron_record_id, raw_query, bot_status)
                VALUES ('test1', '2024-01-01', 12345, 'test query', 'pending')
            """)
            conn.commit()

            # Invalid status should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO purchase_requests
                        (request_id, created_ts, patron_record_id, raw_query, bot_status)
                    VALUES ('test2', '2024-01-01', 12345, 'test query', 'invalid_status')
                """)
        finally:
            conn.close()

    def test_catalog_match_constraint(self, db_path):
        """catalog_match should only accept valid values or NULL."""
        conn = sqlite3.connect(db_path)
        try:
            # NULL should work (default)
            conn.execute("""
                INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query)
                VALUES ('test1', '2024-01-01', 12345, 'test query')
            """)
            conn.commit()

            # Valid value should work
            conn.execute("""
                INSERT INTO purchase_requests
                    (request_id, created_ts, patron_record_id, raw_query, catalog_match)
                VALUES ('test2', '2024-01-01', 12345, 'test query', 'exact')
            """)
            conn.commit()

            # Invalid value should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO purchase_requests
                        (request_id, created_ts, patron_record_id, raw_query, catalog_match)
                    VALUES ('test3', '2024-01-01', 12345, 'test query', 'invalid')
                """)
        finally:
            conn.close()

    def test_event_type_constraint(self, db_path):
        """request_events event_type should only accept valid values."""
        conn = sqlite3.connect(db_path)
        try:
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
            conn.close()

    def test_bot_runs_status_constraint(self, db_path):
        """bot_runs status should only accept valid values."""
        conn = sqlite3.connect(db_path)
        try:
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
            conn.close()


class TestMigrationRunner:
    """Test the migration runner itself."""

    def test_migrations_are_idempotent(self, db_path):
        """Running migrations multiple times should not fail."""
        from datasette_suggest_purchase.migrations import run_migrations

        # Run migrations again - should not fail
        applied = run_migrations(db_path, verbose=False)
        assert applied == []  # Nothing new to apply

    def test_get_current_version(self, db_path):
        """Should report correct schema version."""
        from datasette_suggest_purchase.migrations import get_current_version

        version = get_current_version(db_path)
        assert version == 2  # Base (1) + migration 0002
