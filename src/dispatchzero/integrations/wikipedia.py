"""Wikipedia geosearch + extracts integration.

Adds global coverage of encyclopedia-listed landmarks. Used as a tier-3
fallback in /missions/request when OSM strict and broad layers come up empty.
"""
from dataclasses import dataclass
from typing import Iterable

import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache
from dispatchzero.integrations._throttle import MinIntervalThrottle

_BASE_URL = "https://en.wikipedia.org/w/api.php"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_GEOSEARCH_TTL = 60 * 60 * 24 * 30  # 30 days
_EXTRACT_TTL = 60 * 60 * 24 * 90    # 90 days

# Wikipedia API etiquette: be polite. Process-local 250ms throttle.
_throttle = MinIntervalThrottle(min_interval_seconds=0.25)

# First-sentence patterns that mean "this article is a populated place" — exclude.
_POPULATED_PLACE_MARKERS = (
    " is a town in ",
    " is a city in ",
    " is a village in ",
    " is a community in ",
    " is an unincorporated community in ",
    " is a census-designated place ",
    " is a CDP ",
    " is a township ",
    " is a county ",
    " is a borough ",
    " is a hamlet ",
    " is a neighborhood ",
    " is a suburb ",
    " is a region ",
    " is a province ",
    " is a state ",
    " is a country ",
    " is a parish ",
)


@dataclass(frozen=True)
class WikipediaPlace:
    pageid: int
    title: str
    lat: float
    lng: float
    extract: str | None  # short plaintext intro from the article


class WikipediaClient:
    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def geosearch(
        self, *, lat: float, lng: float, radius_m: int, limit: int = 20,
    ) -> list[WikipediaPlace]:
        """Return Wikipedia articles within radius, with extracts populated.

        Auto-filters out populated-place articles (the town's own page, etc.).
        """
        clamped = min(radius_m, 10_000)  # Wikipedia geosearch maxes at 10km
        cache_key = f"wp:geosearch:{lat:.3f}:{lng:.3f}:{clamped}:{limit}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return [WikipediaPlace(**item) for item in cached]

        async with _throttle:
            r = await self._http.get(
                _BASE_URL,
                params={
                    "action": "query",
                    "list": "geosearch",
                    "gscoord": f"{lat}|{lng}",
                    "gsradius": clamped,
                    "gslimit": limit,
                    "gsnamespace": 0,  # mainspace only
                    "format": "json",
                },
            )
        try:
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return []

        raw = data.get("query", {}).get("geosearch", []) or []
        if not raw:
            await self._cache.set(cache_key, [], _GEOSEARCH_TTL)
            return []

        # Bulk-fetch extracts for all pageids in one call.
        pageids = [item["pageid"] for item in raw]
        extracts = await self._extracts(pageids)

        results: list[WikipediaPlace] = []
        for item in raw:
            pid = item["pageid"]
            extract = extracts.get(pid, "")
            if _looks_like_populated_place(extract):
                continue
            results.append(
                WikipediaPlace(
                    pageid=pid,
                    title=item["title"],
                    lat=float(item["lat"]),
                    lng=float(item["lon"]),
                    extract=extract or None,
                )
            )

        await self._cache.set(
            cache_key,
            [
                {
                    "pageid": p.pageid,
                    "title": p.title,
                    "lat": p.lat,
                    "lng": p.lng,
                    "extract": p.extract,
                }
                for p in results
            ],
            _GEOSEARCH_TTL,
        )
        return results

    async def _extracts(self, pageids: Iterable[int]) -> dict[int, str]:
        """Bulk-fetch first-paragraph plaintext for the given pageids."""
        ids = list(pageids)
        if not ids:
            return {}

        # Cache per-pageid so subsequent geosearches hit warm cache for shared articles.
        result: dict[int, str] = {}
        missing: list[int] = []
        for pid in ids:
            cached = await self._cache.get(f"wp:extract:{pid}")
            if cached is not None:
                result[pid] = cached if isinstance(cached, str) else ""
            else:
                missing.append(pid)

        if not missing:
            return result

        async with _throttle:
            try:
                r = await self._http.get(
                    _BASE_URL,
                    params={
                        "action": "query",
                        "prop": "extracts",
                        "exintro": "true",
                        "explaintext": "true",
                        "exsentences": 3,
                        "pageids": "|".join(str(i) for i in missing),
                        "format": "json",
                    },
                )
                r.raise_for_status()
                data = r.json()
            except (httpx.HTTPError, ValueError):
                return result  # what we have from cache

        pages = data.get("query", {}).get("pages", {}) or {}
        for pid_str, page in pages.items():
            try:
                pid = int(pid_str)
            except (TypeError, ValueError):
                continue
            extract = page.get("extract", "") or ""
            result[pid] = extract
            await self._cache.set(f"wp:extract:{pid}", extract, _EXTRACT_TTL)
        return result


def _looks_like_populated_place(extract: str) -> bool:
    """Heuristic: detect 'X is a town in Y' style articles."""
    if not extract:
        return False
    text = extract[:300].lower()
    return any(marker in text for marker in _POPULATED_PLACE_MARKERS)
