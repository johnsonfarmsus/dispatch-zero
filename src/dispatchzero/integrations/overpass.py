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

# Broader fallback filters — used when the strict set returns no eligible results.
# These pull in named parks, places of worship, peaks, fountains, towers, etc.
# Quality bar drops; coverage rises.
_BROAD_CATEGORY_FILTERS: dict[PlaceCategory, list[str]] = {
    PlaceCategory.MURAL: [],  # nothing reasonable to add here
    PlaceCategory.SCULPTURE: [
        '["amenity"="fountain"]["name"]',
        '["man_made"="sculpture"]["name"]',
    ],
    PlaceCategory.MEMORIAL: [
        '["historic"="wayside_cross"]["name"]',
        '["historic"="wayside_shrine"]["name"]',
    ],
    PlaceCategory.HISTORIC: [
        '["amenity"="place_of_worship"]["name"]',
        '["historic"="castle"]["name"]',
        '["historic"="manor"]["name"]',
        '["historic"="fort"]["name"]',
        '["historic"="ship"]["name"]',
        '["man_made"="lighthouse"]["name"]',
        '["man_made"="watermill"]["name"]',
        '["man_made"="windmill"]["name"]',
        '["man_made"="tower"]["name"]',
    ],
    PlaceCategory.VIEWPOINT: [
        '["natural"="peak"]["name"]',
        '["natural"="waterfall"]["name"]',
        '["leisure"="park"]["name"]',
        '["tourism"="attraction"]["name"]',
    ],
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
    broad: bool = False,
) -> str:
    parts: list[str] = []
    for cat in categories:
        # Some categories (e.g. CHURCH) intentionally have no OSM query —
        # they're sourced exclusively from GNIS / the local DB tier.
        filters = list(_CATEGORY_FILTERS.get(cat, []))
        if broad:
            filters.extend(_BROAD_CATEGORY_FILTERS.get(cat, []))
        for filt in filters:
            parts.append(f"node{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"way{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"relation{filt}(around:{radius_m},{lat},{lng});")
    body = "(" + "".join(parts) + ");"
    return f"[out:json][timeout:25];{body}out center tags;"


def _cache_key(
    lat: float, lng: float, radius_m: int,
    categories: list[PlaceCategory], broad: bool,
) -> str:
    cat_hash = hashlib.sha1(",".join(sorted(c.value for c in categories)).encode()).hexdigest()[:8]
    suffix = "b" if broad else "s"
    return f"overpass:{lat:.3f}:{lng:.3f}:{radius_m}:{cat_hash}:{suffix}"


def _classify(tags: dict) -> PlaceCategory | None:
    """Map an OSM element's tags to one of our categories. First match wins.

    Includes both strict (artwork/historic core) and broad (parks, peaks,
    places of worship, fountains, towers, etc.) tag patterns. The query layer
    decides which set of OSM features get fetched; classify covers everything
    that might come back.
    """
    # ----- Strict patterns first (more specific) -----
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
    if historic in ("wayside_cross", "wayside_shrine"):
        return PlaceCategory.MEMORIAL
    if historic in ("castle", "manor", "fort", "ship"):
        return PlaceCategory.HISTORIC
    if tags.get("tourism") == "viewpoint":
        return PlaceCategory.VIEWPOINT
    if tags.get("tourism") == "artwork":
        return PlaceCategory.SCULPTURE

    # ----- Broad patterns (only relevant when broad mode pulled them in) -----
    amenity = tags.get("amenity")
    if amenity == "fountain":
        return PlaceCategory.SCULPTURE
    if amenity == "place_of_worship":
        return PlaceCategory.HISTORIC
    man_made = tags.get("man_made")
    if man_made == "sculpture":
        return PlaceCategory.SCULPTURE
    if man_made in ("lighthouse", "watermill", "windmill", "tower"):
        return PlaceCategory.HISTORIC
    natural = tags.get("natural")
    if natural in ("peak", "waterfall"):
        return PlaceCategory.VIEWPOINT
    if tags.get("leisure") == "park":
        return PlaceCategory.VIEWPOINT
    if tags.get("tourism") == "attraction":
        return PlaceCategory.VIEWPOINT
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
        broad: bool = False,
    ) -> list[OverpassPlace]:
        key = _cache_key(lat, lng, radius_m, categories, broad)
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

        query = build_query(
            lat=lat, lng=lng, radius_m=radius_m, categories=categories, broad=broad,
        )
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
