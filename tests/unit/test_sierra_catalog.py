"""Tests for SierraClient catalog search methods."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from datasette_suggest_purchase.plugin import SierraClient


class TestSierraClientCatalogSearch:
    """Test SierraClient catalog search functionality."""

    @pytest.fixture
    def mock_client(self):
        """Create a SierraClient with mocked token."""
        client = SierraClient(
            base_url="http://fake-sierra:9009/iii/sierra-api",
            client_key="test_key",
            client_secret="test_secret",
        )
        # Pre-set token to avoid auth calls
        client._token = "fake_token"
        return client

    @pytest.mark.asyncio
    async def test_search_by_isbn_success(self, mock_client):
        """Should return matching bibs for ISBN search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 1,
            "start": 0,
            "entries": [
                {
                    "id": "b1000001",
                    "title": "Test Book",
                    "author": "Test Author",
                    "isbn": ["9780306406157"],
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            result = await mock_client.search_by_isbn("9780306406157")

            assert result["total"] == 1
            assert len(result["entries"]) == 1
            assert result["entries"][0]["title"] == "Test Book"

    @pytest.mark.asyncio
    async def test_search_by_isbn_normalizes_dashes(self, mock_client):
        """Should strip dashes from ISBN before searching."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "start": 0, "entries": []}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            await mock_client.search_by_isbn("978-0-306-40615-7")

            # Verify the request used normalized ISBN
            call_kwargs = mock_instance.get.call_args.kwargs
            assert call_kwargs["params"]["isbn"] == "9780306406157"

    @pytest.mark.asyncio
    async def test_search_by_isbn_returns_empty_on_error(self, mock_client):
        """Should return empty result on error."""
        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.RequestError("Network error")
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            result = await mock_client.search_by_isbn("9780306406157")

            assert result["total"] == 0
            assert result["entries"] == []

    @pytest.mark.asyncio
    async def test_search_by_title_author_success(self, mock_client):
        """Should return matching bibs for title+author search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 2,
            "start": 0,
            "entries": [
                {"id": "b1000001", "title": "The Women", "author": "Hannah, Kristin"},
                {"id": "b1000002", "title": "The Women: A Novel", "author": "Hannah, Kristin"},
            ],
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            result = await mock_client.search_by_title_author(title="The Women", author="Hannah")

            assert result["total"] == 2
            assert len(result["entries"]) == 2

    @pytest.mark.asyncio
    async def test_search_by_title_author_title_only(self, mock_client):
        """Should search by title only when no author provided."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "start": 0, "entries": []}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            await mock_client.search_by_title_author(title="The Women")

            call_kwargs = mock_instance.get.call_args.kwargs
            assert "title" in call_kwargs["params"]
            assert "author" not in call_kwargs["params"]

    @pytest.mark.asyncio
    async def test_search_by_title_author_returns_empty_on_no_criteria(self, mock_client):
        """Should return empty result when no title or author provided."""
        result = await mock_client.search_by_title_author()
        assert result["total"] == 0
        assert result["entries"] == []

    @pytest.mark.asyncio
    async def test_get_item_availability_success(self, mock_client):
        """Should return items for given bib IDs."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 2,
            "start": 0,
            "entries": [
                {
                    "id": "i2000001",
                    "bibIds": ["b1000001"],
                    "location": {"code": "main", "name": "Main Library"},
                    "status": {"code": "-", "display": "Available"},
                },
                {
                    "id": "i2000002",
                    "bibIds": ["b1000001"],
                    "location": {"code": "branch1", "name": "Branch 1"},
                    "status": {"code": "c", "display": "Checked out"},
                },
            ],
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            result = await mock_client.get_item_availability(["b1000001"])

            assert result["total"] == 2
            assert len(result["entries"]) == 2
            # Check first item is available
            assert result["entries"][0]["status"]["code"] == "-"

    @pytest.mark.asyncio
    async def test_get_item_availability_multiple_bibs(self, mock_client):
        """Should handle multiple bib IDs as comma-separated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "start": 0, "entries": []}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            await mock_client.get_item_availability(["b1000001", "b1000002"])

            call_kwargs = mock_instance.get.call_args.kwargs
            assert call_kwargs["params"]["bibIds"] == "b1000001,b1000002"

    @pytest.mark.asyncio
    async def test_get_item_availability_returns_empty_on_no_bibs(self, mock_client):
        """Should return empty result when no bib IDs provided."""
        result = await mock_client.get_item_availability([])
        assert result["total"] == 0
        assert result["entries"] == []


class TestSierraClientCatalogIntegration:
    """Integration tests with fake Sierra server (when available)."""

    @pytest.mark.asyncio
    async def test_full_search_flow(self):
        """Test full search flow with mocked responses."""
        client = SierraClient(
            base_url="http://fake-sierra:9009/iii/sierra-api",
            client_key="test_key",
            client_secret="test_secret",
        )
        client._token = "fake_token"

        # Mock both bib search and item availability
        bib_response = MagicMock()
        bib_response.status_code = 200
        bib_response.json.return_value = {
            "total": 1,
            "start": 0,
            "entries": [
                {
                    "id": "b1000001",
                    "title": "Test Book",
                    "author": "Test Author",
                    "isbn": ["9780306406157"],
                }
            ],
        }

        item_response = MagicMock()
        item_response.status_code = 200
        item_response.json.return_value = {
            "total": 1,
            "start": 0,
            "entries": [
                {
                    "id": "i2000001",
                    "bibIds": ["b1000001"],
                    "status": {"code": "-", "display": "Available"},
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()

            # Return different responses based on URL
            def side_effect(*args, **kwargs):
                if "bibs" in kwargs.get("url", "") or "bibs" in str(args):
                    return bib_response
                return item_response

            mock_instance.get.return_value = bib_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_async_client.return_value = mock_instance

            # Search by ISBN
            bib_result = await client.search_by_isbn("9780306406157")
            assert bib_result["total"] == 1

            # Get availability
            mock_instance.get.return_value = item_response
            item_result = await client.get_item_availability(["b1000001"])
            assert item_result["total"] == 1
