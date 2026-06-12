"""Tests for the OSM publish service (osm_publish.py).

The highest-value coverage here is the LIVE path with submission=None — the
completion-candidate publish (POST /admin/places/{id}/publish-osm). That path
had a latent crash (submission.id read unconditionally) that only surfaced
once OSM_DRY_RUN was flipped off, because dry-run masked it. These tests lock
both the submission and submission=None shapes for dry-run AND live.

OSM HTTP is mocked with respx; no real network. XML helpers are unit-tested
directly.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlalchemy import func, select

from dispatchzero.config import get_settings
from dispatchzero.models import (
    OsmCredentials,
    OsmPublication,
    Place,
    PlaceCategory,
    PlaceStatus,
    User,
)
from dispatchzero.services import osm_publish
from dispatchzero.services.osm_publish import (
    OsmDailyCapReachedError,
    OsmPublishError,
    _build_osmchange_xml,
    _parse_node_id_from_diff,
    publish_place_to_osm,
)

# --- pure XML helpers (no DB / network) --------------------------------------


class TestXmlHelpers:
    def test_osmchange_contains_node_and_tags(self):
        xml = _build_osmchange_xml(
            changeset_id=42, lat=47.5, lng=-118.25,
            tags={"tourism": "artwork", "artwork_type": "mural", "name": "X"},
        ).decode()
        assert 'changeset="42"' in xml
        assert 'lat="47.5000000"' in xml
        assert 'lon="-118.2500000"' in xml
        assert 'k="tourism"' in xml and 'v="artwork"' in xml
        assert 'id="-1"' in xml  # negative placeholder

    def test_parse_node_id_from_diff(self):
        diff = '<diffResult><node old_id="-1" new_id="123456" new_version="1"/></diffResult>'
        assert _parse_node_id_from_diff(diff) == 123456

    def test_parse_node_id_handles_garbage(self):
        assert _parse_node_id_from_diff("not xml") is None
        assert _parse_node_id_from_diff("<diffResult></diffResult>") is None


# --- fixtures ----------------------------------------------------------------


async def _make_user(db, callsign="Reviewer", is_admin=True) -> User:
    u = User(
        callsign=callsign, callsign_lower=callsign.lower(),
        password_hash="x", adventure_style="agency", is_admin=is_admin,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


_osm_id_counter = iter(range(10000, 99999))


async def _make_place(db, *, osm_type="wp", name="Egypt Church",
                      category="church", lat=47.5, lng=-118.25) -> Place:
    place = Place(
        id=uuid.uuid4(),
        osm_type=osm_type,
        # Unique per place so multiple places in one test don't collide on
        # the (osm_type, osm_id) uniqueness constraint.
        osm_id=next(_osm_id_counter),
        name=name,
        category=category,
        coordinates=f"SRID=4326;POINT({lng} {lat})",
        tags={},
        status=PlaceStatus.ACTIVE.value,
    )
    db.add(place)
    await db.commit()
    await db.refresh(place)
    return place


async def _make_credentials(db) -> OsmCredentials:
    creds = OsmCredentials(
        id=1,
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        # Far-future expiry so get_fresh_access_token doesn't try to refresh.
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        osm_user_id=1, osm_username="DispatchZero",
    )
    db.add(creds)
    await db.commit()
    return creds


def _mock_osm_live(settings, *, node_id=987654):
    """Register respx mocks for the 3-step changeset dance."""
    base = settings.osm_base_url
    respx.put(f"{base}/api/0.6/changeset/create").mock(
        return_value=httpx.Response(200, text="555")
    )
    respx.post(f"{base}/api/0.6/changeset/555/upload").mock(
        return_value=httpx.Response(
            200,
            text=f'<diffResult><node old_id="-1" new_id="{node_id}"/></diffResult>',
        )
    )
    respx.put(f"{base}/api/0.6/changeset/555/close").mock(
        return_value=httpx.Response(200)
    )


# --- dry-run path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_place_only_records_publication(db_session, monkeypatch):
    """The completion-candidate shape (submission=None) in dry-run mode."""
    monkeypatch.setenv("OSM_DRY_RUN", "true")
    get_settings.cache_clear()
    settings = get_settings()
    admin = await _make_user(db_session)
    place = await _make_place(db_session, osm_type="wp", category="church")

    pub = await publish_place_to_osm(
        db=db_session, settings=settings, place=place,
        lat=47.5, lng=-118.25, reviewer=admin, submission=None,
    )
    assert pub.dry_run is True
    assert pub.submission_id is None
    assert pub.place_id == place.id
    assert pub.node_id is None  # no real node in dry-run
    # wp-sourced church auto-derives the wikipedia tag
    assert pub.tags_json["wikipedia"] == "en:Egypt Church"
    assert pub.tags_json["amenity"] == "place_of_worship"


# --- live path (the regression that mattered) --------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_live_place_only_publish_does_not_crash(db_session, monkeypatch):
    """REGRESSION: submission=None on the LIVE path used to AttributeError
    after the OSM node was already created. It must now record a publication
    with submission_id=None and stamp the place's osm_published_node_id."""
    monkeypatch.setenv("OSM_DRY_RUN", "false")
    get_settings.cache_clear()
    settings = get_settings()
    admin = await _make_user(db_session)
    place = await _make_place(db_session, osm_type="wp", category="church")
    await _make_credentials(db_session)
    _mock_osm_live(settings, node_id=987654)

    pub = await publish_place_to_osm(
        db=db_session, settings=settings, place=place,
        lat=47.5, lng=-118.25, reviewer=admin, submission=None,
    )

    assert pub.dry_run is False
    assert pub.submission_id is None
    assert pub.node_id == 987654
    assert pub.changeset_id == 555

    # Place stamped + audit row both landed (single transaction).
    refreshed = (await db_session.execute(
        select(Place).where(Place.id == place.id)
    )).scalar_one()
    assert refreshed.osm_published_node_id == 987654

    count = (await db_session.execute(
        select(func.count(OsmPublication.id)).where(OsmPublication.dry_run.is_(False))
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
@respx.mock
async def test_live_publish_counts_against_daily_cap(db_session, monkeypatch):
    monkeypatch.setenv("OSM_DRY_RUN", "false")
    monkeypatch.setenv("OSM_DAILY_PUBLISH_CAP", "1")
    get_settings.cache_clear()
    settings = get_settings()
    admin = await _make_user(db_session)
    await _make_credentials(db_session)
    place1 = await _make_place(db_session, name="A", category="church")
    _mock_osm_live(settings, node_id=111)

    await publish_place_to_osm(
        db=db_session, settings=settings, place=place1,
        lat=47.5, lng=-118.25, reviewer=admin, submission=None,
    )

    # Second publish should be blocked by the cap (1/day).
    place2 = await _make_place(db_session, name="B", category="church", lat=47.6)
    with pytest.raises(OsmDailyCapReachedError):
        await publish_place_to_osm(
            db=db_session, settings=settings, place=place2,
            lat=47.6, lng=-118.25, reviewer=admin, submission=None,
        )


@pytest.mark.asyncio
async def test_already_published_place_is_refused(db_session, monkeypatch):
    monkeypatch.setenv("OSM_DRY_RUN", "false")
    get_settings.cache_clear()
    settings = get_settings()
    admin = await _make_user(db_session)
    place = await _make_place(db_session, category="church")
    place.osm_published_node_id = 42
    await db_session.commit()

    with pytest.raises(OsmPublishError, match="already on OSM"):
        await publish_place_to_osm(
            db=db_session, settings=settings, place=place,
            lat=47.5, lng=-118.25, reviewer=admin, submission=None,
        )


@pytest.mark.asyncio
async def test_ambiguous_category_without_picker_refused(db_session, monkeypatch):
    monkeypatch.setenv("OSM_DRY_RUN", "true")
    get_settings.cache_clear()
    settings = get_settings()
    admin = await _make_user(db_session)
    place = await _make_place(db_session, category="infrastructure", osm_type="node")

    with pytest.raises(OsmPublishError, match="subtype"):
        await publish_place_to_osm(
            db=db_session, settings=settings, place=place,
            lat=47.5, lng=-118.25, reviewer=admin, submission=None,
        )
