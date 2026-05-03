"""Tests for the public /c/{share_token} share routes.

Verify the page returns 200 with the right OG tags, the card route serves
a JPEG, and unknown tokens 404 cleanly.
"""
import secrets
from datetime import datetime, timezone

import pytest

from dispatchzero.models import Completion, Mission, Place, User
from dispatchzero.services.cards import compose_mission_card
from dispatchzero.services.photo import make_test_jpeg, save_thumbnail


async def _seed_completion(db_session, tmp_path, *, style: str = "agency"):
    """Insert a User + Place + Mission + Completion with a known share_token."""
    user = User(
        callsign="ShareTester", callsign_lower="sharetester",
        password_hash="x", adventure_style=style,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    place = Place(
        osm_type="node", osm_id=12345,
        name="Riverfront Park", category="viewpoint",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place)
    await db_session.commit()
    await db_session.refresh(place)

    mission = Mission(
        place_id=place.id, adventure_style=style,
        dispatch_summary="x", briefing_text="y",
    )
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)

    # Synthesize a saved capture photo so the card endpoint can regenerate.
    raw = make_test_jpeg(captured_at=datetime.utcnow())
    photo_path = tmp_path / "captures" / "x.jpg"
    save_thumbnail(raw, photo_path, max_dim=600, quality=70)

    token = secrets.token_urlsafe(7)
    completion = Completion(
        user_id=user.id, mission_id=mission.id, place_id=place.id,
        photo_url=str(photo_path),
        verified=True,
        share_token=token,
        completed_at=datetime(2026, 4, 27, 12, tzinfo=timezone.utc),
    )
    db_session.add(completion)
    await db_session.commit()
    await db_session.refresh(completion)

    return completion, user, place, token


@pytest.mark.asyncio
async def test_share_page_returns_html_with_og_tags(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    _completion, _user, _place, token = await _seed_completion(db_session, tmp_path)

    r = await client.get(f"/c/{token}")
    assert r.status_code == 200
    body = r.text
    # Page contains the place name
    assert "Riverfront Park" in body
    # OG tags present and pointing at the absolute card URL
    assert 'property="og:title"' in body
    assert 'property="og:image"' in body
    assert f"/c/{token}/card.jpg" in body
    assert 'name="twitter:card" content="summary_large_image"' in body


@pytest.mark.asyncio
async def test_share_page_404_for_unknown_token(client, db_session):
    r = await client.get("/c/this-token-does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_card_serves_jpeg_regenerating_on_miss(
    client, db_session, tmp_path, monkeypatch,
):
    """Card endpoint should render a JPEG even if the on-disk file doesn't exist."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    _completion, _user, _place, token = await _seed_completion(db_session, tmp_path)

    r = await client.get(f"/c/{token}/card.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    # JPEG magic bytes
    assert r.content[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_share_card_serves_existing_file_when_present(
    client, db_session, tmp_path, monkeypatch,
):
    """Pre-stage a card file; endpoint serves it without re-rendering."""
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    completion, user, place, token = await _seed_completion(db_session, tmp_path)

    # Pre-render the card so the regen path is NOT taken
    card_dir = tmp_path / "cards"
    card_dir.mkdir(parents=True, exist_ok=True)
    card_path = card_dir / f"{completion.id}.jpg"
    compose_mission_card(
        photo_path=tmp_path / "captures" / "x.jpg",
        place_name=place.name,
        callsign=user.callsign,
        completed_at=completion.completed_at,
        adventure_style="agency",
        rank_at_completion=2,
        dispatch_summary="A test dispatch summary.",
        output_path=card_path,
    )
    pre_size = card_path.stat().st_size

    r = await client.get(f"/c/{token}/card.jpg")
    assert r.status_code == 200
    # Same file, byte-for-byte
    assert len(r.content) == pre_size


@pytest.mark.asyncio
async def test_share_card_404_for_unknown_token(client, db_session):
    r = await client.get("/c/nope/card.jpg")
    assert r.status_code == 404
