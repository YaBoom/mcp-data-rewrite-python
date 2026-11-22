from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx


class HttpConnector:
    ALLOWED_ENDPOINTS = frozenset({"/employees", "/departments", "/projects"})

    def __init__(self, client: httpx.AsyncClient, *, timeout_s: float = 5.0) -> None:
        self._client = client
        self._timeout = timeout_s

    async def execute(
            self, endpoint: str, method: str = "GET", params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if endpoint not in self.ALLOWED_ENDPOINTS:
            raise PermissionError(f"未授权的API端点: {endpoint}")
        if method.upper() != "GET":                     # 补 P2 缺口
            raise PermissionError("api_call 仅支持 GET（读工具不暴露写动词）")

        try:
            resp = await self._client.get(
                endpoint, params=params or {}, timeout=self._timeout
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"API Error {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Network Error: {exc}") from exc

        return {
            "success": True,
            "endpoint": endpoint,
            "method": "GET",
            "data": resp.json(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }