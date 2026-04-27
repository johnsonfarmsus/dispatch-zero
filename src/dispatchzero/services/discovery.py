import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.integrations.overpass import OverpassClient, OverpassPlace
from dispatchzero.integrations.wikidata import WikidataClient
from dispatchzero.models import Place, PlaceCategory, PlaceStatus, User, UserPlaceHistory
from dispatchzero.services.scoring import ScoreInput, score_place

_RE_ENTRY_DAYS = 90


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
) -> list[dict[str, Any]]:
    """Find, persist, score, filter, and return nearby places for `user`.

    `broad=True` widens the OSM tag set to include parks, peaks, places of
    worship, fountains, towers, and other named features. Used as a fallback
    tier when strict filters return nothing eligible.
    """
    cats = categories or list(PlaceCategory)

    overpass = OverpassClient(redis)
    wikidata = WikidataClient(redis)
    try:
        raw_places = await overpass.query_nearby(
            lat=lat, lng=lng, radius_m=radius_m, categories=cats, broad=broad,
        )
        named = [p for p in raw_places if p.name]
        stored: list[Place] = []
        for op in named:
            place = await _upsert_place(db, op, wikidata)
            stored.append(place)
        await db.commit()
    finally:
        await overpass.aclose()
        await wikidata.aclose()

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

    eligible = [
        p
        for p in stored
        if p.id not in recent_completed_ids and p.status == PlaceStatus.ACTIVE.value
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


async def _upsert_place(
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

    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one()
    return place


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
