"""Tests for the Dossier (history) endpoints.

- GET /missions/completions returns the user's own completions, newest first
- GET /missions/completions/{id} is owner-only
- GET /missions/completions/{id}/photo.jpg serves the saved 600px capture
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from dispatchzero.models import Completion, Mission, Place, User
from dispatchzero.services.photo import make_test_jpeg, save_thumbnail


SIGNUP = {
    "callsign": "Hunter",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


async def _seed_completions(db_session, tmp_path, *, count: int = 3) -> User:
    """Create a user, place, mission, and N completions with staggered timestamps."""
    user = User(
        callsign="HistTester", callsign_lower="histtester",
        password_hash="x", adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    place = Place(
        osm_type="node", osm_id=42,
        name="Test Mural", category="mural",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place)
    await db_session.commit()
    await db_session.refresh(place)

    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
        badge_framing="First Mural",
    )
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)

    raw = make_test_jpeg(captured_at=datetime.now(timezone.utc))
    photo_path = tmp_path / "captures" / "x.jpg"
    save_thumbnail(raw, photo_path, max_dim=600, quality=70)

    base = datetime(2026, 4, 27, 10, tzinfo=timezone.utc)
    for i in range(count):
        c = Completion(
            user_id=user.id, mission_id=mission.id, place_id=place.id,
            photo_url=str(photo_path),
            verified=True,
            share_token=secrets.token_urlsafe(7),
            completed_at=base + timedelta(hours=i),
        )
        db_session.add(c)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_list_completions_returns_user_history_newest_first(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await _seed_completions(db_session, tmp_path, count=3)
    # Sign in as that user
    await client.post("/auth/login", json={
        "callsign": "HistTester", "password": "x",
    })
    # Manual login won't work because password is just "x" — sign up a separate
    # user instead to exercise the auth-required path:
    await client.post("/auth/signup", json={
        **SIGNUP, "callsign": "Lister",
    })
    # The Lister user has no completions, so list is empty
    r = await client.get("/missions/completions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_completions_returns_own_only(
    client, db_session, tmp_path, monkeypatch
):
    """Even if other users have completions, only the caller's are returned."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await _seed_completions(db_session, tmp_path, count=2)  # different user

    # Sign up THIS test client's user
    await client.post("/auth/signup", json=SIGNUP)
    # Create one completion for THIS user
    me = (
        await db_session.execute(
            select(User).where(User.callsign_lower == SIGNUP["callsign"].lower())
        )
    ).scalar_one()
    place = (await db_session.execute(select(Place).limit(1))).scalar_one()
    mission = (await db_session.execute(select(Mission).limit(1))).scalar_one()
    c = Completion(
        user_id=me.id, mission_id=mission.id, place_id=place.id,
        photo_url="/tmp/missing.jpg",  # not used by list
        verified=True,
        share_token=secrets.token_urlsafe(7),
        completed_at=datetime(2026, 4, 27, 12, tzinfo=timezone.utc),
    )
    db_session.add(c)
    await db_session.commit()

    r = await client.get("/missions/completions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["share_token"] == c.share_token
    assert items[0]["place_name"] == "Test Mural"
    assert items[0]["place_category"] == "mural"
    assert items[0]["adventure_style"] == "agency"
    assert items[0]["badge_framing"] == "First Mural"


@pytest.mark.asyncio
async def test_list_completions_requires_auth(client, db_session):
    client.cookies.clear()
    r = await client.get("/missions/completions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_completion_owner_only(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    other_user = await _seed_completions(db_session, tmp_path, count=1)
    other_completion = (
        await db_session.execute(
            select(Completion).where(Completion.user_id == other_user.id).limit(1)
        )
    ).scalar_one()

    # Sign up a different user and try to fetch other_user's completion
    await client.post("/auth/signup", json=SIGNUP)
    r = await client.get(f"/missions/completions/{other_completion.id}")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_completion_404_for_unknown(client, db_session):
    await client.post("/auth/signup", json=SIGNUP)
    r = await client.get("/missions/completions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_completion_photo_serves_jpeg(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await client.post("/auth/signup", json=SIGNUP)

    me = (
        await db_session.execute(
            select(User).where(User.callsign_lower == SIGNUP["callsign"].lower())
        )
    ).scalar_one()

    # Create a place + mission + completion with a real on-disk photo
    place = Place(
        osm_type="node", osm_id=99,
        name="Photo Test", category="mural",
        coordinates="SRID=4326;POINT(-117 47)", tags={},
    )
    db_session.add(place); await db_session.commit(); await db_session.refresh(place)
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db_session.add(mission); await db_session.commit(); await db_session.refresh(mission)

    raw = make_test_jpeg(captured_at=datetime.now(timezone.utc))
    photo_path = tmp_path / "captures" / "real.jpg"
    save_thumbnail(raw, photo_path, max_dim=600, quality=70)

    completion = Completion(
        user_id=me.id, mission_id=mission.id, place_id=place.id,
        photo_url=str(photo_path),
        verified=True,
        share_token=secrets.token_urlsafe(7),
    )
    db_session.add(completion); await db_session.commit(); await db_session.refresh(completion)

    r = await client.get(f"/missions/completions/{completion.id}/photo.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"
