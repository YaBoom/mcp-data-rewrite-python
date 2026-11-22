# connectors/mysql.py
from __future__ import annotations
import asyncio
import re
import time
from collections.abc import Mapping
from typing import Any, Protocol

from ..contracts import MySQLQueryArgs, QueryResult, Role
from ..policy import Policy, sanitize_data
from ..sqltext import (
    FORBIDDEN_PATTERNS,
    count_placeholders,
    extract_tables,
    strip_literals_and_comments,
    to_pyformat,
)

_SELECT_HEAD = re.compile(r"^select\b")


class QueryPool(Protocol):
    async def fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[Mapping[str, Any]]:
        ...


class MySQLConnector:
    def __init__(self, pool: QueryPool, policy: Policy, timeout_s: float = 5.0) -> None:
        self._pool = pool
        self._policy = policy
        self._timeout = timeout_s


    async def execute(self, args: MySQLQueryArgs, *, role: Role) -> QueryResult:
        started = time.perf_counter()

        # 防线 1：工具级白名单（纵深防御，server 层还会拦一次）
        if not self._policy.check_permission(role, "mysql_query"):
            raise PermissionError(f"角色 {role} 无权调用 mysql_query")

        clean = strip_literals_and_comments(args.sql)

        # 防线 2：只允许单条 SELECT
        if not _SELECT_HEAD.match(clean.strip().lower()):
            raise ValueError("只允许执行 SELECT 查询语句")

        # 防线 3：SELECT 形态下的写文件 / 加锁 / 多语句
        for pattern, reason in FORBIDDEN_PATTERNS:
            if pattern.search(clean):
                raise ValueError(reason)

        # 防线 4：占位符与参数一一对应
        n = count_placeholders(clean)
        if n != len(args.params):
            raise ValueError(
                f"占位符数量({n})与参数数量({len(args.params)})不一致："
                "条件值请用 ? 占位符并通过 params 传入"
            )

        # 防线 5a：表级权限
        for table in extract_tables(clean):
            if not self._policy.has_table_access(role, table):
                raise PermissionError(f"角色 {role} 无权访问表: {table}")

        # 关键：? → %s
        py_sql = to_pyformat(args.sql)

        try:
            rows = await asyncio.wait_for(
                self._pool.fetch_all(py_sql, tuple(args.params)),
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise TimeoutError(f"查询超时（>{self._timeout}s）") from exc
        except Exception as exc:
            raise RuntimeError(f"查询执行失败: {exc}") from exc

        # 防线 5b：字段脱敏
        return QueryResult(
            success=True,
            row_count=len(rows),
            data=sanitize_data(rows, role),
            execution_time_ms=int((time.perf_counter() - started) * 1000),
        )

