"""Shared pytest fixtures for suggest-a-purchase tests."""

import pytest
from datasette.app import Datasette

from datasette_suggest_purchase.migrations import run_migrations


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with full schema via migrations.

    This is the canonical way to get a test database - uses the same
    migration system as production.
    """
    db_file = tmp_path / "test_suggest.db"
    run_migrations(db_file, verbose=False)
    return db_file


@pytest.fixture
def datasette(db_path):
    """Create a Datasette instance with the plugin configured.

    Uses config= (not metadata=) for Datasette v1 compatibility.
    Includes database permissions (staff-only access to tables).
    """
    db_name = db_path.stem

    return Datasette(
        [str(db_path)],
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
                    "sierra_api_base": "http://fake-sierra:9009/iii/sierra-api",
                    "sierra_client_key": "test_key",
                    "sierra_client_secret": "test_secret",
                    "suggest_db_path": str(db_path),
                }
            },
        },
    )
