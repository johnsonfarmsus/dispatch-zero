from typing import Any

import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache
from dispatchzero.integrations._throttle import MinIntervalThrottle

_BASE_URL = "https://nominatim.openstreetmap.org"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Module-level — one throttle per process. Nominatim policy is 1 req/sec absolute.
_throttle = MinIntervalThrottle(min_interval_seconds=1.0)


class NominatimClient:
    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": _USER_AGENT}
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def geocode(self, query: str) -> dict[str, Any] | None:
        key = f"nominatim:geocode:{query.strip().lower()}"
        cached = await self._cache.get(key)
        if cached is not None:
            return cached if cached else None  # treat empty dict as "no result"

        async with _throttle:
            r = await self._http.get(
                f"{_BASE_URL}/search",
                params={"q": query, "format": "json", "limit": 1},
            )
        r.raise_for_status()
        data = r.json()
        if not data:
            await self._cache.set(key, {}, _CACHE_TTL_SECONDS)
            return None
        first = data[0]
        result = {
            "lat": float(first["lat"]),
            "lng": float(first["lon"]),
            "display_name": first.get("display_name", ""),
        }
        await self._cache.set(key, result, _CACHE_TTL_SECONDS)
        return result
