"""Tests for CatalogLookupStage and catalog module."""

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest

from suggest_a_bot.catalog import (
    CandidateSets,
    CatalogCandidate,
    CatalogSearcher,
    CatalogSource,
    SearchResult,
    determine_match_type,
    sierra_bib_to_candidate,
)
from suggest_a_bot.config import BotConfig
from suggest_a_bot.models import BotDatabase, EventType
from suggest_a_bot.pipeline import CatalogLookupStage, Pipeline


def seed_test_request(
    db_path,
    request_id: str = "req1",
    raw_query: str = "Test Book",
    evidence_packet: dict | None = None,
) -> None:
    """Insert a test request into the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status,
             evidence_packet_json)
        VALUES (?, '2024-01-01T00:00:00Z', 12345, ?, 'new', ?)
        """,
        (request_id, raw_query, json.dumps(evidence_packet) if evidence_packet else None),
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


class TestCatalogCandidate:
    """Test CatalogCandidate dataclass."""

    def test_to_dict_minimal(self):
        """Should serialize minimal candidate."""
        candidate = CatalogCandidate(
            candidate_id="test_1",
            title="Test Title",
        )
        result = candidate.to_dict()
        assert result["candidate_id"] == "test_1"
        assert result["title"] == "Test Title"

    def test_to_dict_full(self):
        """Should serialize full candidate with all fields."""
        candidate = CatalogCandidate(
            candidate_id="test_1",
            title="Test Title",
            authors=["Author One", "Author Two"],
            publisher="Test Publisher",
            publication_year=2024,
            language="eng",
            format="Book",
            identifiers={"isbn": ["9780306406157"]},
            source_rank=1,
            source_record_ref={"bib_id": "b1000001", "availability": "available"},
        )
        result = candidate.to_dict()
        assert result["authors"] == ["Author One", "Author Two"]
        assert result["identifiers"]["isbn"] == ["9780306406157"]
        assert result["source_record_ref"]["availability"] == "available"


class TestCandidateSets:
    """Test CandidateSets artifact."""

    def test_to_dict(self):
        """Should serialize to schema-compliant dict."""
        candidate = CatalogCandidate(
            candidate_id="sierra_bib_1",
            title="Test Book",
        )
        result = SearchResult(
            query_string="isbn:9780306406157",
            candidates=[candidate],
        )
        source = CatalogSource(
            source_name="sierra_catalog",
            results=[result],
        )
        candidate_sets = CandidateSets(sources=[source])

        data = candidate_sets.to_dict()
        assert data["schema_version"] == "1.0.0"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source_name"] == "sierra_catalog"

    def test_has_candidates_true(self):
        """Should return True when candidates exist."""
        candidate = CatalogCandidate(candidate_id="1", title="Test")
        result = SearchResult(query_string="test", candidates=[candidate])
        source = CatalogSource(source_name="test", results=[result])
        cs = CandidateSets(sources=[source])
        assert cs.has_candidates() is True

    def test_has_candidates_false(self):
        """Should return False when no candidates."""
        cs = CandidateSets()
        assert cs.has_candidates() is False

    def test_get_all_candidates(self):
        """Should return all candidates from all sources."""
        c1 = CatalogCandidate(candidate_id="1", title="Test 1")
        c2 = CatalogCandidate(candidate_id="2", title="Test 2")
        result1 = SearchResult(query_string="q1", candidates=[c1])
        result2 = SearchResult(query_string="q2", candidates=[c2])
        source = CatalogSource(source_name="test", results=[result1, result2])
        cs = CandidateSets(sources=[source])

        candidates = cs.get_all_candidates()
        assert len(candidates) == 2

    def test_from_dict(self):
        """Should deserialize from dict."""
        data = {
            "schema_version": "1.0.0",
            "created_utc": "2024-01-01T00:00:00Z",
            "sources": [
                {
                    "source_name": "sierra_catalog",
                    "results": [
                        {
                            "query_string": "isbn:123",
                            "candidates": [
                                {
                                    "candidate_id": "b1",
                                    "title": "Test",
                                    "authors": ["Author"],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        cs = CandidateSets.from_dict(data)
        assert cs.schema_version == "1.0.0"
        assert len(cs.sources) == 1
        assert cs.sources[0].results[0].candidates[0].title == "Test"


class TestSierraBibToCandidate:
    """Test sierra_bib_to_candidate conversion."""

    def test_basic_conversion(self):
        """Should convert basic Sierra bib."""
        bib = {
            "id": "b1000001",
            "title": "Test Book",
            "author": "Test Author",
            "isbn": ["9780306406157"],
        }
        candidate = sierra_bib_to_candidate(bib)

        assert candidate.candidate_id == "sierra_bib_b1000001"
        assert candidate.title == "Test Book"
        assert candidate.authors == ["Test Author"]
        assert candidate.identifiers["isbn"] == ["9780306406157"]

    def test_with_items(self):
        """Should include availability from items."""
        bib = {"id": "b1000001", "title": "Test"}
        items = [
            {"id": "i1", "status": {"code": "-", "display": "Available"}},
            {"id": "i2", "status": {"code": "c", "display": "Checked out"}},
        ]
        candidate = sierra_bib_to_candidate(bib, items=items)

        ref = candidate.source_record_ref
        assert ref["total_copies"] == 2
        assert ref["available_copies"] == 1
        assert ref["availability"] == "available"

    def test_multiple_authors(self):
        """Should parse multiple authors."""
        bib = {
            "id": "b1",
            "title": "Test",
            "author": "Author One; Author Two",
        }
        candidate = sierra_bib_to_candidate(bib)
        assert candidate.authors == ["Author One", "Author Two"]


class TestDetermineMatchType:
    """Test determine_match_type function."""

    def test_exact_match_with_isbn(self):
        """Should return 'exact' when ISBN matches."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        candidate = CatalogCandidate(
            candidate_id="b1",
            title="Test",
            identifiers={"isbn": ["9780306406157"]},
        )
        result = SearchResult(query_string="isbn:9780306406157", candidates=[candidate])
        source = CatalogSource(source_name="sierra", results=[result])
        cs = CandidateSets(sources=[source])

        match = determine_match_type(cs, evidence)
        assert match == "exact"

    def test_partial_match_without_isbn(self):
        """Should return 'partial' when no ISBN match."""
        evidence = make_evidence_packet(title_guess="The Women", author_guess="Hannah")
        candidate = CatalogCandidate(
            candidate_id="b1",
            title="The Women",
            identifiers={},  # No ISBN
        )
        result = SearchResult(query_string="title:The Women", candidates=[candidate])
        source = CatalogSource(source_name="sierra", results=[result])
        cs = CandidateSets(sources=[source])

        match = determine_match_type(cs, evidence)
        assert match == "partial"

    def test_no_match(self):
        """Should return 'none' when no candidates."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        cs = CandidateSets()

        match = determine_match_type(cs, evidence)
        assert match == "none"


class TestCatalogSearcher:
    """Test CatalogSearcher class."""

    @pytest.fixture
    def mock_sierra(self):
        """Create a mock Sierra client."""
        mock = AsyncMock()
        mock.search_by_isbn.return_value = {
            "total": 1,
            "entries": [
                {
                    "id": "b1000001",
                    "title": "Test Book",
                    "isbn": ["9780306406157"],
                }
            ],
        }
        mock.search_by_title_author.return_value = {"total": 0, "entries": []}
        mock.get_item_availability.return_value = {
            "total": 1,
            "entries": [{"id": "i1", "status": {"code": "-"}}],
        }
        return mock

    @pytest.mark.asyncio
    async def test_search_by_isbn(self, mock_sierra):
        """Should search by ISBN when available."""
        searcher = CatalogSearcher(mock_sierra)
        evidence = make_evidence_packet(isbn=["9780306406157"])

        result = await searcher.search(evidence)

        mock_sierra.search_by_isbn.assert_called()
        assert result.has_candidates()

    @pytest.mark.asyncio
    async def test_search_by_title_author(self, mock_sierra):
        """Should search by title+author when no ISBN."""
        mock_sierra.search_by_isbn.return_value = {"total": 0, "entries": []}
        mock_sierra.search_by_title_author.return_value = {
            "total": 1,
            "entries": [{"id": "b1", "title": "Test", "author": "Author"}],
        }
        searcher = CatalogSearcher(mock_sierra)
        evidence = make_evidence_packet(title_guess="Test", author_guess="Author")

        await searcher.search(evidence)

        mock_sierra.search_by_title_author.assert_called_with(title="Test", author="Author")

    @pytest.mark.asyncio
    async def test_search_title_only(self, mock_sierra):
        """Should search by title only when no author."""
        mock_sierra.search_by_title_author.return_value = {
            "total": 1,
            "entries": [{"id": "b1", "title": "Test"}],
        }
        searcher = CatalogSearcher(mock_sierra)
        evidence = make_evidence_packet(title_guess="Test")

        await searcher.search(evidence)

        mock_sierra.search_by_title_author.assert_called_with(title="Test")


class TestCatalogLookupStage:
    """Test CatalogLookupStage pipeline stage."""

    @pytest.fixture
    def mock_sierra(self):
        """Create a mock Sierra client."""
        mock = AsyncMock()
        mock.search_by_isbn.return_value = {
            "total": 1,
            "entries": [
                {
                    "id": "b1000001",
                    "title": "Handbook of Mathematical Functions",
                    "author": "Abramowitz, Milton",
                    "isbn": ["9780306406157"],
                }
            ],
        }
        mock.get_item_availability.return_value = {
            "total": 2,
            "entries": [
                {"id": "i1", "status": {"code": "-", "display": "Available"}},
                {"id": "i2", "status": {"code": "-", "display": "Available"}},
            ],
        }
        return mock

    def test_stage_is_enabled_by_default(self, db_path):
        """Stage should be enabled by default."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db)
        assert stage.is_enabled() is True

    def test_stage_name(self, db_path):
        """Stage should have correct name."""
        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db)
        assert stage.name == "catalog_lookup"

    @pytest.mark.asyncio
    async def test_process_with_isbn(self, db_path, mock_sierra):
        """Should search by ISBN and find match."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(db_path, evidence_packet=evidence)

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["match"] == "exact"
        assert result.data["candidates_count"] == 1

    @pytest.mark.asyncio
    async def test_process_saves_to_database(self, db_path, mock_sierra):
        """Should save catalog results to database."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(db_path, evidence_packet=evidence)

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.catalog_match == "exact"
        assert updated.catalog_holdings_json is not None

    @pytest.mark.asyncio
    async def test_process_logs_event(self, db_path, mock_sierra):
        """Should log BOT_CATALOG_CHECKED event."""
        evidence = make_evidence_packet(isbn=["9780306406157"])
        seed_test_request(db_path, evidence_packet=evidence)

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        await stage.process(request)

        events = db.get_events("req1")
        catalog_events = [e for e in events if e.event_type == EventType.BOT_CATALOG_CHECKED.value]
        assert len(catalog_events) == 1
        assert catalog_events[0].payload is not None
        assert catalog_events[0].payload["match"] == "exact"

    @pytest.mark.asyncio
    async def test_process_without_evidence_packet(self, db_path, mock_sierra):
        """Should skip gracefully when no evidence packet."""
        seed_test_request(db_path, evidence_packet=None)

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["skipped"] is True

    @pytest.mark.asyncio
    async def test_process_no_search_criteria(self, db_path, mock_sierra):
        """Should skip when no searchable identifiers."""
        evidence = make_evidence_packet()  # No ISBN, no title
        seed_test_request(db_path, evidence_packet=evidence)

        config = BotConfig()
        db = BotDatabase(db_path)
        stage = CatalogLookupStage(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        result = await stage.process(request)

        assert result.success is True
        assert result.data is not None
        assert result.data["skipped"] is True


class TestPipelineWithCatalogStage:
    """Test full pipeline with catalog lookup."""

    @pytest.fixture
    def mock_sierra(self):
        """Create a mock Sierra client."""
        mock = AsyncMock()
        mock.search_by_isbn.return_value = {
            "total": 1,
            "entries": [
                {
                    "id": "b1000002",
                    "title": "Handbook of Mathematical Functions",
                    "author": "Abramowitz, Milton",
                    "isbn": ["9780306406157"],
                }
            ],
        }
        mock.search_by_title_author.return_value = {"total": 0, "entries": []}
        mock.get_item_availability.return_value = {
            "total": 1,
            "entries": [{"id": "i1", "status": {"code": "-"}}],
        }
        return mock

    @pytest.mark.asyncio
    async def test_full_pipeline_with_catalog(self, db_path, mock_sierra):
        """Full pipeline should extract evidence and search catalog."""
        seed_test_request(
            db_path,
            raw_query="ISBN 978-0-306-40615-7",
            evidence_packet=None,  # Will be created by evidence stage
        )

        config = BotConfig()
        db = BotDatabase(db_path)
        pipeline = Pipeline(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        success = await pipeline.process_request(request)

        assert success is True

        updated = db.get_request("req1")
        assert updated is not None
        assert updated.evidence_packet_json is not None
        assert updated.catalog_match == "exact"
        assert updated.bot_status == "completed"

    @pytest.mark.asyncio
    async def test_pipeline_events_sequence(self, db_path, mock_sierra):
        """Pipeline should log events in correct sequence."""
        seed_test_request(db_path, raw_query="ISBN 978-0-306-40615-7")

        config = BotConfig()
        db = BotDatabase(db_path)
        pipeline = Pipeline(config, db, sierra_client=mock_sierra)

        request = db.get_request("req1")
        assert request is not None
        await pipeline.process_request(request)

        events = db.get_events("req1")
        event_types = [e.event_type for e in events]

        assert EventType.BOT_STARTED.value in event_types
        assert EventType.BOT_EVIDENCE_EXTRACTED.value in event_types
        assert EventType.BOT_CATALOG_CHECKED.value in event_types
        assert EventType.BOT_COMPLETED.value in event_types

        # Verify order
        started_idx = event_types.index(EventType.BOT_STARTED.value)
        evidence_idx = event_types.index(EventType.BOT_EVIDENCE_EXTRACTED.value)
        catalog_idx = event_types.index(EventType.BOT_CATALOG_CHECKED.value)
        completed_idx = event_types.index(EventType.BOT_COMPLETED.value)

        assert started_idx < evidence_idx < catalog_idx < completed_idx
