import asyncio
import time


class MinIntervalThrottle:
    """Async context manager that enforces a minimum gap between successive entries.

    Process-local. Sufficient for a single app process with sub-1-req/sec ceilings
    (Nominatim's stated limit). For multi-process coordination, swap for a
    Redis-token-bucket later.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._lock = asyncio.Lock()
        self._min_interval = min_interval_seconds
        self._last_call: float = 0.0

    async def __aenter__(self) -> "MinIntervalThrottle":
        await self._lock.acquire()
        gap = time.monotonic() - self._last_call
        if gap < self._min_interval:
            await asyncio.sleep(self._min_interval - gap)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._last_call = time.monotonic()
        self._lock.release()
