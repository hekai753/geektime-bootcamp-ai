"""Persistent JSON configuration store for pg-mcp.

Settings are resolved with the priority:

    environment variables  >  pg-mcp.config.json  >  built-in defaults

The JSON file lets users configure the server visually through the Web UI
(or by hand) without exporting environment variables or editing MCP client
config files. Environment variables still win so that container/CI setups
keep working unchanged.

Precedence is applied per top-level section (``database``, ``openai``,
``security``, ``validation``, ``cache``, ``resilience``, ``observability``):
if any environment variable with the section's prefix (e.g. ``DATABASE_``)
is present, the environment wins for that whole section.

Example file::

    {
      "database": {
        "db_type": "postgres",
        "host": "localhost",
        "port": 5432,
        "name": "blog_small",
        "user": "postgres",
        "password": "secret"
      },
      "llm": {"provider": "anthropic", "api_key": "..."}
    }
"""

import json
from pathlib import Path

from pg_mcp.config.settings import Settings, reset_settings
from pg_mcp.observability.logging import get_logger

logger = get_logger(__name__)

#: Sections of :class:`Settings` that may appear in the JSON file and the
#: environment-variable prefix that overrides each of them.
SECTION_ENV_PREFIXES: dict[str, tuple[str, ...]] = {
    "database": ("DATABASE_",),
    "openai": ("OPENAI_",),
    "anthropic": ("ANTHROPIC_",),
    "llm": ("LLM_",),
    "security": ("SECURITY_",),
    "validation": ("VALIDATION_",),
    "cache": ("CACHE_",),
    "resilience": ("RESILIENCE_",),
    "observability": ("OBSERVABILITY_",),
}

DEFAULT_CONFIG_PATH = Path("pg-mcp.config.json")


def config_file_exists(path: Path | str | None = None) -> bool:
    """Return True if the JSON config file exists.

    Args:
        path: Optional explicit config file path.

    Returns:
        bool: True when the file exists.
    """
    return _resolve_path(path).exists()


def _resolve_path(path: Path | str | None) -> Path:
    """Resolve the config file path (default: ./pg-mcp.config.json)."""
    return Path(path) if path else DEFAULT_CONFIG_PATH


def load_config_dict(path: Path | str | None = None) -> dict[str, dict]:
    """Load the raw section dict from the JSON config file.

    Args:
        path: Optional explicit config file path.

    Returns:
        dict: Mapping of section name to section dict (possibly empty).
    """
    file_path = _resolve_path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Ignoring unreadable config file {file_path}: {e}")
        return {}
    if not isinstance(data, dict):
        logger.warning(f"Ignoring config file {file_path}: top level must be an object")
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and k in SECTION_ENV_PREFIXES}


def _section_overridden_by_env(section: str) -> bool:
    """Check whether any env var for the section's prefix is set."""
    import os

    prefixes = SECTION_ENV_PREFIXES[section]
    return any(key.startswith(prefix) for key in os.environ for prefix in prefixes)


def load_settings(path: Path | str | None = None) -> Settings:
    """Build a Settings instance with priority env > config file > defaults.

    Args:
        path: Optional explicit config file path.

    Returns:
        Settings: Resolved settings object.
    """
    file_data = load_config_dict(path)
    kwargs: dict[str, dict] = {}
    for section, values in file_data.items():
        # Environment variables override the whole section when present.
        if _section_overridden_by_env(section):
            logger.debug(f"Config section '{section}' overridden by environment variables")
            continue
        kwargs[section] = values
    return Settings(**kwargs)


def save_config_dict(
    sections: dict[str, dict],
    path: Path | str | None = None,
) -> None:
    """Persist sections to the JSON config file (full replacement).

    Args:
        sections: Mapping of section name to section dict.
        path: Optional explicit config file path.
    """
    file_path = _resolve_path(path)
    clean: dict[str, dict] = {}
    for name, values in sections.items():
        if name not in SECTION_ENV_PREFIXES:
            continue
        if not isinstance(values, dict):
            continue
        clean[name] = values
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reset_settings()
    logger.info(f"Configuration saved to {file_path}")
