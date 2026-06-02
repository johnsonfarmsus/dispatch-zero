"""Tests for the report-a-bad-place service + endpoint.

Covers:
- Per-user exclusion is written + idempotent
- 'not_found' reports excludes only for the user, doesn't flag the place
- 'unreachable' reports from 2 distinct users flags the place
- Mixed signal: one completion-survey unreachable + one direct report = flag
- 404 on unknown place
- Discovery excludes places the user has reported
"""
import uuid

import pytest
from sqlalchemy import select

from dispatchzero.models import (
    Completion,
    ExclusionReason,
    Mission,
    Place,
    PlaceStatus,
    User,
    UserPlaceExclusion,
)
from dispatchzero.services.discovery import discover_nearby
from dispatchzero.services.place_reports import (
    PlaceNotFoundError,
    report_place,
)


async def _make_user(db, callsign: str) -> User:
    u = User(
        callsign=callsign, callsign_lower=callsign.lower(),
        password_hash="x", adventure_style="agency",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_place(db, *, osm_id: int, name: str = "Phantom Dam") -> Place:
    p = Place(
        id=uuid.uuid4(),
        osm_type="gnis", osm_id=osm_id, name=name, category="infrastructure",
        coordinates="SRID=4326;POINT(-118.25 47.48)",
        tags={"source": "gnis"},
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest.mark.asyncio
async def test_report_writes_per_user_exclusion(db_session):
    user = await _make_user(db_session, "Reporter")
    place = await _make_place(db_session, osm_id=1)

    excl = await report_place(
        db=db_session, user=user, place_id=place.id,
        reason=ExclusionReason.UNREACHABLE,
    )
    assert excl.user_id == user.id
    assert excl.place_id == place.id
    assert excl.reason == "unreachable"

    rows = (
        await db_session.execute(
            select(UserPlaceExclusion).where(UserPlaceExclusion.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_report_is_idempotent_and_updates_reason(db_session):
    """Re-reporting the same place updates the row instead of creating a duplicate."""
    user = await _make_user(db_session, "Reporter")
    place = await _make_place(db_session, osm_id=2)

    await report_place(db=db_session, user=user, place_id=place.id,
                       reason=ExclusionReason.NOT_FOUND)
    await report_place(db=db_session, user=user, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)

    rows = (
        await db_session.execute(
            select(UserPlaceExclusion).where(UserPlaceExclusion.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].reason == "unreachable"


@pytest.mark.asyncio
async def test_report_404_for_unknown_place(db_session):
    user = await _make_user(db_session, "Reporter")
    with pytest.raises(PlaceNotFoundError):
        await report_place(db=db_session, user=user,
                           place_id=uuid.uuid4(),
                           reason=ExclusionReason.UNREACHABLE)


@pytest.mark.asyncio
async def test_not_found_reports_dont_trigger_global_flag(db_session):
    """'not_found' is a weaker signal than 'unreachable' — even multiple
    not_found reports across users shouldn't auto-flag the place."""
    place = await _make_place(db_session, osm_id=3)
    u1 = await _make_user(db_session, "User1")
    u2 = await _make_user(db_session, "User2")
    u3 = await _make_user(db_session, "User3")

    for u in (u1, u2, u3):
        await report_place(db=db_session, user=u, place_id=place.id,
                           reason=ExclusionReason.NOT_FOUND)

    refreshed = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert refreshed.status == PlaceStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_two_unreachable_reports_flag_the_place(db_session):
    place = await _make_place(db_session, osm_id=4)
    u1 = await _make_user(db_session, "User1")
    u2 = await _make_user(db_session, "User2")

    await report_place(db=db_session, user=u1, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)
    # Place still active after one report
    p_after_one = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert p_after_one.status == PlaceStatus.ACTIVE.value

    await report_place(db=db_session, user=u2, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)
    p_after_two = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert p_after_two.status == PlaceStatus.FLAGGED.value


@pytest.mark.asyncio
async def test_same_user_reporting_twice_does_not_flag(db_session):
    """Distinct-users dedupe: one user reporting + then re-reporting from a
    different device shouldn't count as two votes."""
    place = await _make_place(db_session, osm_id=5)
    u1 = await _make_user(db_session, "OnlyOne")

    await report_place(db=db_session, user=u1, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)
    await report_place(db=db_session, user=u1, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)

    refreshed = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert refreshed.status == PlaceStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_mixed_completion_unreachable_plus_direct_report_flags(db_session):
    """Cross-path signal: one user 👎'd unreachable via completion survey,
    another reports via the direct endpoint — together they reach 2 distinct
    users and the place flags."""
    import secrets
    place = await _make_place(db_session, osm_id=6)
    u1 = await _make_user(db_session, "CompletionUser")
    u2 = await _make_user(db_session, "DirectUser")

    # u1 has a mission they completed and then 👎'd-unreachable on the survey
    mission = Mission(place_id=place.id, adventure_style="agency",
                      dispatch_summary="s", briefing_text="b")
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)
    db_session.add(Completion(
        user_id=u1.id, mission_id=mission.id, place_id=place.id,
        verified=True, location_rating="down", location_reason="unreachable",
        share_token=secrets.token_urlsafe(7),
    ))
    await db_session.commit()

    # u2 reports directly
    await report_place(db=db_session, user=u2, place_id=place.id,
                       reason=ExclusionReason.UNREACHABLE)

    refreshed = (
        await db_session.execute(select(Place).where(Place.id == place.id))
    ).scalar_one()
    assert refreshed.status == PlaceStatus.FLAGGED.value


@pytest.mark.asyncio
async def test_discovery_excludes_user_reported_place(db_session, redis_client):
    """A place the user has reported shouldn't appear in discovery, even
    though it's still active and within radius (other users can still see it)."""
    user = await _make_user(db_session, "Reporter")
    place = await _make_place(
        db_session, osm_id=7, name="Phantom Church Reachable to Others",
    )

    # Sanity: discovery returns it before report
    pre = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.48, lng=-118.25, radius_m=2000, limit=10, source="local",
    )
    assert any(p["id"] == place.id for p in pre)

    # After report → gone for this user
    await report_place(db=db_session, user=user, place_id=place.id,
                       reason=ExclusionReason.NOT_FOUND)
    post = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.48, lng=-118.25, radius_m=2000, limit=10, source="local",
    )
    assert not any(p["id"] == place.id for p in post)
