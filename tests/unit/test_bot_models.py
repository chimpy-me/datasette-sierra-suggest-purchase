"""Tests for suggest-a-bot models and database operations."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from suggest_a_bot.models import (
    BotDatabase,
    BotStatus,
    CatalogMatch,
    EventType,
    PurchaseRequest,
    RunStatus,
)


def create_test_db() -> Path:
    """Create a test database with full schema."""
    from datasette_suggest_purchase.migrations import run_migrations

    fd, path = tempfile.mkstemp(suffix=".db")
    db_path = Path(path)

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

    run_migrations(db_path, verbose=False)
    return db_path


def seed_test_request(db_path: Path, request_id: str = "req1", raw_query: str = "Test Book") -> None:
    """Insert a test request into the database."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, status)
        VALUES (?, '2024-01-01T00:00:00Z', 12345, ?, 'new')
    """, (request_id, raw_query))
    conn.commit()
    conn.close()


class TestBotDatabase:
    """Test BotDatabase operations."""

    def test_get_pending_requests(self):
        """Should retrieve requests with bot_status='pending'."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1", "Book One")
            seed_test_request(db_path, "req2", "Book Two")

            db = BotDatabase(db_path)
            requests = db.get_pending_requests()

            assert len(requests) == 2
            assert all(r.bot_status == "pending" for r in requests)
        finally:
            db_path.unlink()

    def test_get_pending_requests_respects_limit(self):
        """Should respect the limit parameter."""
        db_path = create_test_db()
        try:
            for i in range(5):
                seed_test_request(db_path, f"req{i}", f"Book {i}")

            db = BotDatabase(db_path)
            requests = db.get_pending_requests(limit=2)

            assert len(requests) == 2
        finally:
            db_path.unlink()

    def test_get_pending_requests_excludes_processed(self):
        """Should not return already-processed requests."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1", "Book One")
            seed_test_request(db_path, "req2", "Book Two")

            db = BotDatabase(db_path)
            db.mark_completed("req1")

            requests = db.get_pending_requests()

            assert len(requests) == 1
            assert requests[0].request_id == "req2"
        finally:
            db_path.unlink()

    def test_get_request(self):
        """Should retrieve a specific request by ID."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1", "Test Book")

            db = BotDatabase(db_path)
            request = db.get_request("req1")

            assert request is not None
            assert request.request_id == "req1"
            assert request.raw_query == "Test Book"
        finally:
            db_path.unlink()

    def test_get_request_not_found(self):
        """Should return None for non-existent request."""
        db_path = create_test_db()
        try:
            db = BotDatabase(db_path)
            request = db.get_request("nonexistent")

            assert request is None
        finally:
            db_path.unlink()

    def test_mark_processing(self):
        """Should update bot_status to 'processing'."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            db.mark_processing("req1")

            request = db.get_request("req1")
            assert request.bot_status == "processing"
        finally:
            db_path.unlink()

    def test_mark_completed(self):
        """Should update bot_status to 'completed' with timestamp."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            db.mark_completed("req1")

            request = db.get_request("req1")
            assert request.bot_status == "completed"
            assert request.bot_processed_ts is not None
        finally:
            db_path.unlink()

    def test_mark_error(self):
        """Should update bot_status to 'error' with error message."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            db.mark_error("req1", "Something went wrong")

            request = db.get_request("req1")
            assert request.bot_status == "error"
            assert request.bot_error == "Something went wrong"
            assert request.bot_processed_ts is not None
        finally:
            db_path.unlink()

    def test_save_catalog_result(self):
        """Should save catalog lookup results."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            holdings = [{"bib_id": "123", "title": "Test Book", "status": "available"}]
            db.save_catalog_result("req1", CatalogMatch.EXACT, holdings)

            request = db.get_request("req1")
            assert request.catalog_match == "exact"
            assert request.catalog_checked_ts is not None
            assert request.catalog_holdings == holdings
        finally:
            db_path.unlink()

    def test_save_consortium_result(self):
        """Should save consortium check results."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            sources = [{"library": "Columbus Metro", "status": "available"}]
            db.save_consortium_result("req1", True, sources)

            request = db.get_request("req1")
            assert request.consortium_available == 1
            assert request.consortium_checked_ts is not None
            assert request.consortium_sources == sources
        finally:
            db_path.unlink()

    def test_save_refinement(self):
        """Should save input refinement results."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            db.save_refinement(
                "req1",
                title="The Women: A Novel",
                author="Kristin Hannah",
                isbn="9781250178633",
                source="worldcat",
                confidence=0.95,
            )

            request = db.get_request("req1")
            assert request.refined_title == "The Women: A Novel"
            assert request.refined_author == "Kristin Hannah"
            assert request.refined_isbn == "9781250178633"
            assert request.authority_source == "worldcat"
            assert request.refinement_confidence == 0.95
        finally:
            db_path.unlink()

    def test_save_assessment(self):
        """Should save bot assessment results."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            assessment = {
                "recommendation": "purchase",
                "confidence": "high",
                "reasoning": ["Popular author", "Not in catalog"],
            }
            db.save_assessment("req1", assessment, "Recommend purchase.")

            request = db.get_request("req1")
            assert request.bot_assessment == assessment
            assert request.bot_notes == "Recommend purchase."
        finally:
            db_path.unlink()


class TestBotRuns:
    """Test bot run tracking."""

    def test_create_run(self):
        """Should create a new bot run record."""
        db_path = create_test_db()
        try:
            db = BotDatabase(db_path)
            config = {"max_requests": 50}
            run = db.create_run(config)

            assert run.run_id is not None
            assert run.status == "running"
            assert run.started_ts is not None
        finally:
            db_path.unlink()

    def test_complete_run(self):
        """Should mark a run as complete with stats."""
        db_path = create_test_db()
        try:
            db = BotDatabase(db_path)
            run = db.create_run()

            db.complete_run(run.run_id, processed=5, errored=1)

            # Verify in database
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT status, requests_processed, requests_errored FROM bot_runs WHERE run_id = ?",
                (run.run_id,),
            )
            row = cursor.fetchone()
            assert row[0] == "completed"
            assert row[1] == 5
            assert row[2] == 1
        finally:
            db_path.unlink()

    def test_complete_run_with_failure(self):
        """Should mark a run as failed with error message."""
        db_path = create_test_db()
        try:
            db = BotDatabase(db_path)
            run = db.create_run()

            db.complete_run(
                run.run_id,
                processed=2,
                errored=0,
                status=RunStatus.FAILED,
                error_message="Database connection lost",
            )

            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT status, error_message FROM bot_runs WHERE run_id = ?",
                (run.run_id,),
            )
            row = cursor.fetchone()
            assert row[0] == "failed"
            assert row[1] == "Database connection lost"
        finally:
            db_path.unlink()


class TestRequestEvents:
    """Test audit trail events."""

    def test_add_event(self):
        """Should add an event to the audit trail."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            event_id = db.add_event(
                "req1",
                EventType.BOT_STARTED,
                payload={"stage": "catalog_lookup"},
            )

            assert event_id is not None

            events = db.get_events("req1")
            assert len(events) == 1
            assert events[0].event_type == "bot_started"
            assert events[0].actor_id == "bot:suggest-a-bot"
            assert events[0].payload == {"stage": "catalog_lookup"}
        finally:
            db_path.unlink()

    def test_add_multiple_events(self):
        """Should track multiple events in order."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")

            db = BotDatabase(db_path)
            db.add_event("req1", EventType.BOT_STARTED)
            db.add_event("req1", EventType.BOT_CATALOG_CHECKED, payload={"match": "none"})
            db.add_event("req1", EventType.BOT_COMPLETED)

            events = db.get_events("req1")
            assert len(events) == 3
            assert [e.event_type for e in events] == [
                "bot_started",
                "bot_catalog_checked",
                "bot_completed",
            ]
        finally:
            db_path.unlink()

    def test_events_isolated_by_request(self):
        """Events for different requests should be isolated."""
        db_path = create_test_db()
        try:
            seed_test_request(db_path, "req1")
            seed_test_request(db_path, "req2")

            db = BotDatabase(db_path)
            db.add_event("req1", EventType.BOT_STARTED)
            db.add_event("req2", EventType.BOT_STARTED)
            db.add_event("req1", EventType.BOT_COMPLETED)

            events_1 = db.get_events("req1")
            events_2 = db.get_events("req2")

            assert len(events_1) == 2
            assert len(events_2) == 1
        finally:
            db_path.unlink()


class TestPurchaseRequestModel:
    """Test the PurchaseRequest dataclass."""

    def test_json_property_parsing(self):
        """JSON properties should parse correctly."""
        request = PurchaseRequest(
            request_id="test",
            created_ts="2024-01-01",
            patron_record_id=12345,
            raw_query="Test",
            status="new",
            catalog_holdings_json='[{"bib_id": "123"}]',
            consortium_sources_json='[{"library": "Metro"}]',
            bot_assessment_json='{"recommendation": "purchase"}',
        )

        assert request.catalog_holdings == [{"bib_id": "123"}]
        assert request.consortium_sources == [{"library": "Metro"}]
        assert request.bot_assessment == {"recommendation": "purchase"}

    def test_json_properties_handle_none(self):
        """JSON properties should handle None gracefully."""
        request = PurchaseRequest(
            request_id="test",
            created_ts="2024-01-01",
            patron_record_id=12345,
            raw_query="Test",
            status="new",
        )

        assert request.catalog_holdings is None
        assert request.consortium_sources is None
        assert request.bot_assessment is None
