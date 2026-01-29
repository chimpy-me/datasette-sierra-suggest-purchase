"""Integration tests for CSV export safety."""

import sqlite3

import pytest


@pytest.fixture
def seeded_db_path(db_path):
    """Seed database with potentially dangerous CSV content."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO purchase_requests
            (request_id, created_ts, patron_record_id, raw_query, patron_notes, staff_notes, status)
        VALUES
            ('csv-test-001', '2024-01-15T10:00:00Z', 12345,
             '=SUM(1,1)', '+123', '@note', 'new')
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def seeded_datasette(seeded_db_path):
    """Create a Datasette instance with seeded test data."""
    from datasette.app import Datasette

    db_name = seeded_db_path.stem
    return Datasette(
        [str(seeded_db_path)],
        config={
            "databases": {
                db_name: {
                    "allow": {"principal_type": "staff"},
                }
            },
            "plugins": {
                "datasette-suggest-purchase": {
                    "suggest_db_path": str(seeded_db_path),
                }
            },
        },
    )


async def test_csv_export_sanitizes_cells(seeded_datasette, seeded_db_path):
    actor = {
        "id": "staff:reviewer",
        "principal_type": "staff",
        "principal_id": "reviewer",
        "display": "Staff Reviewer",
    }
    staff_cookie = seeded_datasette.sign({"a": actor}, "actor")
    db_name = seeded_db_path.stem

    response = await seeded_datasette.client.get(
        f"/{db_name}/purchase_requests.csv",
        cookies={"ds_actor": staff_cookie},
    )

    assert response.status_code == 200
    assert "'=SUM(1,1)" in response.text
    assert "'+123" in response.text
    assert "'@note" in response.text
