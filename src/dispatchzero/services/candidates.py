"""Candidate-list generation — Stage 3 multi-option dispatch flow.

The user requests a dispatch and gets back N options to pick from, each
with a one-sentence teaser. They pick one → transit. The unpicked ones
keep their generated briefings in the library so future users at those
places benefit from the pre-warm.

Two pieces:

- `gather_candidate_places(...)`: walks the same tiers `discover_nearby`
  uses but DOESN'T stop at the first hit. Collects up to N total places
  from multiple tiers (Overpass strict → broad → Wikipedia → local).
  Returns a deduplicated, scored list. Solves the airport-lockout problem
  from Trevor's trip: high-priority tiers no longer monopolize the slate.

- `generate_candidate_missions(...)`: fans out parallel mission
  generations for the chosen N places via asyncio.gather. The shared
  AsyncSession isn't safe for concurrent ops, so each generation gets its
  own session via the engine. Wall-clock = slowest single generation
  (~30s on the OLMo box) rather than sum-of-three (~90s).

The route layer (`POST /missions/candidates`) calls these two in sequence
and returns the list. The accept endpoint just records the user's pick.
"""
import asyncio
import math
import uuid
from typing import Literal

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatchzero.config import get_settings
from dispatchzero.models import Mission, Place, User
from dispatchzero.services.discovery import discover_nearby

AdventureStyle = Literal["pulp", "agency", "guild"]

# Per-tier (radius_m, source, broad) — mirrors _REQUEST_TIERS in
# missions/routes.py but accumulates across tiers instead of stopping at
# the first hit. Five-tier ladder: close art first, broaden the OSM net,
# fall through to Wikipedia, then a wider OSM sweep.
#
# Tier 5 (10km local GNIS) was removed when the broad-tier expansion
# absorbed all the categories GNIS used to cover (churches, post offices,
# parks, trails, etc.). OSM coverage of the same coordinates is better,
# so the local fallback was costing quality more than it contributed.
_CANDIDATE_TIERS: list[tuple[int, str, bool]] = [
    (2000, "overpass", False),   # Tier 0: 2km narrow OSM (caller's default radius)
    (5000, "overpass", False),   # Tier 1: 5km strict OSM — art-first
    (5000, "overpass", True),    # Tier 2: 5km broad OSM
    (5000, "wikipedia", False),  # Tier 3: Wikipedia geosearch
    (10000, "overpass", True),   # Tier 4: 10km broad OSM
    (10000, "local", False),     # Tier 5: 10km local DB — surfaces community
                                 # submissions that aren't on OSM yet.
]


async def gather_candidate_places(
    *,
    db: AsyncSession,
    redis: aioredis.Redis,
    user: User,
    lat: float,
    lng: float,
    request_radius_m: int,
    target_count: int = 3,
) -> list[dict]:
    """Walk tiers and accumulate up to `target_count` unique candidate places.

    Doesn't stop at first hit — that's the structural fix for the trip
    feedback where the Davenport airport (Wikipedia tier) blocked GNIS-tier
    cemeteries from ever surfacing. Now both tiers contribute to the same
    slate; the user picks.

    Returns a list of place dicts (same shape as `discover_nearby`). Already
    deduped and capped at `target_count`. May return fewer than target_count
    if the geographic pool is genuinely sparse — the route layer surfaces
    that as the "nothing fresh, try another region" message.
    """
    # Tier 0 gets the caller's preferred radius if different from the default.
    tiers = [(request_radius_m, "overpass", False)] + [
        t for t in _CANDIDATE_TIERS if t != (request_radius_m, "overpass", False)
    ]

    seen_keys: set[tuple[int, str, bool]] = set()
    seen_place_ids: set[uuid.UUID] = set()
    candidates: list[dict] = []

    for radius_m, source, broad in tiers:
        key = (radius_m, source, broad)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if len(candidates) >= target_count:
            break
        try:
            # Ask for more than we need — we'll dedupe and pick top-N. Asking
            # for 1 per tier would force us to do tier-by-tier; over-asking
            # lets us see what each tier offers in one round.
            tier_results = await discover_nearby(
                db=db, redis=redis, user=user,
                lat=lat, lng=lng,
                radius_m=radius_m, limit=target_count * 2,
                broad=broad, source=source,
            )
        except httpx.HTTPError:
            # Transient upstream failure — skip this tier and try the next.
            # Matches existing /missions/request resilience pattern.
            continue
        for p in tier_results:
            if p["id"] in seen_place_ids:
                continue
            seen_place_ids.add(p["id"])
            candidates.append(p)
            if len(candidates) >= target_count:
                break

    return candidates[:target_count]


async def generate_candidate_missions(
    *,
    user: User,
    place_ids: list[uuid.UUID],
    adventure_style: str,
) -> list[Mission | Exception]:
    """Generate missions for a list of places SEQUENTIALLY.

    Why sequential and not parallel: live testing against the OLMo 2 13B
    inference box (single GPU, single model loaded) showed asyncio.gather
    didn't actually parallelize — concurrent requests queued at the model
    server. Three "parallel" requests took ~120s wall-clock (same as
    sequential) AND surfaced occasional empty-error transport timeouts
    when queue-induced waits ate the 60s per-request budget.

    Sequential delivers the same wall-clock (~90s for 3 generations on
    OLMo) with zero contention failures. If we ever switch to a model
    backend with real concurrency headroom (cloud-hosted, multi-GPU,
    different model), revisit and try gather again.

    Each generation gets its own AsyncSession (NullPool, short-lived) —
    the shared request-scoped session can't safely hold across long awaits.
    Failures don't poison successes: returns a mixed list where failed
    slots hold the Exception; caller decides what to do.

    Lazy-imports get_or_generate_mission to avoid a circular dep between
    services.missions and services.candidates.
    """
    from dispatchzero.services.missions import get_or_generate_mission

    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    results: list[Mission | Exception] = []
    try:
        for pid in place_ids:
            async with SessionLocal() as task_db:
                # Re-fetch the user inside this session — passing a user
                # from one session into another breaks SQLAlchemy's identity
                # map invariants.
                local_user = (
                    await task_db.execute(select(User).where(User.id == user.id))
                ).scalar_one()
                try:
                    mission = await get_or_generate_mission(
                        db=task_db, user=local_user,
                        place_id=pid, adventure_style=adventure_style,
                    )
                    results.append(mission)
                except Exception as e:  # noqa: BLE001
                    results.append(e)
    finally:
        await engine.dispose()
    return results


def distance_and_bearing_m(
    *, from_lat: float, from_lng: float, to_lat: float, to_lng: float
) -> tuple[int, str]:
    """Great-circle distance in meters + coarse 8-point compass bearing.

    Haversine for distance, standard initial-bearing formula then snapped
    to one of (N, NE, E, SE, S, SW, W, NW). Good enough for "the cemetery
    is 0.4 km NE" — we don't need surveyor-grade precision for a card on
    a phone screen.
    """
    R = 6_371_000.0  # earth radius m
    p1 = math.radians(from_lat)
    p2 = math.radians(to_lat)
    dp = math.radians(to_lat - from_lat)
    dl = math.radians(to_lng - from_lng)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_m = int(R * c)

    y = math.sin(dl) * math.cos(p2)
    x = (math.cos(p1) * math.sin(p2)
         - math.sin(p1) * math.cos(p2) * math.cos(dl))
    bearing_deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((bearing_deg + 22.5) // 45) % 8
    return distance_m, compass[idx]


def empty_message(request_lat: float, request_lng: float) -> str:
    """In-voice "nothing fresh here" message. Currently static; future versions
    could compute the direction to the nearest unfamiliar pool of places."""
    return (
        "No fresh candidates in range, agent. You've worked this ground. "
        "Expand the radius or move to new territory."
    )
