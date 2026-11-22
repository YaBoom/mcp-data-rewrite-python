from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

class RedisLike(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

_JSON_TYPE = {
    bool: "boolean",       # 必须放在 int 前面，bool 是 int 的子类
    int: "number",
    float: "number",
    str: "string",
    list: "object",
    dict: "object",
    type(None): "object",
}


def json_type_name(value: Any) -> str:
    """对齐 JS 的 typeof，供对拍使用。"""
    return _JSON_TYPE.get(type(value), "object")


class RedisConnector:
    def __init__(
            self, client: RedisLike, *, key_prefix: str = "erp:", timeout_s: float = 2.0
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self._timeout = timeout_s

    async def execute(self, key: str) -> dict[str, Any]:
        if not key.startswith(self._prefix):
            raise PermissionError(
                f"仅允许访问 {self._prefix}* 命名空间，拒绝 key: {key}"
            )

        try:
            raw = await asyncio.wait_for(self._client.get(key), timeout=self._timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise TimeoutError(f"Redis 读取超时（>{self._timeout}s）") from exc
        except Exception as exc:
            raise RuntimeError(f"Redis操作失败: {exc}") from exc

        if raw is None:
            return {
                "success": True,
                "exists": False,
                "message": f"Key '{key}' not found",
            }

        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw

        return {
            "success": True,
            "exists": True,
            "key": key,
            "value": value,
            "type": json_type_name(value),
        }