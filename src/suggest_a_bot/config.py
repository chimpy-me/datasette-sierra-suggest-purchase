"""
Configuration for suggest-a-bot.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = "ollama"  # ollama, llama_cpp, openai, anthropic
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    api_key_env: str | None = None

    def get_api_key(self) -> str | None:
        """Get API key from config or environment."""
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass
class StagesConfig:
    """Enable/disable individual processing stages."""

    catalog_lookup: bool = True
    openlibrary_enrichment: bool = True  # Enrich from Open Library
    consortium_check: bool = False  # Off until we have API access
    input_refinement: bool = False  # Off until LLM is configured
    selection_guidance: bool = False  # Off until LLM is configured
    automatic_actions: bool = False  # Always off by default


@dataclass
class AutoActionsConfig:
    """Configuration for automatic actions."""

    hold_on_consortium_match: bool = False
    decline_on_catalog_exact_match: bool = False
    flag_popular_authors: bool = False


@dataclass
class OpenLibraryConfig:
    """Open Library API configuration."""

    enabled: bool = True
    timeout_seconds: float = 10.0
    max_search_results: int = 5
    run_on_no_catalog_match: bool = True
    run_on_partial_catalog_match: bool = True
    run_on_exact_catalog_match: bool = False


@dataclass
class SierraConfig:
    """Sierra ILS connection configuration."""

    api_base: str = "http://127.0.0.1:9009/iii/sierra-api"
    client_key: str = ""
    client_secret: str = ""
    use_db_direct: bool = False
    db_connection_string_env: str | None = None


@dataclass
class BotConfig:
    """Complete suggest-a-bot configuration."""

    enabled: bool = True
    db_path: Path = field(default_factory=lambda: Path("suggest_purchase.db"))
    schedule: str = "*/15 * * * *"  # Every 15 minutes
    max_requests_per_run: int = 50

    stages: StagesConfig = field(default_factory=StagesConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    auto_actions: AutoActionsConfig = field(default_factory=AutoActionsConfig)
    sierra: SierraConfig = field(default_factory=SierraConfig)
    openlibrary: OpenLibraryConfig = field(default_factory=OpenLibraryConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BotConfig":
        """Create config from a dictionary (e.g., from YAML)."""
        config = cls()

        if "enabled" in data:
            config.enabled = data["enabled"]
        if "db_path" in data:
            config.db_path = Path(data["db_path"])
        if "schedule" in data:
            config.schedule = data["schedule"]
        if "max_requests_per_run" in data:
            config.max_requests_per_run = data["max_requests_per_run"]

        if "stages" in data:
            stages = data["stages"]
            config.stages = StagesConfig(
                catalog_lookup=stages.get("catalog_lookup", True),
                openlibrary_enrichment=stages.get("openlibrary_enrichment", True),
                consortium_check=stages.get("consortium_check", False),
                input_refinement=stages.get("input_refinement", False),
                selection_guidance=stages.get("selection_guidance", False),
                automatic_actions=stages.get("automatic_actions", False),
            )

        if "llm" in data:
            llm = data["llm"]
            config.llm = LLMConfig(
                provider=llm.get("provider", "ollama"),
                model=llm.get("model", "llama3.1:8b"),
                base_url=llm.get("base_url", "http://localhost:11434"),
                api_key=llm.get("api_key"),
                api_key_env=llm.get("api_key_env"),
            )

        if "auto_actions" in data:
            aa = data["auto_actions"]
            config.auto_actions = AutoActionsConfig(
                hold_on_consortium_match=aa.get("hold_on_consortium_match", False),
                decline_on_catalog_exact_match=aa.get("decline_on_catalog_exact_match", False),
                flag_popular_authors=aa.get("flag_popular_authors", False),
            )

        if "sierra" in data:
            sierra = data["sierra"]
            config.sierra = SierraConfig(
                api_base=sierra.get("api_base", config.sierra.api_base),
                client_key=sierra.get("client_key", ""),
                client_secret=sierra.get("client_secret", ""),
                use_db_direct=sierra.get("use_db_direct", False),
                db_connection_string_env=sierra.get("db_connection_string_env"),
            )

        if "openlibrary" in data:
            ol = data["openlibrary"]
            config.openlibrary = OpenLibraryConfig(
                enabled=ol.get("enabled", True),
                timeout_seconds=ol.get("timeout_seconds", 10.0),
                max_search_results=ol.get("max_search_results", 5),
                run_on_no_catalog_match=ol.get("run_on_no_catalog_match", True),
                run_on_partial_catalog_match=ol.get("run_on_partial_catalog_match", True),
                run_on_exact_catalog_match=ol.get("run_on_exact_catalog_match", False),
            )

        return config

    @classmethod
    def from_yaml(cls, path: Path) -> "BotConfig":
        """Load config from a YAML file (datasette.yaml format)."""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Look for bot config under plugins.datasette-suggest-purchase.bot
        plugin_config = data.get("plugins", {}).get("datasette-suggest-purchase", {})
        bot_config = plugin_config.get("bot", {})

        config = cls.from_dict(bot_config)

        # Also pull sierra config from main plugin config if not in bot section
        if "sierra" not in bot_config:
            config.sierra = SierraConfig(
                api_base=plugin_config.get("sierra_api_base", config.sierra.api_base),
                client_key=plugin_config.get("sierra_client_key", ""),
                client_secret=plugin_config.get("sierra_client_secret", ""),
            )

        # And db_path
        if "db_path" not in bot_config:
            config.db_path = Path(plugin_config.get("suggest_db_path", "suggest_purchase.db"))

        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        return {
            "enabled": self.enabled,
            "db_path": str(self.db_path),
            "schedule": self.schedule,
            "max_requests_per_run": self.max_requests_per_run,
            "stages": {
                "catalog_lookup": self.stages.catalog_lookup,
                "openlibrary_enrichment": self.stages.openlibrary_enrichment,
                "consortium_check": self.stages.consortium_check,
                "input_refinement": self.stages.input_refinement,
                "selection_guidance": self.stages.selection_guidance,
                "automatic_actions": self.stages.automatic_actions,
            },
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "base_url": self.llm.base_url,
            },
            "openlibrary": {
                "enabled": self.openlibrary.enabled,
                "timeout_seconds": self.openlibrary.timeout_seconds,
                "max_search_results": self.openlibrary.max_search_results,
            },
        }
