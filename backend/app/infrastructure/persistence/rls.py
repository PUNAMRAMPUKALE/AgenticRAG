from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

_SQL_FILE = Path(__file__).with_name("sql") / "rls.sql"


def _sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    in_dollar = False
    i = 0
    while i < len(script):
        if script.startswith("$$", i):
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        if not in_dollar and script[i] == ";":
            stmt = "".join(buf).strip()
            buf = []
            if stmt and not all(line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()):
                statements.append(stmt)
            i += 1
            continue
        buf.append(script[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


async def apply_rls(conn: AsyncConnection) -> None:
    script = _SQL_FILE.read_text(encoding="utf-8")
    for stmt in _sql_statements(script):
        await conn.exec_driver_sql(stmt)


async def apply_row_context(
    db: AsyncSession,
    *,
    user_id: str = "",
    is_manager: bool = False,
    service: bool = False,
) -> None:
    await db.execute(text("SET LOCAL ROLE agenticrag_app"))
    await db.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": user_id},
    )
    await db.execute(
        text("SELECT set_config('app.is_manager', :flag, true)"),
        {"flag": "true" if is_manager else "false"},
    )
    await db.execute(
        text("SELECT set_config('app.service_role', :flag, true)"),
        {"flag": "true" if service else "false"},
    )
