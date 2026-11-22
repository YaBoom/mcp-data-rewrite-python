import httpx

from .connectors.http import HttpConnector
from .connectors.mysql import MySQLConnector
from .connectors.redis import RedisConnector
from .policy import Policy
from .server import build_server

class _Pool:
    async def fetch_all(self, sql, params):
        return [{"name": "张三", "password": "p@ss"}]


class _Redis:
    async def get(self, key):
        return '{"a": 1}'


def _build(role="manager"):
    policy = Policy()
    mysql = MySQLConnector(_Pool(), policy)
    redis = RedisConnector(_Redis())
    http = HttpConnector(httpx.AsyncClient(base_url="http://test"))
    return build_server(mysql, redis, http, role=role)


class TestSchema:
    async def test_three_tools(self):
        mcp = _build()
        tools = await mcp.list_tools()
        assert {t.name for t in tools} == {"mysql_query", "redis_get", "api_call"}

    async def test_user_role_not_exposed(self):
        mcp = _build()
        tools = await mcp.list_tools()
        mt = next(t for t in tools if t.name == "mysql_query")
        # 模型输入里不该出现角色字段，权限只能来自部署配置
        assert "user_role" not in mt.input_schema["properties"]

    async def test_description_present(self):
        mcp = _build()
        tools = await mcp.list_tools()
        mt = next(t for t in tools if t.name == "mysql_query")
        assert "SELECT" in (mt.description or "")