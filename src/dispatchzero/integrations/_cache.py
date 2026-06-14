import json
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)


class JsonCache:
    """Thin Redis JSON cache. Keys are namespaced by the caller.

    Fail-soft by design: a cache must never take down the request path. If
    Redis is unreachable or refusing writes (e.g. MISCONF when the host disk
    is full), get() degrades to a miss and set() becomes a no-op. The caller
    transparently falls back to its source of truth.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._r.get(key)
        except RedisError as e:
            log.warning("cache get failed (key=%s), treating as miss: %s", key, e)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self._r.set(key, json.dumps(value), ex=ttl_seconds)
        except RedisError as e:
            log.warning("cache set failed (key=%s), skipping write: %s", key, e)
