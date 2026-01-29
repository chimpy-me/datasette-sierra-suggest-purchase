"""Integration tests for staff login flow."""

import re

import pytest
from datasette.app import Datasette

from datasette_suggest_purchase.staff_auth import (
    get_staff_account,
    hash_password,
    upsert_staff_account,
    verify_password,
)


async def get_staff_login_csrf(client):
    """Return (token, cookies) from staff login page."""
    response = await client.get("/suggest-purchase/staff-login")
    match = re.search(r'name="csrftoken" value="([^"]+)"', response.text)
    token = match.group(1) if match else None
    cookies = {}
    if "ds_csrftoken" in response.cookies:
        cookies["ds_csrftoken"] = response.cookies["ds_csrftoken"]
    return token, cookies


@pytest.fixture
def staff_db_path(db_path):
    """Create a test database with a staff account."""
    upsert_staff_account(db_path, "teststaff", hash_password("staffpass"), "Test Staff")
    return db_path


@pytest.fixture
def staff_datasette(staff_db_path):
    """Create a Datasette instance with staff account configured."""
    db_name = staff_db_path.stem

    return Datasette(
        [str(staff_db_path)],
        config={
            "databases": {
                db_name: {
                    "allow": {"principal_type": "staff"},
                    "tables": {
                        "purchase_requests": {"allow": {"principal_type": "staff"}},
                    },
                }
            },
            "plugins": {
                "datasette-suggest-purchase": {
                    "suggest_db_path": str(staff_db_path),
                }
            },
        },
    )


class TestStaffLoginPage:
    """Tests for the staff login page."""

    async def test_staff_login_page_renders(self, staff_datasette):
        """Staff login page should render."""
        response = await staff_datasette.client.get("/suggest-purchase/staff-login")
        assert response.status_code == 200
        assert "Staff Sign In" in response.text
        assert 'name="username"' in response.text
        assert 'name="password"' in response.text
        assert 'name="csrftoken"' in response.text

    async def test_staff_login_page_shows_error(self, staff_datasette):
        """Staff login page should show error message."""
        response = await staff_datasette.client.get(
            "/suggest-purchase/staff-login?error=Test+error"
        )
        assert response.status_code == 200
        assert "Test error" in response.text


class TestStaffLogin:
    """Tests for staff login POST."""

    async def test_successful_login_sets_cookie(self, staff_datasette):
        """Successful login should set ds_actor cookie and redirect."""
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers.get("location") == "/suggest_purchase/purchase_requests"
        assert "ds_actor" in response.cookies

    async def test_login_enforces_https_when_configured(self, db_path):
        """Login rejects non-HTTPS when enforce_https is enabled."""
        from datasette.app import Datasette

        from datasette_suggest_purchase.staff_auth import hash_password, upsert_staff_account

        db_name = db_path.stem
        ds = Datasette(
            [str(db_path)],
            config={
                "databases": {
                    db_name: {
                        "allow": {"principal_type": "staff"},
                    }
                },
                "plugins": {
                    "datasette-suggest-purchase": {
                        "suggest_db_path": str(db_path),
                        "enforce_https": True,
                    }
                },
            },
        )

        upsert_staff_account(
            db_path,
            "securestaff",
            hash_password("staffpass"),
            "Secure Staff",
        )
        csrf_token, cookies = await get_staff_login_csrf(ds.client)
        assert csrf_token is not None

        response = await ds.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "securestaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "HTTPS required" in response.text

    async def test_successful_login_actor_has_staff_type(self, staff_datasette, staff_db_path):
        """Logged in staff should have principal_type=staff in actor."""
        # Login
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        login_response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        # Use cookie to access staff route
        cookie = login_response.cookies.get("ds_actor")
        db_name = staff_db_path.stem
        response = await staff_datasette.client.get(
            f"/{db_name}/purchase_requests",
            cookies={"ds_actor": cookie},
        )

        # Staff should be able to access the table
        assert response.status_code == 200

    async def test_failed_login_wrong_password(self, staff_datasette):
        """Wrong password should redirect back with error."""
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "wrongpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "error=" in response.headers.get("location", "")
        assert "ds_actor" not in response.cookies

    async def test_failed_login_nonexistent_user(self, staff_datasette):
        """Non-existent user should redirect back with error."""
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "nouser", "password": "anypass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "error=" in response.headers.get("location", "")

    async def test_login_empty_credentials(self, staff_datasette):
        """Empty credentials should redirect back with error."""
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "", "password": "", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "error=" in response.headers.get("location", "")


class TestStaffLogout:
    """Tests for staff logout."""

    async def test_logout_clears_cookie(self, staff_datasette):
        """Logout should clear the ds_actor cookie."""
        # First login
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        login_response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        cookie = login_response.cookies.get("ds_actor")

        # Then logout
        response = await staff_datasette.client.get(
            "/suggest-purchase/staff-logout",
            cookies={"ds_actor": cookie},
            follow_redirects=False,
        )

        assert response.status_code == 302
        # Cookie should be cleared (set to empty with max_age=0)
        set_cookie = response.headers.get("set-cookie", "")
        assert "ds_actor=" in set_cookie


class TestStaffAccessAfterLogin:
    """Tests for staff access to protected resources after login."""

    async def test_staff_can_access_table_view(self, staff_datasette, staff_db_path):
        """Logged in staff can access the purchase_requests table."""
        # Login
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        login_response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        cookie = login_response.cookies.get("ds_actor")

        # Access table
        db_name = staff_db_path.stem
        response = await staff_datasette.client.get(
            f"/{db_name}/purchase_requests",
            cookies={"ds_actor": cookie},
        )

        assert response.status_code == 200

    async def test_staff_can_update_request(self, staff_datasette, staff_db_path):
        """Logged in staff can update a purchase request."""
        import sqlite3

        # Create a test request
        conn = sqlite3.connect(staff_db_path)
        conn.execute("""
            INSERT INTO purchase_requests
                (request_id, created_ts, patron_record_id, raw_query, status)
            VALUES ('staff-test-001', '2024-01-15T10:00:00Z', 99999, 'Test Book', 'new')
        """)
        conn.commit()
        conn.close()

        # Login
        csrf_token, cookies = await get_staff_login_csrf(staff_datasette.client)
        assert csrf_token is not None
        login_response = await staff_datasette.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "teststaff", "password": "staffpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        cookie = login_response.cookies.get("ds_actor")

        # Update request
        response = await staff_datasette.client.post(
            "/-/suggest-purchase/request/staff-test-001/update",
            data={"status": "in_review", "staff_notes": "Reviewing now", "csrftoken": csrf_token},
            cookies={"ds_actor": cookie, **cookies},
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify update
        conn = sqlite3.connect(staff_db_path)
        cursor = conn.execute(
            "SELECT status, staff_notes FROM purchase_requests WHERE request_id = ?",
            ("staff-test-001",),
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "in_review"
        assert row[1] == "Reviewing now"


class TestStartupHook:
    """Tests for admin account sync on startup."""

    async def test_startup_syncs_admin_from_env(self, db_path, monkeypatch):
        """Startup hook should create admin account from env vars."""
        # Set env vars before creating Datasette
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "envtestpass")
        monkeypatch.setenv("STAFF_ADMIN_DISPLAY_NAME", "Env Test Admin")

        db_name = db_path.stem

        # Create Datasette (this triggers startup hook)
        ds = Datasette(
            [str(db_path)],
            config={
                "databases": {
                    db_name: {
                        "allow": {"principal_type": "staff"},
                    }
                },
                "plugins": {
                    "datasette-suggest-purchase": {
                        "suggest_db_path": str(db_path),
                    }
                },
            },
        )

        # Invoke startup
        await ds.invoke_startup()

        # Verify admin account was created
        account = get_staff_account(db_path, "admin")
        assert account is not None
        assert account["display_name"] == "Env Test Admin"
        assert verify_password("envtestpass", account["password_hash"])

    async def test_startup_updates_existing_admin(self, db_path, monkeypatch):
        """Startup hook should update existing admin account."""
        # Create initial admin account
        upsert_staff_account(db_path, "admin", hash_password("oldpass"), "Old Admin")

        # Set new env password
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "newenvpass")

        db_name = db_path.stem
        ds = Datasette(
            [str(db_path)],
            config={
                "databases": {
                    db_name: {
                        "allow": {"principal_type": "staff"},
                    }
                },
                "plugins": {
                    "datasette-suggest-purchase": {
                        "suggest_db_path": str(db_path),
                    }
                },
            },
        )

        await ds.invoke_startup()

        # Verify password was updated
        account = get_staff_account(db_path, "admin")
        assert account is not None
        assert verify_password("newenvpass", account["password_hash"])
        assert not verify_password("oldpass", account["password_hash"])

    async def test_admin_can_login_after_startup(self, db_path, monkeypatch):
        """Admin created via startup hook can successfully log in."""
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "logintest123")

        db_name = db_path.stem
        ds = Datasette(
            [str(db_path)],
            config={
                "databases": {
                    db_name: {
                        "allow": {"principal_type": "staff"},
                    }
                },
                "plugins": {
                    "datasette-suggest-purchase": {
                        "suggest_db_path": str(db_path),
                    }
                },
            },
        )

        await ds.invoke_startup()

        # Try to login with the env-created credentials
        csrf_token, cookies = await get_staff_login_csrf(ds.client)
        assert csrf_token is not None
        response = await ds.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "admin", "password": "logintest123", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "ds_actor" in response.cookies
