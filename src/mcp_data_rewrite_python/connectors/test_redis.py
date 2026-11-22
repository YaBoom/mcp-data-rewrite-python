from .redis import RedisConnector
import pytest
import asyncio

class FakeRedis:
    def __init__(self, store, *, delay=0.0):
        self.store = store
        self.delay = delay

    async def get(self, key):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.store.get(key)


class TestRedis:
    async def test_namespace_rejected(self):
        c = RedisConnector(FakeRedis({}))
        with pytest.raises(PermissionError, match="命名空间"):
            await c.execute("user:session:123")

    async def test_missing_key(self):
        c = RedisConnector(FakeRedis({}))
        r = await c.execute("erp:config")
        assert r["exists"] is False

    async def test_json_value(self):
        c = RedisConnector(FakeRedis({"erp:config": '{"a": 1}'}))
        r = await c.execute("erp:config")
        assert r["value"] == {"a": 1}
        assert r["type"] == "object"

    async def test_plain_string(self):
        c = RedisConnector(FakeRedis({"erp:name": "hello"}))
        r = await c.execute("erp:name")
        assert r["value"] == "hello"
        assert r["type"] == "string"

    async def test_timeout(self):
        c = RedisConnector(FakeRedis({}, delay=0.3), timeout_s=0.05)
        with pytest.raises(TimeoutError):
            await c.execute("erp:x")