"""Pre-flight OSM check for community submissions.

After a user submits a POI, we fire one Overpass query for OSM nodes/
ways at the same category within ~50m of the submitted coordinates.
The result is stored on the submission row and surfaced to the admin
in the review queue as a heads-up: "OSM has 2 nearby place_of_worship
nodes you should look at before approving."

Design posture: ADVISORY. The pre-flight does not gate approval or
publish actions. False positives (an OSM node that's actually a
different church across the street) and false negatives (OSM has the
place but tagged it differently) are both expected; the admin's
clickable OSM map link is the ground truth.

Each match returned:
    {
        "name": "...",
        "osm_type": "node" | "way",
        "osm_id": 12345,
        "osm_url": "https://www.openstreetmap.org/node/12345",
        "distance_m": 12,
        "tags_summary": "amenity=place_of_worship · religion=christian",
    }

Categories with no liberal-match shape (e.g. "mural" inside the
broader artwork umbrella) use the broadest reasonable tag bundle so
we catch near-misses. Better to surface a possible duplicate than
to miss it.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dispatchzero.config import get_settings
from dispatchzero.db import get_engine
from dispatchzero.models import Submission

log = logging.getLogger(__name__)

# Search radius for the pre-flight Overpass query. 50m is tight enough
# that "I submitted a mural across the street from the post office"
# doesn't false-match, while still catching genuine duplicate work.
_RADIUS_M = 50

# How long we wait for Overpass. Keep tight — the admin queue would
# rather see "check pending" than have the background task hang for
# a minute. If a single check fails, we just leave checked_at NULL
# and the queue shows the pending state.
_TIMEOUT_S = 15

# Liberal Overpass selectors per our category. Each entry is a list of
# tag fragments OR'd together via Overpass union syntax. We deliberately
# query BROADER than what we'd publish — for "mural", we look for any
# tourism=artwork node, since OSM might have it tagged as a generic
# artwork without the artwork_type=mural specifier.
_PREFLIGHT_SELECTORS: dict[str, list[str]] = {
    "mural":          ['["tourism"="artwork"]'],
    "sculpture":      ['["tourism"="artwork"]', '["man_made"="sculpture"]'],
    "memorial":       ['["historic"~"memorial|monument|wayside_cross|wayside_shrine|cannon|milestone|boundary_marker"]'],
    "historic":       ['["historic"]'],
    "viewpoint":      ['["tourism"="viewpoint"]', '["natural"~"peak|waterfall"]', '["leisure"="park"]'],
    "church":         ['["amenity"="place_of_worship"]'],
    "park":           ['["leisure"="park"]', '["leisure"="garden"]'],
    "infrastructure": ['["man_made"~"bridge|tower|silo|windmill|watermill|lighthouse|pumping_station"]', '["waterway"="dam"]'],
    "civic":          ['["amenity"~"post_office|library|townhall|community_centre"]'],
}


def _km(lat1, lng1, lat2, lng2):
    R = 6371
    dl = math.radians(lng2 - lng1)
    dp = math.radians(lat2 - lat1)
    x = (
        math.sin(dp / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dl / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _build_query(*, category: str, lat: float, lng: float) -> str | None:
    selectors = _PREFLIGHT_SELECTORS.get(category)
    if not selectors:
        return None
    parts: list[str] = []
    for sel in selectors:
        parts.append(f"node{sel}(around:{_RADIUS_M},{lat},{lng});")
        parts.append(f"way{sel}(around:{_RADIUS_M},{lat},{lng});")
    body = "(" + "".join(parts) + ");"
    # Modest timeout — Overpass is usually fast for tight-radius queries.
    return f"[out:json][timeout:25];{body}out center tags;"


def _summarize_tags(t: dict) -> str:
    """Pick a few high-signal tags to render as 'k=v · k=v' on the card.
    Skips noisy / long tags like description, wikipedia URLs."""
    keep_keys = (
        "amenity", "historic", "tourism", "artwork_type", "religion",
        "denomination", "man_made", "leisure", "natural", "waterway",
    )
    bits = [f"{k}={t[k]}" for k in keep_keys if k in t]
    return " · ".join(bits[:4])


async def _run_overpass(query: str) -> list[dict]:
    settings = get_settings()
    headers = {"User-Agent": settings.osm_user_agent}
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, headers=headers) as c:
        try:
            r = await c.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
            if r.status_code != 200:
                log.warning("OSM pre-flight overpass HTTP %s", r.status_code)
                return []
            return r.json().get("elements", []) or []
        except (httpx.HTTPError, ValueError) as e:
            log.warning("OSM pre-flight overpass error: %s", e)
            return []


async def run_for_submission(submission_id) -> None:
    """Run the pre-flight check for one submission and persist the result.

    Standalone — owns its own DB session because it's called from a
    FastAPI BackgroundTask after the request's session is gone."""
    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as db:
        await _do_check(db, submission_id)


async def _do_check(db: AsyncSession, submission_id) -> None:
    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if submission is None:
        log.warning("pre-flight skipped: submission %s not found", submission_id)
        return

    # Get the Place's coordinates + category. We re-fetch via raw SQL since
    # the Place model's coordinates column needs the ST_X/ST_Y dance.
    from sqlalchemy import cast, func
    from geoalchemy2 import Geometry
    from dispatchzero.models import Place

    place_row = (
        await db.execute(
            select(
                Place.category,
                func.ST_Y(cast(Place.coordinates, Geometry)),
                func.ST_X(cast(Place.coordinates, Geometry)),
            ).where(Place.id == submission.place_id)
        )
    ).one_or_none()
    if place_row is None:
        log.warning("pre-flight skipped: place gone for submission %s", submission_id)
        return
    category, lat, lng = place_row
    lat = float(lat); lng = float(lng)

    query = _build_query(category=category, lat=lat, lng=lng)
    if query is None:
        # Unknown category. Mark checked_at so the UI shows "ran, no info"
        # rather than pending-forever.
        submission.osm_preflight_checked_at = datetime.now(timezone.utc)
        submission.osm_preflight_matches = []
        await db.commit()
        return

    elements = await _run_overpass(query)

    matches: list[dict] = []
    for e in elements:
        e_lat = e.get("lat") or e.get("center", {}).get("lat")
        e_lng = e.get("lon") or e.get("center", {}).get("lon")
        if e_lat is None:
            continue
        tags = e.get("tags", {}) or {}
        name = tags.get("name") or "(unnamed)"
        osm_type = e.get("type", "node")
        osm_id = e.get("id")
        matches.append({
            "name": name,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "distance_m": int(round(_km(lat, lng, e_lat, e_lng) * 1000)),
            "tags_summary": _summarize_tags(tags),
        })
    matches.sort(key=lambda m: m["distance_m"])

    submission.osm_preflight_checked_at = datetime.now(timezone.utc)
    submission.osm_preflight_matches = matches
    await db.commit()
    log.info(
        "OSM pre-flight for submission %s: %d match(es)",
        submission_id, len(matches),
    )
