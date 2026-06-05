"""Completion-driven OSM publish candidates.

When a user completes a mission at a place that didn't come from OSM
(Wikipedia / GNIS / internal), the place is a candidate for upstream
publication. The admin review queue surfaces these alongside pending
community submissions so they can be reviewed in one workflow.

Filters that define a candidate:

- Place.osm_type NOT IN ('node', 'way', 'relation')   — not already on OSM
- Place.status == 'active'                            — currently dispatchable
- Place.osm_published_node_id IS NULL                 — never been pushed
- Place.osm_skipped_at IS NULL                        — admin hasn't declined it
- At least one verified Completion exists for the place

Each candidate is keyed by place_id (one candidate per place even if many
users completed it). The shown completion is the most recent verified one,
which gives the reviewer a current photo + completer attribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dispatchzero.models import Completion, Place, User


@dataclass(frozen=True)
class CompletionCandidate:
    """One queue-renderable candidate. All fields are pre-extracted so the
    route doesn't need to do further lookups."""
    place: Place
    completion: Completion
    completer: User
    lat: float
    lng: float


def source_label(osm_type: str | None) -> str:
    """Human-readable category for the source-badge UI."""
    if osm_type in ("node", "way", "relation"):
        return "osm"  # filtered out — shouldn't reach UI
    if osm_type == "wp":
        return "wikipedia"
    if osm_type == "community":
        return "community"
    if osm_type == "gnis":
        return "gnis"
    return "other"


async def list_candidates(
    db: AsyncSession,
) -> list[CompletionCandidate]:
    """Return one candidate per qualifying place, ordered by the latest
    verified completion timestamp (newest first — these are the freshest
    eligible places).

    Implementation: window-function trick. For every verified completion
    at a non-OSM, non-published, non-skipped, active place, rank
    completions per place by completed_at DESC. Keep rank=1 → newest
    verified completion per place.
    """
    # Subquery: for each (place_id, completed_at) of a verified completion
    # at a candidate place, attach a row_number partition rank.
    rn = func.row_number().over(
        partition_by=Completion.place_id,
        order_by=desc(Completion.completed_at),
    ).label("rn")

    sub = (
        select(
            Completion.id.label("completion_id"),
            Completion.place_id.label("place_id"),
            Completion.user_id.label("user_id"),
            Completion.completed_at.label("completed_at"),
            rn,
        )
        .join(Place, Place.id == Completion.place_id)
        .where(
            Completion.verified.is_(True),
            Place.osm_type.notin_(["node", "way", "relation"]),
            Place.osm_published_node_id.is_(None),
            Place.osm_skipped_at.is_(None),
            Place.status == "active",
        )
        .subquery()
    )

    # Now join only the rn=1 rows back to Place + User + the Completion
    # itself for full fields, plus extract lat/lng from Place.coordinates.
    from geoalchemy2 import Geometry
    from sqlalchemy import cast
    lat_col = func.ST_Y(cast(Place.coordinates, Geometry))
    lng_col = func.ST_X(cast(Place.coordinates, Geometry))

    completion_alias = aliased(Completion)

    stmt = (
        select(Place, completion_alias, User, lat_col, lng_col)
        .join(sub, sub.c.place_id == Place.id)
        .join(completion_alias, completion_alias.id == sub.c.completion_id)
        .join(User, User.id == sub.c.user_id)
        .where(sub.c.rn == 1)
        .order_by(desc(sub.c.completed_at))
    )

    rows = (await db.execute(stmt)).all()
    return [
        CompletionCandidate(
            place=p,
            completion=c,
            completer=u,
            lat=float(lat),
            lng=float(lng),
        )
        for p, c, u, lat, lng in rows
    ]


async def mark_skipped(
    *, db: AsyncSession, place: Place, admin: User,
) -> Place:
    """Stamp Skip metadata on the place so it's filtered out of the
    candidate list forever (until manually unset in the DB).

    Idempotent: re-skipping a skipped place is a no-op."""
    if place.osm_skipped_at is not None:
        return place
    place.osm_skipped_at = datetime.now(timezone.utc)
    place.osm_skipped_by_user_id = admin.id
    await db.commit()
    await db.refresh(place)
    return place
