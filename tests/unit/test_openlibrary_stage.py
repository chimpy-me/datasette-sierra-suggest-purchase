"""Tests for OpenLibraryEnrichmentStage pipeline stage."""

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest

from suggest_a_bot.config import BotConfig, OpenLibraryConfig, StagesConfig
from suggest_a_bot.models import BotDatabase, EventType
from suggest_a_bot.openlibrary import (
    OpenLibraryAuthor,
    OpenLibraryClient,
    OpenLibraryEdition,
    OpenLibraryWork,
)
from suggest_a_bot.pipeline import OpenLibraryEnrichmentStage, Pipeline


def seed_test_request(
    db_path,
    request_id: str = "req1",
    raw_query: str = "Test Book",
    evidence_packet: dict | None = None,
    catalog_match: str | None = None,
    catalog_checked_ts: str | None = None,
    openlibrary_checked_ts: str | None = None,
) -> None:
    """Insert a test request into the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status,
             evidence_packet_json, catalog_match, catalog_checked_ts,
             openlibrary_checked_ts)
        VALUES (?, '2024-01-01T00:00:00Z', 12345, ?, 'new', ?, ?, ?, ?)
        """,
        (
            request_id,
            raw_query,
            json.dumps(evidence_packet) if evidence_packet else None,
            catalog_match,
            catalog_checked_ts,
            openlibrary_checked_ts,
        ),
    )
    conn.commit()
    conn.close()


def make_evidence_packet(
    isbn: list[str] | None = None,
    title_guess: str | None = None,
    author_guess: str | None = None,
) -> dict:
    """Create a minimal evidence packet for testing."""
    return {
        "schema_version": "1.0.0",
        "created_utc": "2024-01-01T00:00:00Z",
        "inputs": {"omni_input": "Test input"},
        "identifiers": {
            "isbn": isbn or [],
            "issn": [],
            "doi": [],
            "urls": [],
        },
        "extracted": {
            "title_guess": title_guess,
            "author_guess": author_guess,
        },
        "quality": {
            "signals": {
                "valid_isbn_present": bool(isbn),
                "title_like_text_present": bool(title_guess),
            }
        },
    }


class TestOpenLibraryEnrichmentStage:
    """Test OpenLibraryEnrichmentStage pipeline stage."""

    @pytest.fixture
    def mock_ol_client(self):
        """Create a mock Open Library client."""
        mock = AsyncMock(spec=OpenLibraryClient)
        return mock

    def test_stage_name(self, db_path):
        """Stage should have correct name."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)
        assert stage.name == "openlibrary_enrichment"

    def test_stage_is_enabled_by_default(self, db_path):
        """Stage should be enabled by default."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)
        assert stage.is_enabled() is True

    def test_stage_disabled_when_stage_disabled(self, db_path):
        """Stage should be disabled when stage flag is off."""
        config = BotConfig()
        config.stages.openlibrary_enrichment = False
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)
        assert stage.is_enabled() is False

    def test_stage_disabled_when_openlibrary_disabled(self, db_path):
        """Stage should be disabled when openlibrary config is off."""
        config = BotConfig()
        config.openlibrary.enabled = False
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)
        assert stage.is_enabled() is False

    def test_should_enrich_no_catalog_match(self, db_path):
        """Should enrich when catalog_match is 'none'."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)

        seed_test_request(
            db_path,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )
        request = db.get_request("req1")
        assert request is not None

        should, reason = stage._should_enrich(request)
        assert should is True
        assert reason == "no_catalog_match"

    def test_should_enrich_partial_catalog_match(self, db_path):
        """Should enrich when catalog_match is 'partial'."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)

        seed_test_request(
            db_path,
            catalog_match="partial",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )
        request = db.get_request("req1")
        assert request is not None

        should, reason = stage._should_enrich(request)
        assert should is True
        assert reason == "partial_catalog_match"

    def test_should_not_enrich_exact_match_by_default(self, db_path):
        """Should not enrich when catalog_match is 'exact' by default."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)

        seed_test_request(
            db_path,
            catalog_match="exact",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )
        request = db.get_request("req1")
        assert request is not None

        should, reason = stage._should_enrich(request)
        assert should is False
        assert reason == "skip_exact_match"

    def test_should_not_enrich_already_checked(self, db_path):
        """Should not enrich when already checked."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)

        seed_test_request(
            db_path,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
            openlibrary_checked_ts="2024-01-01T00:00:00Z",
        )
        request = db.get_request("req1")
        assert request is not None

        should, reason = stage._should_enrich(request)
        assert should is False
        assert reason == "already_checked"

    def test_should_not_enrich_no_catalog_check(self, db_path):
        """Should not enrich when catalog hasn't been checked yet."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db)

        seed_test_request(db_path)
        request = db.get_request("req1")
        assert request is not None

        should, reason = stage._should_enrich(request)
        assert should is False
        assert reason == "no_catalog_check"

    @pytest.mark.asyncio
    async def test_process_skips_exact_match(self, db_path, mock_ol_client):
        """Should skip when catalog match is exact."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(
            db_path,
            evidence_packet=evidence,
            catalog_match="exact",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["skipped"] is True
        mock_ol_client.lookup_isbn.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_with_isbn(self, db_path, mock_ol_client):
        """Should enrich with ISBN lookup."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(
            db_path,
            evidence_packet=evidence,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        # Set up mock response
        mock_ol_client.lookup_isbn.return_value = OpenLibraryEdition(
            key="/books/OL123M",
            title="Handbook of Mathematical Functions",
            authors=[OpenLibraryAuthor(key="/authors/OL1A")],
            isbn_13=["9780306406157"],
            works=["/works/OL1W"],
        )
        mock_ol_client.get_author_name.return_value = "Abramowitz, Milton"
        mock_ol_client.lookup_work.return_value = OpenLibraryWork(
            key="/works/OL1W",
            description="A comprehensive reference.",
        )
        mock_ol_client.get_cover_url.return_value = (
            "https://covers.openlibrary.org/b/isbn/9780306406157-M.jpg"
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["found"] is True
        assert result.data["match_confidence"] == "high"

    @pytest.mark.asyncio
    async def test_process_saves_to_database(self, db_path, mock_ol_client):
        """Should save enrichment results to database."""
        evidence = make_evidence_packet(title_guess="The Women", author_guess="Hannah")
        seed_test_request(
            db_path,
            evidence_packet=evidence,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        # Set up mock for title/author search
        mock_ol_client.lookup_isbn.return_value = None
        mock_ol_client.search.return_value = [
            type(
                "SearchResult",
                (),
                {
                    "key": "/works/OL1W",
                    "title": "The Women",
                    "author_name": ["Kristin Hannah"],
                    "isbn": ["9781250178633"],
                    "to_dict": lambda self: {"key": "/works/OL1W", "title": "The Women"},
                },
            )()
        ]
        mock_ol_client.get_cover_url.return_value = None

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.openlibrary_checked_ts is not None
        assert updated.openlibrary_found is not None

    @pytest.mark.asyncio
    async def test_process_logs_event(self, db_path, mock_ol_client):
        """Should log BOT_OPENLIBRARY_CHECKED event."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(
            db_path,
            evidence_packet=evidence,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        mock_ol_client.lookup_isbn.return_value = OpenLibraryEdition(
            key="/books/OL123M",
            title="Test Book",
            isbn_13=["9780306406157"],
            works=[],
        )
        mock_ol_client.get_cover_url.return_value = None

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        events = db.get_events("req1")
        ol_events = [
            e for e in events if e.event_type == EventType.BOT_OPENLIBRARY_CHECKED.value
        ]
        assert len(ol_events) == 1
        assert ol_events[0].payload is not None
        assert ol_events[0].payload["found"] is True
        assert ol_events[0].payload["match_confidence"] == "high"

    @pytest.mark.asyncio
    async def test_process_without_evidence_packet(self, db_path, mock_ol_client):
        """Should skip gracefully when no evidence packet."""
        seed_test_request(
            db_path,
            evidence_packet=None,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["skipped"] is True

    @pytest.mark.asyncio
    async def test_process_no_search_criteria(self, db_path, mock_ol_client):
        """Should skip when no searchable criteria."""
        evidence = make_evidence_packet()  # No ISBN, no title
        seed_test_request(
            db_path,
            evidence_packet=evidence,
            catalog_match="none",
            catalog_checked_ts="2024-01-01T00:00:00Z",
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = OpenLibraryEnrichmentStage(config, db, ol_client=mock_ol_client)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["skipped"] is True


class TestPipelineWithOpenLibraryStage:
    """Test full pipeline with Open Library enrichment."""

    @pytest.fixture
    def mock_sierra(self):
        """Create a mock Sierra client."""
        mock = AsyncMock()
        mock.search_by_isbn.return_value = {"total": 0, "entries": []}
        mock.search_by_title_author.return_value = {"total": 0, "entries": []}
        mock.get_item_availability.return_value = {"total": 0, "entries": []}
        return mock

    @pytest.fixture
    def mock_ol_client(self):
        """Create a mock Open Library client."""
        mock = AsyncMock(spec=OpenLibraryClient)
        mock.lookup_isbn.return_value = OpenLibraryEdition(
            key="/books/OL123M",
            title="Test Book",
            authors=[OpenLibraryAuthor(key="/authors/OL1A")],
            isbn_13=["9780306406157"],
            works=["/works/OL1W"],
        )
        mock.get_author_name.return_value = "Test Author"
        mock.lookup_work.return_value = OpenLibraryWork(
            key="/works/OL1W",
            description="Test description.",
        )
        mock.get_cover_url.return_value = "https://covers.openlibrary.org/b/isbn/123-M.jpg"
        return mock

    @pytest.mark.asyncio
    async def test_full_pipeline_with_openlibrary(
        self, db_path, mock_sierra, mock_ol_client
    ):
        """Full pipeline should enrich from Open Library when catalog has no match."""
        seed_test_request(
            db_path,
            raw_query="ISBN 978-0-306-40615-7",
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        pipeline = Pipeline(
            config, db, sierra_client=mock_sierra, ol_client=mock_ol_client
        )

        request = db.get_request("req1")
        assert request is not None
        success = await pipeline.process_request(request)

        assert success is True

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        assert updated.catalog_match == "none"  # Sierra had no results
        assert updated.openlibrary_checked_ts is not None
        assert updated.openlibrary_found == 1
        assert updated.bot_status == "completed"

    @pytest.mark.asyncio
    async def test_pipeline_events_sequence(
        self, db_path, mock_sierra, mock_ol_client
    ):
        """Pipeline should log events in correct sequence."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7")

        config = BotConfig()
        db = BotDatabase(db_path)
        pipeline = Pipeline(
            config, db, sierra_client=mock_sierra, ol_client=mock_ol_client
        )

        request = db.get_request("req1")
        assert request is not None
        await pipeline.process_request(request)

        events = db.get_events("req1")
        event_types = [e.event_type for e in events]

        assert EventType.BOT_STARTED.value in event_types
        assert EventType.BOT_EVIDENCE_EXTRACTED.value in event_types
        assert EventType.BOT_CATALOG_CHECKED.value in event_types
        assert EventType.BOT_OPENLIBRARY_CHECKED.value in event_types
        assert EventType.BOT_COMPLETED.value in event_types

        # Verify order
        started_idx = event_types.index(EventType.BOT_STARTED.value)
        evidence_idx = event_types.index(EventType.BOT_EVIDENCE_EXTRACTED.value)
        catalog_idx = event_types.index(EventType.BOT_CATALOG_CHECKED.value)
        ol_idx = event_types.index(EventType.BOT_OPENLIBRARY_CHECKED.value)
        completed_idx = event_types.index(EventType.BOT_COMPLETED.value)

        assert started_idx < evidence_idx < catalog_idx < ol_idx < completed_idx

    @pytest.mark.asyncio
    async def test_pipeline_skips_openlibrary_on_exact_match(
        self, db_path, mock_ol_client
    ):
        """Pipeline should skip Open Library when catalog has exact match."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7")

        # Sierra returns a match
        mock_sierra = AsyncMock()
        mock_sierra.search_by_isbn.return_value = {
            "total": 1,
            "entries": [
                {
                    "id": "b1000001",
                    "title": "Test Book",
                    "isbn": ["9780306406157"],
                }
            ],
        }
        mock_sierra.get_item_availability.return_value = {
            "total": 1,
            "entries": [{"id": "i1", "status": {"code": "-"}}],
        }

        config = BotConfig()
        db = BotDatabase(db_path)
        pipeline = Pipeline(
            config, db, sierra_client=mock_sierra, ol_client=mock_ol_client
        )

        request = db.get_request("req1")
        assert request is not None
        await pipeline.process_request(request)

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.catalog_match == "exact"

        # Open Library should be skipped
        events = db.get_events("req1")
        ol_events = [
            e for e in events if e.event_type == EventType.BOT_OPENLIBRARY_CHECKED.value
        ]
        # Event may still be logged with skipped=True
        if ol_events:
            assert ol_events[0].payload is not None
            assert ol_events[0].payload.get("skipped") is True


class TestOpenLibraryConfigParsing:
    """Test Open Library configuration parsing."""

    def test_stages_config_includes_openlibrary(self):
        """StagesConfig should include openlibrary_enrichment."""
        stages = StagesConfig()
        assert hasattr(stages, "openlibrary_enrichment")
        assert stages.openlibrary_enrichment is True

    def test_openlibrary_config_defaults(self):
        """OpenLibraryConfig should have sensible defaults."""
        config = OpenLibraryConfig()
        assert config.enabled is True
        assert config.allow_pii is False
        assert config.timeout_seconds == 10.0
        assert config.max_search_results == 5
        assert config.run_on_no_catalog_match is True
        assert config.run_on_partial_catalog_match is True
        assert config.run_on_exact_catalog_match is False

    def test_bot_config_includes_openlibrary(self):
        """BotConfig should include openlibrary config."""
        config = BotConfig()
        assert hasattr(config, "openlibrary")
        assert isinstance(config.openlibrary, OpenLibraryConfig)

    def test_bot_config_from_dict(self):
        """BotConfig should parse openlibrary config from dict."""
        data = {
            "stages": {
                "openlibrary_enrichment": False,
            },
            "openlibrary": {
                "enabled": True,
                "allow_pii": True,
                "timeout_seconds": 15.0,
                "max_search_results": 10,
                "run_on_exact_catalog_match": True,
            },
        }
        config = BotConfig.from_dict(data)
        assert config.stages.openlibrary_enrichment is False
        assert config.openlibrary.allow_pii is True
        assert config.openlibrary.timeout_seconds == 15.0
        assert config.openlibrary.max_search_results == 10
        assert config.openlibrary.run_on_exact_catalog_match is True

    def test_bot_config_to_dict(self):
        """BotConfig.to_dict should include openlibrary config."""
        config = BotConfig()
        data = config.to_dict()
        assert "openlibrary_enrichment" in data["stages"]
        assert "openlibrary" in data
        assert data["openlibrary"]["enabled"] is True
        assert data["openlibrary"]["allow_pii"] is False
