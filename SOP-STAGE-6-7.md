# 阶段 6 & 7 详细执行 SOP

> **出处**：`PYTHON-REWRITE-SOP.md` 第五部分「阶段 6：测试与双实现对拍」「阶段 7：打包与部署」
> **适配**：已按本仓库真实情况校正（包名 `mcp_data_rewrite_python`、Python ≥3.13、mcp SDK 2.x、入口 `python -m mcp_data_rewrite_python`）
> **读法**：每一节都有「做什么 → 命令 → 验收」，做完一节勾一节，不要连着看完再动手。

---

## 0. 开工前的基线快照

动手前先确认这三条命令都是绿的，否则后面全是空中楼阁。

```powershell
uv run pytest -q          # 期望 39 passed
uv run ruff check src     # 期望无 error（style 可暂时忽略）
uv run mypy src           # 允许有 warning，先记数量
```

当前仓库事实（阶段 5 结束时的状态）：

| 项 | 值 |
|---|---|
| 包名 | `mcp_data_rewrite_python` |
| 启动命令 | `uv run python -m mcp_data_rewrite_python` |
| 脚本入口 | `mcp-data-rewrite-python`（见 `[project.scripts]`） |
| 角色来源 | 环境变量 `MCP_USER_ROLE`，默认 `employee` |
| 工具数量 | 3：`mysql_query` / `redis_get` / `api_call` |
| 测试数量 | 39 条，`asyncio_mode = "auto"` |
| 配置位置 | 根目录 `.env`（已被 `.gitignore` 忽略） |

**权限矩阵（写用例的唯一依据）**

| 角色 | 可调工具 | 可访问表 |
|---|---|---|
| `admin` | mysql_query, redis_get, api_call | `*`（全部） |
| `manager` | mysql_query, redis_get, api_call | employees, departments, projects, sales |
| `employee` | redis_get, api_call | employees, departments, projects（**但拿不到 mysql_query**） |

**脱敏字段**：`password` / `id_card` / `phone` / `salary`（非 admin 一律变 `***`）

---

# 阶段 6：测试与双实现对拍

## 6.1 这一阶段的产出物

不是"多写几个测试"，而是交付三件可给别人看的东西：

| 产出 | 路径 | 作用 |
|---|---|---|
| 黄金用例集 | `tests/golden_cases.json` | 与语言无关的验收清单，Node / Python 共用 |
| Python driver | `scripts/run_golden.py` | 读用例 → 跑 → 输出结构化结果 |
| 差异台账 | `DIFFERENCES.md` | 记录"两个实现哪些地方必然不同" |

> 判断你做完没：**别人只看 `golden_cases.json` 就能重新实现这个连接器，不需要读源码。**

## 6.2 为什么"对拍"比"单测"更重要

单测只证明"我认为对"；对拍证明"两个实现行为一致"。重写型项目的验收标准必须是后者。

本仓库已经吃过一次"我以为对"的亏：`contracts.ToolError` 一开始继承内置 `Exception`，单测 37 条全绿，但在 Inspector 里只显示 `Error executing tool mysql_query`——因为 SDK 对非 `ToolError` 的异常会丢弃原文。**测试没洞，是测试没覆盖跨层行为。** 对拍+端到端才能抓到这类问题。

## 6.3 Step 0：先给测试分层

别把所有东西都塞进黄金集，先想清楚测什么层：

| 层 | 测什么 | 本仓库对应文件 | 进黄金集？ |
|---|---|---|---|
| L1 纯函数 | SQL 文本归一化、表名提取 | `sqltext.py` | 部分（通过连接器间接覆盖） |
| L2 连接器 | 权限 + 只读硬化 + 脱敏 | `connectors/mysql.py` | **是，主体** |
| L3 工具层 | 参数契约、错误码映射 | `server.py` + `contracts.py` | 是（角色是否暴露） |
| L4 端到端 | 真实 stdio 调用 | `__main__.py` | 手动 + 冒烟脚本 |

黄金集聚焦 L2/L3，L4 放到阶段 7 的容器冒烟。

## 6.4 Step 1：建黄金用例集

新建 `tests/golden_cases.json`。设计要点：

- 字段与语言无关（不出现 Python 类名、不出现 JS 类型名）
- 每条用例只测一个行为
- `expect.kind` 只有两个值：`ok` / `error`
- 错误用 `type` + `match` 双约束（类型对但消息错，也算失败）

```json
{
  "version": 1,
  "cases": [
    {
      "id": "tool-employee-denied",
      "group": "tool-permission",
      "role": "employee",
      "sql": "SELECT * FROM employees",
      "params": [],
      "expect": { "kind": "error", "type": "PermissionError", "match": "无权调用" }
    },
    {
      "id": "tool-manager-allowed",
      "group": "tool-permission",
      "role": "manager",
      "sql": "SELECT * FROM sales",
      "params": [],
      "rows": [{ "id": 1 }],
      "expect": { "kind": "ok", "row_count": 1 }
    },
    {
      "id": "table-manager-blocked-audit",
      "group": "table-permission",
      "role": "manager",
      "sql": "SELECT * FROM audit_logs",
      "params": [],
      "expect": { "kind": "error", "type": "PermissionError", "match": "audit_logs" }
    },
    {
      "id": "table-admin-wildcard",
      "group": "table-permission",
      "role": "admin",
      "sql": "SELECT * FROM audit_logs",
      "params": [],
      "rows": [{ "id": 1 }],
      "expect": { "kind": "ok" }
    },
    {
      "id": "table-db-qualified-name",
      "group": "table-permission",
      "role": "manager",
      "sql": "SELECT * FROM `erp`.`sales`",
      "params": [],
      "rows": [{ "id": 1 }],
      "expect": { "kind": "ok" }
    },
    {
      "id": "rl-non-select",
      "group": "readonly",
      "role": "admin",
      "sql": "DELETE FROM employees",
      "params": [],
      "expect": { "kind": "error", "type": "ValueError", "match": "只允许执行 SELECT" }
    },
    {
      "id": "rl-outfile",
      "group": "readonly",
      "role": "admin",
      "sql": "SELECT * FROM employees INTO OUTFILE '/tmp/x'",
      "params": [],
      "expect": { "kind": "error", "type": "ValueError", "match": "OUTFILE" }
    },
    {
      "id": "rl-for-update",
      "group": "readonly",
      "role": "admin",
      "sql": "SELECT * FROM employees FOR UPDATE",
      "params": [],
      "expect": { "kind": "error", "type": "ValueError", "match": "FOR UPDATE" }
    },
    {
      "id": "rl-multi-statement",
      "group": "readonly",
      "role": "admin",
      "sql": "SELECT 1; DROP TABLE t",
      "params": [],
      "expect": { "kind": "error", "type": "ValueError", "match": "多条语句" }
    },
    {
      "id": "rl-literal-not-false-positive",
      "group": "readonly",
      "role": "manager",
      "sql": "SELECT * FROM employees WHERE note = 'from sales'",
      "params": [],
      "rows": [{ "id": 1 }],
      "expect": { "kind": "ok" }
    },
    {
      "id": "ph-missing-params",
      "group": "placeholder",
      "role": "manager",
      "sql": "SELECT * FROM employees WHERE id = ?",
      "params": [],
      "expect": { "kind": "error", "type": "ValueError", "match": "不一致" }
    },
    {
      "id": "ph-extra-params",
      "group": "placeholder",
      "role": "manager",
      "sql": "SELECT * FROM employees WHERE id = ?",
      "params": [1, 2],
      "expect": { "kind": "error", "type": "ValueError", "match": "不一致" }
    },
    {
      "id": "ph-bound-not-inlined",
      "group": "placeholder",
      "role": "manager",
      "sql": "SELECT name FROM employees WHERE department = ? LIMIT ?",
      "params": ["技术部", 10],
      "rows": [{ "name": "张三" }],
      "expect": { "kind": "ok", "sent_params": ["技术部", 10], "sent_sql_not_contains": "技术部" }
    },
    {
      "id": "ph-question-mark-in-literal",
      "group": "placeholder",
      "role": "manager",
      "sql": "SELECT * FROM employees WHERE note = 'a?b'",
      "params": [],
      "rows": [{ "id": 1 }],
      "expect": { "kind": "ok" }
    },
    {
      "id": "mask-manager",
      "group": "masking",
      "role": "manager",
      "sql": "SELECT * FROM employees",
      "params": [],
      "rows": [{ "name": "张三", "password": "p@ss", "salary": 20000 }],
      "expect": { "kind": "ok", "masked": ["password", "salary"], "plain": { "name": "张三" } }
    },
    {
      "id": "mask-admin-none",
      "group": "masking",
      "role": "admin",
      "sql": "SELECT * FROM employees",
      "params": [],
      "rows": [{ "name": "张三", "password": "p@ss" }],
      "expect": { "kind": "ok", "plain": { "password": "p@ss" } }
    },
    {
      "id": "timeout",
      "group": "timeout",
      "role": "manager",
      "sql": "SELECT * FROM employees",
      "params": [],
      "rows": [],
      "delay": 0.3,
      "timeout_s": 0.05,
      "expect": { "kind": "error", "type": "TimeoutError", "match": "超时" }
    },
    {
      "id": "contract-reject-user-role",
      "group": "role-injection",
      "role": "manager",
      "sql": "SELECT * FROM employees",
      "params": [],
      "extra_args": { "user_role": "admin" },
      "expect": { "kind": "error", "type": "ValidationError" }
    }
  ]
}
```

**用例设计的三条纪律**

1. **正向和反向必须成对**：`rl-for-update`（拒绝）对应 `rl-literal-not-false-positive`（不能误伤）。
2. **越权用例必须断言"什么都没发生"**：`tool-employee-denied` 除报错外，还要断言 `pool.sent == []`（一条 SQL 都没发出去）。
3. **脱敏用例必须同时测 admin**：只测 manager 变 `***`，无法证明是脱敏而不是查询失败。

## 6.5 Step 2：Python driver

新建 `scripts/run_golden.py`。它不依赖 pytest，也不连真实数据库——用 `FakePool` 替换。

```python
"""读 tests/golden_cases.json，跑一遍，输出结构化结果。"""
from __future__ import annotations

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
    def __init__(self, rows: list[dict[str, Any]], delay: float = 0.0) -> None:
        self.rows = rows
        self.delay = delay
        self.sent: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_all(self, sql: str, params: tuple[Any, ...]):
        self.sent.append((sql, params))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.rows


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    pool = FakePool(case.get("rows", []), case.get("delay", 0.0))
    conn = MySQLConnector(pool, Policy(), timeout_s=case.get("timeout_s", 5.0))
    expect = case["expect"]
    actual: dict[str, Any] = {}
    passed = False

    try:
        kwargs = dict(case.get("extra_args", {}))
        args = MySQLQueryArgs(sql=case["sql"], params=case.get("params", []), **kwargs)
    except ValidationError:
        actual = {"kind": "error", "type": "ValidationError"}
        passed = expect["kind"] == "error" and expect.get("type") == "ValidationError"
        return _report(case, actual, passed)

    try:
        result = await conn.execute(args, role=case["role"])
    except Exception as exc:
        actual = {"kind": "error", "type": type(exc).__name__, "message": str(exc)}
        passed = (
            expect["kind"] == "error"
            and actual["type"] == expect.get("type")
            and expect.get("match", "") in str(exc)
            and (case["group"] != "tool-permission" or pool.sent == [])
        )
        return _report(case, actual, passed)

    actual = {
        "kind": "ok",
        "row_count": result.row_count,
        "data": result.data,
        "sent_sql": [s for s, _ in pool.sent],
        "sent_params": [p for _, p in pool.sent],
    }
    passed = expect["kind"] == "ok"
    if passed and "row_count" in expect:
        passed = actual["row_count"] == expect["row_count"]
    if passed and "masked" in expect:
        row = result.data[0] if result.data else {}
        passed = all(row.get(k) == "***" for k in expect["masked"])
    if passed and "plain" in expect:
        row = result.data[0] if result.data else {}
        passed = all(row.get(k) == v for k, v in expect["plain"].items())
    if passed and "sent_sql_not_contains" in expect:
        needle = expect["sent_sql_not_contains"]
        passed = all(needle not in s for s in actual["sent_sql"])
    return _report(case, actual, passed)


def _report(case, actual, passed) -> dict[str, Any]:
    return {"id": case["id"], "group": case["group"], "pass": passed, "actual": actual}


async def main() -> int:
    spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
    results = [await run_case(c) for c in spec["cases"]]
    failed = [r for r in results if not r["pass"]]
    print(json.dumps(
        {"total": len(results), "failed": len(failed), "results": results},
        ensure_ascii=False, indent=2, default=str,
    ))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

运行：

```powershell
uv run python scripts/run_golden.py
```

**验收**：`"failed": 0`。

## 6.6 Step 3：Node 侧对拍（或退化方案）

理想做法：把同一份 JSON 交给 Node 版仓库的 driver 跑，比较两边输出。

**如果拿不到 Node 原版**（多数人情况），用**规格化对拍**：把 Node 版 `mysql-tool.test.ts` 的 18 条用例期望值手工转录进 `golden_cases.json` 的 `expect`。这样"对拍"退化为"照规格实现"，仍然有效——因为用例来自对方，不是你自己编的。

判断标准：**`expect` 里的每个值，都能指向 Node 源码的某一行**。指不出来的，说明你在自说自话。

## 6.7 Step 4：写 `DIFFERENCES.md`

不写这份文件，等于没做对拍。模板如下（本仓库已验证的真实差异已填入）：

```markdown
# Node 版 vs Python 版 差异台账

| # | 项 | Node 版 | Python 版 | 性质 | 处理 |
|---|---|---|---|---|---|
| 1 | 类型命名 | `object` / `string` | `dict` / `str` | 语言差异 | 对外 JSON 保持 JS 命名 |
| 2 | `executionTimeMs` | number，可能为 0 | int 毫秒，可能为 0 | 一致 | 无需处理 |
| 3 | `DECIMAL` 字段 | mysql2 自动转 number | `decimal.Decimal`，需 `jsonable()` 转 float | 行为差异 | 已在 contracts 统一 |
| 4 | 错误形态 | `查询执行失败: xxx` 纯文本 | `[ERROR_CODE] xxx` | **声明差异** | Python 更严格，保留 |
| 5 | 角色来源 | 工具参数 `userRole` | 环境变量 `MCP_USER_ROLE` | **安全增强** | 有意为之，schema 不暴露 |
| 6 | 参数校验 | 手写 `typeof` 判空 | pydantic `extra="forbid"` | 能力增强 | 多余字段直接拒绝 |
```

差异只分两类，没有第三类：

- **必须修的**：会导致调用方行为变化（比如字段名不同）
- **声明保留的**：安全或严格性提升（比如 #4 #5）

## 6.8 Step 5：pytest 的三个必知点

本仓库 `pyproject.toml` 已配好：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["src"]
```

| 事项 | 写法 | 对应 vitest |
|---|---|---|
| 异步测试 | `async def test_x():`（auto 模式下无需装饰器） | `it('x', async () => {})` |
| 断言异常 | `with pytest.raises(ValueError, match="不一致"):` | `rejects.toThrow()` |
| 断言成功 | 直接 `await`，再断言返回值 | `resolves.toBeTruthy()` |
| 参数化 | `@pytest.mark.parametrize("src,expected", [...])` | `it.each` |
| 临时替身 | **构造注入** `MySQLConnector(FakePool(), Policy())` | `vi.mock` |

**优先级铁律**：能用构造注入就别用 `monkeypatch`。Node 版被迫 `vi.mock('mysql2/promise')` 是因为连接池在构造函数内部 `new`；Python 版把 pool 作为参数注入，测试天然不需要 mock 魔法——这就是重构换来的可测性。

## 6.9 Step 6：补两条"防回归"测试（必做）

阶段 5 的核心成果是"角色不可由模型控制"。这个结论必须**被测试锁死**，否则下次重构就悄悄回退。

本仓库已在 `test_connectors.py` 和 `test_server.py` 中各放一条：

```python
# 契约层：多余字段直接拒绝
with pytest.raises(ValidationError):
    MySQLQueryArgs(sql="SELECT 1", user_role="admin")

# 协议层：schema 里根本不该出现 user_role
tools = await mcp.list_tools()
mt = next(t for t in tools if t.name == "mysql_query")
assert "user_role" not in mt.input_schema["properties"]
```

照这个模式，再给 `redis_get` / `api_call` 也补上，防止未来新增工具时漏掉。

## 6.10 Step 7：破坏性验证（做完才算真做完）

改一行 → 跑测试 → 记录"哪条用例抓到了我"。抓不到，说明测试有洞，当场补。

| 实验 | 预期变红的用例 | 学到的点 |
|---|---|---|
| 删掉 `if "*" in allowed` | `table-admin-wildcard` | 通配符语义靠测试保命 |
| 删掉 `strip_literals_and_comments` | `rl-literal-not-false-positive` | 词法归一化必须先于语法判断 |
| 把 `to_pyformat` 换成 `sql.replace("?", "%s")` | `ph-question-mark-in-literal` | 朴素替换会吃掉字面量里的 `?` |
| 让 `sanitize_data` 直接 return | `mask-manager` | 脱敏是防线，不是装饰 |
| 把 `role=role` 改成 `role="admin"` | `tool-employee-denied` | 闭包角色是权限的唯一来源 |
| cursor 换回默认 tuple | **可能全绿**（危险！） | 脱敏会静默失效，必须补断言 |

最后一行是本项目最阴的坑：`DictCursor` 去掉后 `isinstance(row, Mapping)` 为 False，`sanitize_data` 直接原样返回，**不报错**。所以还要补一条结构性断言：`assert isinstance(result.data[0], dict)`。

## 6.11 阶段 6 验收清单

- [ ] `uv run pytest -q` → 全绿
- [ ] `uv run python scripts/run_golden.py` → `"failed": 0`
- [ ] `uv run mypy src` → 无 error
- [ ] `uv run ruff check src` → 无 error
- [ ] `golden_cases.json` ≥ 18 条，覆盖 6 个 group
- [ ] `DIFFERENCES.md` 至少 5 行，且每条标了"必须修 / 声明保留"
- [ ] 做过至少 3 次破坏性实验，每次都记录"谁抓到了我"
- [ ] 越权用例断言了 `pool.sent == []`（证明拒绝发生在访问数据库之前）

---

# 阶段 7：打包与部署

## 7.1 产出物

| 产出 | 路径 | 验收 |
|---|---|---|
| 镜像定义 | `Dockerfile` | `docker build` 成功 |
| 构建忽略 | `.dockerignore` | 镜像里没有 `.env` / `.venv` |
| 冒烟脚本 | `scripts/smoke.sh` 或 PowerShell 等价物 | 容器返回 `serverInfo` |
| 客户端配置片段 | 写进 README 或本文 | 复制即用 |

## 7.2 Step 1：`.dockerignore`

镜像里**绝对不能**出现 `.env`（含 DB 密码）。先建这个文件：

```text
.venv/
.env
.git/
.idea/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
tests/
docs/
```

## 7.3 Step 2：Dockerfile（针对本仓库修正了 4 处）

```dockerfile
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ① 先只拷依赖清单，装第三方依赖（利用层缓存）
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# ② 再拷源码并安装本项目
COPY src ./src
RUN uv sync --frozen --no-dev

# 非 root 运行
RUN useradd -m app && chown -R app /app
USER app

# 关键：stdio 服务不能包 TTY
ENTRYPOINT ["uv", "run", "--frozen", "python", "-m", "mcp_data_rewrite_python"]
```

**相对原文的 4 处修正，逐条说明原因**

| # | 原文写法 | 本仓库必须是 | 不改会怎样 |
|---|---|---|---|
| 1 | `python:3.12-slim` | `python:3.13-slim` | `requires-python = ">=3.13"`，3.12 直接解析失败 |
| 2 | `COPY pyproject.toml uv.lock ./` | 多拷一个 `README.md` | `pyproject.toml` 里 `readme = "README.md"`，缺文件构建报错 |
| 3 | 一次性 `uv sync` | 先 `--no-install-project`，再装项目 | 第一次 sync 时 `src/` 还没拷进来，构建失败 |
| 4 | `python -m mcp_data` | `python -m mcp_data_rewrite_python` | 模块不存在，容器起来就退出 |

## 7.4 Step 3：构建

```powershell
docker build -t mcp-data-rewrite-python:0.1.0 .
```

验收：

```powershell
docker images mcp-data-rewrite-python
```

## 7.5 Step 4：容器冒烟

**先纠正一个错误认知：这个 server 启动时强依赖 MySQL。** `_serve()` 一开头就 `await AsyncmyPool.create(...)`，DB 连不上容器直接抛异常退出，连 `redis_get` / `api_call` 都不可用。所以冒烟必须给一个可连的库。

stdio 服务读 stdin 的 JSON-RPC、写 stdout。注意 `--env-file .env` 里的 `DB_HOST=localhost` 在容器内指向**容器自己**，必须覆盖。

### 冒烟 1：协议握手

```powershell
$req = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
$req | docker run -i --rm --env-file .env -e DB_HOST=host.docker.internal mcp-data-rewrite-python:0.1.0
```

期望输出包含：

```json
"serverInfo":{"name":"enterprise-data-server"}
```

### 冒烟 2：工具清单 + 权限（推荐，能一次性验证三件事）

新建 `_smoke.jsonl`，四行：

```text
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"mysql_query","arguments":{"sql":"SELECT * FROM employees"}}}
```

```powershell
Get-Content _smoke.jsonl -Encoding utf8 |
  docker run -i --rm --env-file .env -e DB_HOST=host.docker.internal -e MCP_USER_ROLE=employee mcp-data-rewrite-python:0.1.0
```

通过标准（三条同时满足）：

- `"id":2` 的 `tools` 数组里恰好 3 个工具
- `mysql_query` 的 `inputSchema` 里**没有** `user_role`
- `"id":3` 返回 `[PERMISSION_DENIED] 角色 employee 无权调用 mysql_query`

### PowerShell 的两个坑

1. `-e DB_PASSWORD=` 这种**空值写法会把后面的参数一起吞掉**，变量看似传了其实没传。要么整个省略这个 `-e`（默认就是空），要么写成 `-e "DB_PASSWORD="`。
2. 容器日志是 UTF-8，PowerShell 默认按 GBK 解码会显示成乱码。开头加 `[Console]::OutputEncoding = [Text.Encoding]::UTF8` 即可。

## 7.6 Step 5：客户端接入

Claude Desktop / Cursor 的 `mcpServers` 配置（Windows）：

```json
{
  "mcpServers": {
    "enterprise-data": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "MCP_USER_ROLE=manager",
        "-e", "DB_HOST=host.docker.internal",
        "-e", "DB_USER=mcp_readonly",
        "-e", "DB_PASSWORD=***",
        "-e", "DB_NAME=enterprise_db",
        "mcp-data-rewrite-python:0.1.0"
      ]
    }
  }
}
```

**原文这里有个隐蔽错误**：它把变量写在 `"env": {...}` 里。那个 `env` 是**给 `docker` 命令本身**的环境，不会自动进容器。要进容器必须用 `-e`（或 `--env-file`）。照着原文抄，容器里永远拿不到 `DB_HOST`。

## 7.7 Step 6：三个必踩的坑

| # | 坑 | 现象 | 正确做法 |
|---|---|---|---|
| 1 | 加了 `-t` | 客户端解析 JSON 报错 | **只要 `-i`，不要 `-t`**。TTY 会插入控制字符破坏帧 |
| 2 | 没设 `PYTHONUNBUFFERED=1` | 日志一条看不到，出问题完全瞎 | Dockerfile 的 `ENV` 里固定 |
| 3 | 用 `pip install -r` | 依赖版本漂移，本地/线上不一致 | `uv sync --frozen`，等价 `npm ci` |

**第四个坑（Windows 特有）**：PowerShell 管道传中文会被转码污染，冒烟测试时 SQL 里别带中文，或者用 `--env-file` 而不是 `-e` 传配置。

## 7.8 阶段 7 验收清单

- [x] `docker build` 成功，镜像 546MB（基础镜像 + `.venv` 84MB + uv），控制在 600MB 内即可
- [x] 镜像内无 `.env`：`docker run --rm --entrypoint ls mcp-data-rewrite-python:0.1.0 -a /app` → 只有 .venv / README.md / pyproject.toml / src / uv.lock
- [x] 冒烟返回 `serverInfo`
- [x] 容器内 `tools/list` 返回 3 个工具且 schema 无 `user_role`
- [x] 容器内 employee 调用被拒：`[PERMISSION_DENIED]`
- [x] 容器内 `MCP_USER_ROLE` 生效（启动日志打印了角色）
- [x] 以非 root 运行：`uid=10001(app)`
- [ ] 客户端配置复制即用，不报缺少依赖
- [ ] 一份 1 页设计说明（ADR）已写完（见附录 C）

## 7.9 本地三件套部署实践（MySQL + Redis + Server，已实测通过）

镜像能 build，只能证明“代码能装进盒子”；服务能不能跑，还差两个依赖。于是补三个文件：

| 文件 | 作用 |
|---|---|
| `docker-compose.yml` | mysql 8.4 + redis 7 + mcp-server，一条命令起整个栈 |
| `deploy/init.sql` | 建库建表 + 种子数据，表名与 `policy.py` 白名单严格对齐 |
| `scripts/smoke_container.py` | 真 MCP 客户端 → `docker compose run` → 容器内 server，11 条断言 |

### 四步跑完

```powershell
# 1) 起基础设施（首次会拉镜像）
docker compose up -d mysql redis

# 2) 等 mysql 变 healthy
docker inspect --format '{{.State.Health.Status}}' mcp-mysql

# 3) 行为验收（真客户端，逐角色起独立容器）
uv run python scripts/smoke_container.py

# 4) 收尾（-v 才会删数据卷）
docker compose down
```

第 3 步期望输出：

```
[employee] mysql_query props=['params', 'sql']  user_role泄漏=False
  [PASS] employee 调 mysql_query 应被拒
[manager] ...
  [PASS] manager 查 employees 应成功且脱敏
  [PASS] manager 查 audit_logs 应被表级权限拒绝
[admin] ...
  [PASS] admin 查 audit_logs 应放行（通配符）

total=11 passed=11 failed=0
```

`scripts/smoke_container.py` 把“一个进程一个角色”落实成了“一个角色一个容器”：
它用 `docker compose run -e MCP_USER_ROLE=<role>` 起容器，所以**换角色不需要改任何代码或配置文件**。

### 三个实测出来的坑

**坑 1：init.sql 里的中文变成乱码（最隐蔽）**

现象：`SELECT name FROM employees` 在容器里查出来是 `å¼ ä¸‰`，`HEX(name)` 是 `C3A5C2BCC2A0...`
而不是正确的 `E5BCA0...`。看起来像“客户端显示问题”，实际是**存进库就已经错了**。

根因：官方 `mysql` 镜像里 `LANG` 为空，mysql CLI 回落到 `latin1`。
初始化脚本的 UTF-8 字节被当作 latin1 声明给服务端，服务端又转成 utf8mb4 → 双重编码。

```sql
-- 修正：必须是第一条可执行语句
SET NAMES utf8mb4;
```

**并且 `init.sql` 只在数据卷为空时执行一次**，改完源码必须重建卷才会生效：

```powershell
docker compose down -v; docker compose up -d mysql redis
```

验证方式永远看 `HEX()`，不要看控制台输出：

```powershell
docker exec mcp-mysql mysql -uroot -p*** -N -B -e "SELECT HEX(name) FROM enterprise_db.employees"
# 期望 E5BCA0E4B889（“张三”的 UTF-8 字节）
```

**坑 2：compose 会自动读项目根的 `.env`**

`MCP_USER_ROLE: ${MCP_USER_ROLE:-manager}` 看着很安全，但 `.env` 里写了 `MCP_USER_ROLE=admin`，
compose 会把它插进去，**静默变成 admin**。启动日志里能看出来，但很容易归因错。

结论：角色在 compose 里写死默认值（如 `manager`），换角色用 `-e` 在命令行覆盖：

```powershell
docker compose run --rm -T -e MCP_USER_ROLE=employee mcp-server
```

**坑 3：用管道喂多条 JSON-RPC 会“时好时坏”**

`Get-Content x.jsonl | docker compose run -T mcp-server` 偶尔能跑，但第 3 条常收到
`{"code":-32000,"message":"Connection closed"}`。PowerShell 写完后立刻关闭 stdin，
服务端读到 EOF 就退出，还没处理的请求被丢弃（竞态，不一定每次复现）。

结论：**管道只够验证握手**（`initialize` 一条），行为验证必须用真客户端等 response。

### 数据持久化边界

| 命令 | 数据 |
|---|---|
| `docker compose stop` / `start` | 保留 |
| `docker compose down` | **保留**（命名卷 `mysql_data` 不删） |
| `docker compose down -v` | 删除（重建时重跑 `init.sql`） |

实测：`down` 后再 `up`，`SELECT COUNT(*) FROM employees` 仍为 3。

---

# 附录 A：原文与仓库的 5 处偏差

后续再读原文时，遇到下列描述以本仓库为准：

| 原文 | 本仓库 | 原因 |
|---|---|---|
| `python -m mcp_data` | `python -m mcp_data_rewrite_python` | 包命名 |
| `FastMCP` | `MCPServer`（`mcp.server.mcpserver`） | mcp SDK 2.x 改名 |
| 工具 schema 字段 `inputSchema` | `input_schema` | SDK 2.x 改名 |
| 阶段 5 才删 `user_role` | 已删，角色来自 `MCP_USER_ROLE` | 提前完成 |
| `python:3.12-slim` | `python:3.13-slim` | `requires-python` 约束 |

# 附录 B：D9 六个架构缺口（选做，但决定项目成色）

原文说"D9 是分水岭"：不做这六项，你只是"翻译了一遍"；做了才有资格叫"能上生产的第二个项目"。

| # | 缺口 | 现状 | 补法 |
|---|---|---|---|
| 1 | 列别名绕过脱敏 | `SELECT salary AS total` → 脱敏失效 | 改基于列的元数据脱敏，或直接查视图 |
| 2 | Redis 命名空间 | 已有 `key_prefix` | 补一条断言 `key` 必须以 `erp:` 开头的测试 |
| 3 | HTTP 仅 GET | 已实现 | 补 POST 拒绝用例 |
| 4 | 审计日志 | 只有 `logger.info` | 落库 `audit_log` 表：谁、何时、什么 SQL、返回几行 |
| 5 | 超时粒度 | 连接级 5s | 查询级 + 总预算，防慢查询拖死池 |
| 6 | 可观测 | 无指标 | 暴露 `tool_calls_total{name,result}` 计数 |

优先级：**1 > 4 > 6 > 5 > 2 > 3**。第 1 项是安全洞，第 4 项是运维底线。

# 附录 C：每阶段 5 行 ADR 模板

不要写长篇。每个阶段收尾时回答五个问题，这就是面试时"讲讲你的设计"的标准答法。

```text
1. 我做了什么决定？（例：连接池从内部 new 改为构造注入）
2. 为什么？（例：消除 mock 依赖，测试可直接传 FakePool）
3. 放弃了什么？（例：失去"构造即就绪"的简洁，装配代码变长）
4. 什么条件下这个决定会错？（例：若未来需要按请求动态切库）
5. 怎么验证？（例：test_connectors.py 全绿 + 破坏性实验）
```

阶段 6 的 ADR 示例：

```text
1. 决定：用语言无关的 golden_cases.json 做验收标准，而不是只写 pytest。
2. 原因：单测只能证明"我认为对"，对拍能证明两边行为一致。
3. 放弃：写测试的自由度下降，用例必须能被两个语言表达。
4. 会错的条件：如果 Node 版本身有 bug，照抄会把 bug 一起继承。
5. 验证：run_golden.py 输出 failed=0，且每条 expect 都能指向 Node 源码行。
```
