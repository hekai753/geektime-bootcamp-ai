"""Unit tests for MySQL support and multi-database routing (AC1).

All driver interactions are mocked; real-database verification happens in
the end-to-end deployment check.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pg_mcp.config.settings import (
    DatabaseConfig,
    ResilienceConfig,
    SecurityConfig,
    ValidationConfig,
)
from pg_mcp.db.driver import (
    MySqlSchemaIntrospector,
    create_executor_for,
    create_introspector_for,
)
from pg_mcp.models.query import QueryRequest, ResultValidationResult, ReturnType
from pg_mcp.services.mysql_executor import MySqlSQLExecutor
from pg_mcp.services.orchestrator import QueryOrchestrator
from pg_mcp.services.sql_executor import SQLExecutor
from pg_mcp.services.sql_validator import SQLValidator


def _mysql_config() -> DatabaseConfig:
    return DatabaseConfig(
        db_type="mysql",
        host="m",
        port=3306,
        name="db",
        user="u",
        password="p",
        _env_file=None,
    )


class TestDriverFactories:
    """Tests for dialect dispatch."""

    def test_executor_factory_returns_mysql_executor(self) -> None:
        executor = create_executor_for(MagicMock(), _mysql_config(), SecurityConfig())
        assert isinstance(executor, MySqlSQLExecutor)

    def test_executor_factory_returns_pg_executor(self) -> None:
        cfg = DatabaseConfig(_env_file=None)
        executor = create_executor_for(MagicMock(), cfg, SecurityConfig())
        assert type(executor) is SQLExecutor

    def test_introspector_factory_dispatch(self) -> None:
        mysql_cfg = _mysql_config()
        assert isinstance(
            create_introspector_for(MagicMock(), "db", mysql_cfg),
            MySqlSchemaIntrospector,
        )
        from pg_mcp.db.introspection import SchemaIntrospector

        pg_cfg = DatabaseConfig(_env_file=None)
        assert type(create_introspector_for(MagicMock(), "db", pg_cfg)) is SchemaIntrospector


class TestMySqlValidatorDialect:
    """SQL validation must respect the configured dialect (AC1)."""

    def test_backtick_identifiers_valid_for_mysql(self) -> None:
        validator = SQLValidator(config=SecurityConfig(), dialect="mysql")
        ok, err = validator.validate("SELECT `id`, `name` FROM `users` WHERE `id` = 1")
        assert ok, err

    def test_pg_cast_still_valid_for_postgres(self) -> None:
        validator = SQLValidator(config=SecurityConfig(), dialect="postgres")
        ok, err = validator.validate("SELECT id::text FROM users")
        assert ok, err


class _FakeCursor:
    """Minimal aiomysql DictCursor double driven by canned result sets."""

    def __init__(self, results: list[list[dict]]) -> None:
        self._results = list(results)
        self.queries: list[str] = []

    async def execute(self, query: str, args: Any = None) -> None:
        self.queries.append(query)

    async def fetchall(self) -> list[dict]:
        return self._results.pop(0) if self._results else []

    async def close(self) -> None:
        pass


class TestMySqlSchemaIntrospector:
    """Tests for information_schema-driven introspection."""

    @pytest.mark.asyncio
    async def test_introspect_builds_schema(self) -> None:
        tables_page = [{"TABLE_NAME": "users", "TABLE_COMMENT": "Blog users", "TABLE_ROWS": 8}]
        columns_page = [
            {
                "COLUMN_NAME": "id",
                "DATA_TYPE": "int",
                "IS_NULLABLE": "NO",
                "COLUMN_KEY": "PRI",
                "COLUMN_COMMENT": "",
            },
            {
                "COLUMN_NAME": "username",
                "DATA_TYPE": "varchar",
                "CHARACTER_MAXIMUM_LENGTH": 50,
                "IS_NULLABLE": "NO",
                "COLUMN_KEY": "",
            },
        ]
        version_page = [{"v": "8.0.36"}]

        cursor = _FakeCursor([tables_page, columns_page, version_page])
        conn = MagicMock()
        conn.cursor = AsyncMock(return_value=cursor)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMockContext(conn))

        introspector = MySqlSchemaIntrospector(pool, "blog_small")
        schema = await introspector.introspect()

        assert schema.database_name == "blog_small"
        assert len(schema.tables) == 1
        table = schema.tables[0]
        assert table.table_name == "users"
        assert table.comment == "Blog users"
        assert table.columns[0].is_primary_key is True
        assert table.columns[1].data_type == "varchar(50)"


class AsyncMockContext:
    """Async context manager returning a fixed object."""

    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        return self._value

    async def __aexit__(self, *exc: Any) -> None:
        return None


class TestMySqlExecutor:
    """Tests for the aiomysql-backed executor."""

    @pytest.mark.asyncio
    async def test_execute_returns_serialized_rows(self) -> None:
        cursor = _FakeCursor([])
        conn = MagicMock()

        async def _cursor(_cursor_class=None):
            return cursor

        conn.cursor = _cursor
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMockContext(conn))

        executor = MySqlSQLExecutor(pool, SecurityConfig(), _mysql_config())
        # Drive execute with a canned fetchall sequence
        cursor._results = [[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]]

        results, total = await executor.execute("SELECT id, name FROM users")
        assert total == 2
        assert results[0]["name"] == "a"


class TestMultiDatabaseRouting:
    """The orchestrator must route by the request database field (AC1)."""

    def _orchestrator(self) -> tuple[QueryOrchestrator, MagicMock, MagicMock]:
        pg_executor, mysql_executor = MagicMock(), MagicMock()
        pg_executor.execute = AsyncMock(return_value=([{"db": "pg"}], 1))
        mysql_executor.execute = AsyncMock(return_value=([{"db": "mysql"}], 1))

        generator = MagicMock()
        generator.generate = AsyncMock(return_value="SELECT 1")
        validator = MagicMock()
        validator.validate_or_raise = MagicMock(return_value=None)
        schema_cache = MagicMock()
        schema_cache.get = MagicMock(return_value=MagicMock(tables=[]))
        result_validator = MagicMock()
        result_validator.validate = AsyncMock(
            return_value=ResultValidationResult(confidence=90, explanation="ok", is_acceptable=True)
        )

        orchestrator = QueryOrchestrator(
            sql_generator=generator,
            sql_validator=validator,
            sql_executor=pg_executor,
            result_validator=result_validator,
            schema_cache=schema_cache,
            pools={"pg_db": MagicMock(), "mysql_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=False),
            sql_executors={"mysql_db": mysql_executor},
        )
        return orchestrator, pg_executor, mysql_executor

    @pytest.mark.asyncio
    async def test_request_routes_to_mysql_executor(self) -> None:
        orchestrator, _, mysql_executor = self._orchestrator()
        response = await orchestrator.execute_query(QueryRequest(question="q", database="mysql_db"))
        assert response.success is True
        assert response.data.rows == [{"db": "mysql"}]
        mysql_executor.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_request_routes_to_default_executor(self) -> None:
        orchestrator, pg_executor, _ = self._orchestrator()
        response = await orchestrator.execute_query(QueryRequest(question="q", database="pg_db"))
        assert response.success is True
        assert response.data.rows == [{"db": "pg"}]
        pg_executor.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_database_rejected(self) -> None:
        orchestrator, _, _ = self._orchestrator()
        response = await orchestrator.execute_query(QueryRequest(question="q", database="nope"))
        assert response.success is False
        assert "not found" in response.error.message.lower()

    @pytest.mark.asyncio
    async def test_sql_only_mode_skips_execution(self) -> None:
        orchestrator, pg_executor, mysql_executor = self._orchestrator()
        response = await orchestrator.execute_query(
            QueryRequest(question="q", database="mysql_db", return_type=ReturnType.SQL)
        )
        assert response.success is True
        assert response.data is None
        pg_executor.execute.assert_not_awaited()
        mysql_executor.execute.assert_not_awaited()
