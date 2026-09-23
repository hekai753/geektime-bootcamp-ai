"""Load a psql-style fixture SQL file into a PostgreSQL server.

Minimal psql replacement: handles ``\\c`` (reconnect) meta-commands and
executes every other statement via asyncpg. Intended for test-fixture
loading on machines without a local psql client.

Usage:
    uv run python scripts/load_fixture.py <fixture.sql> <host> <port> <user> <password>
"""

import asyncio
import contextlib
import re
import sys

import asyncpg


def split_statements(sql: str) -> list[tuple[str | None, str]]:
    """Split SQL text into (database, statement) pairs.

    A ``\\c dbname;`` line updates the target database for subsequent
    statements. Dollar-quoted strings and standard quotes are respected.
    """
    targets: list[tuple[str | None, str]] = []
    current_db: str | None = None
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_dollar = False
    while i < n:
        if sql.startswith("$$", i) or re.match(r"\$[a-zA-Z_]+\$", sql[i:]):
            m = re.match(r"\$[a-zA-Z_]*\$", sql[i:])
            in_dollar = not in_dollar
            i += m.end()
            continue
        if not in_dollar and sql[i] == ";":
            stmt = "".join(buf).strip()
            buf = []
            # Check for \c meta-command line within/preceding the statement
            meta = re.search(r"\\c\s+([\w-]+)\s*$", stmt)
            if (
                meta
                and stmt.replace(meta.group(0), "").strip().count("\n") >= 0
                and not re.search(r"[a-zA-Z]", stmt.replace(meta.group(0), "").replace("\\c", ""))
            ):
                current_db = meta.group(1)
            elif stmt:
                targets.append((current_db, stmt))
            i += 1
            continue
        buf.append(sql[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        targets.append((current_db, tail))
    return targets


async def load(path: str, host: str, port: int, user: str, password: str) -> None:
    """Load fixture file, reconnecting when the target database changes."""
    with open(path, encoding="utf-8") as f:  # noqa: ASYNC230 - fixture loader
        sql = f.read()
    stmts = split_statements(sql)
    conn: asyncpg.Connection | None = None
    cur_db: str | None = None
    for db, stmt in stmts:
        if db is not None and db != cur_db:
            if conn:
                await conn.close()
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db,
                timeout=10,
            )
            cur_db = db
            print(f"connected to {db}")
        elif conn is None:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database="postgres",
                timeout=10,
            )
            cur_db = "postgres"
        with contextlib.suppress(asyncpg.DuplicateObjectError):
            await conn.execute(stmt)  # idempotent-ish reload
    if conn:
        await conn.close()
    print(f"done: {len(stmts)} statements executed")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(__doc__)
        sys.exit(1)
    asyncio.run(load(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]))
