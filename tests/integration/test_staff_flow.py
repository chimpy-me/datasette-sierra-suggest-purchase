"""Integration tests for staff review functionality."""

import re
import sqlite3

import pytest


@pytest.fixture
def seeded_db_path(db_path):
    """Seed the test database with a purchase request for staff tests."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status)
        VALUES
            ('test-req-001', '2024-01-15T10:00:00Z', 12345, 'Test Book Request', 'new')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def seeded_datasette(seeded_db_path):
    """Create a Datasette instance with seeded test data."""
    from datasette.app import Datasette

    return Datasette(
        [str(seeded_db_path)],
        config={
            "plugins": {
                "datasette-suggest-purchase": {
                    "suggest_db_path": str(seeded_db_path),
                }
            }
        },
    )


async def get_csrf_token_and_cookies(client):
    """Return (token, cookies) from a staff login page load."""
    response = await client.get("/suggest-purchase/staff-login")
    match = re.search(r'name="csrftoken" value="([^"]+)"', response.text)
    token = match.group(1) if match else None
    cookies = {}
    if "ds_csrftoken" in response.cookies:
        cookies["ds_csrftoken"] = response.cookies["ds_csrftoken"]
    return token, cookies


class TestStaffUpdate:
    """Tests for staff request updates."""

    @pytest.fixture
    def staff_cookie(self, seeded_datasette):
        """Create a signed actor cookie for staff."""
        actor = {
            "id": "staff:jsmith",
            "principal_type": "staff",
            "principal_id": "jsmith",
            "display": "Jane Smith",
        }
        return seeded_datasette.sign({"a": actor}, "actor")

    async def test_staff_can_update_status(self, seeded_datasette, staff_cookie, seeded_db_path):
        """Staff can update request status."""
        csrf_token, cookies = await get_csrf_token_and_cookies(seeded_datasette.client)
        assert csrf_token is not None
        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "in_review", "csrftoken": csrf_token},
            cookies={"ds_actor": staff_cookie, **cookies},
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify database update
        conn = sqlite3.connect(seeded_db_path)
        cursor = conn.execute(
            "SELECT status FROM purchase_requests WHERE request_id = 'test-req-001'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "in_review"

    async def test_staff_can_add_notes(self, seeded_datasette, staff_cookie, seeded_db_path):
        """Staff can add notes to a request."""
        csrf_token, cookies = await get_csrf_token_and_cookies(seeded_datasette.client)
        assert csrf_token is not None
        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"staff_notes": "Checking availability with vendor", "csrftoken": csrf_token},
            cookies={"ds_actor": staff_cookie, **cookies},
            follow_redirects=False,
        )

        assert response.status_code == 302

        conn = sqlite3.connect(seeded_db_path)
        cursor = conn.execute(
            "SELECT staff_notes FROM purchase_requests WHERE request_id = 'test-req-001'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "Checking availability with vendor"

    async def test_staff_can_update_status_and_notes(
        self, seeded_datasette, staff_cookie, seeded_db_path
    ):
        """Staff can update both status and notes together."""
        csrf_token, cookies = await get_csrf_token_and_cookies(seeded_datasette.client)
        assert csrf_token is not None
        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={
                "status": "ordered",
                "staff_notes": "Ordered from Baker & Taylor",
                "csrftoken": csrf_token,
            },
            cookies={"ds_actor": staff_cookie, **cookies},
            follow_redirects=False,
        )

        assert response.status_code == 302

        conn = sqlite3.connect(seeded_db_path)
        cursor = conn.execute(
            """SELECT status, staff_notes, updated_ts
            FROM purchase_requests WHERE request_id = 'test-req-001'"""
        )
        row = cursor.fetchone()
        cursor = conn.execute(
            """
            SELECT event_type, actor_id, payload_json FROM request_events
            WHERE request_id = 'test-req-001'
            ORDER BY ts ASC
            """
        )
        events = cursor.fetchall()
        conn.close()

        assert row[0] == "ordered"
        assert row[1] == "Ordered from Baker & Taylor"
        assert row[2] is not None  # updated_ts should be set
        assert ("status_changed", "staff:jsmith", '{"status": "ordered"}') in events
        assert ("note_added", "staff:jsmith", '{"note_added": true}') in events

    async def test_invalid_status_rejected(self, seeded_datasette, staff_cookie):
        """Invalid status values are rejected."""
        csrf_token, cookies = await get_csrf_token_and_cookies(seeded_datasette.client)
        assert csrf_token is not None
        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "invalid_status", "csrftoken": csrf_token},
            cookies={"ds_actor": staff_cookie, **cookies},
        )

        assert response.status_code == 400
        assert "Invalid status" in response.text

    async def test_patron_cannot_update(self, seeded_datasette):
        """Patrons cannot access staff update route."""
        actor = {
            "id": "patron:12345",
            "principal_type": "patron",
            "principal_id": "12345",
        }
        cookie_value = seeded_datasette.sign({"a": actor}, "actor")

        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "ordered"},
            cookies={"ds_actor": cookie_value},
        )

        assert response.status_code == 403

    async def test_unauthenticated_cannot_update(self, seeded_datasette):
        """Unauthenticated users cannot update requests."""
        response = await seeded_datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "ordered"},
        )

        assert response.status_code == 403


class TestStaffView:
    """Tests for staff viewing requests."""

    @pytest.fixture
    def staff_view_cookie(self, seeded_datasette):
        """Create a signed actor cookie for staff viewing."""
        actor = {
            "id": "staff:viewer",
            "principal_type": "staff",
            "principal_id": "viewer",
            "display": "Staff Viewer",
        }
        return seeded_datasette.sign({"a": actor}, "actor")

    async def test_requests_visible_in_datasette_table(
        self, seeded_datasette, seeded_db_path, staff_view_cookie
    ):
        """Requests are visible in the Datasette table view for staff."""
        db_name = seeded_db_path.stem

        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.json",
            cookies={"ds_actor": staff_view_cookie},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["rows"]) == 1
        assert data["rows"][0]["raw_query"] == "Test Book Request"
        assert data["rows"][0]["status"] == "new"

    async def test_csv_export_available(self, seeded_datasette, seeded_db_path, staff_view_cookie):
        """CSV export is available via Datasette for staff."""
        db_name = seeded_db_path.stem

        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.csv",
            cookies={"ds_actor": staff_view_cookie},
        )

        assert response.status_code == 200
        # Datasette may return text/plain or text/csv depending on version
        content_type = response.headers.get("content-type", "")
        assert "text/csv" in content_type or "text/plain" in content_type
        assert "Test Book Request" in response.text
