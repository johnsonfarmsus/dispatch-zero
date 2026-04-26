import redis.asyncio as aioredis


class LoginRateLimiter:
    def __init__(
        self,
        redis: aioredis.Redis,
        max_attempts: int,
        window_seconds: int,
    ) -> None:
        self._r = redis
        self._max = max_attempts
        self._window = window_seconds

    @staticmethod
    def _key(ip: str) -> str:
        return f"rl:login:{ip}"

    async def is_allowed(self, ip: str) -> bool:
        count = await self._r.get(self._key(ip))
        return count is None or int(count) < self._max

    async def record_failure(self, ip: str) -> None:
        key = self._key(ip)
        # Atomic INCR; set TTL on first increment only (NX prevents extending the window).
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._window, nx=True)
            await pipe.execute()
