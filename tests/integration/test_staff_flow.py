"""Integration tests for staff review functionality."""

import pytest
import sqlite3

from datasette.app import Datasette


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with test data."""
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

        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, status)
        VALUES
            ('test-req-001', '2024-01-15T10:00:00Z', 12345, 'Test Book Request', 'new');
    """)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture
def datasette(db_path):
    """Create a Datasette instance."""
    return Datasette(
        [str(db_path)],
        metadata={
            "plugins": {
                "datasette-suggest-purchase": {
                    "suggest_db_path": str(db_path),
                }
            }
        },
    )


class TestStaffUpdate:
    """Tests for staff request updates."""

    @pytest.fixture
    def staff_cookie(self, datasette):
        """Create a signed actor cookie for staff."""
        actor = {
            "id": "staff:jsmith",
            "principal_type": "staff",
            "principal_id": "jsmith",
            "display": "Jane Smith",
        }
        return datasette.sign({"a": actor}, "actor")

    async def test_staff_can_update_status(self, datasette, staff_cookie, db_path):
        """Staff can update request status."""
        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "in_review"},
            cookies={"ds_actor": staff_cookie},
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify database update
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT status FROM purchase_requests WHERE request_id = 'test-req-001'")
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "in_review"

    async def test_staff_can_add_notes(self, datasette, staff_cookie, db_path):
        """Staff can add notes to a request."""
        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"staff_notes": "Checking availability with vendor"},
            cookies={"ds_actor": staff_cookie},
            follow_redirects=False,
        )

        assert response.status_code == 302

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT staff_notes FROM purchase_requests WHERE request_id = 'test-req-001'")
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "Checking availability with vendor"

    async def test_staff_can_update_status_and_notes(self, datasette, staff_cookie, db_path):
        """Staff can update both status and notes together."""
        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={
                "status": "ordered",
                "staff_notes": "Ordered from Baker & Taylor",
            },
            cookies={"ds_actor": staff_cookie},
            follow_redirects=False,
        )

        assert response.status_code == 302

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT status, staff_notes, updated_ts FROM purchase_requests WHERE request_id = 'test-req-001'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "ordered"
        assert row[1] == "Ordered from Baker & Taylor"
        assert row[2] is not None  # updated_ts should be set

    async def test_invalid_status_rejected(self, datasette, staff_cookie):
        """Invalid status values are rejected."""
        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "invalid_status"},
            cookies={"ds_actor": staff_cookie},
        )

        assert response.status_code == 400
        assert "Invalid status" in response.text

    async def test_patron_cannot_update(self, datasette):
        """Patrons cannot access staff update route."""
        actor = {
            "id": "patron:12345",
            "principal_type": "patron",
            "principal_id": "12345",
            "display": "Patron User",
            "sierra": {"patron_record_id": 12345},
        }
        cookie_value = datasette.sign({"a": actor}, "actor")

        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "ordered"},
            cookies={"ds_actor": cookie_value},
        )

        assert response.status_code == 403

    async def test_unauthenticated_cannot_update(self, datasette):
        """Unauthenticated users cannot update requests."""
        response = await datasette.client.post(
            "/-/suggest-purchase/request/test-req-001/update",
            data={"status": "ordered"},
        )

        assert response.status_code == 403


class TestStaffView:
    """Tests for staff viewing requests."""

    async def test_requests_visible_in_datasette_table(self, datasette, db_path):
        """Requests are visible in the Datasette table view."""
        # Get the database name from the path
        db_name = db_path.stem

        response = await datasette.client.get(f"/{db_name}/purchase_requests.json")

        assert response.status_code == 200
        data = response.json()
        assert len(data["rows"]) == 1
        assert data["rows"][0]["raw_query"] == "Test Book Request"
        assert data["rows"][0]["status"] == "new"

    async def test_csv_export_available(self, datasette, db_path):
        """CSV export is available via Datasette."""
        db_name = db_path.stem

        response = await datasette.client.get(f"/{db_name}/purchase_requests.csv")

        assert response.status_code == 200
        # Datasette may return text/plain or text/csv depending on version
        content_type = response.headers.get("content-type", "")
        assert "text/csv" in content_type or "text/plain" in content_type
        assert "Test Book Request" in response.text
