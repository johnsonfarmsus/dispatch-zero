from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import Completion, Mission, Place, User
from dispatchzero.services.mission_flow import (
    CaptureFailedError,
    capture_mission,
    rate_completion,
    user_completions_count,
)
from dispatchzero.services.photo import make_test_jpeg


async def _seed(db: AsyncSession) -> tuple[User, Place, Mission]:
    user = User(
        callsign="Tester", callsign_lower="tester", password_hash="x",
        adventure_style="agency",
    )
    place = Place(
        osm_type="node", osm_id=1, name="Test Sculpture", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db.add_all([user, place])
    await db.commit()
    await db.refresh(user); await db.refresh(place)
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return user, place, mission


@pytest.mark.asyncio
async def test_capture_happy_path_persists_completion(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)

    raw = make_test_jpeg(captured_at=datetime.utcnow())
    completion = await capture_mission(
        db=db_session, user=user, mission=mission, place=place,
        raw_photo=raw,
        capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
    )
    assert completion.verified is True
    assert completion.photo_url is not None

    refreshed = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert refreshed.missions_this_week == 1

    count = await user_completions_count(db_session, user_id=user.id)
    assert count == 1


@pytest.mark.asyncio
async def test_capture_rejects_out_of_radius(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)

    raw = make_test_jpeg(captured_at=datetime.utcnow())
    with pytest.raises(CaptureFailedError, match="out_of_radius"):
        await capture_mission(
            db=db_session, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=47.6700, capture_lng=-117.4100, capture_accuracy_m=8.0,
        )
    rows = (await db_session.execute(select(Completion))).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_capture_rejects_stale_exif(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    old = datetime.utcnow() - timedelta(hours=2)
    raw = make_test_jpeg(captured_at=old)
    with pytest.raises(CaptureFailedError, match="stale"):
        await capture_mission(
            db=db_session, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
        )


@pytest.mark.asyncio
async def test_rate_updates_aggregates_on_place_and_mission(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    raw = make_test_jpeg(captured_at=datetime.utcnow())
    completion = await capture_mission(
        db=db_session, user=user, mission=mission, place=place,
        raw_photo=raw,
        capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
    )
    await rate_completion(
        db=db_session, user=user, completion=completion,
        location_rating="up", mission_rating="down",
        location_reason=None,
    )
    refreshed_place = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert refreshed_place.location_thumbs_up == 1
    refreshed_mission = (
        await db_session.execute(select(Mission).where(Mission.id == mission.id))
    ).scalar_one()
    assert refreshed_mission.mission_thumbs_down == 1
    assert refreshed_mission.status == "needs_regen"


@pytest.mark.asyncio
async def test_auto_retire_fires_on_three_of_five_negatives(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    # Manually seed 5 prior rated completions: 3 down, 2 up
    import secrets
    for rating in ["down", "up", "down", "up", "down"]:
        c = Completion(
            user_id=user.id, mission_id=mission.id, place_id=place.id,
            verified=True, location_rating=rating,
            share_token=secrets.token_urlsafe(7),
        )
        db_session.add(c)
    await db_session.commit()

    # Now create a 6th completion and rate it (auto-retire reads last 5)
    raw = make_test_jpeg(captured_at=datetime.utcnow())
    sixth = await capture_mission(
        db=db_session, user=user, mission=mission, place=place,
        raw_photo=raw,
        capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
    )
    await rate_completion(
        db=db_session, user=user, completion=sixth,
        location_rating="down", mission_rating=None, location_reason="not_found",
    )
    refreshed = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert refreshed.status == "flagged"
