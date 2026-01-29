"""
Catalog search functionality for suggest-a-bot.

Provides Sierra catalog search and CandidateSets artifact building
following the schema in llore/09_bot-artifacts-json-schemas.md.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .evidence import EvidencePacket

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


class MatchConfidence(str, Enum):
    """Confidence level for a catalog match."""

    HIGH = "high"  # ISBN match
    MEDIUM = "medium"  # Title+author match
    LOW = "low"  # Title-only match


@dataclass
class CatalogCandidate:
    """A candidate bib record from catalog search."""

    candidate_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    publication_year: int | None = None
    language: str | None = None
    format: str | None = None
    identifiers: dict[str, list[str]] = field(default_factory=dict)
    source_rank: int = 1
    source_record_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "title": self.title,
        }
        if self.authors:
            result["authors"] = self.authors
        if self.publisher:
            result["publisher"] = self.publisher
        if self.publication_year:
            result["publication_year"] = self.publication_year
        if self.language:
            result["language"] = self.language
        if self.format:
            result["format"] = self.format
        if self.identifiers:
            result["identifiers"] = self.identifiers
        if self.source_rank:
            result["source_rank"] = self.source_rank
        if self.source_record_ref:
            result["source_record_ref"] = self.source_record_ref
        return result


@dataclass
class SearchResult:
    """Result from a single search query."""

    query_string: str
    candidates: list[CatalogCandidate] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "query_string": self.query_string,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class CatalogSource:
    """Results from a single catalog source."""

    source_name: str
    results: list[SearchResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_name": self.source_name,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class CandidateSets:
    """
    Candidate sets artifact following the schema.

    Contains all candidates found from catalog searches,
    organized by source and query.
    """

    schema_version: str = SCHEMA_VERSION
    created_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sources: list[CatalogSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "created_utc": self.created_utc,
            "sources": [s.to_dict() for s in self.sources],
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateSets":
        """Create from dictionary."""
        sources = []
        for source_data in data.get("sources", []):
            results = []
            for result_data in source_data.get("results", []):
                candidates = []
                for cand_data in result_data.get("candidates", []):
                    candidates.append(
                        CatalogCandidate(
                            candidate_id=cand_data["candidate_id"],
                            title=cand_data["title"],
                            authors=cand_data.get("authors", []),
                            publisher=cand_data.get("publisher"),
                            publication_year=cand_data.get("publication_year"),
                            language=cand_data.get("language"),
                            format=cand_data.get("format"),
                            identifiers=cand_data.get("identifiers", {}),
                            source_rank=cand_data.get("source_rank", 1),
                            source_record_ref=cand_data.get("source_record_ref", {}),
                        )
                    )
                results.append(
                    SearchResult(
                        query_string=result_data["query_string"],
                        candidates=candidates,
                        error=result_data.get("error"),
                    )
                )
            sources.append(
                CatalogSource(
                    source_name=source_data["source_name"],
                    results=results,
                )
            )
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            created_utc=data.get("created_utc", datetime.now(UTC).isoformat()),
            sources=sources,
        )

    def get_all_candidates(self) -> list[CatalogCandidate]:
        """Get all candidates from all sources and queries."""
        candidates = []
        for source in self.sources:
            for result in source.results:
                candidates.extend(result.candidates)
        return candidates

    def has_candidates(self) -> bool:
        """Check if any candidates were found."""
        return len(self.get_all_candidates()) > 0


def sierra_bib_to_candidate(
    bib: dict[str, Any],
    rank: int = 1,
    items: list[dict[str, Any]] | None = None,
) -> CatalogCandidate:
    """
    Convert a Sierra bib record to a CatalogCandidate.

    Args:
        bib: Sierra bib record from API response
        rank: Search result rank
        items: Optional item/holdings records for this bib
    """
    # Parse author(s) - Sierra may return single author string
    author_str = bib.get("author", "")
    if author_str:
        # Split on semicolon or "and" for multiple authors
        if "; " in author_str:
            authors = [a.strip() for a in author_str.split("; ")]
        elif " and " in author_str.lower():
            authors = [a.strip() for a in author_str.lower().split(" and ")]
        else:
            authors = [author_str]
    else:
        authors = []

    # Build identifiers dict
    identifiers: dict[str, list[str]] = {}
    isbns = bib.get("isbn", [])
    if isbns:
        identifiers["isbn"] = isbns if isinstance(isbns, list) else [isbns]

    # Parse material type for format
    material_type = bib.get("materialType", {})
    format_code = material_type.get("code") if isinstance(material_type, dict) else None
    format_value = material_type.get("value") if isinstance(material_type, dict) else None

    # Parse language
    language_data = bib.get("language", {})
    language = language_data.get("code") if isinstance(language_data, dict) else None

    # Build source record reference with availability info
    source_ref: dict[str, Any] = {
        "bib_id": bib.get("id"),
    }

    if items is not None:
        available_count = sum(
            1 for item in items if item.get("status", {}).get("code") == "-"
        )
        total_count = len(items)
        source_ref["total_copies"] = total_count
        source_ref["available_copies"] = available_count
        source_ref["availability"] = "available" if available_count > 0 else "unavailable"

        # Include item details
        source_ref["items"] = [
            {
                "id": item.get("id"),
                "location": item.get("location", {}).get("name"),
                "status": item.get("status", {}).get("display"),
                "call_number": item.get("callNumber"),
            }
            for item in items[:5]  # Limit to first 5 items
        ]

    return CatalogCandidate(
        candidate_id=f"sierra_bib_{bib.get('id', 'unknown')}",
        title=bib.get("title", "Unknown Title"),
        authors=authors,
        publisher=bib.get("publisher"),
        publication_year=bib.get("publishYear"),
        language=language,
        format=format_value or format_code,
        identifiers=identifiers,
        source_rank=rank,
        source_record_ref=source_ref,
    )


class CatalogSearcher:
    """
    Coordinates catalog searches for suggest-a-bot.

    Uses evidence packet identifiers to search Sierra catalog
    with a tiered search strategy:
    1. ISBN search (high confidence)
    2. Title + Author search (medium confidence)
    3. Title only search (low confidence)
    """

    def __init__(self, sierra_client):
        """
        Initialize searcher with Sierra client.

        Args:
            sierra_client: SierraClient instance for API calls
        """
        self.sierra = sierra_client

    async def search(self, evidence: EvidencePacket | dict) -> CandidateSets:
        """
        Search catalog using evidence packet.

        Executes tiered search strategy, stopping on first match.

        Args:
            evidence: EvidencePacket or dict with evidence data

        Returns:
            CandidateSets artifact with all search results
        """
        # Handle dict input
        if isinstance(evidence, dict):
            evidence = EvidencePacket.from_dict(evidence)

        candidate_sets = CandidateSets()
        sierra_source = CatalogSource(source_name="sierra_catalog")

        # Tier 1: ISBN search
        isbns = evidence.identifiers.isbn
        if isbns:
            for isbn in isbns[:3]:  # Limit to first 3 ISBNs
                result = await self._search_by_isbn(isbn)
                sierra_source.results.append(result)
                if result.candidates:
                    logger.info(f"ISBN search found {len(result.candidates)} candidates")
                    # Stop on first successful ISBN match
                    break

        # Tier 2: Title + Author search (only if no ISBN matches)
        if not sierra_source.results or not any(r.candidates for r in sierra_source.results):
            title = evidence.extracted.title_guess
            author = evidence.extracted.author_guess

            if title and author:
                result = await self._search_by_title_author(title, author)
                sierra_source.results.append(result)

            # Tier 3: Title only (if title+author found nothing)
            elif title:
                result = await self._search_by_title(title)
                sierra_source.results.append(result)

        candidate_sets.sources.append(sierra_source)
        return candidate_sets

    async def _search_by_isbn(self, isbn: str) -> SearchResult:
        """Execute ISBN search."""
        query_string = f"isbn:{isbn}"
        try:
            response = await self.sierra.search_by_isbn(isbn)
            entries = response.get("entries", [])

            candidates = []
            for rank, bib in enumerate(entries, 1):
                # Fetch item availability for each bib
                bib_id = bib.get("id")
                items = []
                if bib_id:
                    items_response = await self.sierra.get_item_availability([bib_id])
                    items = items_response.get("entries", [])

                candidate = sierra_bib_to_candidate(bib, rank, items)
                candidates.append(candidate)

            return SearchResult(query_string=query_string, candidates=candidates)

        except Exception as e:
            logger.exception(f"ISBN search failed for {isbn}")
            return SearchResult(query_string=query_string, error=str(e))

    async def _search_by_title_author(self, title: str, author: str) -> SearchResult:
        """Execute title + author search."""
        query_string = f"title:{title} author:{author}"
        try:
            response = await self.sierra.search_by_title_author(title=title, author=author)
            entries = response.get("entries", [])

            candidates = []
            for rank, bib in enumerate(entries, 1):
                bib_id = bib.get("id")
                items = []
                if bib_id:
                    items_response = await self.sierra.get_item_availability([bib_id])
                    items = items_response.get("entries", [])

                candidate = sierra_bib_to_candidate(bib, rank, items)
                candidates.append(candidate)

            return SearchResult(query_string=query_string, candidates=candidates)

        except Exception as e:
            logger.exception("Title/author search failed")
            return SearchResult(query_string=query_string, error=str(e))

    async def _search_by_title(self, title: str) -> SearchResult:
        """Execute title-only search."""
        query_string = f"title:{title}"
        try:
            response = await self.sierra.search_by_title_author(title=title)
            entries = response.get("entries", [])

            candidates = []
            for rank, bib in enumerate(entries, 1):
                bib_id = bib.get("id")
                items = []
                if bib_id:
                    items_response = await self.sierra.get_item_availability([bib_id])
                    items = items_response.get("entries", [])

                candidate = sierra_bib_to_candidate(bib, rank, items)
                candidates.append(candidate)

            return SearchResult(query_string=query_string, candidates=candidates)

        except Exception as e:
            logger.exception("Title search failed")
            return SearchResult(query_string=query_string, error=str(e))


def determine_match_type(
    candidate_sets: CandidateSets,
    evidence: EvidencePacket | dict,
) -> str:
    """
    Determine the match type from search results.

    Args:
        candidate_sets: Search results
        evidence: Original evidence packet

    Returns:
        'exact', 'partial', or 'none'
    """
    if isinstance(evidence, dict):
        evidence = EvidencePacket.from_dict(evidence)

    if not candidate_sets.has_candidates():
        return "none"

    # Check for ISBN match
    search_isbns = set(evidence.identifiers.isbn)
    for candidate in candidate_sets.get_all_candidates():
        candidate_isbns = set(candidate.identifiers.get("isbn", []))
        if search_isbns & candidate_isbns:
            return "exact"

    # If we have candidates but no ISBN match, it's partial
    return "partial"
