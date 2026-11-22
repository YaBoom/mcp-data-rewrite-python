import httpx
import pytest
from .http import HttpConnector

def make_http(handler, timeout_s=5.0):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return HttpConnector(client, timeout_s=timeout_s)

class TestHttp:
    async def test_allowed_endpoint(self):
        c = make_http(lambda req: httpx.Response(200, json=[{"name": "张三"}]))
        r = await c.execute("/employees")
        assert r["data"] == [{"name": "张三"}]
        assert r["method"] == "GET"

    async def test_endpoint_rejected(self):
        c = make_http(lambda req: httpx.Response(200))
        with pytest.raises(PermissionError, match="未授权"):
            await c.execute("/admin/secrets")

    async def test_post_rejected(self):
        c = make_http(lambda req: httpx.Response(200))
        with pytest.raises(PermissionError, match="仅支持 GET"):
            await c.execute("/employees", method="POST")

    async def test_4xx_becomes_runtime_error(self):
        c = make_http(lambda req: httpx.Response(404, json={"message": "nf"}))
        with pytest.raises(RuntimeError, match="API Error 404"):
            await c.execute("/employees")

    async def test_params_passed_as_query(self):
        seen = {}

        def handler(req):
            seen["url"] = str(req.url)
            print(req.url)
            return httpx.Response(200, json={})

        c = make_http(handler)
        await c.execute("/employees", params={"department": "技术部"})
        assert "department=" in seen["url"]
