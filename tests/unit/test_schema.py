"""Unit tests for database schema and initialization."""

import sqlite3

import pytest


class TestSchemaCreation:
    """Test that the schema is correctly created via migrations."""

    def test_purchase_requests_table_exists(self, db_path):
        """Test that purchase_requests table exists after migrations."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='purchase_requests'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_can_insert_purchase_request(self, db_path):
        """Test inserting a row into purchase_requests."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO purchase_requests
                    (request_id, created_ts, patron_record_id, raw_query, status)
                VALUES ('test123', '2024-01-01T00:00:00Z', 12345, 'Test Book', 'new')
                """
            )
            conn.commit()

            cursor = conn.execute("SELECT * FROM purchase_requests WHERE request_id = 'test123'")
            row = cursor.fetchone()
            assert row is not None
        finally:
            conn.close()

    def test_schema_migrations_table_exists(self, db_path):
        """Test that schema_migrations table is created."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_indexes_created(self, db_path):
        """Test that expected indexes exist."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_requests_%'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
            assert "idx_requests_status_created" in indexes
            assert "idx_requests_patron_created" in indexes
        finally:
            conn.close()

    def test_login_attempts_table_exists(self, db_path):
        """Test that login_attempts table exists after migrations."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='login_attempts'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()


class TestStatusConstraint:
    """Test that status CHECK constraint works."""

    def test_valid_statuses_accepted(self, db_path):
        """Valid status values should be accepted."""
        conn = sqlite3.connect(db_path)
        try:
            valid_statuses = [
                "new",
                "in_review",
                "ordered",
                "declined",
                "duplicate_or_already_owned",
            ]
            insert_sql = """
                INSERT INTO purchase_requests
                    (request_id, created_ts, patron_record_id, raw_query, status)
                VALUES (?, '2024-01-01', 1, 'test', ?)
            """
            for i, status in enumerate(valid_statuses):
                conn.execute(insert_sql, (f"req{i}", status))
            conn.commit()

            cursor = conn.execute("SELECT COUNT(*) FROM purchase_requests")
            assert cursor.fetchone()[0] == len(valid_statuses)
        finally:
            conn.close()

    def test_invalid_status_rejected(self, db_path):
        """Invalid status values should be rejected."""
        conn = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO purchase_requests
                        (request_id, created_ts, patron_record_id, raw_query, status)
                    VALUES ('bad', '2024-01-01', 1, 'test', 'invalid_status')
                """)
        finally:
            conn.close()
