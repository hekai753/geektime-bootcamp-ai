"""MySQL SQL executor.

Mirrors :class:`pg_mcp.services.sql_executor.SQLExecutor` semantics for
MySQL (aiomysql): row limiting, type serialization, and error wrapping.
Read-only enforcement for MySQL relies on the SQL validation layer (only
SELECT statements pass) plus a read-only database account, since MySQL
driver support for read-only transactions varies.
"""

import asyncio
from typing import Any

from pg_mcp.models.errors import DatabaseError, ExecutionTimeoutError
from pg_mcp.services.sql_executor import SQLExecutor


class MySqlSQLExecutor(SQLExecutor):
    """SQL executor for MySQL databases using an aiomysql pool."""

    async def execute(
        self,
        sql: str,
        timeout: float | None = None,  # noqa: ASYNC109
        max_rows: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Execute a validated SELECT statement against MySQL.

        Args:
            sql: SQL query to execute (should already be validated).
            timeout: Query timeout in seconds (uses config default if None).
            max_rows: Maximum rows to return (uses config default if None).

        Returns:
            tuple: (results, total_row_count) before row limiting.

        Raises:
            ExecutionTimeoutError: If query execution exceeds timeout.
            DatabaseError: If the database operation fails.
        """
        import aiomysql

        timeout = timeout or self.security_config.max_execution_time
        max_rows = max_rows or self.security_config.max_rows

        try:
            async with self.pool.acquire() as connection:
                cursor = await connection.cursor(aiomysql.DictCursor)
                try:
                    try:
                        await asyncio.wait_for(cursor.execute(sql), timeout=timeout)
                        records = list(await asyncio.wait_for(cursor.fetchall(), timeout=timeout))
                    except TimeoutError as e:
                        raise ExecutionTimeoutError(
                            message=f"Query execution exceeded timeout of {timeout} seconds",
                            details={
                                "timeout_seconds": timeout,
                                "sql": sql[:200],
                            },
                        ) from e

                    total_count = len(records)
                    if len(records) > max_rows:
                        records = records[:max_rows]

                    results = self._serialize_results(records)
                    return results, total_count
                finally:
                    await cursor.close()

        except ExecutionTimeoutError:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Database query failed: {e!s}",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "sql": sql[:200],
                },
            ) from e
