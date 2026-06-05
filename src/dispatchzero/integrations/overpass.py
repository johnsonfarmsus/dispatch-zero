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

# OSM tag selectors per category.
#
# STRICT tier (this dict): the curated, high-signal cultural/artistic finds.
# Tier 1 of the dispatch ladder queries these — what we want users to find
# first when they request a dispatch. Murals, sculptures, monuments,
# memorials, narrow-definition historic buildings, viewpoints. Anything in
# strict has been hand-picked for "this is the kind of thing the game is
# really about."
#
# BROAD tier (the dict below): everything else worth visiting that's
# common enough to warrant inclusion but doesn't rise to "primary find"
# status — churches, post offices, libraries, cemeteries, parks, peaks,
# waterfalls, etc. Tiers 2 and 4 of the ladder pull from broad.
#
# The strict-first bias preserves the game's character: a user in an
# art-rich town gets art before they get a post office.
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
    # CIVIC intentionally absent from strict: post offices / libraries /
    # town halls are everyday landmarks, not primary finds. They live in
    # broad below so users discover them after the art layer is exhausted.
}

# Broad tier — populated for nearly every category. Pulls in named parks,
# places of worship, post offices, libraries, town halls, cemeteries,
# peaks, fountains, towers, etc. Quality bar drops; coverage rises.
# The full GNIS layer used to backfill these gaps; OSM coverage of the
# same data is consistently better, so as of the 0019-ish refactor we
# pull everything from OSM and the local DB is empty.
_BROAD_CATEGORY_FILTERS: dict[PlaceCategory, list[str]] = {
    PlaceCategory.MURAL: [],  # nothing reasonable to add here
    PlaceCategory.SCULPTURE: [
        '["amenity"="fountain"]["name"]',
        '["man_made"="sculpture"]["name"]',
    ],
    PlaceCategory.MEMORIAL: [
        '["historic"="wayside_cross"]["name"]',
        '["historic"="wayside_shrine"]["name"]',
        # Cemeteries function as memorials — every headstone is one,
        # and the whole site reads as a memorial landscape. Require name
        # to filter out generic plots.
        '["landuse"="cemetery"]["name"]',
        '["amenity"="grave_yard"]["name"]',
        # Roadside historical markers / mile markers / boundary stones.
        '["historic"="cannon"]["name"]',
        '["historic"="milestone"]["name"]',
        '["historic"="boundary_marker"]["name"]',
    ],
    PlaceCategory.HISTORIC: [
        # Note: place_of_worship MOVED to CHURCH broad below where it
        # belongs semantically. Historic broad now keeps only the
        # specific historic-building types.
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
    # New in the broad-tier expansion: pull churches, post offices,
    # libraries, town halls directly from OSM. Each requires a name so
    # we don't surface generic chapel-shaped buildings or PO boxes.
    PlaceCategory.CHURCH: [
        '["amenity"="place_of_worship"]["name"]',
    ],
    PlaceCategory.CIVIC: [
        '["amenity"="post_office"]["name"]',
        '["amenity"="library"]["name"]',
        '["amenity"="townhall"]["name"]',
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
    """Build an Overpass QL string covering every requested category's
    strict filters (plus broad filters when broad=True).

    Only node + way are queried. relation is intentionally excluded:
    on real-world Overpass servers, an `around:` filter on relation
    can trip on a large nearby boundary multi-polygon and time the
    whole query out at 25-30s with zero useful results returned.
    Almost no POI we care about is a relation (place_of_worship is
    ~always a node or way; same for art, viewpoints, post offices).
    """
    parts: list[str] = []
    for cat in categories:
        filters = list(_CATEGORY_FILTERS.get(cat, []))
        if broad:
            filters.extend(_BROAD_CATEGORY_FILTERS.get(cat, []))
        for filt in filters:
            parts.append(f"node{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"way{filt}(around:{radius_m},{lat},{lng});")
    body = "(" + "".join(parts) + ");"
    # Generous timeout — broad queries with many filters can be heavy.
    return f"[out:json][timeout:60];{body}out center tags;"


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
    # place_of_worship now goes to CHURCH (was HISTORIC) so the broad
    # tier surfaces churches as their own category rather than mixed
    # with castles, ruins, and lighthouses.
    if amenity == "place_of_worship":
        return PlaceCategory.CHURCH
    if amenity in ("post_office", "library", "townhall"):
        return PlaceCategory.CIVIC
    if amenity == "grave_yard":
        return PlaceCategory.MEMORIAL
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
    # landuse=cemetery (the polygon variant; amenity=grave_yard is the
    # smaller parish-style alternative handled above).
    if tags.get("landuse") == "cemetery":
        return PlaceCategory.MEMORIAL
    # Extra historic-marker variants surfaced via the broad MEMORIAL tier.
    if historic in ("cannon", "milestone", "boundary_marker"):
        return PlaceCategory.MEMORIAL
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
