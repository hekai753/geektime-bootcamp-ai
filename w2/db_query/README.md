# Database Query Tool

A web-based database workbench for managing connections, exploring schema metadata, and
running read-only SQL queries — with a **natural-language → SQL** feature powered by OpenAI.

> Inspired by tools like MotherDuck / DBeaver, this project is a full-stack teaching
> reference: a layered **FastAPI** backend (adapter pattern) paired with a **Refine +
> Ant Design** frontend, showing how to bring AI (NL2SQL) into a developer tool.

## ✨ Features

- **Multi-database connections** — register PostgreSQL and MySQL datasources; the type is
  auto-detected from the connection URL and validated with a live test before saving.
- **Schema exploration** — browse tables, views, and columns from a metadata tree.
  Metadata is cached in the app DB and can be force-refreshed.
- **Read-only SQL execution** — run `SELECT` statements safely. A `sqlglot`-backed
  validator rejects any statement that is not a read-only query.
- **Natural language → SQL** — describe what you want in English or Chinese; OpenAI
  generates an editable SQL query using your live schema as context.
- **Result export** — download query results as CSV (RFC 4180) or pretty-printed JSON,
  with a confirmation modal for datasets larger than 10,000 rows.
- **Query history** — every executed query is recorded with timing, row count, status,
  and source (manual / natural-language).

## 🧱 Tech Stack

| Layer      | Technologies |
|------------|-------------|
| Backend    | FastAPI · SQLModel · Alembic · sqlglot · OpenAI SDK · asyncpg / PyMySQL · uv |
| Frontend   | React · TypeScript · Refine 5 · Ant Design · Vite · Axios |
| App DB     | SQLite (`~/.db_query/db_query.db`) — stores connections, metadata cache, query history |

## 🏛 Architecture

A three-column web UI talking to a layered backend:

```
┌──────────────────────────────────────┐
│  Browser — React + Refine UI         │
└─────────────────┬────────────────────┘
                  │  HTTP / JSON  (/api/v1/dbs/*)
                  ▼
┌──────────────────────────────────────┐
│  API Layer — FastAPI routes          │   thin transport + validation
└─────────────────┬────────────────────┘
                  ▼
┌──────────────────────────────────────┐
│  Service Layer (Facade)              │   orchestrates: SQL validation,
│  DatabaseService · NL2SQL · Metadata │   execution, metadata, history
└─────────────────┬────────────────────┘
                  ▼
┌──────────────────────────────────────┐
│  Adapter Layer — Adapter + Registry  │   DatabaseAdapter ABC + per-DB impls
└────────┬────────────────────┬────────┘
         ▼                    ▼
   ┌────────────┐       ┌────────────┐
   │ PostgreSQL │       │   MySQL    │   ← add one file to support a new DB
   └────────────┘       └────────────┘
```

The adapter + registry design means new databases can be added **without modifying
existing code**. See [`docs/ARCHITECTURE_REDESIGN.md`](docs/ARCHITECTURE_REDESIGN.md).

## 📁 Project Structure

```
w2/db_query/
├── backend/                FastAPI service (Python 3.12+)
│   ├── app/
│   │   ├── api/v1/         # databases.py, queries.py
│   │   ├── adapters/       # base, registry, postgresql, mysql
│   │   ├── services/       # database_service, nl2sql, sql_validator, query_wrapper, metadata
│   │   ├── models/         # SQLModel tables + Pydantic schemas
│   │   ├── config.py       # pydantic-settings (env)
│   │   └── main.py         # FastAPI app entry
│   ├── alembic/            # DB migrations for the app DB
│   └── pyproject.toml
├── frontend/               React + TypeScript (Refine 5, Vite)
│   └── src/{pages,components,services,types,styles}
├── docs/                   architecture & design docs
├── fixtures/               REST Client (.rest) test files
├── Makefile                dev commands
└── PHASE3_IMPLEMENTATION.md
```

## 🚀 Quick Start

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 18+ (LTS) and npm
- An OpenAI API key (only required for the NL → SQL feature)
- A PostgreSQL or MySQL database to query (optional for exploring the UI)

### Setup

```bash
# 1. Install all dependencies
make install

# 2. Apply app-DB migrations
make setup
#    → then copy backend/.env.example to backend/.env and set:
#         OPENAI_API_KEY=sk-...

# 3. Start both dev servers
make dev
```

Then open:
- **Frontend** → http://localhost:5173
- **Backend API docs** (Swagger) → http://localhost:8000/docs

## 🔌 API Reference

All routes are prefixed with `/api/v1/dbs`. Responses use camelCase keys.

### Databases
| Method & Path | Description |
|---------------|-------------|
| `GET    /api/v1/dbs` | List saved connections |
| `PUT    /api/v1/dbs/{name}` | Create or update a connection (tests it first; auto-detects type from URL) |
| `GET    /api/v1/dbs/{name}` | Fetch schema metadata (tables, views, columns) — cached, with `isStale` flag |
| `POST   /api/v1/dbs/{name}/refresh` | Force-refresh the metadata cache |
| `DELETE /api/v1/dbs/{name}` | Delete a connection |

### Queries
| Method & Path | Description |
|---------------|-------------|
| `POST /api/v1/dbs/{name}/query` | Execute a read-only SQL statement |
| `POST /api/v1/dbs/{name}/query/natural` | Convert natural language → SQL (returns `sql` + `explanation`) |
| `GET  /api/v1/dbs/{name}/history` | Query execution history (default `limit=50`) |

Plus `GET /health`.

**Example — run a query**
```http
POST /api/v1/dbs/my-shop/query
Content-Type: application/json

{ "sql": "SELECT id, email FROM users LIMIT 10" }
```

**Example — natural language**
```http
POST /api/v1/dbs/my-shop/query/natural
Content-Type: application/json

{ "prompt": "查询最近 7 天注册的用户" }
```

## ⚙️ Configuration

Environment is read from `backend/.env` (copy from `backend/.env.example`):

| Variable             | Default       | Purpose |
|----------------------|---------------|---------|
| `OPENAI_API_KEY`     | —             | Required for NL → SQL |
| `DB_QUERY_DATA_DIR`  | `~/.db_query` | Directory for the app SQLite DB |
| `LOG_LEVEL`          | `INFO`        | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CORS_ORIGINS`       | `*`           | Comma-separated allowed origins |

## 🛠 Development

```bash
make help                        # list all commands
make dev                         # backend + frontend together
make test                        # pytest + frontend tests
make lint                        # ruff + frontend lint
make format                      # ruff format + frontend --fix
make backend-check               # mypy + ruff on the backend
make db-migrate MESSAGE="add x"  # generate an Alembic migration
make db-upgrade                  # apply migrations
make health                      # probe the backend
make docs                        # open Swagger UI
```

### API testing (VSCode)
Install the [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client)
extension, open `fixtures/test.rest`, and click *Send Request* above any block.
See `fixtures/README.md` for the full guide.

## ➕ Adding a New Database Type

Thanks to the adapter + registry, adding a database requires **no changes to existing code**:

1. Implement `DatabaseAdapter` (from `app/adapters/base.py`) in a new file under `app/adapters/`.
2. Register it in `app/adapters/registry.py` and add the value to the `DatabaseType` enum.
3. Done — metadata, query, and NL2SQL all work automatically.

See [`docs/MYSQL_SUPPORT.md`](docs/MYSQL_SUPPORT.md) for a worked example.

## 📚 Further Documentation

- `docs/ARCHITECTURE_REDESIGN.md` — adapter redesign rationale (SOLID, before/after)
- `docs/ARCHITECTURE_SUMMARY.md` · `docs/CLASS_DIAGRAM.md` · `docs/ARCHITECTURE_INDEX.md`
- `docs/MYSQL_SUPPORT.md` — MySQL adapter notes
- `docs/QUICK_REFERENCE.md` — command cheat-sheet
- `PHASE3_IMPLEMENTATION.md` — NL query + export feature notes
