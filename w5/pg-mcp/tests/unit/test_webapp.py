"""Unit tests for the FastAPI web layer (AC7 server-side contracts).

The shared MCP lifespan is not started here; app.state is injected with
fakes so the endpoints' request/response contracts can be tested in
isolation. Real end-to-end verification happens against live databases.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pg_mcp.config.settings import DatabaseConfig, OpenAIConfig, Settings
from pg_mcp.models.query import QueryResponse
from pg_mcp.webapp.app import create_app


@pytest.fixture
def client():
    """TestClient with fake settings/orchestrator injected (no lifespan)."""
    app = create_app()
    settings = Settings(
        database=DatabaseConfig(host="h", name="pg_db", password="secret", _env_file=None),
        openai=OpenAIConfig(api_key=SecretStr("sk-test-1234"), _env_file=None),
        _env_file=None,
    )
    settings.databases = {}
    orchestrator = MagicMock()
    orchestrator.execute_query = AsyncMock(
        return_value=QueryResponse(success=True, generated_sql="SELECT 1", confidence=95)
    )

    app.state.settings = lambda: settings
    app.state.orchestrator = lambda: orchestrator
    # Not using `with` intentionally: entering the client context would run
    # the shared MCP lifespan and connect to real databases.
    yield TestClient(app), orchestrator


def test_query_endpoint_returns_to_dict(client):
    c, orchestrator = client
    res = c.post("/api/query", json={"question": "how many users?", "database": "pg_db"})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["generated_sql"] == "SELECT 1"
    assert body["tokens_used"] == 0  # single to_dict contract
    orchestrator.execute_query.assert_awaited_once()


def test_query_endpoint_rejects_bad_return_type(client):
    c, _ = client
    res = c.post("/api/query", json={"question": "q", "return_type": "bogus"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_PARAMETER"


def test_databases_endpoint_lists_primary(client):
    c, _ = client
    res = c.get("/api/databases")
    assert res.status_code == 200
    assert res.json()["databases"][0]["name"] == "pg_db"


def test_settings_masks_api_keys(client):
    c, _ = client
    res = c.get("/api/settings")
    assert res.status_code == 200
    assert res.json()["database"]["password"] == "***"
