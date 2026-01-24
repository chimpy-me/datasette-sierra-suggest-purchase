"""Smoke tests for plugin configuration loading.

These tests verify that plugin config is correctly loaded via Datasette's
plugin_config() API, catching mis-keyed plugin config that might pass
other tests but fail in real deployments.
"""

import pytest
from datasette.app import Datasette


class TestPluginConfigLoading:
    """Tests for plugin configuration via datasette.plugin_config()."""

    @pytest.mark.asyncio
    async def test_plugin_config_is_loaded(self, db_path):
        """Plugin config should be readable via datasette.plugin_config()."""
        ds = Datasette(
            [str(db_path)],
            config={
                "plugins": {
                    "datasette-suggest-purchase": {
                        "sierra_api_base": "http://test-sierra/api",
                        "sierra_client_key": "test_key_value",
                        "sierra_client_secret": "test_secret_value",
                        "suggest_db_path": str(db_path),
                    }
                }
            },
        )

        config = ds.plugin_config("datasette-suggest-purchase")

        assert config is not None, "Plugin config should not be None"
        assert config["sierra_api_base"] == "http://test-sierra/api"
        assert config["sierra_client_key"] == "test_key_value"
        assert config["sierra_client_secret"] == "test_secret_value"

    @pytest.mark.asyncio
    async def test_plugin_config_wrong_key_returns_none(self, db_path):
        """Mis-keyed plugin config should return None."""
        ds = Datasette(
            [str(db_path)],
            config={
                "plugins": {
                    # Deliberately wrong key (underscore instead of hyphen)
                    "datasette_suggest_purchase": {
                        "sierra_api_base": "http://test-sierra/api",
                    }
                }
            },
        )

        # The correct key should return None when config uses wrong key
        config = ds.plugin_config("datasette-suggest-purchase")
        assert config is None, "Wrong plugin key should result in None config"

    @pytest.mark.asyncio
    async def test_plugin_config_missing_returns_none(self, db_path):
        """Missing plugin config should return None."""
        ds = Datasette([str(db_path)], config={})

        config = ds.plugin_config("datasette-suggest-purchase")
        assert config is None, "Missing plugin config should return None"

    @pytest.mark.asyncio
    async def test_plugin_config_partial_values(self, db_path):
        """Partial plugin config should be readable."""
        ds = Datasette(
            [str(db_path)],
            config={
                "plugins": {
                    "datasette-suggest-purchase": {
                        "sierra_api_base": "http://partial-config/api",
                        # Other keys intentionally omitted
                    }
                }
            },
        )

        config = ds.plugin_config("datasette-suggest-purchase")

        assert config is not None
        assert config["sierra_api_base"] == "http://partial-config/api"
        assert config.get("sierra_client_key") is None
