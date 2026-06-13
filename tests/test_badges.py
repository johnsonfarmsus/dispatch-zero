"""Tests for the computed badge system."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from dispatchzero.models import (
    Completion,
    Mission,
    Place,
    PlaceCategory,
    PlaceStatus,
    User,
)
from dispatchzero.services.badges import compute_badges


async def _make_user(db, callsign="Player") -> User:
    u = User(
        callsign=callsign, callsign_lower=callsign.lower(),
        password_hash="x", adventure_style="agency",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


_place_counter = iter(range(1000, 99999))


async def _make_place(db, category="mural") -> Place:
    p = Place(
        id=uuid.uuid4(), osm_type="node", osm_id=next(_place_counter),
        name=f"P-{category}", category=category,
        coordinates="SRID=4326;POINT(-118.25 47.48)", tags={},
        status=PlaceStatus.ACTIVE.value,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _complete(db, user, place, *, when: datetime) -> None:
    # mission_id is a non-null FK, so create a minimal mission to satisfy it.
    mission = Mission(
        id=uuid.uuid4(), place_id=place.id, adventure_style="agency",
        dispatch_summary="s", briefing_text="b",
    )
    db.add(mission)
    await db.flush()
    c = Completion(
        id=uuid.uuid4(), user_id=user.id, mission_id=mission.id,
        place_id=place.id, photo_url="x.jpg", verified=True,
        completed_at=when, share_token=f"t-{uuid.uuid4().hex[:8]}",
    )
    db.add(c)
    await db.commit()


def _badge(badges, key):
    return next(b for b in badges if b.key == key)


@pytest.mark.asyncio
async def test_no_completions_all_locked(db_session):
    user = await _make_user(db_session)
    badges = await compute_badges(db_session, user_id=user.id)
    assert all(not b.earned for b in badges)
    # 9 category + cartographer + 4 cadence = 14
    assert len(badges) == 14


@pytest.mark.asyncio
async def test_category_badge_earned_at_threshold(db_session):
    user = await _make_user(db_session)
    now = datetime.now(timezone.utc)
    place = await _make_place(db_session, "mural")
    # 3 mural completions -> Muralist earned.
    for i in range(3):
        await _complete(db_session, user, place, when=now - timedelta(days=i))
    badges = await compute_badges(db_session, user_id=user.id)
    muralist = _badge(badges, "cat:mural")
    assert muralist.earned
    assert muralist.current == 3 and muralist.target == 3
    # Sculpture still locked.
    assert not _badge(badges, "cat:sculpture").earned


@pytest.mark.asyncio
async def test_category_badge_progress_below_threshold(db_session):
    user = await _make_user(db_session)
    now = datetime.now(timezone.utc)
    place = await _make_place(db_session, "church")
    await _complete(db_session, user, place, when=now)
    badges = await compute_badges(db_session, user_id=user.id)
    church = _badge(badges, "cat:church")
    assert not church.earned
    assert church.current == 1 and church.target == 3


@pytest.mark.asyncio
async def test_field_active_three_in_one_week(db_session):
    user = await _make_user(db_session)
    # Three completions in the same ISO week (same Monday).
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)  # a Monday
    for i in range(3):
        place = await _make_place(db_session, "park")
        await _complete(db_session, user, place, when=base + timedelta(days=i))
    badges = await compute_badges(db_session, user_id=user.id)
    assert _badge(badges, "cadence:active").earned
    assert not _badge(badges, "cadence:relentless").earned  # needs 5


@pytest.mark.asyncio
async def test_consecutive_weeks_streak(db_session):
    user = await _make_user(db_session)
    # One completion in each of two consecutive ISO weeks.
    wk1 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)   # Mon, week N
    wk2 = wk1 + timedelta(days=7)                            # Mon, week N+1
    for when in (wk1, wk2):
        place = await _make_place(db_session, "viewpoint")
        await _complete(db_session, user, place, when=when)
    badges = await compute_badges(db_session, user_id=user.id)
    assert _badge(badges, "cadence:steadfast").earned  # 2 consecutive
    assert not _badge(badges, "cadence:devoted").earned  # needs 4


@pytest.mark.asyncio
async def test_cartographer_needs_all_nine(db_session):
    user = await _make_user(db_session)
    now = datetime.now(timezone.utc)
    cats = [c.value for c in PlaceCategory]
    assert len(cats) == 9
    for cat in cats:
        place = await _make_place(db_session, cat)
        await _complete(db_session, user, place, when=now)
    badges = await compute_badges(db_session, user_id=user.id)
    carto = _badge(badges, "cat:cartographer")
    assert carto.earned
    assert carto.current == 9 and carto.target == 9
