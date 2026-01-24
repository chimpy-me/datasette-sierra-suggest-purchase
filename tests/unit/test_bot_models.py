"""Tests for suggest-a-bot models and database operations."""

import sqlite3

import pytest

from suggest_a_bot.models import (
    BotDatabase,
    CatalogMatch,
    EventType,
    PurchaseRequest,
    RunStatus,
)


def seed_test_request(db_path, request_id: str = "req1", raw_query: str = "Test Book") -> None:
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

    def test_get_pending_requests(self, db_path):
        """Should retrieve requests with bot_status='pending'."""
        seed_test_request(db_path, "req1", "Book One")
        seed_test_request(db_path, "req2", "Book Two")

        db = BotDatabase(db_path)
        requests = db.get_pending_requests()

        assert len(requests) == 2
        assert all(r.bot_status == "pending" for r in requests)

    def test_get_pending_requests_respects_limit(self, db_path):
        """Should respect the limit parameter."""
        for i in range(5):
            seed_test_request(db_path, f"req{i}", f"Book {i}")

        db = BotDatabase(db_path)
        requests = db.get_pending_requests(limit=2)

        assert len(requests) == 2

    def test_get_pending_requests_excludes_processed(self, db_path):
        """Should not return already-processed requests."""
        seed_test_request(db_path, "req1", "Book One")
        seed_test_request(db_path, "req2", "Book Two")

        db = BotDatabase(db_path)
        db.mark_completed("req1")

        requests = db.get_pending_requests()

        assert len(requests) == 1
        assert requests[0].request_id == "req2"

    def test_get_request(self, db_path):
        """Should retrieve a specific request by ID."""
        seed_test_request(db_path, "req1", "Test Book")

        db = BotDatabase(db_path)
        request = db.get_request("req1")

        assert request is not None
        assert request.request_id == "req1"
        assert request.raw_query == "Test Book"

    def test_get_request_not_found(self, db_path):
        """Should return None for non-existent request."""
        db = BotDatabase(db_path)
        request = db.get_request("nonexistent")

        assert request is None

    def test_mark_processing(self, db_path):
        """Should update bot_status to 'processing'."""
        seed_test_request(db_path, "req1")

        db = BotDatabase(db_path)
        db.mark_processing("req1")

        request = db.get_request("req1")
        assert request.bot_status == "processing"

    def test_mark_completed(self, db_path):
        """Should update bot_status to 'completed' with timestamp."""
        seed_test_request(db_path, "req1")

        db = BotDatabase(db_path)
        db.mark_completed("req1")

        request = db.get_request("req1")
        assert request.bot_status == "completed"
        assert request.bot_processed_ts is not None

    def test_mark_error(self, db_path):
        """Should update bot_status to 'error' with error message."""
        seed_test_request(db_path, "req1")

        db = BotDatabase(db_path)
        db.mark_error("req1", "Something went wrong")

        request = db.get_request("req1")
        assert request.bot_status == "error"
        assert request.bot_error == "Something went wrong"
        assert request.bot_processed_ts is not None

    def test_save_catalog_result(self, db_path):
        """Should save catalog lookup results."""
        seed_test_request(db_path, "req1")

        db = BotDatabase(db_path)
        holdings = [{"bib_id": "123", "title": "Test Book", "status": "available"}]
        db.save_catalog_result("req1", CatalogMatch.EXACT, holdings)

        request = db.get_request("req1")
        assert request.catalog_match == "exact"
        assert request.catalog_checked_ts is not None
        assert request.catalog_holdings == holdings

    def test_save_consortium_result(self, db_path):
        """Should save consortium check results."""
        seed_test_request(db_path, "req1")

        db = BotDatabase(db_path)
        sources = [{"library": "Columbus Metro", "status": "available"}]
        db.save_consortium_result("req1", True, sources)

        request = db.get_request("req1")
        assert request.consortium_available == 1
        assert request.consortium_checked_ts is not None
        assert request.consortium_sources == sources

    def test_save_refinement(self, db_path):
        """Should save input refinement results."""
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

    def test_save_assessment(self, db_path):
        """Should save bot assessment results."""
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


class TestBotRuns:
    """Test bot run tracking."""

    def test_create_run(self, db_path):
        """Should create a new bot run record."""
        db = BotDatabase(db_path)
        config = {"max_requests": 50}
        run = db.create_run(config)

        assert run.run_id is not None
        assert run.status == "running"
        assert run.started_ts is not None

    def test_complete_run(self, db_path):
        """Should mark a run as complete with stats."""
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

    def test_complete_run_with_failure(self, db_path):
        """Should mark a run as failed with error message."""
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


class TestRequestEvents:
    """Test audit trail events."""

    def test_add_event(self, db_path):
        """Should add an event to the audit trail."""
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

    def test_add_multiple_events(self, db_path):
        """Should track multiple events in order."""
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

    def test_events_isolated_by_request(self, db_path):
        """Events for different requests should be isolated."""
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
