"""Tests for EvidenceExtractionStage pipeline integration."""

import json
import sqlite3

import pytest

from suggest_a_bot.config import BotConfig
from suggest_a_bot.models import BotDatabase, EventType
from suggest_a_bot.pipeline import EvidenceExtractionStage, Pipeline


def seed_test_request(
    db_path,
    request_id: str = "req1",
    raw_query: str = "Test Book",
    format_preference: str | None = None,
    patron_notes: str | None = None,
) -> None:
    """Insert a test request into the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status,
             format_preference, patron_notes)
        VALUES (?, '2024-01-01T00:00:00Z', 12345, ?, 'new', ?, ?)
        """,
        (request_id, raw_query, format_preference, patron_notes),
    )
    conn.commit()
    conn.close()


def get_default_config() -> BotConfig:
    """Create a default BotConfig for testing."""
    return BotConfig()


class TestEvidenceExtractionStage:
    """Test the EvidenceExtractionStage."""

    def test_stage_is_always_enabled(self, db_path):
        """Stage should always be enabled regardless of config."""
        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        assert stage.is_enabled() is True

    def test_stage_name(self, db_path):
        """Stage should have correct name."""
        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        assert stage.name == "evidence_extraction"

    @pytest.mark.asyncio
    async def test_process_creates_evidence_packet(self, db_path):
        """Should create and save evidence packet."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert "identifiers" in result.data

    @pytest.mark.asyncio
    async def test_process_saves_to_database(self, db_path):
        """Should save evidence packet to database."""
        seed_test_request(db_path, raw_query="The Women by Kristin Hannah")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        # Reload and check
        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        assert updated.evidence_extracted_ts is not None

        # Verify packet content
        assert updated.evidence_packet_json is not None
        packet = json.loads(updated.evidence_packet_json)
        assert packet["inputs"]["omni_input"] == "The Women by Kristin Hannah"

    @pytest.mark.asyncio
    async def test_process_logs_event(self, db_path):
        """Should log BOT_EVIDENCE_EXTRACTED event."""
        seed_test_request(db_path, raw_query="Test Book")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        events = db.get_events("req1")
        evidence_events = [
            e for e in events if e.event_type == EventType.BOT_EVIDENCE_EXTRACTED.value
        ]
        assert len(evidence_events) == 1

    @pytest.mark.asyncio
    async def test_process_event_has_summary(self, db_path):
        """Event payload should contain summary statistics."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7 https://amazon.com/dp/123")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        events = db.get_events("req1")
        evidence_event = next(
            e for e in events if e.event_type == EventType.BOT_EVIDENCE_EXTRACTED.value
        )

        payload = evidence_event.payload
        assert payload is not None
        assert "isbn_count" in payload
        assert "url_count" in payload
        assert payload["isbn_count"] >= 1

    @pytest.mark.asyncio
    async def test_process_with_format_preference(self, db_path):
        """Should include format preference in evidence packet."""
        seed_test_request(db_path, raw_query="Some Book", format_preference="paperback")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        packet = json.loads(updated.evidence_packet_json)
        assert packet["inputs"]["structured_hints"]["format_preference"] == "paperback"

    @pytest.mark.asyncio
    async def test_process_with_patron_notes(self, db_path):
        """Should include patron notes in evidence packet."""
        seed_test_request(
            db_path,
            raw_query="Some Book",
            patron_notes="Saw this on Goodreads",
        )

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        packet = json.loads(updated.evidence_packet_json)
        assert packet["inputs"]["narrative_context"] == "Saw this on Goodreads"


class TestPipelineWithEvidenceStage:
    """Test Pipeline with EvidenceExtractionStage."""

    def test_evidence_stage_is_first(self, db_path):
        """EvidenceExtractionStage should be first in pipeline."""
        config = get_default_config()
        db = BotDatabase(db_path)
        pipeline = Pipeline(config, db)

        assert isinstance(pipeline.stages[0], EvidenceExtractionStage)
        assert pipeline.stages[0].name == "evidence_extraction"

    @pytest.mark.asyncio
    async def test_full_pipeline_extracts_evidence(self, db_path):
        """Full pipeline should extract evidence before other stages."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7")

        config = get_default_config()
        db = BotDatabase(db_path)
        pipeline = Pipeline(config, db)

        request = db.get_request("req1")
        assert request is not None
        success = await pipeline.process_request(request)

        assert success is True

        # Check evidence was extracted
        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        assert updated.bot_status == "completed"

    @pytest.mark.asyncio
    async def test_pipeline_continues_after_evidence(self, db_path):
        """Pipeline should continue to other stages after evidence extraction."""
        seed_test_request(db_path, raw_query="Test Book")

        config = get_default_config()
        db = BotDatabase(db_path)
        pipeline = Pipeline(config, db)

        request = db.get_request("req1")
        assert request is not None
        await pipeline.process_request(request)

        # Check events show multiple stages ran
        events = db.get_events("req1")
        event_types = [e.event_type for e in events]

        assert EventType.BOT_STARTED.value in event_types
        assert EventType.BOT_EVIDENCE_EXTRACTED.value in event_types
        assert EventType.BOT_COMPLETED.value in event_types


class TestEvidencePacketRetrieval:
    """Test retrieving evidence packet from database."""

    @pytest.mark.asyncio
    async def test_evidence_packet_property(self, db_path):
        """PurchaseRequest.evidence_packet should parse JSON."""
        seed_test_request(db_path, raw_query="Test Book by Author")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        updated = db.get_request("req1")
        assert updated is not None
        packet = updated.evidence_packet

        assert packet is not None
        assert packet["inputs"]["omni_input"] == "Test Book by Author"
        assert "identifiers" in packet
        assert "quality" in packet

    def test_evidence_packet_property_handles_none(self, db_path):
        """evidence_packet should return None when not set."""
        seed_test_request(db_path, raw_query="Test Book")

        db = BotDatabase(db_path)
        request = db.get_request("req1")
        assert request is not None

        assert request.evidence_packet is None


class TestEvidenceExtractionEdgeCases:
    """Test edge cases for evidence extraction."""

    @pytest.mark.asyncio
    async def test_process_with_empty_query(self, db_path):
        """Should handle empty raw_query gracefully."""
        seed_test_request(db_path, raw_query="")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        # Should succeed but with errors noted
        assert result.success is True
        assert result.data is not None
        packet = result.data
        assert len(packet["quality"]["errors"]) > 0

    @pytest.mark.asyncio
    async def test_process_with_unicode(self, db_path):
        """Should handle unicode in input."""
        seed_test_request(db_path, raw_query="日本語の本 by 著者")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        packet = json.loads(updated.evidence_packet_json)
        assert "日本語の本" in packet["inputs"]["omni_input"]

    @pytest.mark.asyncio
    async def test_process_multiple_requests(self, db_path):
        """Should handle multiple requests independently."""
        seed_test_request(db_path, "req1", "ISBN 978-0-306-40615-7")
        seed_test_request(db_path, "req2", "The Women by Kristin Hannah")

        config = get_default_config()
        db = BotDatabase(db_path)
        stage = EvidenceExtractionStage(config, db)

        for req_id in ["req1", "req2"]:
            request = db.get_request(req_id)
            assert request is not None
            await stage.process(request)

        # Check each has unique evidence
        req1 = db.get_request("req1")
        req2 = db.get_request("req2")
        assert req1 is not None
        assert req2 is not None

        assert req1.evidence_packet_json is not None
        packet1 = json.loads(req1.evidence_packet_json)
        assert req2.evidence_packet_json is not None
        packet2 = json.loads(req2.evidence_packet_json)

        assert len(packet1["identifiers"]["isbn"]) >= 1
        assert len(packet2["identifiers"]["isbn"]) == 0
