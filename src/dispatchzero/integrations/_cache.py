import json
from typing import Any

import redis.asyncio as aioredis


class JsonCache:
    """Thin Redis JSON cache. Keys are namespaced by the caller."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._r.set(key, json.dumps(value), ex=ttl_seconds)
