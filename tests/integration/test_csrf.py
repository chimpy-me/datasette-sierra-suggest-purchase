"""Integration tests for CSRF protection.

These tests verify that:
- POST to /suggest-purchase/submit without CSRF token fails (403)
- POST to /suggest-purchase/submit with valid CSRF token succeeds
- Login is exempt from CSRF (no prior authenticated page)
- Staff update routes still require authentication despite being CSRF-exempt
"""

import re
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest


async def get_csrf_token_and_cookies(client, cookies):
    """Get CSRF token and cookies by loading the form page.

    Returns (token, combined_cookies) where combined_cookies includes both
    the original cookies and the ds_csrftoken cookie set by the response.
    """
    response = await client.get("/suggest-purchase", cookies=cookies)
    match = re.search(r'name="csrftoken" value="([^"]+)"', response.text)
    token = match.group(1) if match else None

    # Combine original cookies with any new cookies set by the response
    combined_cookies = dict(cookies) if cookies else {}
    if "ds_csrftoken" in response.cookies:
        combined_cookies["ds_csrftoken"] = response.cookies["ds_csrftoken"]

    return token, combined_cookies


class TestCSRFEnforcement:
    """Tests for CSRF token enforcement on patron submission."""

    @pytest.fixture
    def patron_cookie(self, datasette):
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

    async def test_submit_without_csrf_token_fails(self, datasette, patron_cookie):
        """POST to submit without CSRF token returns 403."""
        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={
                "query": "A Book Without CSRF",
                "format": "print",
            },
            cookies={"ds_actor": patron_cookie},
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_submit_with_invalid_csrf_token_fails(self, datasette, patron_cookie):
        """POST to submit with invalid CSRF token returns 403."""
        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={
                "query": "A Book With Bad Token",
                "format": "print",
                "csrftoken": "invalid-token-value",
            },
            cookies={"ds_actor": patron_cookie},
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_submit_with_csrf_token_succeeds(self, datasette, patron_cookie, db_path):
        """POST to submit with valid CSRF token succeeds."""
        # Get a valid CSRF token and cookies from the form page
        csrf_token, cookies = await get_csrf_token_and_cookies(
            datasette.client, {"ds_actor": patron_cookie}
        )
        assert csrf_token is not None, "Failed to get CSRF token"

        response = await datasette.client.post(
            "/suggest-purchase/submit",
            data={
                "query": "A Book With Valid CSRF",
                "format": "print",
                "csrftoken": csrf_token,
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/suggest-purchase/confirmation" in response.headers.get("location", "")

        # Verify the request was actually created
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT raw_query FROM purchase_requests WHERE raw_query = 'A Book With Valid CSRF'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None


class TestCSRFExemptions:
    """Tests for intentional CSRF exemptions."""

    async def test_patron_login_without_csrf_succeeds(self, datasette):
        """Patron login POST works without CSRF token (intentional exemption)."""
        mock_patron_info = {
            "patron_record_id": 99999,
            "ptype": 3,
            "home_library": "MAIN",
            "name": "CSRF Test User",
        }

        with patch(
            "datasette_suggest_purchase.plugin.SierraClient.authenticate_patron",
            new_callable=AsyncMock,
            return_value=mock_patron_info,
        ):
            response = await datasette.client.post(
                "/suggest-purchase/login",
                data={"barcode": "99999999999999", "pin": "9999"},
                follow_redirects=False,
            )

        # Should succeed with redirect (302), not fail with CSRF error (403)
        assert response.status_code == 302
        assert response.headers.get("location") == "/suggest-purchase"

    async def test_staff_login_without_csrf_succeeds(self, datasette, db_path):
        """Staff login POST works without CSRF token (intentional exemption)."""
        from datasette_suggest_purchase.staff_auth import hash_password, upsert_staff_account

        # Create a staff account
        upsert_staff_account(db_path, "csrftest", hash_password("testpass"), "CSRF Test Staff")

        response = await datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "csrftest", "password": "testpass"},
            follow_redirects=False,
        )

        # Should succeed with redirect (302), not fail with CSRF error (403)
        assert response.status_code == 302
        assert "ds_actor" in response.cookies

    async def test_staff_update_exempt_but_requires_auth(self, datasette, db_path):
        """Staff update routes are CSRF-exempt but still require staff authentication."""
        # Seed a request to update
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO purchase_requests
                (request_id, created_ts, patron_record_id, raw_query, status)
            VALUES
                ('csrf-test-001', '2024-01-15T10:00:00Z', 12345, 'CSRF Test Book', 'new')
        """)
        conn.commit()
        conn.close()

        # Try without any authentication - should fail
        response = await datasette.client.post(
            "/-/suggest-purchase/request/csrf-test-001/update",
            data={"status": "in_review"},
        )
        assert response.status_code == 403

    async def test_staff_update_works_for_staff(self, datasette, db_path):
        """Staff update works for authenticated staff (CSRF-exempt, auth required)."""
        # Seed a request
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO purchase_requests
                (request_id, created_ts, patron_record_id, raw_query, status)
            VALUES
                ('csrf-test-002', '2024-01-15T10:00:00Z', 12345, 'Staff Update Test', 'new')
        """)
        conn.commit()
        conn.close()

        # Create staff cookie
        actor = {
            "id": "staff:admin",
            "principal_type": "staff",
            "principal_id": "admin",
            "display": "Admin User",
        }
        staff_cookie = datasette.sign({"a": actor}, "actor")

        response = await datasette.client.post(
            "/-/suggest-purchase/request/csrf-test-002/update",
            data={"status": "in_review"},
            cookies={"ds_actor": staff_cookie},
            follow_redirects=False,
        )

        # Should succeed (302 redirect)
        assert response.status_code == 302

        # Verify update happened
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT status FROM purchase_requests WHERE request_id = 'csrf-test-002'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "in_review"


class TestPatronAccessWithCSRF:
    """Tests that patron routes work correctly with CSRF protection."""

    @pytest.fixture
    def patron_cookie(self, datasette):
        """Create a signed actor cookie for a patron."""
        actor = {
            "id": "patron:54321",
            "principal_type": "patron",
            "principal_id": "54321",
            "display": "Patron User",
            "sierra": {
                "patron_record_id": 54321,
                "ptype": 3,
                "home_library": "BRANCH",
            },
        }
        return datasette.sign({"a": actor}, "actor")

    async def test_form_page_includes_csrf_token(self, datasette, patron_cookie):
        """The submission form includes a CSRF token input."""
        response = await datasette.client.get(
            "/suggest-purchase",
            cookies={"ds_actor": patron_cookie},
        )
        assert response.status_code == 200
        assert 'name="csrftoken"' in response.text
        # Token should have a value
        match = re.search(r'name="csrftoken" value="([^"]+)"', response.text)
        assert match is not None
        assert len(match.group(1)) > 0
