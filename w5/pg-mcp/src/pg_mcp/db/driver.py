"""Database driver selection for PostgreSQL and MySQL.

The dialect-specific pieces live in sibling modules:

- pools: :mod:`pg_mcp.db.pool` (PostgreSQL/asyncpg) and this module's
  :func:`create_mysql_pool` (MySQL/aiomysql)
- introspection: :class:`pg_mcp.db.introspection.SchemaIntrospector` (PG) and
  :class:`MySqlSchemaIntrospector` (MySQL/information_schema)

The factories here pick the right implementation from ``DatabaseConfig``,
so the layers above (cache, orchestrator, server bootstrap) stay
dialect-agnostic.
"""

from typing import Any

from pg_mcp.config.settings import DatabaseConfig
from pg_mcp.db.introspection import SchemaIntrospector


def _pick(row: dict[str, Any], *names: str) -> Any:
    """Return the first non-empty value among case variants of a column name."""
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def sqlglot_dialect(config: DatabaseConfig) -> str:
    """Map a database config to its sqlglot dialect name.

    Args:
        config: Database configuration.

    Returns:
        str: "mysql" or "postgres".
    """
    return config.sqlglot_dialect


async def create_mysql_pool(config: DatabaseConfig) -> Any:
    """Create an aiomysql connection pool for a MySQL database.

    Args:
        config: Database configuration (host/port/name/user/password and
            pool sizing; min_pool_size is ignored by aiomysql).

    Returns:
        Any: An aiomysql Pool instance.

    Raises:
        Exception: Propagates connection failures from aiomysql.
    """
    import aiomysql

    pool = await aiomysql.create_pool(
        host=config.host,
        port=config.port,
        db=config.name,
        user=config.user,
        password=config.password,
        maxsize=config.max_pool_size,
        pool_recycle=3600,
        autocommit=True,
    )
    return pool


async def create_pool_for(config: DatabaseConfig) -> Any:
    """Create a connection pool for the configured database engine.

    Args:
        config: Database configuration including ``db_type``.

    Returns:
        Any: asyncpg Pool (postgres) or aiomysql Pool (mysql).
    """
    if config.db_type == "mysql":
        return await create_mysql_pool(config)
    from pg_mcp.db.pool import create_pool

    return await create_pool(config)


def create_introspector_for(pool: Any, database_name: str, config: DatabaseConfig) -> Any:
    """Create a schema introspector for the configured engine.

    Args:
        pool: Connection pool for the database.
        database_name: Name of the database being introspected.
        config: Database configuration including ``db_type``.

    Returns:
        Any: SchemaIntrospector (postgres) or MySqlSchemaIntrospector (mysql).
    """
    if config.db_type == "mysql":
        # MySQL pools connect to a fixed schema (config.name); the alias
        # under which the database is registered may differ.
        return MySqlSchemaIntrospector(pool, config.name)
    return SchemaIntrospector(pool, database_name)


def create_executor_for(pool: Any, config: DatabaseConfig, security_config: Any) -> Any:
    """Create a SQL executor for the configured engine.

    Args:
        pool: Connection pool for the database.
        config: Database configuration including ``db_type``.
        security_config: Security configuration (limits, timeouts).

    Returns:
        Any: SQLExecutor (postgres) or MySqlSQLExecutor (mysql).
    """
    from pg_mcp.services.mysql_executor import MySqlSQLExecutor
    from pg_mcp.services.sql_executor import SQLExecutor

    if config.db_type == "mysql":
        return MySqlSQLExecutor(pool, security_config, config)
    return SQLExecutor(pool, security_config, config)


class MySqlSchemaIntrospector:
    """Introspect MySQL schema metadata via information_schema.

    Produces the same :class:`~pg_mcp.models.schema.DatabaseSchema` shape as
    the PostgreSQL introspector so the LLM prompt pipeline stays unchanged.
    """

    def __init__(self, pool: Any, database_name: str) -> None:
        """Initialize the MySQL introspector.

        Args:
            pool: aiomysql connection pool.
            database_name: Database (schema) name to introspect.
        """
        self.pool = pool
        self.database_name = database_name

    async def introspect(self) -> Any:
        """Introspect tables, columns, and keys from information_schema.

        Returns:
            DatabaseSchema: Schema metadata (foreign keys/indexes/views are
            best-effort and may be empty).
        """
        import aiomysql

        from pg_mcp.models.schema import ColumnInfo, DatabaseSchema, TableInfo

        async with self.pool.acquire() as conn:
            cursor = await conn.cursor(aiomysql.DictCursor)
            try:
                await cursor.execute(
                    """
                    SELECT table_name, engine, table_rows, table_comment
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (self.database_name,),
                )
                tables = await cursor.fetchall()

                result_tables: list[TableInfo] = []
                for t in tables:
                    table_name = _pick(t, "TABLE_NAME", "table_name") or ""
                    comment = _pick(t, "TABLE_COMMENT", "table_comment") or ""
                    rows_estimate = _pick(t, "TABLE_ROWS", "table_rows") or 0

                    await cursor.execute(
                        """
                        SELECT column_name, data_type, is_nullable, column_default,
                               character_maximum_length, column_key, column_comment
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (self.database_name, table_name),
                    )
                    columns = await cursor.fetchall()

                    col_infos = []
                    for c in columns:
                        name = _pick(c, "COLUMN_NAME", "column_name") or ""
                        data_type = _pick(c, "DATA_TYPE", "data_type") or ""
                        max_len = _pick(c, "CHARACTER_MAXIMUM_LENGTH", "character_maximum_length")
                        if max_len:
                            data_type = f"{data_type}({max_len})"
                        col_infos.append(
                            ColumnInfo(
                                name=name,
                                data_type=data_type,
                                is_nullable=(_pick(c, "IS_NULLABLE", "is_nullable") or "YES")
                                == "YES",
                                default=_pick(c, "COLUMN_DEFAULT", "column_default"),
                                comment=_pick(c, "COLUMN_COMMENT", "column_comment") or None,
                                is_primary_key=(_pick(c, "COLUMN_KEY", "column_key")) == "PRI",
                            )
                        )

                    result_tables.append(
                        TableInfo(
                            schema_name=self.database_name,
                            table_name=table_name,
                            columns=col_infos,
                            row_estimate=int(rows_estimate) if rows_estimate else None,
                            comment=comment or None,
                        )
                    )

                version_rows: list[dict[str, Any]] = []
                await cursor.execute("SELECT version() AS v")
                version_rows = await cursor.fetchall()
                version = None
                if version_rows:
                    raw = next(iter(version_rows[0].values()), None)
                    version = str(raw) if raw else None

                return DatabaseSchema(
                    database_name=self.database_name,
                    tables=result_tables,
                    version=version,
                )
            finally:
                await cursor.close()
