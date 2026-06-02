import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.integrations.overpass import OverpassClient, OverpassPlace
from dispatchzero.integrations.wikidata import WikidataClient
from dispatchzero.integrations.wikipedia import WikipediaClient, WikipediaPlace
from dispatchzero.models import (
    Place,
    PlaceCategory,
    PlaceStatus,
    User,
    UserPlaceExclusion,
    UserPlaceHistory,
)
from dispatchzero.services.scoring import ScoreInput, score_place

# Re-entry window: a place a user has already completed won't be re-dispatched
# to them within this window. Dropped from 90 to 30 days when the list-of-
# candidates UI landed — with multiple candidates per request the lockout
# matters less than freshness for small-town users with limited local pools.
# Re-dispatched missions are also force-regenerated (see services.missions —
# repeat_visit), so a place coming back at day 31 gets a fresh briefing, not
# the same one the user already read.
_RE_ENTRY_DAYS = 30

Source = Literal["overpass", "wikipedia", "local"]

# Safety filter: never direct users to places primarily occupied by minors.
# Substring match (case-insensitive). False positives (e.g. "Old Schoolhouse
# Museum") are an acceptable cost — we err on the side of exclusion.
# Applied at ingestion (so excluded names never enter the DB) AND at the
# eligibility filter (so anything already in the DB from prior runs is also
# excluded — defense in depth).
_NAME_EXCLUSIONS: tuple[str, ...] = (
    "school",
    "academy",
    "elementary",
    "kindergarten",
    "preschool",
    "daycare",
)


def _excluded_by_name(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.lower()
    return any(token in lowered for token in _NAME_EXCLUSIONS)


async def discover_nearby(
    *,
    db: AsyncSession,
    redis: aioredis.Redis,
    user: User,
    lat: float,
    lng: float,
    radius_m: int,
    limit: int,
    categories: list[PlaceCategory] | None = None,
    broad: bool = False,
    source: Source = "overpass",
) -> list[dict[str, Any]]:
    """Find, persist, score, filter, and return nearby places for `user`.

    `source="overpass"` (default): query OpenStreetMap. With `broad=True`,
    widens the tag set to parks, peaks, places of worship, fountains, etc.

    `source="wikipedia"`: query Wikipedia geosearch. Returns encyclopedia-listed
    landmarks regardless of OSM presence — global coverage. The `broad` flag is
    ignored for Wikipedia.
    """
    cats = categories or list(PlaceCategory)

    if source == "overpass":
        stored = await _ingest_overpass(db, redis, lat, lng, radius_m, cats, broad)
    elif source == "wikipedia":
        stored = await _ingest_wikipedia(db, redis, lat, lng, radius_m)
    elif source == "local":
        stored = await _ingest_local(db, lat, lng, radius_m)
    else:
        raise ValueError(f"unknown source: {source!r}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=_RE_ENTRY_DAYS)
    recent_completed_ids = set(
        (
            await db.execute(
                select(UserPlaceHistory.place_id).where(
                    UserPlaceHistory.user_id == user.id,
                    UserPlaceHistory.last_completed_at > cutoff,
                )
            )
        ).scalars()
    )
    # User-reported permanent exclusions ("this place isn't really there /
    # can't be reached"). One report from the user removes it from THEIR
    # eligibility forever — distinct from the time-windowed completion filter.
    user_excluded_ids = set(
        (
            await db.execute(
                select(UserPlaceExclusion.place_id).where(
                    UserPlaceExclusion.user_id == user.id,
                )
            )
        ).scalars()
    )

    eligible = [
        p
        for p in stored
        if p.id not in recent_completed_ids
        and p.id not in user_excluded_ids
        and p.status == PlaceStatus.ACTIVE.value
        and not _excluded_by_name(p.name)
    ]

    scored = sorted(
        eligible,
        key=lambda p: score_place(
            ScoreInput(
                name=p.name,
                description=p.description,
                has_wikidata=bool(p.wikidata_id),
                category=PlaceCategory(p.category),
                thumbs_up=p.location_thumbs_up,
                thumbs_down=p.location_thumbs_down,
            )
        ),
        reverse=True,
    )[:limit]

    return [_serialize_place(p) for p in scored]


# ---- per-source ingestion ----


async def _ingest_overpass(
    db: AsyncSession,
    redis: aioredis.Redis,
    lat: float,
    lng: float,
    radius_m: int,
    cats: list[PlaceCategory],
    broad: bool,
) -> list[Place]:
    overpass = OverpassClient(redis)
    wikidata = WikidataClient(redis)
    try:
        raw = await overpass.query_nearby(
            lat=lat, lng=lng, radius_m=radius_m, categories=cats, broad=broad,
        )
        named = [p for p in raw if p.name and not _excluded_by_name(p.name)]
        stored: list[Place] = []
        for op in named:
            place = await _upsert_overpass_place(db, op, wikidata)
            stored.append(place)
        await db.commit()
        return stored
    finally:
        await overpass.aclose()
        await wikidata.aclose()


async def _ingest_wikipedia(
    db: AsyncSession,
    redis: aioredis.Redis,
    lat: float,
    lng: float,
    radius_m: int,
) -> list[Place]:
    wp = WikipediaClient(redis)
    try:
        raw = await wp.geosearch(lat=lat, lng=lng, radius_m=radius_m, limit=20)
        named = [p for p in raw if p.title and not _excluded_by_name(p.title)]
        stored: list[Place] = []
        for wpp in named:
            place = await _upsert_wikipedia_place(db, wpp)
            stored.append(place)
        await db.commit()
        return stored
    finally:
        await wp.aclose()


async def _ingest_local(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_m: int,
) -> list[Place]:
    """Query the places table directly via PostGIS for any pre-stored places
    within radius. Used as the last tier — surfaces curated/imported data
    (GNIS, future manual entries) when external sources came up empty.

    Doesn't hit any external API. Returns whatever the DB has within radius
    of (lat, lng); downstream eligibility + scoring filters do the rest.
    """
    # ST_DWithin on geography type uses meters directly. Wrap the point
    # literal in ST_GeogFromText so the planner sees both args as geography
    # (asyncpg's typed-bind path won't auto-cast a bare string).
    target = func.ST_GeogFromText(f"SRID=4326;POINT({lng} {lat})")
    rows = (
        await db.execute(
            select(Place).where(
                func.ST_DWithin(Place.coordinates, target, radius_m)
            )
        )
    ).scalars().all()
    return list(rows)


# ---- upserts ----


async def _upsert_overpass_place(
    db: AsyncSession, op: OverpassPlace, wikidata: WikidataClient
) -> Place:
    qid = op.tags.get("wikidata")
    description = await wikidata.get_description(qid) if qid else None

    stmt = (
        pg_insert(Place)
        .values(
            id=uuid.uuid4(),
            osm_type=op.osm_type,
            osm_id=op.osm_id,
            name=op.name,
            category=op.category.value,
            coordinates=f"SRID=4326;POINT({op.lng} {op.lat})",
            tags=op.tags,
            description=description,
            wikidata_id=qid,
        )
        .on_conflict_do_update(
            index_elements=["osm_type", "osm_id"],
            set_={
                "name": op.name,
                "category": op.category.value,
                "tags": op.tags,
                "description": description,
                "wikidata_id": qid,
                "coordinates": f"SRID=4326;POINT({op.lng} {op.lat})",
            },
        )
        .returning(Place.id)
    )

    result = await db.execute(stmt)
    place_id = result.scalar_one()
    return (await db.execute(select(Place).where(Place.id == place_id))).scalar_one()


async def _upsert_wikipedia_place(db: AsyncSession, wpp: WikipediaPlace) -> Place:
    category = _classify_wikipedia(wpp.title, wpp.extract or "")
    tags = {"source": "wikipedia", "title": wpp.title}

    stmt = (
        pg_insert(Place)
        .values(
            id=uuid.uuid4(),
            osm_type="wp",
            osm_id=wpp.pageid,
            name=wpp.title,
            category=category.value,
            coordinates=f"SRID=4326;POINT({wpp.lng} {wpp.lat})",
            tags=tags,
            description=wpp.extract,
            wikidata_id=None,
        )
        .on_conflict_do_update(
            index_elements=["osm_type", "osm_id"],
            set_={
                "name": wpp.title,
                "category": category.value,
                "tags": tags,
                "description": wpp.extract,
                "coordinates": f"SRID=4326;POINT({wpp.lng} {wpp.lat})",
            },
        )
        .returning(Place.id)
    )

    result = await db.execute(stmt)
    place_id = result.scalar_one()
    return (await db.execute(select(Place).where(Place.id == place_id))).scalar_one()


def _classify_wikipedia(title: str, extract: str) -> PlaceCategory:
    """Best-effort category from title + first-paragraph keywords. Defaults to HISTORIC.

    Wikipedia's geosearch hits a wide range of articles. Most local landmarks
    that warrant a Wikipedia article are 'historic' for our purposes. We do
    light pattern-matching to push obvious sculptures/parks/memorials into
    their right buckets.
    """
    text = f"{title} {extract}".lower()
    if "mural" in text:
        return PlaceCategory.MURAL
    if any(w in text for w in (" sculpture", " statue", "fountain")):
        return PlaceCategory.SCULPTURE
    if any(w in text for w in ("memorial", "monument", "obelisk", "cenotaph")):
        return PlaceCategory.MEMORIAL
    if any(w in text for w in (" park", "viewpoint", "overlook", "summit", " peak", "trailhead", "lookout")):
        return PlaceCategory.VIEWPOINT
    return PlaceCategory.HISTORIC


def _serialize_place(p: Place) -> dict[str, Any]:
    return {
        "id": p.id,
        "osm_type": p.osm_type,
        "osm_id": p.osm_id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "wikidata_id": p.wikidata_id,
        "thumbs_up": p.location_thumbs_up,
        "thumbs_down": p.location_thumbs_down,
    }
