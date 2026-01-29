"""
Open Library API client for suggest-a-bot.

Provides metadata enrichment from Open Library's free API for items
not found in the Sierra catalog.

API Documentation: https://openlibrary.org/developers/api
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

# Open Library API endpoints
OL_API_BASE = "https://openlibrary.org"
OL_COVERS_BASE = "https://covers.openlibrary.org"

# PII scrubbing patterns for outbound queries
PII_PATTERNS = [
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # phone numbers
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # emails
    re.compile(r"\b\d{12,16}\b"),  # long numeric strings (e.g., card numbers)
]


def scrub_pii(text: str | None) -> str | None:
    """Remove likely PII from outbound Open Library queries."""
    if text is None:
        return None
    scrubbed = text
    for pattern in PII_PATTERNS:
        scrubbed = pattern.sub("[redacted]", scrubbed)
    scrubbed = re.sub(r"\s{2,}", " ", scrubbed).strip()
    return scrubbed


@dataclass
class OpenLibraryAuthor:
    """Author information from Open Library."""

    key: str  # e.g., "/authors/OL1A"
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"key": self.key}
        if self.name:
            result["name"] = self.name
        return result


@dataclass
class OpenLibraryEdition:
    """Edition (book) information from Open Library."""

    key: str  # e.g., "/books/OL123M"
    title: str
    authors: list[OpenLibraryAuthor] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    publish_date: str | None = None
    isbn_10: list[str] = field(default_factory=list)
    isbn_13: list[str] = field(default_factory=list)
    number_of_pages: int | None = None
    subjects: list[str] = field(default_factory=list)
    covers: list[int] = field(default_factory=list)  # Cover IDs
    works: list[str] = field(default_factory=list)  # Work keys

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
        }
        if self.authors:
            result["authors"] = [a.to_dict() for a in self.authors]
        if self.publishers:
            result["publishers"] = self.publishers
        if self.publish_date:
            result["publish_date"] = self.publish_date
        if self.isbn_10:
            result["isbn_10"] = self.isbn_10
        if self.isbn_13:
            result["isbn_13"] = self.isbn_13
        if self.number_of_pages:
            result["number_of_pages"] = self.number_of_pages
        if self.subjects:
            result["subjects"] = self.subjects
        if self.covers:
            result["covers"] = self.covers
        if self.works:
            result["works"] = self.works
        return result


@dataclass
class OpenLibraryWork:
    """Work-level information from Open Library."""

    key: str  # e.g., "/works/OL1W"
    title: str | None = None
    description: str | None = None
    subjects: list[str] = field(default_factory=list)
    first_publish_date: str | None = None
    covers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"key": self.key}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if self.subjects:
            result["subjects"] = self.subjects
        if self.first_publish_date:
            result["first_publish_date"] = self.first_publish_date
        if self.covers:
            result["covers"] = self.covers
        return result


@dataclass
class OpenLibrarySearchResult:
    """A single search result from Open Library."""

    key: str
    title: str
    author_name: list[str] = field(default_factory=list)
    first_publish_year: int | None = None
    isbn: list[str] = field(default_factory=list)
    edition_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
        }
        if self.author_name:
            result["author_name"] = self.author_name
        if self.first_publish_year:
            result["first_publish_year"] = self.first_publish_year
        if self.isbn:
            result["isbn"] = self.isbn
        if self.edition_count:
            result["edition_count"] = self.edition_count
        return result


@dataclass
class OpenLibraryEnrichment:
    """
    Complete enrichment result from Open Library.

    Schema version: 1.0.0
    """

    schema_version: str = SCHEMA_VERSION
    created_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_query: str = ""
    match_confidence: str = "none"  # "high", "medium", "low", "none"
    edition: OpenLibraryEdition | None = None
    work: OpenLibraryWork | None = None
    search_results: list[OpenLibrarySearchResult] = field(default_factory=list)
    cover_url: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "created_utc": self.created_utc,
            "source_query": self.source_query,
            "match_confidence": self.match_confidence,
        }
        if self.edition:
            result["edition"] = self.edition.to_dict()
        if self.work:
            result["work"] = self.work.to_dict()
        if self.search_results:
            result["search_results"] = [r.to_dict() for r in self.search_results]
        if self.cover_url:
            result["cover_url"] = self.cover_url
        if self.error:
            result["error"] = self.error
        return result

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenLibraryEnrichment":
        """Create from dictionary."""
        edition = None
        if "edition" in data and data["edition"]:
            ed = data["edition"]
            edition = OpenLibraryEdition(
                key=ed["key"],
                title=ed["title"],
                authors=[
                    OpenLibraryAuthor(key=a["key"], name=a.get("name"))
                    for a in ed.get("authors", [])
                ],
                publishers=ed.get("publishers", []),
                publish_date=ed.get("publish_date"),
                isbn_10=ed.get("isbn_10", []),
                isbn_13=ed.get("isbn_13", []),
                number_of_pages=ed.get("number_of_pages"),
                subjects=ed.get("subjects", []),
                covers=ed.get("covers", []),
                works=ed.get("works", []),
            )

        work = None
        if "work" in data and data["work"]:
            w = data["work"]
            work = OpenLibraryWork(
                key=w["key"],
                title=w.get("title"),
                description=w.get("description"),
                subjects=w.get("subjects", []),
                first_publish_date=w.get("first_publish_date"),
                covers=w.get("covers", []),
            )

        search_results = []
        for sr in data.get("search_results", []):
            search_results.append(
                OpenLibrarySearchResult(
                    key=sr["key"],
                    title=sr["title"],
                    author_name=sr.get("author_name", []),
                    first_publish_year=sr.get("first_publish_year"),
                    isbn=sr.get("isbn", []),
                    edition_count=sr.get("edition_count", 0),
                )
            )

        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            created_utc=data.get("created_utc", datetime.now(UTC).isoformat()),
            source_query=data.get("source_query", ""),
            match_confidence=data.get("match_confidence", "none"),
            edition=edition,
            work=work,
            search_results=search_results,
            cover_url=data.get("cover_url"),
            error=data.get("error"),
        )


class OpenLibraryClient:
    """
    Client for the Open Library API.

    Provides methods for ISBN lookup, work lookup, and title/author search.
    """

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        max_search_results: int = 5,
    ):
        """
        Initialize the Open Library client.

        Args:
            timeout_seconds: Request timeout in seconds
            max_search_results: Maximum search results to return
        """
        self.timeout = timeout_seconds
        self.max_search_results = max_search_results

    async def lookup_isbn(self, isbn: str) -> OpenLibraryEdition | None:
        """
        Look up a book by ISBN.

        Args:
            isbn: ISBN-10 or ISBN-13

        Returns:
            OpenLibraryEdition if found, None otherwise
        """
        # Normalize ISBN (remove hyphens)
        clean_isbn = isbn.replace("-", "").replace(" ", "")
        url = f"{OL_API_BASE}/isbn/{clean_isbn}.json"

        logger.debug(f"Looking up ISBN {clean_isbn}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, follow_redirects=True)
                if response.status_code == 404:
                    logger.debug(f"ISBN {clean_isbn} not found")
                    return None
                response.raise_for_status()
                data = response.json()
                return self._parse_edition(data)
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error looking up ISBN {clean_isbn}: {e}")
                return None
            except Exception:
                logger.exception(f"Error looking up ISBN {clean_isbn}")
                raise

    async def lookup_work(self, work_key: str) -> OpenLibraryWork | None:
        """
        Look up a work by its key.

        Args:
            work_key: Work key (e.g., "/works/OL1W" or just "OL1W")

        Returns:
            OpenLibraryWork if found, None otherwise
        """
        # Normalize key
        if not work_key.startswith("/works/"):
            work_key = f"/works/{work_key}"

        url = f"{OL_API_BASE}{work_key}.json"
        logger.debug(f"Looking up work {work_key}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, follow_redirects=True)
                if response.status_code == 404:
                    logger.debug(f"Work {work_key} not found")
                    return None
                response.raise_for_status()
                data = response.json()
                return self._parse_work(data)
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error looking up work {work_key}: {e}")
                return None
            except Exception:
                logger.exception(f"Error looking up work {work_key}")
                raise

    async def search(
        self,
        title: str | None = None,
        author: str | None = None,
    ) -> list[OpenLibrarySearchResult]:
        """
        Search for books by title and/or author.

        Args:
            title: Book title to search for
            author: Author name to search for

        Returns:
            List of search results (up to max_search_results)
        """
        if not title and not author:
            return []

        # Build search query
        parts = []
        if title:
            parts.append(f"title:{title}")
        if author:
            parts.append(f"author:{author}")
        query = " ".join(parts)

        url = f"{OL_API_BASE}/search.json"
        params = {
            "q": query,
            "limit": self.max_search_results,
            "fields": "key,title,author_name,first_publish_year,isbn,edition_count",
        }

        logger.debug(f"Searching Open Library: {query}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params, follow_redirects=True)
                response.raise_for_status()
                data = response.json()
                return self._parse_search_results(data)
            except Exception:
                logger.exception("Error searching Open Library")
                raise

    async def get_author_name(self, author_key: str) -> str | None:
        """
        Get author name from author key.

        Args:
            author_key: Author key (e.g., "/authors/OL1A" or just "OL1A")

        Returns:
            Author name if found, None otherwise
        """
        # Normalize key
        if not author_key.startswith("/authors/"):
            author_key = f"/authors/{author_key}"

        url = f"{OL_API_BASE}{author_key}.json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, follow_redirects=True)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
                return data.get("name")
            except Exception:
                logger.warning(f"Could not fetch author name for {author_key}")
                return None

    def get_cover_url(
        self,
        isbn: str | None = None,
        cover_id: int | None = None,
        size: str = "M",
    ) -> str | None:
        """
        Get cover image URL.

        Args:
            isbn: ISBN to look up cover for
            cover_id: Open Library cover ID
            size: Size (S, M, L)

        Returns:
            Cover URL or None
        """
        if cover_id:
            return f"{OL_COVERS_BASE}/b/id/{cover_id}-{size}.jpg"
        elif isbn:
            clean_isbn = isbn.replace("-", "").replace(" ", "")
            return f"{OL_COVERS_BASE}/b/isbn/{clean_isbn}-{size}.jpg"
        return None

    def _parse_edition(self, data: dict[str, Any]) -> OpenLibraryEdition:
        """Parse edition data from API response."""
        # Parse authors
        authors = []
        for author_ref in data.get("authors", []):
            if isinstance(author_ref, dict):
                author_key = author_ref.get("key", "")
                authors.append(OpenLibraryAuthor(key=author_key))
            elif isinstance(author_ref, str):
                authors.append(OpenLibraryAuthor(key=author_ref))

        # Parse works
        works = []
        for work_ref in data.get("works", []):
            if isinstance(work_ref, dict):
                works.append(work_ref.get("key", ""))
            elif isinstance(work_ref, str):
                works.append(work_ref)

        return OpenLibraryEdition(
            key=data.get("key", ""),
            title=data.get("title", "Unknown Title"),
            authors=authors,
            publishers=data.get("publishers", []),
            publish_date=data.get("publish_date"),
            isbn_10=data.get("isbn_10", []),
            isbn_13=data.get("isbn_13", []),
            number_of_pages=data.get("number_of_pages"),
            subjects=data.get("subjects", []),
            covers=data.get("covers", []),
            works=works,
        )

    def _parse_work(self, data: dict[str, Any]) -> OpenLibraryWork:
        """Parse work data from API response."""
        # Description can be a string or object with "value" key
        description = data.get("description")
        if isinstance(description, dict):
            description = description.get("value")

        return OpenLibraryWork(
            key=data.get("key", ""),
            title=data.get("title"),
            description=description,
            subjects=data.get("subjects", []),
            first_publish_date=data.get("first_publish_date"),
            covers=data.get("covers", []),
        )

    def _parse_search_results(
        self, data: dict[str, Any]
    ) -> list[OpenLibrarySearchResult]:
        """Parse search results from API response."""
        results = []
        for doc in data.get("docs", [])[: self.max_search_results]:
            results.append(
                OpenLibrarySearchResult(
                    key=doc.get("key", ""),
                    title=doc.get("title", "Unknown"),
                    author_name=doc.get("author_name", []),
                    first_publish_year=doc.get("first_publish_year"),
                    isbn=doc.get("isbn", [])[:5],  # Limit ISBNs
                    edition_count=doc.get("edition_count", 0),
                )
            )
        return results


async def enrich_from_openlibrary(
    client: OpenLibraryClient,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
) -> OpenLibraryEnrichment:
    """
    Enrich a purchase request using Open Library.

    Search strategy:
    1. If ISBN provided, look up edition directly (high confidence)
    2. If no ISBN but title/author, search and get best match (medium/low confidence)
    3. If edition found, also fetch work for description/subjects

    Args:
        client: OpenLibraryClient instance
        isbn: ISBN to look up (preferred)
        title: Title to search for (fallback)
        author: Author to search for (with title)

    Returns:
        OpenLibraryEnrichment with results
    """
    enrichment = OpenLibraryEnrichment()

    try:
        # Strategy 1: ISBN lookup (high confidence)
        if isbn:
            enrichment.source_query = f"isbn:{isbn}"
            edition = await client.lookup_isbn(isbn)

            if edition:
                enrichment.edition = edition
                enrichment.match_confidence = "high"

                # Resolve author names
                for author_obj in edition.authors:
                    if author_obj.key and not author_obj.name:
                        name = await client.get_author_name(author_obj.key)
                        if name:
                            author_obj.name = name

                # Fetch work for more metadata
                if edition.works:
                    work = await client.lookup_work(edition.works[0])
                    if work:
                        enrichment.work = work

                # Get cover URL
                if edition.isbn_13:
                    enrichment.cover_url = client.get_cover_url(isbn=edition.isbn_13[0])
                elif edition.isbn_10:
                    enrichment.cover_url = client.get_cover_url(isbn=edition.isbn_10[0])
                elif edition.covers:
                    enrichment.cover_url = client.get_cover_url(
                        cover_id=edition.covers[0]
                    )

                return enrichment

        # Strategy 2: Title/author search (medium/low confidence)
        if title:
            query_parts = [f"title:{title}"]
            if author:
                query_parts.append(f"author:{author}")
            enrichment.source_query = " ".join(query_parts)

            results = await client.search(title=title, author=author)
            enrichment.search_results = results

            if results:
                # Best match is first result
                best = results[0]
                enrichment.match_confidence = "medium" if author else "low"

                # If search result has ISBNs, try to get edition details
                if best.isbn:
                    edition = await client.lookup_isbn(best.isbn[0])
                    if edition:
                        enrichment.edition = edition

                        # Resolve author names
                        for author_obj in edition.authors:
                            if author_obj.key and not author_obj.name:
                                name = await client.get_author_name(author_obj.key)
                                if name:
                                    author_obj.name = name

                        # Fetch work
                        if edition.works:
                            work = await client.lookup_work(edition.works[0])
                            if work:
                                enrichment.work = work

                        # Get cover URL
                        if edition.covers:
                            enrichment.cover_url = client.get_cover_url(
                                cover_id=edition.covers[0]
                            )

            return enrichment

        # No search criteria
        enrichment.match_confidence = "none"
        return enrichment

    except Exception as e:
        logger.exception("Error enriching from Open Library")
        enrichment.error = str(e)
        enrichment.match_confidence = "none"
        return enrichment
