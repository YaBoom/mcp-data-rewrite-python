from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from .mysql import MySQLConnector
from ..contracts import MySQLQueryArgs
from ..policy import Policy
from ..sqltext import to_pyformat


class FakePool:
    def __init__(self, rows=None, *, error=None, delay: float = 0.0):
        self.rows = rows if rows is not None else []
        self.error = error
        self.delay = delay
        self.calls: list[tuple[str, tuple]] = []

    async def fetch_all(self, sql, params):
        self.calls.append((sql, params))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.rows


ROWS = [{"name": "张三", "password": "p@ss", "salary": 20000}]


def make(rows=None, **kw):
    pool = FakePool(rows if rows is not None else ROWS, **kw)
    return MySQLConnector(pool, Policy()), pool


def args(sql, params=None):
    return MySQLQueryArgs(sql=sql, params=params or [])


async def run(conn, sql, params=None, role="manager"):
    """角色不在 args 里，由调用方显式传入。"""
    return await conn.execute(args(sql, params), role=role)


class TestRoleNotFromModel:
    """角色只能来自部署配置，模型输入无法携带 user_role。"""

    def test_user_role_field_removed(self):
        with pytest.raises(ValidationError):
            MySQLQueryArgs(sql="SELECT 1", user_role="admin")

    def test_schema_has_no_user_role(self):
        assert "user_role" not in MySQLQueryArgs.model_fields


class TestToolWhitelist:
    async def test_employee_rejected_and_no_sql_sent(self):
        conn, pool = make()
        with pytest.raises(PermissionError, match="无权调用"):
            await run(conn, "SELECT * FROM employees", role="employee")
        assert pool.calls == []          # ★ 被拒时一格 SQL 都没发出去


class TestTableWhitelist:
    async def test_manager_blocked(self):
        conn, _ = make()
        with pytest.raises(PermissionError, match="audit_logs"):
            await run(conn, "SELECT * FROM audit_logs")

    async def test_manager_allowed(self):
        conn, _ = make()
        await run(conn, "SELECT * FROM sales")

    async def test_admin_wildcard(self):
        conn, _ = make()
        await run(conn, "SELECT * FROM audit_logs", role="admin")

    async def test_db_table_form(self):
        conn, _ = make()
        await run(conn, "SELECT * FROM `erp`.`sales`")


class TestReadOnlyHardening:
    async def test_non_select(self):
        conn, _ = make()
        with pytest.raises(ValueError, match="只允许执行 SELECT"):
            await run(conn, "DELETE FROM employees", role="admin")

    async def test_outfile(self):
        conn, _ = make()
        with pytest.raises(ValueError, match="OUTFILE"):
            await run(
                conn, "SELECT * FROM employees INTO OUTFILE '/tmp/x'", role="admin"
            )

    async def test_for_update(self):
        conn, _ = make()
        with pytest.raises(ValueError, match="FOR UPDATE"):
            await run(conn, "SELECT * FROM employees FOR UPDATE", role="admin")

    async def test_multi_statement(self):
        conn, _ = make()
        with pytest.raises(ValueError, match="多条语句"):
            await run(conn, "SELECT 1; DROP TABLE t", role="admin")


class TestPlaceholder:
    async def test_mismatch_rejected(self):
        conn, _ = make()
        with pytest.raises(ValueError, match="不一致"):
            await run(conn, "SELECT * FROM employees WHERE id = ?")

    async def test_value_not_in_sql_text(self):
        conn, pool = make()
        await run(
            conn,
            "SELECT name FROM employees WHERE department = ? LIMIT ?",
            ["技术部", 10],
        )
        sql, params = pool.calls[0]
        assert params == ("技术部", 10)
        assert "技术部" not in sql
        assert "%s" in sql and "?" not in sql


class TestToPyformat:
    @pytest.mark.parametrize("src,expected", [
        ("SELECT ? , ?", "SELECT %s , %s"),
        ("WHERE note = 'a?b'", "WHERE note = 'a?b'"),
        ("WHERE s = 'it''s ?'", "WHERE s = 'it''s ?'"),
        (r"WHERE s = 'a\'?b'", r"WHERE s = 'a\'?b'"),
        ('WHERE d = "x?y"', 'WHERE d = "x?y"'),
        ("SELECT * FROM t", "SELECT * FROM t"),
    ])
    def test_cases(self, src, expected):
        assert to_pyformat(src) == expected


class TestResult:
    async def test_mask(self):
        conn, _ = make()
        r = await run(conn, "SELECT * FROM employees")
        row = r.data[0]
        assert row["password"] == "***"
        assert row["salary"] == "***"
        assert row["name"] == "张三"

    async def test_admin_no_mask(self):
        conn, _ = make()
        r = await run(conn, "SELECT * FROM employees", role="admin")
        assert r.data[0]["password"] == "p@ss"

    async def test_execution_time_is_duration(self):
        conn, _ = make()
        r = await run(conn, "SELECT * FROM employees")
        assert 0 <= r.execution_time_ms < 5000


class TestTimeout:
    async def test_timeout_raises(self):
        conn = MySQLConnector(FakePool([], delay=0.3), Policy(), timeout_s=0.05)
        with pytest.raises(TimeoutError, match="超时"):
            await run(conn, "SELECT * FROM employees")
