"""读 tests/golden_cases.json，跑一遍，输出结构化结果。

用法：
    uv run python scripts/run_golden.py
    uv run python scripts/run_golden.py --verbose

退出码 0 表示全部通过，1 表示有失败用例。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mcp_data_rewrite_python.connectors.mysql import MySQLConnector
from mcp_data_rewrite_python.contracts import MySQLQueryArgs
from mcp_data_rewrite_python.policy import Policy

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden_cases.json"


class FakePool:
    """替代真实连接池：记录收到的 SQL，返回预设行。"""

    def __init__(self, rows: list[dict[str, Any]], delay: float = 0.0) -> None:
        self.rows = rows
        self.delay = delay
        self.sent: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        self.sent.append((sql, params))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.rows


def _report(case: dict[str, Any], actual: dict[str, Any], passed: bool, reason: str) -> dict[str, Any]:
    return {
        "id": case["id"],
        "group": case["group"],
        "pass": passed,
        "reason": reason,
        "actual": actual,
    }


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    pool = FakePool(case.get("rows", []), case.get("delay", 0.0))
    conn = MySQLConnector(pool, Policy(), timeout_s=case.get("timeout_s", 5.0))
    expect = case["expect"]

    # ---- 契约层：多余字段应当直接被拒 ----
    try:
        extra = dict(case.get("extra_args", {}))
        args = MySQLQueryArgs(sql=case["sql"], params=case.get("params", []), **extra)
    except ValidationError:
        actual = {"kind": "error", "type": "ValidationError"}
        passed = expect["kind"] == "error" and expect.get("type") == "ValidationError"
        return _report(case, actual, passed, "contract rejected unexpected field")

    # ---- 连接器层：期望报错 ----
    try:
        result = await conn.execute(args, role=case["role"])
    except Exception as exc:
        actual = {"kind": "error", "type": type(exc).__name__, "message": str(exc)}
        type_ok = actual["type"] == expect.get("type")
        match_ok = expect.get("match", "") in str(exc)
        # 越权必须发生在访问数据库之前：一条 SQL 都不能发出去
        silent_ok = case["group"] != "tool-permission" or pool.sent == []
        passed = expect["kind"] == "error" and type_ok and match_ok and silent_ok
        reason = "ok" if passed else f"type_ok={type_ok} match_ok={match_ok} silent_ok={silent_ok}"
        return _report(case, actual, passed, reason)

    # ---- 连接器层：期望成功 ----
    actual = {
        "kind": "ok",
        "row_count": result.row_count,
        "data": result.data,
        "sent_sql": [s for s, _ in pool.sent],
        "sent_params": [p for _, p in pool.sent],
    }
    checks: list[tuple[str, bool]] = [("kind", expect["kind"] == "ok")]

    if "row_count" in expect:
        checks.append(("row_count", actual["row_count"] == expect["row_count"]))
    if "masked" in expect:
        row = result.data[0] if result.data else {}
        checks.append(("masked", all(row.get(k) == "***" for k in expect["masked"])))
    if "plain" in expect:
        row = result.data[0] if result.data else {}
        checks.append(("plain", all(row.get(k) == v for k, v in expect["plain"].items())))
    if "sent_params" in expect:
        got = actual["sent_params"][0] if actual["sent_params"] else ()
        checks.append(("sent_params", list(got) == expect["sent_params"]))
    if "sent_sql_not_contains" in expect:
        needle = expect["sent_sql_not_contains"]
        checks.append(("no_inline", all(needle not in s for s in actual["sent_sql"])))
    # 结构性断言：脱敏依赖 dict 行，若是 tuple 则脱敏静默失效
    if result.data:
        checks.append(("mapping_rows", isinstance(result.data[0], dict)))

    failed = [name for name, ok in checks if not ok]
    return _report(case, actual, not failed, "ok" if not failed else f"failed: {failed}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="跑黄金用例集")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印每条用例详情")
    opts = parser.parse_args()

    spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = spec["cases"]
    results = [await run_case(c) for c in cases]
    failed = [r for r in results if not r["pass"]]

    if opts.verbose:
        for r in results:
            flag = "PASS" if r["pass"] else "FAIL"
            print(f"[{flag}] {r['id']:<32} {r['reason']}")
    else:
        for r in failed:
            print(f"[FAIL] {r['id']:<32} {r['reason']}")
            print(f"       actual: {json.dumps(r['actual'], ensure_ascii=False, default=str)}")

    groups: dict[str, list[bool]] = {}
    for r in results:
        groups.setdefault(r["group"], []).append(r["pass"])
    print()
    for name, oks in groups.items():
        print(f"  {name:<18} {sum(oks)}/{len(oks)}")
    print(f"\ntotal={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
