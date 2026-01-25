"""Tests for Open Library API client and data models."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from suggest_a_bot.openlibrary import (
    OpenLibraryAuthor,
    OpenLibraryClient,
    OpenLibraryEdition,
    OpenLibraryEnrichment,
    OpenLibrarySearchResult,
    OpenLibraryWork,
    enrich_from_openlibrary,
)


class TestOpenLibraryAuthor:
    """Test OpenLibraryAuthor dataclass."""

    def test_to_dict_minimal(self):
        """Should serialize minimal author."""
        author = OpenLibraryAuthor(key="/authors/OL1A")
        result = author.to_dict()
        assert result == {"key": "/authors/OL1A"}

    def test_to_dict_with_name(self):
        """Should include name when present."""
        author = OpenLibraryAuthor(key="/authors/OL1A", name="Test Author")
        result = author.to_dict()
        assert result["key"] == "/authors/OL1A"
        assert result["name"] == "Test Author"


class TestOpenLibraryEdition:
    """Test OpenLibraryEdition dataclass."""

    def test_to_dict_minimal(self):
        """Should serialize minimal edition."""
        edition = OpenLibraryEdition(
            key="/books/OL123M",
            title="Test Book",
        )
        result = edition.to_dict()
        assert result["key"] == "/books/OL123M"
        assert result["title"] == "Test Book"

    def test_to_dict_full(self):
        """Should serialize full edition with all fields."""
        edition = OpenLibraryEdition(
            key="/books/OL123M",
            title="Test Book",
            authors=[OpenLibraryAuthor(key="/authors/OL1A", name="Author One")],
            publishers=["Test Publisher"],
            publish_date="2024",
            isbn_10=["0306406152"],
            isbn_13=["9780306406157"],
            number_of_pages=500,
            subjects=["Mathematics", "Reference"],
            covers=[12345],
            works=["/works/OL1W"],
        )
        result = edition.to_dict()
        assert result["publishers"] == ["Test Publisher"]
        assert result["isbn_13"] == ["9780306406157"]
        assert result["subjects"] == ["Mathematics", "Reference"]
        assert result["authors"][0]["name"] == "Author One"


class TestOpenLibraryWork:
    """Test OpenLibraryWork dataclass."""

    def test_to_dict_minimal(self):
        """Should serialize minimal work."""
        work = OpenLibraryWork(key="/works/OL1W")
        result = work.to_dict()
        assert result == {"key": "/works/OL1W"}

    def test_to_dict_full(self):
        """Should serialize work with all fields."""
        work = OpenLibraryWork(
            key="/works/OL1W",
            title="Test Work",
            description="A comprehensive test work.",
            subjects=["Testing", "Software"],
            first_publish_date="2020",
            covers=[67890],
        )
        result = work.to_dict()
        assert result["title"] == "Test Work"
        assert result["description"] == "A comprehensive test work."
        assert result["subjects"] == ["Testing", "Software"]


class TestOpenLibrarySearchResult:
    """Test OpenLibrarySearchResult dataclass."""

    def test_to_dict(self):
        """Should serialize search result."""
        result = OpenLibrarySearchResult(
            key="/works/OL1W",
            title="Test Book",
            author_name=["Test Author"],
            first_publish_year=2024,
            isbn=["9780306406157"],
            edition_count=3,
        )
        data = result.to_dict()
        assert data["key"] == "/works/OL1W"
        assert data["title"] == "Test Book"
        assert data["author_name"] == ["Test Author"]
        assert data["first_publish_year"] == 2024


class TestOpenLibraryEnrichment:
    """Test OpenLibraryEnrichment dataclass."""

    def test_to_dict_minimal(self):
        """Should serialize minimal enrichment."""
        enrichment = OpenLibraryEnrichment(
            source_query="isbn:9780306406157",
            match_confidence="high",
        )
        result = enrichment.to_dict()
        assert result["schema_version"] == "1.0.0"
        assert result["source_query"] == "isbn:9780306406157"
        assert result["match_confidence"] == "high"

    def test_to_dict_with_edition(self):
        """Should include edition when present."""
        edition = OpenLibraryEdition(key="/books/OL123M", title="Test")
        enrichment = OpenLibraryEnrichment(
            source_query="isbn:123",
            match_confidence="high",
            edition=edition,
        )
        result = enrichment.to_dict()
        assert result["edition"]["key"] == "/books/OL123M"

    def test_to_json(self):
        """Should serialize to JSON string."""
        enrichment = OpenLibraryEnrichment(
            source_query="test",
            match_confidence="none",
        )
        json_str = enrichment.to_json()
        data = json.loads(json_str)
        assert data["source_query"] == "test"

    def test_from_dict(self):
        """Should deserialize from dictionary."""
        data = {
            "schema_version": "1.0.0",
            "created_utc": "2024-01-01T00:00:00Z",
            "source_query": "isbn:9780306406157",
            "match_confidence": "high",
            "edition": {
                "key": "/books/OL123M",
                "title": "Test Book",
                "authors": [{"key": "/authors/OL1A", "name": "Author"}],
                "isbn_13": ["9780306406157"],
            },
            "work": {
                "key": "/works/OL1W",
                "description": "A test work.",
            },
            "search_results": [
                {
                    "key": "/works/OL1W",
                    "title": "Test",
                    "author_name": ["Author"],
                }
            ],
            "cover_url": "https://covers.openlibrary.org/b/isbn/123-M.jpg",
        }
        enrichment = OpenLibraryEnrichment.from_dict(data)
        assert enrichment.source_query == "isbn:9780306406157"
        assert enrichment.edition.title == "Test Book"
        assert enrichment.edition.authors[0].name == "Author"
        assert enrichment.work.description == "A test work."
        assert len(enrichment.search_results) == 1


class TestOpenLibraryClient:
    """Test OpenLibraryClient class."""

    @pytest.fixture
    def mock_response(self):
        """Create a mock httpx response."""

        def _make_response(json_data, status_code=200):
            response = MagicMock()
            response.status_code = status_code
            response.json.return_value = json_data
            response.raise_for_status = MagicMock()
            if status_code >= 400:
                from httpx import HTTPStatusError, Request, Response

                response.raise_for_status.side_effect = HTTPStatusError(
                    "Error", request=MagicMock(), response=response
                )
            return response

        return _make_response

    def test_get_cover_url_by_isbn(self):
        """Should generate cover URL from ISBN."""
        client = OpenLibraryClient()
        url = client.get_cover_url(isbn="9780306406157", size="M")
        assert url == "https://covers.openlibrary.org/b/isbn/9780306406157-M.jpg"

    def test_get_cover_url_by_cover_id(self):
        """Should generate cover URL from cover ID."""
        client = OpenLibraryClient()
        url = client.get_cover_url(cover_id=12345, size="L")
        assert url == "https://covers.openlibrary.org/b/id/12345-L.jpg"

    def test_get_cover_url_none(self):
        """Should return None when no identifier."""
        client = OpenLibraryClient()
        url = client.get_cover_url()
        assert url is None

    def test_parse_edition(self):
        """Should parse edition from API response."""
        client = OpenLibraryClient()
        data = {
            "key": "/books/OL123M",
            "title": "Test Book",
            "authors": [{"key": "/authors/OL1A"}],
            "publishers": ["Publisher"],
            "publish_date": "2024",
            "isbn_13": ["9780306406157"],
            "subjects": ["Math"],
            "covers": [123],
            "works": [{"key": "/works/OL1W"}],
        }
        edition = client._parse_edition(data)
        assert edition.key == "/books/OL123M"
        assert edition.title == "Test Book"
        assert edition.authors[0].key == "/authors/OL1A"
        assert edition.works == ["/works/OL1W"]

    def test_parse_work(self):
        """Should parse work from API response."""
        client = OpenLibraryClient()
        data = {
            "key": "/works/OL1W",
            "title": "Test Work",
            "description": {"value": "A description with object format."},
            "subjects": ["Testing"],
            "first_publish_date": "2020",
        }
        work = client._parse_work(data)
        assert work.key == "/works/OL1W"
        assert work.description == "A description with object format."

    def test_parse_work_string_description(self):
        """Should handle string description."""
        client = OpenLibraryClient()
        data = {
            "key": "/works/OL1W",
            "description": "Simple string description.",
        }
        work = client._parse_work(data)
        assert work.description == "Simple string description."

    def test_parse_search_results(self):
        """Should parse search results from API response."""
        client = OpenLibraryClient()
        data = {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Test",
                    "author_name": ["Author"],
                    "first_publish_year": 2024,
                    "isbn": ["123", "456", "789", "abc", "def", "ghi"],
                    "edition_count": 5,
                },
            ],
        }
        results = client._parse_search_results(data)
        assert len(results) == 1
        assert results[0].title == "Test"
        # ISBNs should be limited to 5
        assert len(results[0].isbn) == 5

    @pytest.mark.asyncio
    async def test_lookup_isbn_found(self, mock_response):
        """Should return edition when ISBN is found."""
        client = OpenLibraryClient()
        response = mock_response(
            {
                "key": "/books/OL123M",
                "title": "Test Book",
                "isbn_13": ["9780306406157"],
            }
        )

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            edition = await client.lookup_isbn("9780306406157")

            assert edition is not None
            assert edition.title == "Test Book"

    @pytest.mark.asyncio
    async def test_lookup_isbn_not_found(self, mock_response):
        """Should return None when ISBN is not found."""
        client = OpenLibraryClient()
        response = mock_response({}, status_code=404)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            edition = await client.lookup_isbn("0000000000")

            assert edition is None

    @pytest.mark.asyncio
    async def test_lookup_work(self, mock_response):
        """Should return work when found."""
        client = OpenLibraryClient()
        response = mock_response(
            {
                "key": "/works/OL1W",
                "title": "Test Work",
                "description": "Description",
            }
        )

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            work = await client.lookup_work("/works/OL1W")

            assert work is not None
            assert work.title == "Test Work"

    @pytest.mark.asyncio
    async def test_search(self, mock_response):
        """Should return search results."""
        client = OpenLibraryClient()
        response = mock_response(
            {
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "The Women",
                        "author_name": ["Kristin Hannah"],
                    }
                ],
            }
        )

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            results = await client.search(title="The Women", author="Hannah")

            assert len(results) == 1
            assert results[0].title == "The Women"

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Should return empty list for empty query."""
        client = OpenLibraryClient()
        results = await client.search()
        assert results == []

    @pytest.mark.asyncio
    async def test_get_author_name(self, mock_response):
        """Should return author name when found."""
        client = OpenLibraryClient()
        response = mock_response({"name": "Kristin Hannah"})

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            name = await client.get_author_name("/authors/OL1A")

            assert name == "Kristin Hannah"


class TestEnrichFromOpenLibrary:
    """Test the enrich_from_openlibrary function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock OpenLibrary client."""
        mock = AsyncMock(spec=OpenLibraryClient)
        mock.get_cover_url.return_value = "https://covers.openlibrary.org/b/isbn/123-M.jpg"
        return mock

    @pytest.mark.asyncio
    async def test_enrich_by_isbn(self, mock_client):
        """Should enrich by ISBN with high confidence."""
        mock_client.lookup_isbn.return_value = OpenLibraryEdition(
            key="/books/OL123M",
            title="Test Book",
            authors=[OpenLibraryAuthor(key="/authors/OL1A")],
            isbn_13=["9780306406157"],
            works=["/works/OL1W"],
        )
        mock_client.get_author_name.return_value = "Test Author"
        mock_client.lookup_work.return_value = OpenLibraryWork(
            key="/works/OL1W",
            description="A test description.",
        )

        enrichment = await enrich_from_openlibrary(
            client=mock_client,
            isbn="9780306406157",
        )

        assert enrichment.match_confidence == "high"
        assert enrichment.edition.title == "Test Book"
        assert enrichment.edition.authors[0].name == "Test Author"
        assert enrichment.work.description == "A test description."

    @pytest.mark.asyncio
    async def test_enrich_by_title_author(self, mock_client):
        """Should enrich by title+author with medium confidence."""
        mock_client.lookup_isbn.return_value = None
        mock_client.search.return_value = [
            OpenLibrarySearchResult(
                key="/works/OL1W",
                title="The Women",
                author_name=["Kristin Hannah"],
                isbn=["9781250178633"],
            )
        ]
        mock_client.lookup_work.return_value = None

        # Second lookup_isbn call for search result ISBN
        mock_client.lookup_isbn.side_effect = [
            None,  # First call with original ISBN
            OpenLibraryEdition(
                key="/books/OL456M",
                title="The Women",
                isbn_13=["9781250178633"],
                works=[],
            ),
        ]

        enrichment = await enrich_from_openlibrary(
            client=mock_client,
            title="The Women",
            author="Kristin Hannah",
        )

        assert enrichment.match_confidence == "medium"
        assert len(enrichment.search_results) == 1

    @pytest.mark.asyncio
    async def test_enrich_by_title_only(self, mock_client):
        """Should enrich by title only with low confidence."""
        mock_client.search.return_value = [
            OpenLibrarySearchResult(
                key="/works/OL1W",
                title="The Women",
                isbn=[],
            )
        ]

        enrichment = await enrich_from_openlibrary(
            client=mock_client,
            title="The Women",
        )

        assert enrichment.match_confidence == "low"

    @pytest.mark.asyncio
    async def test_enrich_no_results(self, mock_client):
        """Should return none confidence when nothing found."""
        mock_client.lookup_isbn.return_value = None
        mock_client.search.return_value = []

        enrichment = await enrich_from_openlibrary(
            client=mock_client,
            title="Nonexistent Book",
        )

        assert enrichment.match_confidence in ("low", "none")

    @pytest.mark.asyncio
    async def test_enrich_no_criteria(self, mock_client):
        """Should return none confidence with no search criteria."""
        enrichment = await enrich_from_openlibrary(client=mock_client)

        assert enrichment.match_confidence == "none"

    @pytest.mark.asyncio
    async def test_enrich_handles_error(self, mock_client):
        """Should handle errors gracefully."""
        mock_client.lookup_isbn.side_effect = Exception("Network error")

        enrichment = await enrich_from_openlibrary(
            client=mock_client,
            isbn="9780306406157",
        )

        assert enrichment.error == "Network error"
        assert enrichment.match_confidence == "none"
