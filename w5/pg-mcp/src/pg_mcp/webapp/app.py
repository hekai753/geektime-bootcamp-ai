"""FastAPI web application exposing the pg-mcp query pipeline over HTTP.

Shares the exact component wiring with the MCP stdio server by entering its
lifespan context, then serving:

- ``GET  /``              static chat UI
- ``POST /api/query``     natural language query (same payload as the MCP tool)
- ``GET  /api/databases`` configured databases with engine types
- ``GET  /api/settings``  effective configuration (secrets masked)
- ``PUT  /api/settings``  persist configuration and hot-reload components
- ``GET  /metrics``       Prometheus exposition

Run with ``uv run python -m pg_mcp.webapp``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from pg_mcp.config import store
from pg_mcp.config.settings import Settings
from pg_mcp.observability.logging import get_logger
from pg_mcp.server import lifespan as mcp_lifespan
from pg_mcp.server import mcp
from pg_mcp.services.orchestrator import QueryOrchestrator

logger = get_logger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

#: Secret fields that must never be returned in full by /api/settings.
_SECRET_FIELDS = {("openai", "api_key"), ("anthropic", "api_key")}


class QueryPayload(BaseModel):
    """Request body for /api/query."""

    question: str = Field(..., min_length=1)
    database: str | None = None
    return_type: str = "result"


def _mask_secrets(section: dict[str, Any]) -> dict[str, Any]:
    """Mask api_key-like values for safe display."""
    masked = dict(section)
    for key, value in masked.items():
        if "api_key" in key and isinstance(value, str) and value:
            masked[key] = f"***{value[-4:]}" if len(value) > 4 else "***"
    return masked


def _settings_to_dict(settings: Settings) -> dict[str, dict[str, Any]]:
    """Serialize the effective settings into section dicts (secrets masked)."""
    data: dict[str, dict[str, Any]] = {
        "database": settings.database.model_dump(mode="json"),
        "databases": {
            name: cfg.model_dump(mode="json") for name, cfg in settings.databases.items()
        },
        "openai": settings.openai.model_dump(mode="json"),
        "anthropic": settings.anthropic.model_dump(mode="json"),
        "llm": settings.llm.model_dump(mode="json"),
        "security": settings.security.model_dump(mode="json"),
        "validation": settings.validation.model_dump(mode="json"),
        "resilience": settings.resilience.model_dump(mode="json"),
    }
    for openai_or_anthropic in ("openai", "anthropic"):
        data[openai_or_anthropic] = _mask_secrets(data[openai_or_anthropic])
    # SecretStr fields serialize as strings once dumped; mask database passwords too
    data["database"]["password"] = "***" if data["database"].get("password") else ""
    data["databases"] = {
        name: {**cfg, "password": "***" if cfg.get("password") else ""}
        for name, cfg in data["databases"].items()
    }
    return data


def create_app() -> FastAPI:
    """Create the FastAPI app bound to the shared MCP component lifecycle."""

    @asynccontextmanager
    async def web_lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Keep the raw context manager around so /api/settings can exit and
        # re-enter it to hot-reload components after configuration changes.
        ctx = mcp_lifespan(mcp)
        app.state._lifespan_ctx = ctx
        async with ctx:
            from pg_mcp import server

            app.state.settings = lambda: server._settings
            app.state.orchestrator = lambda: server._orchestrator
            logger.info("Web UI ready (http interface sharing MCP components)")
            yield

    app = FastAPI(
        title="pg-mcp", description="Natural language database queries", lifespan=web_lifespan
    )

    def _require_orchestrator(request: Request) -> QueryOrchestrator:
        orchestrator = request.app.state.orchestrator()
        if orchestrator is None:
            raise RuntimeError("Server components are not initialized")
        return orchestrator

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.post("/api/query")
    async def api_query(payload: QueryPayload, request: Request) -> JSONResponse:
        if payload.return_type not in ("sql", "result"):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": "INVALID_PARAMETER",
                        "message": (
                            f"Invalid return_type: '{payload.return_type}'."
                            " Must be 'sql' or 'result'."
                        ),
                    },
                },
            )
        orchestrator = _require_orchestrator(request)
        from pg_mcp.models.query import QueryRequest, ReturnType

        query_request = QueryRequest(
            question=payload.question,
            database=payload.database,
            return_type=ReturnType(payload.return_type),
        )
        response = await orchestrator.execute_query(query_request)
        return JSONResponse(content=response.to_dict())

    @app.get("/api/databases")
    async def api_databases(request: Request) -> JSONResponse:
        settings: Settings | None = request.app.state.settings()
        if settings is None:
            return JSONResponse(status_code=503, content={"error": "not initialized"})
        databases = [{"name": settings.database.name, "db_type": settings.database.db_type}]
        databases += [
            {"name": name, "db_type": cfg.db_type} for name, cfg in settings.databases.items()
        ]
        return JSONResponse(content={"databases": databases})

    @app.get("/api/settings")
    async def api_get_settings(request: Request) -> JSONResponse:
        settings: Settings | None = request.app.state.settings()
        if settings is None:
            return JSONResponse(status_code=503, content={"error": "not initialized"})
        return JSONResponse(content=_settings_to_dict(settings))

    @app.put("/api/settings")
    async def api_put_settings(request: Request) -> JSONResponse:
        body: dict[str, Any] = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"error": "body must be a JSON object"})

        # Merge with the existing file so masked passwords/keys are preserved.
        existing = store.load_config_dict()

        def _merge(
            section: str, incoming: dict[str, Any], current: dict[str, Any]
        ) -> dict[str, Any]:
            merged = dict(current)
            for key, value in incoming.items():
                is_secret = "password" in key or "api_key" in key
                keep_secret = is_secret and (
                    not isinstance(value, str)
                    or value.strip() in ("", "***")
                    or value.startswith("***")
                )
                if not keep_secret:
                    merged[key] = value
            return merged

        new_file: dict[str, dict[str, Any]] = {}
        for section, values in body.items():
            if section not in store.SECTION_ENV_PREFIXES or not isinstance(values, dict):
                continue
            if section == "databases":
                # Map of alias -> DatabaseConfig dict
                existing_dbs = existing.get("databases", {})
                new_file[section] = {
                    alias: _merge(alias, db_values, existing_dbs.get(alias, {}))
                    for alias, db_values in values.items()
                    if isinstance(db_values, dict)
                }
            else:
                new_file[section] = _merge(section, values, existing.get(section, {}))

        store.save_config_dict(new_file)

        # Hot-reload components by exiting the current lifespan and entering
        # a fresh one (asynccontextmanager instances are single-use).
        try:
            old_ctx = request.app.state._lifespan_ctx
            await old_ctx.__aexit__(None, None, None)
            new_ctx = mcp_lifespan(mcp)
            request.app.state._lifespan_ctx = new_ctx
            await new_ctx.__aenter__()
        except Exception as e:
            logger.error(f"Component reload failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Settings saved, but reload failed: {e}"},
            )
        settings: Settings | None = request.app.state.settings()
        return JSONResponse(content={"status": "saved", "settings": _settings_to_dict(settings)})

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        from prometheus_client import generate_latest

        return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain")

    return app


app = create_app()


def main() -> None:
    """Run the web UI server."""
    import uvicorn

    from pg_mcp.config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - demo UI is intended for LAN access
        port=8000,
        log_level=settings.observability.log_level.lower(),
    )


if __name__ == "__main__":
    main()
