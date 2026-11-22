# connectors/asyncmy_pool.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import asyncmy
from asyncmy.cursors import DictCursor


class AsyncmyPool:
    def __init__(self, pool: asyncmy.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(
            cls, *, host: str, user: str, password: str,
            database: str, pool_size: int = 10,
    ) -> "AsyncmyPool":
        pool = await asyncmy.create_pool(
            host=host, user=user, password=password, database=database,
            minsize=1, maxsize=pool_size, autocommit=True,
        )
        return cls(pool)

    async def fetch_all(
            self, sql: str, params: tuple[Any, ...]
    ) -> list[Mapping[str, Any]]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:   # ★ 脱敏的前提
                await cur.execute(sql, params or None)
                return list(await cur.fetchall())

    async def close(self) -> None:
        self._pool.close()
        await self._pool.wait_closed()