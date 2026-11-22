from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import cast

import httpx
import redis.asyncio as aioredis

from .connectors.http import HttpConnector
from .connectors.mysql import MySQLConnector
from .connectors.redis import RedisConnector
from .connectors.syncmy_pool import AsyncmyPool
from .contracts import Role
from .policy import Policy
from .server import build_server

_ALLOWED_ROLES: tuple[Role, ...] = ("admin", "manager", "employee")


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,                     # ★ 绝不能是 stdout
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _resolve_role() -> Role:
    """角色只从部署环境读取，模型/客户端无法自行提升权限。"""
    role = os.environ.get("MCP_USER_ROLE", "employee")
    if role not in _ALLOWED_ROLES:
        raise SystemExit(f"非法的 MCP_USER_ROLE: {role}")
    return cast(Role, role)


async def _serve() -> None:
    log = logging.getLogger("mcp_data")
    role = _resolve_role()
    log.info("当前角色 MCP_USER_ROLE=%s", role)
    policy = Policy()

    # AsyncmyPool.create 是异步工厂，必须在事件循环里调用
    pool = await AsyncmyPool.create(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "enterprise_db"),
        pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
    )
    mysql = MySQLConnector(
        pool, policy, timeout_s=float(os.environ.get("DB_TIMEOUT_S", "5"))
    )

    redis_client = aioredis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,                 # ★ 否则拿到 bytes
    )
    redis_conn = RedisConnector(
        redis_client, key_prefix=os.environ.get("REDIS_KEY_PREFIX", "erp:")
    )

    http_client = httpx.AsyncClient(
        base_url=os.environ.get("API_BASE_URL", "http://localhost:3001"),
        timeout=float(os.environ.get("API_TIMEOUT_S", "5")),
        headers={"Authorization": f"Bearer {os.environ.get('API_TOKEN', '')}"},
    )
    http_conn = HttpConnector(http_client)

    mcp = build_server(mysql, redis_conn, http_conn, role=role)

    try:
        log.info("MCP server starting on stdio")
        # 复用当前事件循环，不能调 mcp.run()（它内部会再开一个 loop）
        await mcp.run_stdio_async()
    finally:
        await pool.close()
        await redis_client.aclose()
        await http_client.aclose()


def main() -> None:
    _setup_logging()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
