import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache

_BASE_URL = "https://www.wikidata.org/w/api.php"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


class WikidataClient:
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

    async def get_description(self, qid: str) -> str | None:
        """Return the English Wikidata description for a Q-ID, or None on miss/error."""
        key = f"wikidata:desc:{qid}"
        cached = await self._cache.get(key)
        if cached is not None:
            return cached or None  # empty string sentinel = "we know there isn't one"

        try:
            r = await self._http.get(
                _BASE_URL,
                params={
                    "action": "wbgetentities",
                    "ids": qid,
                    "props": "descriptions",
                    "languages": "en",
                    "format": "json",
                },
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return None  # fail open — Wikidata is enrichment, not required

        try:
            desc = data["entities"][qid]["descriptions"]["en"]["value"]
        except (KeyError, TypeError):
            await self._cache.set(key, "", _CACHE_TTL_SECONDS)
            return None

        await self._cache.set(key, desc, _CACHE_TTL_SECONDS)
        return desc
