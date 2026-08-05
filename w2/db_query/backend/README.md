# db-query-backend

Database Query Tool Backend API — a FastAPI service that exposes natural-language
and SQL query endpoints over configurable PostgreSQL/MySQL datasources, backed by
SQLModel + Alembic.

## Develop

```bash
uv sync --extra dev          # install runtime + dev deps
uv run alembic upgrade head  # apply migrations
uv run uvicorn app.main:app --reload
```

See `.env.example` for required configuration.
