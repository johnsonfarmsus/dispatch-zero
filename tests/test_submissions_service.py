"""Tests for the community-submission service.

Covers:
- create_submission writes Place(PENDING) + Submission(PENDING), saves photo,
  composes the contribution card
- Rejected up-front: empty name, missing GPS, stale photo
- approve_submission flips both rows, re-stamps card, is idempotent
- reject_submission flips submission only (place stays PENDING), idempotent
- _user_has_visited sees the submission as a prior visit (so a future
  dispatch to the same place triggers repeat-visit briefing framing)
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from dispatchzero.models import (
    Place,
    PlaceCategory,
    PlaceStatus,
    Submission,
    SubmissionStatus,
    User,
)
from dispatchzero.services.missions import _user_has_visited
from dispatchzero.services.photo import make_test_jpeg
from dispatchzero.services.submissions import (
    SubmissionRejectedError,
    approve_submission,
    create_submission,
    reject_submission,
)


def _photo_with_gps(
    *,
    captured_at: datetime | None = None,
    lat: float = 47.4808,
    lng: float = -118.2547,
) -> bytes:
    """JPEG that carries both GPS and DateTimeOriginal in its EXIF —
    matches the shape the capture endpoint expects.

    make_test_jpeg writes EMPTY GPS by default; the submission service is
    designed to reject that ("no GPS in photo"). For the happy-path tests
    we synthesize a fully-populated EXIF block instead.
    """
    import io as _io
    import piexif
    from PIL import Image

    if captured_at is None:
        captured_at = datetime.utcnow()

    def _to_dms(value: float) -> tuple:
        v = abs(value)
        d = int(v)
        m_f = (v - d) * 60
        m = int(m_f)
        s = round((m_f - m) * 60 * 1000)  # millisecond precision
        return ((d, 1), (m, 1), (s, 1000))

    exif_dict: dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal:
                captured_at.strftime("%Y:%m:%d %H:%M:%S").encode("ascii"),
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitude: _to_dms(lat),
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLongitude: _to_dms(lng),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lng >= 0 else b"W",
        },
        "1st": {}, "thumbnail": None,
    }
    img = Image.new("RGB", (200, 200), (80, 90, 100))
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", exif=piexif.dump(exif_dict))
    return buf.getvalue()


async def _make_user(db, callsign: str = "Submitter") -> User:
    u = User(
        callsign=callsign, callsign_lower=callsign.lower(),
        password_hash="x", adventure_style="agency",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_create_submission_happy_path_persists_everything(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)

    submission = await create_submission(
        db=db_session, user=user,
        raw_photo=_photo_with_gps(),
        name="The Old Truss Bridge",
        category=PlaceCategory.INFRASTRUCTURE,
        description="Steel truss over the creek north of town.",
        lat=47.4808, lng=-118.2547,
    )

    assert submission.status == SubmissionStatus.PENDING.value
    assert submission.description == "Steel truss over the creek north of town."
    assert submission.photo_url
    assert Path(submission.photo_url).exists(), "photo should be on disk"
    assert submission.card_path
    assert Path(submission.card_path).exists(), "contribution card should be on disk"
    assert submission.share_token

    place = (await db_session.execute(
        select(Place).where(Place.id == submission.place_id)
    )).scalar_one()
    assert place.osm_type == "community"
    assert place.osm_id > 0
    assert place.name == "The Old Truss Bridge"
    assert place.category == PlaceCategory.INFRASTRUCTURE.value
    assert place.status == PlaceStatus.PENDING.value
    assert place.submitted_by_user_id == user.id
    assert place.submission_description == "Steel truss over the creek north of town."


@pytest.mark.asyncio
async def test_create_submission_rejects_blank_name(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)
    with pytest.raises(SubmissionRejectedError, match="name"):
        await create_submission(
            db=db_session, user=user, raw_photo=_photo_with_gps(),
            name="   ", category=PlaceCategory.MURAL, description=None,
            lat=47.4808, lng=-118.2547,
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_overlong_description(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)
    with pytest.raises(SubmissionRejectedError, match="description"):
        await create_submission(
            db=db_session, user=user, raw_photo=_photo_with_gps(),
            name="Wall A", category=PlaceCategory.MURAL,
            description="x" * 141,
            lat=47.4808, lng=-118.2547,
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_invalid_coordinates(
    db_session, tmp_path, monkeypatch,
):
    """GPS comes from the browser, not the photo. We still range-check
    the values the route forwards us."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)
    with pytest.raises(SubmissionRejectedError, match="coordinates"):
        await create_submission(
            db=db_session, user=user, raw_photo=_photo_with_gps(),
            name="Sample", category=PlaceCategory.MURAL, description=None,
            lat=999.0, lng=0.0,  # out of range
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_stale_photo(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)
    stale_time = datetime.utcnow() - timedelta(hours=2)
    with pytest.raises(SubmissionRejectedError, match="old"):
        await create_submission(
            db=db_session, user=user,
            raw_photo=_photo_with_gps(captured_at=stale_time),
            name="Sample", category=PlaceCategory.MURAL, description=None,
            lat=47.4808, lng=-118.2547,
        )


@pytest.mark.asyncio
async def test_approve_submission_flips_status_and_activates_place(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session, "Submitter")
    reviewer = await _make_user(db_session, "Reviewer")

    submission = await create_submission(
        db=db_session, user=user, raw_photo=_photo_with_gps(),
        name="Sample", category=PlaceCategory.MURAL, description=None, lat=47.4808, lng=-118.2547,
    )

    approved = await approve_submission(
        db=db_session, reviewer=reviewer, submission_id=submission.id,
    )
    assert approved.status == SubmissionStatus.APPROVED.value
    assert approved.reviewer_user_id == reviewer.id
    assert approved.reviewed_at is not None

    place = (await db_session.execute(
        select(Place).where(Place.id == submission.place_id)
    )).scalar_one()
    assert place.status == PlaceStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_approve_submission_is_idempotent(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session, "Submitter")
    reviewer = await _make_user(db_session, "Reviewer")
    submission = await create_submission(
        db=db_session, user=user, raw_photo=_photo_with_gps(),
        name="Sample", category=PlaceCategory.MURAL, description=None, lat=47.4808, lng=-118.2547,
    )
    first = await approve_submission(
        db=db_session, reviewer=reviewer, submission_id=submission.id,
    )
    second = await approve_submission(
        db=db_session, reviewer=reviewer, submission_id=submission.id,
    )
    assert first.reviewed_at == second.reviewed_at  # idempotent — no overwrite


@pytest.mark.asyncio
async def test_reject_submission_deletes_orphan_place_and_snapshots_name(
    db_session, tmp_path, monkeypatch,
):
    """Returning a submission now garbage-collects the orphan Place row
    (it would otherwise sit forever as status=pending dead weight) while
    keeping the Submission alive for the dossier history. The place name
    is snapshot onto the Submission so the user's dossier card still
    reads 'Sample' after the Place is gone. See migration 0015 + the
    reject_submission service for the rationale.
    """
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session, "Submitter")
    reviewer = await _make_user(db_session, "Reviewer")
    submission = await create_submission(
        db=db_session, user=user, raw_photo=_photo_with_gps(),
        name="Sample", category=PlaceCategory.MURAL, description=None, lat=47.4808, lng=-118.2547,
    )
    place_id_before = submission.place_id

    rejected = await reject_submission(
        db=db_session, reviewer=reviewer, submission_id=submission.id,
        note="Location inaccurate",
    )
    assert rejected.status == SubmissionStatus.RETURNED.value
    # Submission survives with place_id=NULL (FK is SET NULL ondelete).
    assert rejected.place_id is None
    # Name snapshot lets the dossier card still render the place name.
    assert rejected.place_name_snapshot == "Sample"
    # Reviewer note persists for the submitter to read.
    assert rejected.review_note == "Location inaccurate"
    # Orphan Place row is hard-deleted.
    place = (await db_session.execute(
        select(Place).where(Place.id == place_id_before)
    )).scalar_one_or_none()
    assert place is None


@pytest.mark.asyncio
async def test_submission_counts_as_prior_visit_for_repeat_briefing(
    db_session, tmp_path, monkeypatch,
):
    """End-to-end check on the cross-feature wire: if a user submitted a
    place, services.missions._user_has_visited should treat it as a prior
    visit, which then triggers repeat-visit briefing framing on a future
    dispatch to the same place."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user = await _make_user(db_session)
    submission = await create_submission(
        db=db_session, user=user, raw_photo=_photo_with_gps(),
        name="My Local Plaza", category=PlaceCategory.PARK, description=None, lat=47.4808, lng=-118.2547,
    )

    visited = await _user_has_visited(
        db_session, user_id=user.id, place_id=submission.place_id,
    )
    assert visited is True


@pytest.mark.asyncio
async def test_other_user_did_not_visit_a_submitted_place(
    db_session, tmp_path, monkeypatch,
):
    """The submission-as-visit signal is per-user. Another user dispatched to
    the same place should still get first-visit framing."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    submitter = await _make_user(db_session, "Submitter")
    bystander = await _make_user(db_session, "Bystander")
    submission = await create_submission(
        db=db_session, user=submitter, raw_photo=_photo_with_gps(),
        name="My Local Plaza", category=PlaceCategory.PARK, description=None, lat=47.4808, lng=-118.2547,
    )

    visited_by_other = await _user_has_visited(
        db_session, user_id=bystander.id, place_id=submission.place_id,
    )
    assert visited_by_other is False
