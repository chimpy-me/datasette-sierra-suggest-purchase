"""Integration tests for the patron submission flow."""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from datasette.app import Datasette


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with the POC schema."""
    db_file = tmp_path / "test_suggest.db"
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE purchase_requests (
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
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_ts TEXT);
        INSERT INTO schema_migrations VALUES (1, datetime('now'));
    """)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture
def datasette(db_path):
    """Create a Datasette instance with the plugin configured."""
    return Datasette(
        [str(db_path)],
        metadata={
            "plugins": {
                "datasette-suggest-purchase": {
                    "sierra_api_base": "http://fake-sierra:9009/iii/sierra-api",
                    "sierra_client_key": "test_key",
                    "sierra_client_secret": "test_secret",
                    "suggest_db_path": str(db_path),
                }
            }
        },
    )


class TestLoginPage:
    """Tests for the login page."""

    async def test_unauthenticated_shows_login_form(self, datasette):
        """Unauthenticated users see the login form."""
        response = await datasette.client.get("/suggest-purchase")
        assert response.status_code == 200
        assert "Library Card Number" in response.text
        assert "PIN" in response.text

    async def test_login_without_credentials_shows_error(self, datasette):
        """Login without credentials redirects with error."""
        response = await datasette.client.post(
            "/suggest-purchase/login",
            data={"barcode": "", "pin": ""},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error=" in response.headers.get("location", "")


class TestPatronLogin:
    """Tests for patron authentication."""

    async def test_successful_login_sets_cookie(self, datasette):
        """Successful Sierra auth sets the ds_actor cookie."""
        mock_patron_info = {
            "patron_record_id": 12345,
            "ptype": 3,
            "home_library": "MAIN",
            "name": "Test User",
        }

        with patch(
            "datasette_suggest_purchase.plugin.SierraClient.authenticate_patron",
            new_callable=AsyncMock,
            return_value=mock_patron_info,
        ):
            response = await datasette.client.post(
                "/suggest-purchase/login",
                data={"barcode": "12345678901234", "pin": "1234"},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert response.headers.get("location") == "/suggest-purchase"
        # Check cookie was set
        assert "ds_actor" in response.headers.get("set-cookie", "")

    async def test_failed_login_shows_error(self, datasette):
        """Failed Sierra auth redirects with error message."""
        with patch(
            "datasette_suggest_purchase.plugin.SierraClient.authenticate_patron",
            new_callable=AsyncMock,
            return_value=None,  # Auth failed
        ):
            response = await datasette.client.post(
                "/suggest-purchase/login",
                data={"barcode": "invalid", "pin": "wrong"},
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "error=" in location
        assert "Invalid" in location or "invalid" in location.lower()

    async def test_sierra_connection_error_shows_friendly_message(self, datasette):
        """Sierra connection errors show a user-friendly message."""
        with patch(
            "datasette_suggest_purchase.plugin.SierraClient.authenticate_patron",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            response = await datasette.client.post(
                "/suggest-purchase/login",
                data={"barcode": "12345678901234", "pin": "1234"},
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "Unable+to+connect" in location or "error=" in location


class TestSubmission:
    """Tests for purchase suggestion submission."""

    @pytest.fixture
    def actor_cookie(self, datasette):
        """Create a signed actor cookie for a patron."""
        actor = {
            "id": "patron:12345",
            "principal_type": "patron",
            "principal_id": "12345",
            "display": "Test Patron",
            "sierra": {
                "patron_record_id": 12345,
                "ptype": 3,
                "home_library": "MAIN",
            },
        }
        return datasette.sign({"a": actor}, "actor")

    async def test_authenticated_user_sees_submission_form(self, datasette, actor_cookie):
        """Authenticated patrons see the submission form."""
        response = await datasette.client.get(
            "/suggest-purchase",
            cookies={"ds_actor": actor_cookie},
        )
        assert response.status_code == 200
        assert "What would you like us to consider purchasing?" in response.text
        assert "Submit Suggestion" in response.text

    async def test_submit_creates_request(self, datasette, actor_cookie, db_path):
        """Submitting a suggestion creates a database record."""
        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={
                "query": "The Midnight Library by Matt Haig",
                "format": "ebook",
                "notes": "Heard great reviews",
            },
            cookies={"ds_actor": actor_cookie},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "/suggest-purchase/confirmation" in response.headers.get("location", "")

        # Verify database record
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT raw_query, format_preference, patron_notes, status FROM purchase_requests")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "The Midnight Library by Matt Haig"
        assert row[1] == "ebook"
        assert row[2] == "Heard great reviews"
        assert row[3] == "new"

    async def test_submit_empty_query_shows_error(self, datasette, actor_cookie):
        """Submitting without a query shows an error."""
        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={"query": "", "format": "print"},
            cookies={"ds_actor": actor_cookie},
        )

        assert response.status_code == 200
        assert "Please enter" in response.text

    async def test_unauthenticated_submit_redirects_to_login(self, datasette):
        """Unauthenticated submission attempts redirect to login."""
        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={"query": "Some Book"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers.get("location") == "/suggest-purchase"


class TestMyRequests:
    """Tests for the My Requests page."""

    async def test_shows_only_own_requests(self, datasette, db_path):
        """Patrons only see their own requests."""
        # Insert requests for two different patrons
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, status) VALUES (?, ?, ?, ?, ?)",
            ("req1", "2024-01-01T00:00:00Z", 12345, "My Book", "new"),
        )
        conn.execute(
            "INSERT INTO purchase_requests (request_id, created_ts, patron_record_id, raw_query, status) VALUES (?, ?, ?, ?, ?)",
            ("req2", "2024-01-01T00:00:00Z", 99999, "Other Patron Book", "new"),
        )
        conn.commit()
        conn.close()

        # Create authenticated cookie for patron 12345
        actor = {
            "id": "patron:12345",
            "principal_type": "patron",
            "principal_id": "12345",
            "display": "Test Patron",
            "sierra": {"patron_record_id": 12345, "ptype": 3, "home_library": "MAIN"},
        }
        cookie_value = datasette.sign({"a": actor}, "actor")

        response = await datasette.client.get(
            "/suggest-purchase/my-requests",
            cookies={"ds_actor": cookie_value},
        )

        assert response.status_code == 200
        assert "My Book" in response.text
        assert "Other Patron Book" not in response.text

    async def test_unauthenticated_redirects(self, datasette):
        """Unauthenticated users are redirected to login."""
        response = await datasette.client.get(
            "/suggest-purchase/my-requests",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers.get("location") == "/suggest-purchase"


class TestLogout:
    """Tests for logout functionality."""

    async def test_logout_clears_cookie(self, datasette):
        """Logout clears the session cookie."""
        response = await datasette.client.get(
            "/suggest-purchase/logout",
            follow_redirects=False,
        )

        assert response.status_code == 302
        set_cookie = response.headers.get("set-cookie", "")
        assert "ds_actor" in set_cookie
        assert "Max-Age=0" in set_cookie or 'ds_actor=""' in set_cookie or "ds_actor=;" in set_cookie
