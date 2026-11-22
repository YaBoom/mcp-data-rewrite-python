# 企业数据查询 MCP Server

让 LLM 能查企业数据库，但**查不到不该看的东西**。

基于 [MCP](https://modelcontextprotocol.io) 的 stdio 服务，把 MySQL、Redis、内部 HTTP API 包装成三个只读工具。
权限不写在提示词里，也不写在工具参数里，而是由**部署时的环境变量**决定——模型无论怎么诱导，都无法通过参数给自己提权。

```text
MCP 客户端（Claude Desktop / Inspector）
        │  stdio（JSON-RPC）
        ▼
   server.py           工具注册 + 统一错误码
        ▼
   connectors/mysql.py 5 道只读防线 + 表级权限 + 字段脱敏
        ▼
   MySQL / Redis / 内部 API
```

## 三个工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `mysql_query` | `sql`、`params` | 执行**单条只读 SELECT**。条件值必须用 `?` 占位符 + `params` 绑定，不接受字符串拼接 |
| `redis_get` | `key` | 按 key 读缓存，仅允许 `erp:` 命名空间；值是 JSON 时自动解析 |
| `api_call` | `endpoint`、`params` | 调用内部 API，仅 `GET`，端点枚举为 `/employees`、`/departments`、`/projects` |

## 权限矩阵

角色通过环境变量 `MCP_USER_ROLE` 注入，取值 `admin` / `manager` / `employee`，非法值启动即退出。

| 角色 | 可用工具 | 可访问表 | 敏感字段 |
|---|---|---|---|
| `admin` | 全部 | 全部（`*`） | 不脱敏 |
| `manager` | 全部 | `employees`、`departments`、`projects`、`sales` | `password`、`id_card`、`phone`、`salary` → `***` |
| `employee` | `redis_get`、`api_call` | —（无 `mysql_query` 权限） | — |

> 角色是**部署方**决定的，不是调用方决定的。`mysql_query` 的输入 schema 里没有 `user_role` 字段，
> `scripts/smoke_container.py` 会专门断言这个字段没有泄漏。

## `mysql_query` 的五道防线

1. **工具级白名单**——当前角色无权用这个工具，直接 `PERMISSION_DENIED`
2. **只允许单条 SELECT**——先剥离注释和字符串字面量，再判断语句头，`DELETE` / `WITH` / 多语句一律拒绝
3. **SELECT 形态下的危险子句**——禁止 `INTO OUTFILE` / `INTO DUMPFILE`（写服务器文件）、`FOR UPDATE` / `LOCK IN SHARE MODE`（加锁）
4. **占位符数量与参数数量必须相等**——不一致直接报错，堵住「条件值拼进 SQL」的路子；`?` 到驱动层才转成 `%s`，且跳过字符串字面量内部的 `?`
5. **表级权限 → 字段脱敏**——从 `FROM` / `JOIN` 提取表名做白名单校验，查询返回后按 `SENSITIVE_FIELDS` 把敏感列替换为 `***`

关键点：**越权失败发生在碰数据库之前**。黄金用例里专门断言了越权请求下连接池收到的 SQL 数量为 `0`。

脱敏依赖「行是 dict」。如果驱动返回 tuple，脱敏会**静默失效**——所以黄金用例里有一条结构性断言，强制校验返回行是映射类型。

## 错误码

所有可预期失败都通过继承 SDK `ToolError` 抛回客户端，格式 `[CODE] message`：

| 码 | 含义 |
|---|---|
| `INVALID_ARGS` | 参数未通过 pydantic 契约校验（多余字段会被 `extra="forbid"` 拒绝） |
| `PERMISSION_DENIED` | 角色无工具权限、或表不在白名单、或 key 越界 |
| `INVALID_SQL` | 非 SELECT、命中禁止模式、占位符与参数不匹配 |
| `TIMEOUT` | 查询 / Redis 读取超时 |
| `EXECUTION_ERROR` | 下游执行失败 |

## 快速开始

前置：Python **3.13**（`pyproject.toml` 里 `requires-python = ">=3.13"`）、[uv](https://docs.astral.sh/uv/)、Docker。

```bash
git clone https://github.com/YaBoom/mcp-data-rewrite-python.git
cd mcp-data-rewrite-python

cp .env.example .env        # 填 DB_PASSWORD 等真实值；.env 已被 gitignore
uv sync
```

### 本地一键起 MySQL + Redis + Server

`docker compose` 里三者都定义好了，MySQL 映射到宿主机 **3307**（避开本机 3306），Redis 映射到 **6380**。
`deploy/init.sql` 会在首次建卷时自动建库建表并灌入演示数据。

```bash
docker compose up -d mysql redis                     # 起基础设施
uv run python scripts/smoke_container.py             # 真实 MCP 客户端冒烟，逐角色验证
docker compose down                                  # 结束（加 -v 连数据卷一起清掉）
```

交互式手动跑一次 server：

```bash
docker compose run --rm -T -e MCP_USER_ROLE=manager mcp-server
```

### 接入 MCP 客户端

本地源码方式：

```json
{
  "mcpServers": {
    "enterprise-data": {
      "command": "uv",
      "args": [
        "run", "--frozen", "--no-sync",
        "--directory", "/absolute/path/to/mcp-data-rewrite-python",
        "python", "-m", "mcp_data_rewrite_python"
      ],
      "env": {
        "MCP_USER_ROLE": "manager",
        "DB_HOST": "127.0.0.1",
        "DB_USER": "root",
        "DB_PASSWORD": "your-password",
        "DB_NAME": "enterprise_db"
      }
    }
  }
}
```

容器方式（不用在本机装 Python 依赖）：

```json
{
  "command": "docker",
  "args": ["compose", "run", "--rm", "-T", "mcp-server"],
  "cwd": "/absolute/path/to/mcp-data-rewrite-python",
  "env": { "MCP_USER_ROLE": "manager" }
}
```

> 日志全部走 **stderr**。stdio 协议下 stdout 只能有协议帧，任何 `print` 到 stdout 都会把客户端搞崩。

## 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `MCP_USER_ROLE` | `employee` | 角色，`admin` / `manager` / `employee` |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `localhost` / `root` / 空 / `enterprise_db` | MySQL 连接，密码无默认值 |
| `DB_POOL_SIZE` | `10` | 连接池大小 |
| `DB_TIMEOUT_S` | `5` | 单次查询超时 |
| `REDIS_URL` | `redis://localhost:6379` | Redis 连接串 |
| `REDIS_KEY_PREFIX` | `erp:` | 允许访问的 key 前缀 |
| `API_BASE_URL` | `http://localhost:3001` | 内部 API 地址 |
| `API_TIMEOUT_S` | `5` | API 超时 |
| `API_TOKEN` | 空 | 以 `Authorization: Bearer` 头发送 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 测试

```bash
uv run pytest -q                          # 39 passed：契约、server、三个连接器
uv run python scripts/run_golden.py       # 18 条黄金用例，7 组
uv run python scripts/run_golden.py -v    # 逐条打印
uv run python scripts/smoke_container.py  # 容器内真实 MCP 客户端，11 条断言 × 3 角色
```

黄金用例集 `tests/golden_cases.json` 不需要真实数据库——用 `FakePool` 替换连接池，
因此既能断言「结果对不对」，也能断言「到底有没有把 SQL 发出去」。

| 组 | 覆盖 |
|---|---|
| `readonly` | 非 SELECT、多语句、写文件、加锁 |
| `placeholder` | 占位符与参数数量、字面量里的 `?` 不被替换 |
| `tool-permission` / `table-permission` | 越权拒绝，且**零 SQL 触达数据库** |
| `masking` | 敏感字段 `***`、admin 不脱敏 |
| `timeout` / `role-injection` | 超时映射、`user_role` 无法从参数注入 |

## Docker 构建

Dockerfile 分两层装依赖，改代码不会让第三方依赖层失效：

```dockerfile
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project   # ① 只装三方依赖，可缓存
COPY src ./src
RUN uv sync --frozen --no-dev                        # ② 再装本项目
```

`--frozen` 表示只认 `uv.lock`、不重新解析。所以**改了 `pyproject.toml` 必须先跑 `uv lock` 并提交**，否则构建会在第二步直接失败。
容器以非 root（uid 10001）运行，`ENTRYPOINT` 带 `--no-sync`，启动时不会联网拉包。

## 项目结构

```text
src/mcp_data_rewrite_python/
├── __main__.py        启动：读环境变量 → 建连接池 → 起 stdio
├── server.py          工具注册与错误码映射
├── policy.py          角色 → 工具/表白名单、敏感字段脱敏
├── sqltext.py         SQL 文本处理：剥离注释字面量、抽表名、? → %s
├── contracts.py       pydantic 契约（extra="forbid"）、Role、QueryResult
└── connectors/
    ├── mysql.py       5 道只读防线 + 脱敏
    ├── redis.py       命名空间前缀校验
    ├── http.py        端点枚举 + 只读动词
    └── syncmy_pool.py asyncmy 连接池
deploy/init.sql        建库建表 + 演示数据（含 SET NAMES utf8mb4）
tests/golden_cases.json 黄金用例（16 条安全 + 2 条脱敏）
scripts/               run_golden.py、smoke_container.py
```

## 已知边界

- **启动强依赖 MySQL**：连接池在 `_serve()` 里立即创建，数据库不可用时进程直接退出，不会降级为「只提供 Redis / API 能力」。
- **只读**：不支持 `EXPLAIN`、`SHOW`、存储过程，也没有写入工具。
- **无行数上限**：`SELECT * FROM` 大表仍可能返回巨量数据，靠 `DB_TIMEOUT_S` 兜底。生产接入建议补 `LIMIT` 强制或权限视图。
- **审计日志只到 stderr**：`deploy/init.sql` 里的 `audit_logs` 是演示数据，服务本身还没有把调用落库。
- **单进程单角色**：一个 server 进程对应一个角色，换角色就是换进程（这正是权限无法被模型提权的原因）。