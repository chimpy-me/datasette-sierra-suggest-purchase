"""Tests for suggest-a-bot configuration."""

import tempfile
from pathlib import Path

from suggest_a_bot.config import BotConfig, LLMConfig


class TestBotConfig:
    """Test configuration loading and parsing."""

    def test_default_config(self):
        """Default config should have sensible values."""
        config = BotConfig()

        assert config.enabled is True
        assert config.max_requests_per_run == 50
        assert config.stages.catalog_lookup is True
        assert config.stages.consortium_check is False  # Off by default
        assert config.stages.automatic_actions is False  # Always off by default
        assert config.llm.provider == "ollama"

    def test_from_dict(self):
        """Should parse config from dictionary."""
        data = {
            "enabled": True,
            "max_requests_per_run": 100,
            "stages": {
                "catalog_lookup": True,
                "consortium_check": True,
                "input_refinement": False,
            },
            "llm": {
                "provider": "openai",
                "model": "gpt-4",
            },
        }

        config = BotConfig.from_dict(data)

        assert config.max_requests_per_run == 100
        assert config.stages.consortium_check is True
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4"

    def test_from_yaml(self):
        """Should load config from YAML file."""
        yaml_content = """
plugins:
  datasette-suggest-purchase:
    sierra_api_base: "http://localhost:9009/iii/sierra-api"
    suggest_db_path: "test.db"
    bot:
      enabled: true
      max_requests_per_run: 25
      stages:
        catalog_lookup: true
        consortium_check: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            yaml_path = Path(f.name)

        try:
            config = BotConfig.from_yaml(yaml_path)

            assert config.enabled is True
            assert config.max_requests_per_run == 25
            assert config.stages.catalog_lookup is True
            assert config.stages.consortium_check is True
            assert config.db_path == Path("test.db")
            assert "localhost:9009" in config.sierra.api_base
        finally:
            yaml_path.unlink()

    def test_from_yaml_missing_file(self):
        """Should return defaults for missing file."""
        config = BotConfig.from_yaml(Path("/nonexistent/config.yaml"))

        assert config.enabled is True  # Default
        assert config.max_requests_per_run == 50  # Default

    def test_to_dict(self):
        """Should serialize config to dictionary."""
        config = BotConfig()
        config.max_requests_per_run = 75

        data = config.to_dict()

        assert data["max_requests_per_run"] == 75
        assert "stages" in data
        assert "llm" in data

    def test_sierra_config_inheritance(self):
        """Bot should inherit Sierra config from main plugin config."""
        yaml_content = """
plugins:
  datasette-suggest-purchase:
    sierra_api_base: "https://sierra.example.org/iii/sierra-api"
    sierra_client_key: "mykey"
    sierra_client_secret: "mysecret"
    suggest_db_path: "suggest.db"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            yaml_path = Path(f.name)

        try:
            config = BotConfig.from_yaml(yaml_path)

            assert config.sierra.api_base == "https://sierra.example.org/iii/sierra-api"
            assert config.sierra.client_key == "mykey"
            assert config.sierra.client_secret == "mysecret"
        finally:
            yaml_path.unlink()


class TestLLMConfig:
    """Test LLM configuration."""

    def test_get_api_key_from_config(self):
        """Should return API key from config."""
        config = LLMConfig(api_key="direct_key")
        assert config.get_api_key() == "direct_key"

    def test_get_api_key_from_env(self, monkeypatch):
        """Should read API key from environment variable."""
        monkeypatch.setenv("TEST_API_KEY", "env_key")
        config = LLMConfig(api_key_env="TEST_API_KEY")
        assert config.get_api_key() == "env_key"

    def test_get_api_key_prefers_direct(self):
        """Direct API key should take precedence over env var."""
        config = LLMConfig(api_key="direct", api_key_env="TEST_KEY")
        assert config.get_api_key() == "direct"

    def test_get_api_key_none(self):
        """Should return None if no key configured."""
        config = LLMConfig()
        assert config.get_api_key() is None
