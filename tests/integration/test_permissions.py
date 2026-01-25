"""Integration tests for permission/access control on Datasette tables.

These tests verify that:
- Anonymous users cannot access table data (HTML, JSON, CSV)
- Patrons cannot access table data (they use custom plugin routes)
- Staff can access table data in all formats
"""

import sqlite3

import pytest


@pytest.fixture
def seeded_db_path(db_path):
    """Seed the test database with a purchase request."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status)
        VALUES
            ('perm-test-001', '2024-01-15T10:00:00Z', 12345, 'Permission Test Book', 'new')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def seeded_datasette(seeded_db_path):
    """Create a Datasette instance with seeded test data and permission config."""
    from datasette.app import Datasette

    db_name = seeded_db_path.stem

    return Datasette(
        [str(seeded_db_path)],
        config={
            # Database permissions - staff only access to data tables
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
                    "suggest_db_path": str(seeded_db_path),
                }
            },
        },
    )


class TestAnonymousAccess:
    """Tests that anonymous users cannot access table data."""

    async def test_anonymous_cannot_view_table_html(self, seeded_datasette, seeded_db_path):
        """Anonymous users cannot view the HTML table view."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(f"/{db_name}/purchase_requests")
        assert response.status_code == 403

    async def test_anonymous_cannot_view_json_export(self, seeded_datasette, seeded_db_path):
        """Anonymous users cannot access JSON export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(f"/{db_name}/purchase_requests.json")
        assert response.status_code == 403

    async def test_anonymous_cannot_view_csv_export(self, seeded_datasette, seeded_db_path):
        """Anonymous users cannot access CSV export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(f"/{db_name}/purchase_requests.csv")
        assert response.status_code == 403


class TestPatronAccess:
    """Tests that patrons cannot access staff table views."""

    @pytest.fixture
    def patron_cookie(self, seeded_datasette):
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
        return seeded_datasette.sign({"a": actor}, "actor")

    async def test_patron_cannot_view_table_html(
        self, seeded_datasette, seeded_db_path, patron_cookie
    ):
        """Patrons cannot view the HTML table view."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests",
            cookies={"ds_actor": patron_cookie},
        )
        assert response.status_code == 403

    async def test_patron_cannot_view_json_export(
        self, seeded_datasette, seeded_db_path, patron_cookie
    ):
        """Patrons cannot access JSON export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.json",
            cookies={"ds_actor": patron_cookie},
        )
        assert response.status_code == 403

    async def test_patron_cannot_view_csv_export(
        self, seeded_datasette, seeded_db_path, patron_cookie
    ):
        """Patrons cannot access CSV export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.csv",
            cookies={"ds_actor": patron_cookie},
        )
        assert response.status_code == 403

    async def test_patron_my_requests_still_works(self, seeded_datasette, patron_cookie):
        """Patrons can still access their own requests via the custom route."""
        response = await seeded_datasette.client.get(
            "/suggest-purchase/my-requests",
            cookies={"ds_actor": patron_cookie},
        )
        assert response.status_code == 200
        assert "My Requests" in response.text


class TestStaffAccess:
    """Tests that staff can access table data."""

    @pytest.fixture
    def staff_cookie(self, seeded_datasette):
        """Create a signed actor cookie for staff."""
        actor = {
            "id": "staff:reviewer",
            "principal_type": "staff",
            "principal_id": "reviewer",
            "display": "Staff Reviewer",
        }
        return seeded_datasette.sign({"a": actor}, "actor")

    async def test_staff_can_view_table_html(
        self, seeded_datasette, seeded_db_path, staff_cookie
    ):
        """Staff can view the HTML table view."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests",
            cookies={"ds_actor": staff_cookie},
        )
        assert response.status_code == 200
        assert "Permission Test Book" in response.text

    async def test_staff_can_view_json_export(
        self, seeded_datasette, seeded_db_path, staff_cookie
    ):
        """Staff can access JSON export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.json",
            cookies={"ds_actor": staff_cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["rows"]) == 1
        assert data["rows"][0]["raw_query"] == "Permission Test Book"

    async def test_staff_can_view_csv_export(
        self, seeded_datasette, seeded_db_path, staff_cookie
    ):
        """Staff can access CSV export."""
        db_name = seeded_db_path.stem
        response = await seeded_datasette.client.get(
            f"/{db_name}/purchase_requests.csv",
            cookies={"ds_actor": staff_cookie},
        )
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/csv" in content_type or "text/plain" in content_type
        assert "Permission Test Book" in response.text
