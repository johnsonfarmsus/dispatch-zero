"""Community-submission service layer.

Three operations sit on top of the Submission + Place models:

  create_submission   — user POSTs a photo + name + category + description.
                        Persists Place(status=PENDING, osm_type='community')
                        + Submission(status=PENDING) and composes the initial
                        PENDING contribution card.
  approve_submission  — reviewer flips status to APPROVED. Place becomes
                        ACTIVE (dispatchable). Card is re-stamped VERIFIED.
                        The submitter's rank-event count goes up by one
                        (see services.rank for how that's read).
  reject_submission   — reviewer flips status to RETURNED. Place stays
                        PENDING (effectively dead). Card re-stamps RETURNED.

Photo handling mirrors capture_mission:
- EXIF GPS extracted to drive the Place's coordinates
- EXIF freshness checked so users can't backdate camera-roll uploads
- Photo saved EXIF-stripped under /uploads/submissions/{user}/{sub}.jpg
- Composed card saved under /uploads/submission_cards/{sub}.jpg

The card is intentionally a Pillow render right now (mirrors the mission
card) rather than a fresh AI generation — the framing text is templated
per status. Submissions don't need OLMo briefings; they just need an
artifact the user can keep and share.
"""
import io
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import piexif
from PIL import Image
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.models import (
    Place,
    PlaceCategory,
    PlaceStatus,
    Submission,
    SubmissionStatus,
    User,
)
from dispatchzero.services.cards import compose_contribution_card
from dispatchzero.services.photo import save_thumbnail

log = logging.getLogger(__name__)


class SubmissionRejectedError(RuntimeError):
    """Raised when the submission payload fails up-front validation —
    bad photo, missing EXIF GPS, stale EXIF, junk fields. Message is the
    fail_reason string the route surfaces to the user."""


class SubmissionNotFoundError(LookupError):
    """The submission ID doesn't exist in our DB."""


async def create_submission(
    *,
    db: AsyncSession,
    user: User,
    raw_photo: bytes,
    name: str,
    category: PlaceCategory,
    description: str | None,
    lat: float,
    lng: float,
) -> Submission:
    """Process a community POI submission end-to-end.

    GPS coordinates come from the browser via navigator.geolocation, NOT
    from the photo's EXIF. This is a deliberate UX choice — most users
    don't enable Location for the iOS Camera app, but the browser can
    request its own location permission independently. The frontend
    calls getFreshFix() before opening the camera and posts both the
    photo + coords here.

    EXIF freshness IS still enforced (anti-camera-roll: the photo's
    DateTimeOriginal must be within settings.exif_freshness_window_seconds
    of now) so users can't upload an old photo with fresh GPS.

    Raises SubmissionRejectedError on validation failure with a
    human-readable message. No DB writes happen in that case.
    """
    name = (name or "").strip()
    if not name:
        raise SubmissionRejectedError("name is required")
    if len(name) > 200:
        raise SubmissionRejectedError("name too long (max 200 chars)")
    if description is not None:
        description = description.strip() or None
    if description is not None and len(description) > 140:
        raise SubmissionRejectedError("description too long (max 140 chars)")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise SubmissionRejectedError("invalid coordinates")

    settings = get_settings()

    # GPS comes from the browser (already validated above). EXIF timestamp
    # is consulted ONLY as a sanity check — most web-captured photos via
    # <input capture="environment"> have no EXIF timestamp at all (iOS
    # strips it on capture), so a missing timestamp is fine. A PRESENT but
    # stale timestamp still gets rejected (catches users who navigated to
    # the photo library from inside the camera UI and picked an old shot).
    _, _, captured_at = _extract_exif(raw_photo)

    now = datetime.now(timezone.utc)
    if captured_at is not None:
        age_seconds = (now - captured_at).total_seconds()
        if age_seconds > settings.exif_freshness_window_seconds:
            raise SubmissionRejectedError(
                "photo is too old; take a fresh one at the location"
            )

    # Allocate the Place's osm_id from the dedicated community sequence so
    # the (osm_type, osm_id) uniqueness constraint holds without picking IDs
    # that collide with OSM's real node IDs.
    community_osm_id = (
        await db.execute(select(func.nextval("community_place_id_seq")))
    ).scalar_one()

    place = Place(
        id=uuid.uuid4(),
        osm_type="community",
        osm_id=int(community_osm_id),
        name=name,
        category=category.value,
        coordinates=f"SRID=4326;POINT({lng} {lat})",
        tags={
            "source": "community",
            "submitted_at": now.isoformat(),
        },
        description=description,  # also feeds discovery scoring
        status=PlaceStatus.PENDING.value,
        submitted_by_user_id=user.id,
        submission_description=description,
    )
    db.add(place)
    await db.flush()  # need place.id below

    submission = Submission(
        id=uuid.uuid4(),
        user_id=user.id,
        place_id=place.id,
        photo_url="",  # filled in below once we know the path
        description=description,
        status=SubmissionStatus.PENDING.value,
        share_token=secrets.token_urlsafe(7),
    )
    db.add(submission)
    await db.flush()  # need submission.id for the file path

    # Save the photo + compose the PENDING contribution card.
    photo_dir = Path(settings.photo_upload_dir) / "submissions" / str(user.id)
    photo_path = photo_dir / f"{submission.id}.jpg"
    save_thumbnail(
        raw_photo, photo_path,
        max_dim=settings.photo_max_dimension,
        quality=settings.photo_jpeg_quality,
    )
    submission.photo_url = str(photo_path)

    card_path = Path(settings.photo_upload_dir) / "submission_cards" / f"{submission.id}.jpg"
    try:
        compose_contribution_card(
            photo_path=photo_path,
            place_name=name,
            callsign=user.callsign,
            submitted_at=now,
            adventure_style=user.adventure_style,
            status=SubmissionStatus.PENDING,
            output_path=card_path,
        )
        submission.card_path = str(card_path)
    except Exception:  # noqa: BLE001
        # Card is best-effort; submission still records. Reviewer can still
        # see the photo via /submissions/{id}/photo.jpg.
        log.exception("contribution-card compose failed for submission %s", submission.id)

    await db.commit()
    await db.refresh(submission)
    return submission


async def approve_submission(
    *,
    db: AsyncSession,
    reviewer: User,
    submission_id: uuid.UUID,
) -> Submission:
    """Flip submission to APPROVED, flip linked Place to ACTIVE, re-stamp card."""
    submission, place = await _load(db, submission_id)

    if submission.status == SubmissionStatus.APPROVED.value:
        return submission  # idempotent

    submission.status = SubmissionStatus.APPROVED.value
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewer_user_id = reviewer.id

    await db.execute(
        update(Place)
        .where(Place.id == place.id)
        .values(status=PlaceStatus.ACTIVE.value)
    )

    submitter = await _load_user(db, submission.user_id)
    await _restamp_card(submission, place, submitter, SubmissionStatus.APPROVED)

    await db.commit()
    await db.refresh(submission)
    return submission


async def reject_submission(
    *,
    db: AsyncSession,
    reviewer: User,
    submission_id: uuid.UUID,
) -> Submission:
    """Flip submission to RETURNED, leave Place at PENDING (dead-end), re-stamp card."""
    submission, place = await _load(db, submission_id)

    if submission.status == SubmissionStatus.RETURNED.value:
        return submission  # idempotent

    submission.status = SubmissionStatus.RETURNED.value
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewer_user_id = reviewer.id

    submitter = await _load_user(db, submission.user_id)
    await _restamp_card(submission, place, submitter, SubmissionStatus.RETURNED)

    await db.commit()
    await db.refresh(submission)
    return submission


async def _load_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    return (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one()


# ---------------------------------------------------------------------------


async def _load(
    db: AsyncSession, submission_id: uuid.UUID
) -> tuple[Submission, Place]:
    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise SubmissionNotFoundError(f"submission {submission_id} not found")
    place = (
        await db.execute(select(Place).where(Place.id == submission.place_id))
    ).scalar_one()
    return submission, place


async def _restamp_card(
    submission: Submission,
    place: Place,
    submitter: User,
    status: SubmissionStatus,
) -> None:
    """Re-render the contribution card with the new status stamp.

    Failure is logged but doesn't bubble — the submission state change still
    lands. The user just keeps seeing the old (PENDING) card."""
    if submission.card_path is None or not submission.photo_url:
        return
    output_path = Path(submission.card_path)
    photo_path = Path(submission.photo_url)
    try:
        compose_contribution_card(
            photo_path=photo_path,
            place_name=place.name or "",
            callsign=submitter.callsign,
            submitted_at=submission.submitted_at,
            adventure_style=submitter.adventure_style,
            status=status,
            output_path=output_path,
        )
    except Exception:  # noqa: BLE001
        log.exception("contribution-card restamp failed for submission %s", submission.id)


def _extract_exif(raw_bytes: bytes) -> tuple[float | None, float | None, datetime | None]:
    """Pull lat/lng + DateTimeOriginal out of the photo's EXIF.

    Returns (lat, lng, captured_at) where any field may be None on missing/
    malformed data. The capture endpoint surfaces a specific user-facing
    fail_reason when GPS or timestamp is missing.
    """
    try:
        exif = piexif.load(raw_bytes)
    except Exception:  # noqa: BLE001
        return None, None, None

    gps = exif.get("GPS", {}) or {}
    lat = _exif_gps_to_decimal(gps, piexif.GPSIFD.GPSLatitude, piexif.GPSIFD.GPSLatitudeRef)
    lng = _exif_gps_to_decimal(gps, piexif.GPSIFD.GPSLongitude, piexif.GPSIFD.GPSLongitudeRef)

    captured_at: datetime | None = None
    raw_dto = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if isinstance(raw_dto, bytes):
        try:
            captured_at = datetime.strptime(
                raw_dto.decode("ascii"), "%Y:%m:%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
        except (ValueError, UnicodeDecodeError):
            captured_at = None

    return lat, lng, captured_at


def _exif_gps_to_decimal(
    gps: dict, coord_key: int, ref_key: int
) -> float | None:
    """Convert EXIF GPS rational triplets ((deg num, deg den), (min, den), (sec, den))
    + N/S/E/W reference to a signed decimal degree. Returns None on missing/malformed."""
    coord = gps.get(coord_key)
    ref = gps.get(ref_key)
    if not coord or not ref:
        return None
    try:
        d = coord[0][0] / coord[0][1]
        m = coord[1][0] / coord[1][1]
        s = coord[2][0] / coord[2][1]
    except (IndexError, ZeroDivisionError, TypeError):
        return None
    value = d + m / 60.0 + s / 3600.0
    ref_char = ref.decode("ascii") if isinstance(ref, bytes) else ref
    if ref_char in ("S", "W"):
        value = -value
    return value
