"""Integration tests for Open Library gating in staff UI."""

from datasette.app import Datasette

from datasette_suggest_purchase.migrations import run_migrations


async def test_openlibrary_test_route_disabled(tmp_path):
    db_path = tmp_path / "openlibrary_gate.db"
    run_migrations(db_path, verbose=False)
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
                    "bot": {
                        "openlibrary": {"enabled": False}
                    },
                }
            },
        },
    )

    actor = {
        "id": "staff:tester",
        "principal_type": "staff",
        "principal_id": "tester",
        "display": "Tester",
    }
    staff_cookie = ds.sign({"a": actor}, "actor")

    response = await ds.client.get(
        "/suggest-purchase/staff/test-openlibrary",
        cookies={"ds_actor": staff_cookie},
    )

    assert response.status_code == 200
    assert "Open Library enrichment is disabled." in response.text
