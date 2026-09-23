"""Unit tests for the JSON configuration store (pg-mcp.config.json)."""

import json
from pathlib import Path

import pytest

from pg_mcp.config.store import (
    config_file_exists,
    load_config_dict,
    load_settings,
    save_config_dict,
)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Provide an isolated config file path."""
    return tmp_path / "pg-mcp.config.json"


class TestLoadConfigDict:
    """Tests for load_config_dict."""

    def test_missing_file_returns_empty(self, config_path: Path) -> None:
        assert load_config_dict(config_path) == {}
        assert not config_file_exists(config_path)

    def test_invalid_json_returns_empty(self, config_path: Path) -> None:
        config_path.write_text("{not json", encoding="utf-8")
        assert load_config_dict(config_path) == {}

    def test_non_object_top_level_returns_empty(self, config_path: Path) -> None:
        config_path.write_text("[]", encoding="utf-8")
        assert load_config_dict(config_path) == {}

    def test_unknown_sections_filtered(self, config_path: Path) -> None:
        config_path.write_text(
            json.dumps({"database": {"host": "h"}, "bogus": {"x": 1}}),
            encoding="utf-8",
        )
        data = load_config_dict(config_path)
        assert data == {"database": {"host": "h"}}


class TestLoadSettings:
    """Tests for load_settings precedence handling."""

    def test_file_values_applied(self, config_path: Path) -> None:
        config_path.write_text(
            json.dumps(
                {
                    "database": {"host": "file-host", "name": "file-db"},
                    "security": {"blocked_tables": ["secrets"]},
                }
            ),
            encoding="utf-8",
        )
        settings = load_settings(config_path)
        assert settings.database.host == "file-host"
        assert settings.database.name == "file-db"
        assert settings.security.blocked_tables == ["secrets"]

    def test_env_overrides_file_section(
        self, config_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)  # isolate from the project's .env
        config_path.write_text(
            json.dumps({"database": {"host": "file-host", "name": "file-db"}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("DATABASE_HOST", "env-host")
        settings = load_settings(config_path)
        # Whole section falls back to env/defaults: name is NOT from the file.
        assert settings.database.host == "env-host"
        assert settings.database.name == "postgres"

    def test_defaults_without_file(
        self, config_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)  # isolate from the project's .env
        settings = load_settings(config_path)
        assert settings.database.host == "localhost"


class TestSaveConfigDict:
    """Tests for save_config_dict."""

    def test_save_and_reload(self, config_path: Path) -> None:
        save_config_dict(
            {"database": {"host": "saved-host"}, "junk": {"a": 1}},
            config_path,
        )
        assert config_file_exists(config_path)
        data = load_config_dict(config_path)
        assert "junk" not in data
        settings = load_settings(config_path)
        assert settings.database.host == "saved-host"
