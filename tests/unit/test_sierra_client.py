"""Unit tests for the Sierra API client."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from datasette_suggest_purchase.plugin import SierraClient


class TestSierraClient:
    """Tests for the SierraClient class."""

    @pytest.fixture
    def client(self):
        """Create a Sierra client instance."""
        return SierraClient(
            base_url="http://sierra.example.org/iii/sierra-api",
            client_key="test_key",
            client_secret="test_secret",
        )

    async def test_authenticate_patron_success(self, client):
        """Successful patron authentication returns patron info."""
        # Mock the token request
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"access_token": "fake_token"}
        token_response.raise_for_status = MagicMock()

        # Mock the auth request
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {"patronId": 12345}

        # Mock the patron info request
        info_response = MagicMock()
        info_response.status_code = 200
        info_response.json.return_value = {
            "id": 12345,
            "patronType": 3,
            "homeLibraryCode": "MAIN",
            "names": ["Test Patron"],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # Configure mock to return different responses for different calls
            mock_instance.post.side_effect = [token_response, auth_response]
            mock_instance.get.return_value = info_response

            result = await client.authenticate_patron("12345678901234", "1234")

        assert result is not None
        assert result["patron_record_id"] == 12345
        assert result["ptype"] == 3
        assert result["home_library"] == "MAIN"
        assert result["name"] == "Test Patron"

    async def test_authenticate_patron_invalid_credentials(self, client):
        """Invalid credentials return None."""
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"access_token": "fake_token"}
        token_response.raise_for_status = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 401  # Unauthorized

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = [token_response, auth_response]

            result = await client.authenticate_patron("invalid", "wrong")

        assert result is None

    async def test_token_is_cached(self, client):
        """Token is cached and reused."""
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"access_token": "cached_token"}
        token_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = token_response

            # Get token twice
            token1 = await client._get_token()
            token2 = await client._get_token()

        assert token1 == "cached_token"
        assert token2 == "cached_token"
        # Token endpoint should only be called once
        assert mock_instance.post.call_count == 1

    async def test_base_url_trailing_slash_normalized(self):
        """Base URL with trailing slash is normalized."""
        client = SierraClient(
            base_url="http://sierra.example.org/iii/sierra-api/",
            client_key="key",
            client_secret="secret",
        )

        assert client.base_url == "http://sierra.example.org/iii/sierra-api"


class TestActorBuilding:
    """Tests for building patron actors from Sierra data."""

    def test_patron_actor_shape(self):
        """Patron actor has the expected shape."""
        patron_info = {
            "patron_record_id": 12345,
            "ptype": 3,
            "home_library": "MAIN",
            "name": "Test User",
        }

        # This is how the actor is built in the login route
        actor = {
            "id": f"patron:{patron_info['patron_record_id']}",
            "principal_type": "patron",
            "principal_id": str(patron_info["patron_record_id"]),
            "display": patron_info.get("name", "Patron"),
            "sierra": {
                "patron_record_id": patron_info["patron_record_id"],
                "ptype": patron_info.get("ptype"),
                "home_library": patron_info.get("home_library"),
            },
        }

        assert actor["id"] == "patron:12345"
        assert actor["principal_type"] == "patron"
        assert actor["principal_id"] == "12345"
        assert actor["display"] == "Test User"
        assert actor["sierra"]["patron_record_id"] == 12345
        assert actor["sierra"]["ptype"] == 3
        assert actor["sierra"]["home_library"] == "MAIN"

    def test_patron_actor_minimal(self):
        """Patron actor works with minimal data."""
        patron_info = {
            "patron_record_id": 99999,
        }

        actor = {
            "id": f"patron:{patron_info['patron_record_id']}",
            "principal_type": "patron",
            "principal_id": str(patron_info["patron_record_id"]),
            "display": patron_info.get("name", "Patron"),
            "sierra": {
                "patron_record_id": patron_info["patron_record_id"],
                "ptype": patron_info.get("ptype"),
                "home_library": patron_info.get("home_library"),
            },
        }

        assert actor["id"] == "patron:99999"
        assert actor["display"] == "Patron"  # Default
        assert actor["sierra"]["ptype"] is None
        assert actor["sierra"]["home_library"] is None
