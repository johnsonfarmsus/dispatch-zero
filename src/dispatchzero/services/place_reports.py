"""Report-a-bad-place service.

A user tells the system "this place isn't really there / I can't reach it."
We:
  1. Insert (or update) a per-user exclusion row → the user never sees this
     place dispatched again.
  2. Re-evaluate the global auto-flag rule for the place. If 2+ distinct
     users have ever signaled unreachable (via either this report path OR
     a post-completion survey 👎 with reason='unreachable'), the place
     auto-flags for the maintainer to review.

No GPS-proximity check. Local knowledge wins — someone who's lived in a
town for years often knows a church was demolished without needing to
stand next to where it was.

Exposed via POST /places/{id}/report. Idempotent.
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import (
    Completion,
    ExclusionReason,
    Place,
    PlaceStatus,
    User,
    UserPlaceExclusion,
)


class PlaceNotFoundError(LookupError):
    """The place_id doesn't exist in our DB."""


async def report_place(
    *,
    db: AsyncSession,
    user: User,
    place_id: uuid.UUID,
    reason: ExclusionReason,
) -> UserPlaceExclusion:
    """Record a user's report against a place and re-run the global auto-flag.

    Idempotent: if the user already has an exclusion for this place, the
    row's reason is updated to the latest one (useful when escalating
    'not_found' → 'unreachable' after a return visit).
    """
    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()
    if place is None:
        raise PlaceNotFoundError(f"place {place_id} not found")

    stmt = (
        pg_insert(UserPlaceExclusion)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            place_id=place_id,
            reason=reason.value,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "place_id"],
            set_={"reason": reason.value},
        )
        .returning(UserPlaceExclusion.id)
    )
    new_id = (await db.execute(stmt)).scalar_one()
    await db.commit()

    # Only 'unreachable' contributes to global flagging. 'not_found' is a
    # weaker signal (could be user error / GPS / signage) and excludes only
    # for the reporting user.
    if reason == ExclusionReason.UNREACHABLE:
        await _apply_global_unreachable_flag(db, place_id=place_id)
        await db.commit()

    return (
        await db.execute(
            select(UserPlaceExclusion).where(UserPlaceExclusion.id == new_id)
        )
    ).scalar_one()


async def _apply_global_unreachable_flag(
    db: AsyncSession, *, place_id: uuid.UUID
) -> None:
    """If 2+ distinct users have signaled 'unreachable' for this place via
    EITHER a direct report OR a post-completion 👎-with-unreachable, flag it.

    No time window — physical inaccessibility doesn't usually self-heal.
    Distinct-users dedupe matters because one user reporting twice (e.g. via
    completion + then a direct report) shouldn't double-count.

    Auto-action stops at FLAGGED. The maintainer reviews + manually moves
    to RETIRED. Same rule as services.mission_flow._apply_auto_retire.
    """
    completion_users = set(
        (
            await db.execute(
                select(Completion.user_id).where(
                    Completion.place_id == place_id,
                    Completion.location_rating == "down",
                    Completion.location_reason == "unreachable",
                )
            )
        ).scalars()
    )
    exclusion_users = set(
        (
            await db.execute(
                select(UserPlaceExclusion.user_id).where(
                    UserPlaceExclusion.place_id == place_id,
                    UserPlaceExclusion.reason == ExclusionReason.UNREACHABLE.value,
                )
            )
        ).scalars()
    )
    distinct_unreachable_users = completion_users | exclusion_users

    if len(distinct_unreachable_users) >= 2:
        await db.execute(
            update(Place)
            .where(Place.id == place_id)
            .values(status=PlaceStatus.FLAGGED.value)
        )
