import hashlib
from dataclasses import dataclass
from typing import Iterable

import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache
from dispatchzero.models import PlaceCategory

_BASE_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# OSM tag selectors per category. Keep these explicit and reviewable.
_CATEGORY_FILTERS: dict[PlaceCategory, list[str]] = {
    PlaceCategory.MURAL: [
        '["artwork_type"="mural"]',
    ],
    PlaceCategory.SCULPTURE: [
        '["tourism"="artwork"]["artwork_type"="sculpture"]',
        '["tourism"="artwork"]["artwork_type"="statue"]',
    ],
    PlaceCategory.MEMORIAL: [
        '["historic"="memorial"]',
        '["historic"="monument"]',
    ],
    PlaceCategory.HISTORIC: [
        '["historic"="building"]',
        '["historic"="ruins"]',
        '["historic"="archaeological_site"]',
    ],
    PlaceCategory.VIEWPOINT: ['["tourism"="viewpoint"]'],
}


@dataclass(frozen=True)
class OverpassPlace:
    osm_type: str
    osm_id: int
    lat: float
    lng: float
    tags: dict
    name: str | None
    category: PlaceCategory


def build_query(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    categories: Iterable[PlaceCategory],
) -> str:
    parts: list[str] = []
    for cat in categories:
        for filt in _CATEGORY_FILTERS[cat]:
            parts.append(f"node{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"way{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"relation{filt}(around:{radius_m},{lat},{lng});")
    body = "(" + "".join(parts) + ");"
    return f"[out:json][timeout:25];{body}out center tags;"


def _cache_key(lat: float, lng: float, radius_m: int, categories: list[PlaceCategory]) -> str:
    cat_hash = hashlib.sha1(",".join(sorted(c.value for c in categories)).encode()).hexdigest()[:8]
    return f"overpass:{lat:.3f}:{lng:.3f}:{radius_m}:{cat_hash}"


def _classify(tags: dict) -> PlaceCategory | None:
    """Map an OSM element's tags to one of our categories. First match wins."""
    artwork_type = tags.get("artwork_type")
    if artwork_type == "mural":
        return PlaceCategory.MURAL
    if artwork_type in ("sculpture", "statue"):
        return PlaceCategory.SCULPTURE
    historic = tags.get("historic")
    if historic in ("memorial", "monument"):
        return PlaceCategory.MEMORIAL
    if historic in ("building", "ruins", "archaeological_site"):
        return PlaceCategory.HISTORIC
    if tags.get("tourism") == "viewpoint":
        return PlaceCategory.VIEWPOINT
    if tags.get("tourism") == "artwork":
        # Generic artwork without a specific type — treat as sculpture by default
        return PlaceCategory.SCULPTURE
    return None


class OverpassClient:
    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": _USER_AGENT}
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def query_nearby(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        categories: list[PlaceCategory],
    ) -> list[OverpassPlace]:
        key = _cache_key(lat, lng, radius_m, categories)
        cached = await self._cache.get(key)
        if cached is not None:
            return [
                OverpassPlace(
                    osm_type=item["osm_type"],
                    osm_id=item["osm_id"],
                    lat=item["lat"],
                    lng=item["lng"],
                    tags=item["tags"],
                    name=item["name"],
                    category=PlaceCategory(item["category"]),
                )
                for item in cached
            ]

        query = build_query(lat=lat, lng=lng, radius_m=radius_m, categories=categories)
        r = await self._http.post(_BASE_URL, data={"data": query})
        r.raise_for_status()
        data = r.json()

        results: list[OverpassPlace] = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            cat = _classify(tags)
            if cat is None:
                continue
            if el["type"] == "node":
                lat_, lng_ = el.get("lat"), el.get("lon")
            else:
                center = el.get("center", {})
                lat_, lng_ = center.get("lat"), center.get("lon")
            if lat_ is None or lng_ is None:
                continue
            results.append(
                OverpassPlace(
                    osm_type=el["type"],
                    osm_id=el["id"],
                    lat=lat_,
                    lng=lng_,
                    tags=tags,
                    name=tags.get("name"),
                    category=cat,
                )
            )

        await self._cache.set(
            key,
            [
                {
                    "osm_type": p.osm_type,
                    "osm_id": p.osm_id,
                    "lat": p.lat,
                    "lng": p.lng,
                    "tags": p.tags,
                    "name": p.name,
                    "category": p.category.value,
                }
                for p in results
            ],
            _CACHE_TTL_SECONDS,
        )
        return results
