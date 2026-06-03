import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.models import (
    Completion,
    Mission,
    MissionStatus,
    Place,
    PlaceStatus,
    User,
    UserPlaceHistory,
)
from dispatchzero.services.cards import compose_mission_card
from dispatchzero.services.photo import save_thumbnail
from dispatchzero.services.rank import completions_to_rank, stats_at_completion
from dispatchzero.services.verification import verify_capture


class CaptureFailedError(RuntimeError):
    """Raised when photo capture verification fails. Message contains the fail_reason."""


async def capture_mission(
    *,
    db: AsyncSession,
    user: User,
    mission: Mission,
    place: Place,
    raw_photo: bytes,
    capture_lat: float,
    capture_lng: float,
    capture_accuracy_m: float | None,
) -> Completion:
    settings = get_settings()
    target_lat, target_lng = await _place_lat_lng(db, place.id)

    result = verify_capture(
        raw_bytes=raw_photo,
        capture_lat=capture_lat,
        capture_lng=capture_lng,
        target_lat=target_lat,
        target_lng=target_lng,
        radius_m=settings.gps_verification_radius_m,
        freshness_window_seconds=settings.exif_freshness_window_seconds,
    )
    if not result.verified:
        raise CaptureFailedError(result.fail_reason or "unknown")

    completion_id = uuid.uuid4()
    photo_dir = Path(settings.photo_upload_dir) / "completions" / str(user.id)
    photo_path = photo_dir / f"{completion_id}.jpg"
    save_thumbnail(
        raw_photo,
        photo_path,
        max_dim=settings.photo_max_dimension,
        quality=settings.photo_jpeg_quality,
    )

    # Compose the shareable mission card. Done synchronously at capture so the
    # Debrief screen's "Save card" is instant. Failure here doesn't fail the
    # capture — log and skip; the card endpoint will regenerate on demand.
    # Stats are a snapshot AT THIS completion's moment. The new completion
    # isn't committed yet, so include_self=False adds 1 to both counts.
    now_ts = datetime.now(timezone.utc)
    total_at, week_at = await stats_at_completion(
        db, user_id=user.id, at_time=now_ts, include_self=False,
    )
    rank_now = completions_to_rank(total_at)

    card_path = Path(settings.photo_upload_dir) / "cards" / f"{completion_id}.jpg"
    try:
        compose_mission_card(
            photo_path=photo_path,
            place_name=place.name or "Unmarked target",
            callsign=user.callsign,
            completed_at=now_ts,
            adventure_style=mission.adventure_style,
            rank_at_completion=rank_now,
            completions_total=total_at,
            completions_this_week=week_at,
            dispatch_summary=mission.dispatch_summary,
            output_path=card_path,
        )
    except Exception:
        # Card generation is best-effort. The completion still saves.
        pass

    completion = Completion(
        id=completion_id,
        user_id=user.id,
        mission_id=mission.id,
        place_id=place.id,
        photo_url=str(photo_path),
        verified=True,
        # Unguessable short token for the public /c/{token} share URL.
        share_token=secrets.token_urlsafe(7),
    )
    db.add(completion)

    # Bump weekly counter; total completions are computed via COUNT() at read time.
    now = datetime.now(timezone.utc)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            missions_this_week=User.missions_this_week + 1,
            last_login_at=now,
        )
    )

    # Upsert user_place_history (latest completion bumps last_completed_at).
    await db.execute(
        pg_insert(UserPlaceHistory)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            place_id=place.id,
            last_completed_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "place_id"],
            set_={"last_completed_at": now},
        )
    )

    await db.execute(
        update(Mission)
        .where(Mission.id == mission.id)
        .values(implicit_completions=Mission.implicit_completions + 1)
    )

    await db.commit()
    await db.refresh(completion)
    return completion


async def rate_completion(
    *,
    db: AsyncSession,
    user: User,
    completion: Completion,
    location_rating: Literal["up", "down"] | None,
    mission_rating: Literal["up", "down"] | None,
    location_reason: str | None,
    mission_reason: str | None = None,
) -> Completion:
    """Apply a two-axis rating. Idempotent (overwrites if re-submitted)."""
    completion.location_rating = location_rating
    completion.mission_rating = mission_rating
    completion.location_reason = location_reason
    completion.mission_reason = mission_reason
    db.add(completion)

    if location_rating == "up":
        await db.execute(
            update(Place)
            .where(Place.id == completion.place_id)
            .values(location_thumbs_up=Place.location_thumbs_up + 1)
        )
    elif location_rating == "down":
        await db.execute(
            update(Place)
            .where(Place.id == completion.place_id)
            .values(location_thumbs_down=Place.location_thumbs_down + 1)
        )

    if mission_rating == "up":
        await db.execute(
            update(Mission)
            .where(Mission.id == completion.mission_id)
            .values(mission_thumbs_up=Mission.mission_thumbs_up + 1)
        )
    elif mission_rating == "down":
        await db.execute(
            update(Mission)
            .where(Mission.id == completion.mission_id)
            .values(
                mission_thumbs_down=Mission.mission_thumbs_down + 1,
                status=MissionStatus.NEEDS_REGEN.value,
            )
        )

    await db.commit()
    if location_rating == "down":
        await _apply_auto_retire(db, place_id=completion.place_id)
        await db.commit()
    await db.refresh(completion)
    return completion


async def user_completions_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Total rank-events for a user. Computed; not denormalized.

    Counts BOTH:
    - Verified mission completions (the original sense)
    - Approved community submissions

    Both involve the user being physically at a location with a camera, and
    Trevor explicitly wanted submissions to count toward rank rather than
    sitting as a separate sub-score.
    """
    from dispatchzero.models import Submission, SubmissionStatus  # local: avoid cycle

    mission_count = (
        await db.execute(
            select(func.count(Completion.id)).where(
                Completion.user_id == user_id,
                Completion.verified.is_(True),
            )
        )
    ).scalar_one()
    submission_count = (
        await db.execute(
            select(func.count(Submission.id)).where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.APPROVED.value,
            )
        )
    ).scalar_one()
    return int(mission_count) + int(submission_count)


# ---- internals ----


async def _place_lat_lng(db: AsyncSession, place_id: uuid.UUID) -> tuple[float, float]:
    row = (
        await db.execute(
            text(
                "SELECT ST_Y(coordinates::geometry), ST_X(coordinates::geometry) "
                "FROM places WHERE id = :pid"
            ),
            {"pid": place_id},
        )
    ).one()
    return float(row[0]), float(row[1])


async def _apply_auto_retire(db: AsyncSession, *, place_id: uuid.UUID) -> None:
    """Flag a place for review based on recent rating signal.

    Two independent rules trigger FLAGGED (which hides the place from
    discovery but leaves the row for admin review — only Trevor manually
    moves to RETIRED):

    - **General negativity**: 3+ of the last 5 up/down ratings are 'down'.
      Catches places that are boring, hard to enjoy, or just consistently
      disappointing.
    - **Unreachable fast-flag**: 2+ of the last 5 down-rated completions
      carry `location_reason='unreachable'`. Catches phantom GNIS rows and
      demolished/fenced-off places faster than waiting for 5 total ratings.

    Either rule firing is sufficient. We never auto-retire — that's a human
    judgment call after looking at the photos/reasons.
    """
    rows = (
        await db.execute(
            select(Completion.location_rating, Completion.location_reason)
            .where(
                Completion.place_id == place_id,
                Completion.location_rating.in_(["up", "down"]),
            )
            .order_by(desc(Completion.completed_at))
            .limit(5)
        )
    ).all()

    downs = sum(1 for rating, _ in rows if rating == "down")
    unreachable_reports = sum(
        1 for rating, reason in rows
        if rating == "down" and reason == "unreachable"
    )

    # Rule 1: general negativity needs 5 ratings to fire (existing behavior).
    rule_general = len(rows) >= 5 and downs >= 3
    # Rule 2: unreachable fast-flag fires as soon as 2 such reports exist,
    # even before 5 total ratings — phantom places shouldn't keep dispatching.
    rule_unreachable = unreachable_reports >= 2

    if rule_general or rule_unreachable:
        await db.execute(
            update(Place)
            .where(Place.id == place_id)
            .values(status=PlaceStatus.FLAGGED.value)
        )
