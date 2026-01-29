"""Integration tests for login rate limiting."""

import re
from unittest.mock import AsyncMock, patch

from datasette.app import Datasette

from datasette_suggest_purchase.migrations import run_migrations
from datasette_suggest_purchase.staff_auth import hash_password, upsert_staff_account


async def get_staff_login_csrf(client):
    """Return (token, cookies) from staff login page."""
    response = await client.get("/suggest-purchase/staff-login")
    match = re.search(r'name="csrftoken" value="([^"]+)"', response.text)
    token = match.group(1) if match else None
    cookies = {}
    if "ds_csrftoken" in response.cookies:
        cookies["ds_csrftoken"] = response.cookies["ds_csrftoken"]
    return token, cookies


def build_datasette(db_path, rules, bot_config=None):
    """Build a Datasette instance with rate limit rules."""
    db_name = db_path.stem
    plugin_config = {
        "suggest_db_path": str(db_path),
        "rules": rules,
    }
    if bot_config is not None:
        plugin_config["bot"] = bot_config
    return Datasette(
        [str(db_path)],
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
                    **plugin_config,
                }
            },
        },
    )


class TestStaffLoginRateLimit:
    """Tests for staff login rate limiting."""

    async def test_staff_login_rate_limited(self, tmp_path):
        db_path = tmp_path / "rate_limit_staff.db"
        run_migrations(db_path, verbose=False)
        upsert_staff_account(db_path, "staffer", hash_password("goodpass"), "Staff User")

        ds = build_datasette(
            db_path,
            {"login_rate_limit": {"max_attempts": 2, "window_seconds": 3600}},
        )

        csrf_token, cookies = await get_staff_login_csrf(ds.client)
        assert csrf_token is not None

        # First failed attempt
        response = await ds.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "staffer", "password": "badpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302

        # Second failed attempt (still allowed)
        response = await ds.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "staffer", "password": "badpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302

        # Third attempt should be blocked
        response = await ds.client.post(
            "/suggest-purchase/staff-login",
            data={"username": "staffer", "password": "badpass", "csrftoken": csrf_token},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 429
        assert "Too many login attempts" in response.text


class TestPatronLoginRateLimit:
    """Tests for patron login rate limiting."""

    async def test_patron_login_rate_limited(self, tmp_path):
        db_path = tmp_path / "rate_limit_patron.db"
        run_migrations(db_path, verbose=False)

        ds = build_datasette(
            db_path,
            {"login_rate_limit": {"max_attempts": 1, "window_seconds": 3600}},
        )

        with patch(
            "datasette_suggest_purchase.plugin.SierraClient.authenticate_patron",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await ds.client.post(
                "/suggest-purchase/login",
                data={"barcode": "1234567890", "pin": "0000"},
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Second attempt should be blocked
            response = await ds.client.post(
                "/suggest-purchase/login",
                data={"barcode": "1234567890", "pin": "0000"},
                follow_redirects=False,
            )
            assert response.status_code == 429
            assert "Too many login attempts" in response.text
