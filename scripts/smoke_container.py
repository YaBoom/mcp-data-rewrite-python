"""容器部署冒烟：真实 MCP 客户端 -> docker compose run -> 容器内 server。

用法：
    uv run python scripts/smoke_container.py

它会为每个角色单独起一个容器进程（一个进程一个角色），
逐条发 tools/call，然后按预期判定通过/失败。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

# (角色, 用例名, sql, params, 期望)
CASES: list[tuple[str, str, str, list[Any], dict[str, Any]]] = [
    (
        "employee", "employee 调 mysql_query 应被拒",
        "SELECT id, name FROM employees", [],
        {"ok": False, "match": "PERMISSION_DENIED"},
    ),
    (
        "manager", "manager 查 employees 应成功且脱敏",
        "SELECT id, name, department, phone, id_card, password, salary FROM employees WHERE department = ?",
        ["技术部"],
        {"ok": True, "row_count": 2, "masked": ["phone", "id_card", "password", "salary"]},
    ),
    (
        "manager", "manager 查 sales 应成功",
        "SELECT region, amount FROM sales", [],
        {"ok": True, "row_count": 2},
    ),
    (
        "manager", "manager 查 audit_logs 应被表级权限拒绝",
        "SELECT * FROM audit_logs", [],
        {"ok": False, "match": "audit_logs"},
    ),
    (
        "admin", "admin 查 audit_logs 应放行（通配符）",
        "SELECT actor, action FROM audit_logs", [],
        {"ok": True, "row_count": 2},
    ),
    (
        "admin", "admin 查 employees 不脱敏",
        "SELECT phone FROM employees WHERE id = ?", [1],
        {"ok": True, "row_count": 1, "unmasked": ["phone"]},
    ),
    (
        "manager", "非 SELECT 语句应被拦截",
        "DELETE FROM employees", [],
        {"ok": False, "match": "INVALID_SQL"},
    ),
    (
        "manager", "占位符数量不匹配应报错",
        "SELECT * FROM employees WHERE id = ? AND name = ?", [1],
        {"ok": False},
    ),
]


def _params(role: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="docker",
        args=[
            "compose", "run", "--rm", "-T",
            "-e", f"MCP_USER_ROLE={role}",
            "mcp-server",
        ],
        cwd=str(ROOT),
        env={**os.environ},
        encoding="utf-8",
        encoding_error_handler="replace",
    )


def _payload(result: Any) -> dict[str, Any] | str:
    text = "".join(
        getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text"
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def _run_role(role: str, cases: list[tuple[str, str, list[Any], dict[str, Any]]]) -> list[bool]:
    results: list[bool] = []
    async with stdio_client(_params(role)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            schema = next(t for t in tools.tools if t.name == "mysql_query").input_schema
            props = sorted(schema.get("properties", {}))
            leak = "user_role" in props
            print(f"\n[{role}] tools={[t.name for t in tools.tools]}")
            print(f"[{role}] mysql_query props={props}  user_role泄漏={leak}")
            results.append(not leak)

            for name, sql, params, expect in cases:
                res = await session.call_tool("mysql_query", {"sql": sql, "params": params})
                body = _payload(res)
                results.append(_judge(role, name, res.is_error, body, expect))
    return results


def _judge(role: str, name: str, is_error: bool, body: Any, expect: dict[str, Any]) -> bool:
    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    problems: list[str] = []

    if expect["ok"]:
        if is_error:
            problems.append("预期成功，实际返错")
        data = body.get("data", []) if isinstance(body, dict) else []
        if "row_count" in expect and len(data) != expect["row_count"]:
            problems.append(f"行数 {len(data)} != {expect['row_count']}")
        for field in expect.get("masked", []):
            if not data or data[0].get(field) != "***":
                problems.append(f"{field} 未脱敏: {data[0].get(field) if data else None!r}")
        for field in expect.get("unmasked", []):
            if not data or data[0].get(field) in (None, "***"):
                problems.append(f"{field} 被错误脱敏")
    else:
        if not is_error:
            problems.append("预期失败，实际成功")
        if "match" in expect and expect["match"] not in text:
            problems.append(f"错误信息未包含 {expect['match']}")

    ok = not problems
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"         原因: {'; '.join(problems)}")
        print(f"         实际: {text[:400]}")
    return ok


async def main() -> int:
    grouped: dict[str, list[tuple[str, str, list[Any], dict[str, Any]]]] = {}
    for role, name, sql, params, expect in CASES:
        grouped.setdefault(role, []).append((name, sql, params, expect))

    all_ok: list[bool] = []
    for role, cases in grouped.items():
        all_ok.extend(await _run_role(role, cases))

    total, passed = len(all_ok), sum(all_ok)
    print(f"\ntotal={total} passed={passed} failed={total - passed}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
