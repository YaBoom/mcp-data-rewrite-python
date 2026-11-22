from __future__ import annotations

import json
import logging
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ValidationError

from .connectors.http import HttpConnector
from .connectors.mysql import MySQLConnector
from .connectors.redis import RedisConnector
from .contracts import MySQLQueryArgs, ToolError, jsonable

logger = logging.getLogger("mcp_data.server")

Role = Literal["admin", "manager", "employee"]


def _dumps(obj: Any, indent: int | None = 2) -> str:
    """统一出口：pydantic 模型走 model_dump_json，其余走 json + jsonable。"""
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=indent)
    return json.dumps(jsonable(obj), ensure_ascii=False, indent=indent)


def build_server(
        mysql: MySQLConnector,
        redis: RedisConnector,
        http: HttpConnector,
        *,
        role: Role,
) -> MCPServer:
    mcp = MCPServer("enterprise-data-server")

    # ---------------- mysql_query ----------------
    @mcp.tool(
        name="mysql_query",
        description=(
                "执行 MySQL 只读查询：仅单条 SELECT，条件值走 ? 占位符绑定。"
                "表级权限与敏感字段脱敏由部署时配置的角色自动执行"
        ),
    )
    async def mysql_query(
            sql: str,
            params: list[str | int | float | bool | None] | None = None,
    ) -> str:
        """执行一条只读 SELECT。

        Args:
            sql: 单条 SELECT 语句。条件值必须写 ? 占位符，不要拼接字面量。
            params: 与 sql 中 ? 占位符一一对应的参数值。
        """
        try:
            args = MySQLQueryArgs(sql=sql, params=params or [])
        except ValidationError as exc:
            raise ToolError(
                "INVALID_ARGS",
                _dumps({"details": exc.errors(include_url=False)}, indent=None),
            ) from exc

        try:
            result = await mysql.execute(args, role=role)
        except PermissionError as exc:
            raise ToolError("PERMISSION_DENIED", str(exc)) from exc
        except ValueError as exc:
            raise ToolError("INVALID_SQL", str(exc)) from exc
        except TimeoutError as exc:
            raise ToolError("TIMEOUT", str(exc)) from exc
        except RuntimeError as exc:
            raise ToolError("EXECUTION_ERROR", str(exc)) from exc

        logger.info(
            "mysql_query ok role=%s rows=%s cost=%sms",
            role, result.row_count, result.execution_time_ms,
        )
        return result.model_dump_json(indent=2)

    # ---------------- redis_get ----------------
    @mcp.tool(
        name="redis_get",
        description="从 Redis 获取缓存数据（仅允许 erp: 命名空间）",
    )
    async def redis_get(key: str) -> str:
        """按 key 读取 Redis，自动尝试 JSON 解析。

        Args:
            key: Redis 键名，必须以 erp: 开头。
        """
        try:
            payload = await redis.execute(key)
        except PermissionError as exc:
            raise ToolError("PERMISSION_DENIED", str(exc)) from exc
        except TimeoutError as exc:
            raise ToolError("TIMEOUT", str(exc)) from exc
        except RuntimeError as exc:
            raise ToolError("EXECUTION_ERROR", str(exc)) from exc

        return _dumps(payload)

    # ---------------- api_call ----------------
    @mcp.tool(
        name="api_call",
        description="调用内部 API（员工信息、部门架构等），仅支持 GET",
    )
    async def api_call(
            endpoint: Literal["/employees", "/departments", "/projects"],
            params: dict[str, Any] | None = None,
    ) -> str:
        """查询内部 API。

        Args:
            endpoint: 端点，取值 /employees、/departments、/projects。
            params: 查询参数（query string）。
        """
        try:
            payload = await http.execute(endpoint, "GET", params)
        except PermissionError as exc:
            raise ToolError("PERMISSION_DENIED", str(exc)) from exc
        except RuntimeError as exc:
            raise ToolError("EXECUTION_ERROR", str(exc)) from exc

        return _dumps(payload)

    return mcp