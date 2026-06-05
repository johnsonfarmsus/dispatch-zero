"""Publish an approved Dispatch Zero submission as an OSM node.

Two modes governed by settings.osm_dry_run:

- Dry run (default): build the changeset metadata + osmChange XML,
  log it, store an osm_publications row with dry_run=True, do NOT
  POST to OSM. Used to verify the round-trip (OAuth + tag mapping +
  XML construction) before any real edit lands.

- Live: do the full three-step OSM Editing API dance:
    1. PUT /api/0.6/changeset/create           → changeset_id
    2. POST /api/0.6/changeset/:id/upload      → node_id (in response)
    3. PUT /api/0.6/changeset/:id/close
  Record the result in osm_publications with the real changeset_id +
  node_id and dry_run=False. That row is what the daily cap counts.

The function is structured so the daily-cap check fires BEFORE we do
any network work. Cap-busted requests never call OSM.

References:
- API 0.6 docs: https://wiki.openstreetmap.org/wiki/API_v0.6
- Automated edits etiquette: https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import Settings
from dispatchzero.models import OsmPublication, Place, Submission, User
from dispatchzero.services import osm_oauth, osm_tagging

log = logging.getLogger(__name__)


class OsmPublishError(RuntimeError):
    """Raised when a publish can't proceed. The admin route turns this
    into a 4xx / 5xx with the message text."""


class OsmDailyCapReachedError(OsmPublishError):
    """Specific failure for cap exhaustion — the route shows a
    user-friendly explanation."""


async def todays_real_publish_count(db: AsyncSession) -> int:
    """How many real (non-dry-run) publishes have landed since midnight UTC.
    Used to gate the Approve+OSM button + the publish endpoint itself."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return int(
        (
            await db.execute(
                select(func.count(OsmPublication.id))
                .where(OsmPublication.published_at >= today_start)
                .where(OsmPublication.dry_run.is_(False))
            )
        ).scalar_one()
        or 0
    )


def _build_changeset_xml(
    *, settings: Settings, place_name: str, category: str,
) -> bytes:
    osm = ET.Element("osm")
    cs = ET.SubElement(osm, "changeset")
    # created_by lets OSM tools filter our edits at a glance.
    for k, v in [
        ("created_by", settings.osm_user_agent.split(" ", 1)[0]),
        ("comment", osm_tagging.changeset_comment(
            place_name=place_name, category=category,
        )),
        ("source", "survey;Dispatch Zero"),
        ("bot", "no"),  # OSM convention: 'no' for reviewer-mediated edits
    ]:
        ET.SubElement(cs, "tag", {"k": k, "v": v})
    return ET.tostring(osm, encoding="utf-8", xml_declaration=True)


def _build_osmchange_xml(
    *,
    changeset_id: int,
    lat: float,
    lng: float,
    tags: dict[str, str],
) -> bytes:
    """Build the <osmChange> body for /changeset/:id/upload. The new node
    uses a negative placeholder id (-1); OSM rewrites it on accept and
    returns the real ID in the diffResult."""
    osc = ET.Element("osmChange", {"version": "0.6", "generator": "Dispatch Zero"})
    create = ET.SubElement(osc, "create")
    node = ET.SubElement(
        create, "node",
        {
            "id": "-1",
            "version": "0",
            "changeset": str(changeset_id),
            "lat": f"{lat:.7f}",
            "lon": f"{lng:.7f}",
        },
    )
    for k, v in tags.items():
        ET.SubElement(node, "tag", {"k": k, "v": v})
    return ET.tostring(osc, encoding="utf-8", xml_declaration=True)


def _parse_node_id_from_diff(diff_xml: str) -> int | None:
    """The OSM upload response is <diffResult> with one or more <node>
    children each carrying old_id="-1" and new_id="N". Pull the first
    new_id we find."""
    try:
        root = ET.fromstring(diff_xml)
    except ET.ParseError:
        return None
    for n in root.findall("node"):
        nid = n.attrib.get("new_id")
        if nid is not None:
            try:
                return int(nid)
            except ValueError:
                continue
    return None


async def publish_place_to_osm(
    *,
    db: AsyncSession,
    settings: Settings,
    place: Place,
    lat: float,
    lng: float,
    reviewer: User,
    submission: Submission | None = None,
    picker_choice: str | None = None,
) -> OsmPublication:
    """Publish (or dry-publish) a Place to OSM as a node.

    Two calling shapes:
      - With submission=...: the submission-driven path. external_link
        is read off the submission row; submission_id is recorded on the
        publication.
      - With submission=None: the completion-candidate path. external_link
        comes only from the place itself (wikipedia= auto-derived for
        wp osm_type); the publication row's submission_id stays NULL.

    Returns the OsmPublication row recording what happened. Raises
    OsmPublishError on any failure (cap, missing tags, OAuth, HTTP).
    See publish_submission_to_osm for the submission-flavored wrapper
    kept for back-compat.
    """
    """Publish (or dry-publish) one approved submission to OSM as a node.

    Caller already invoked approve_submission separately; this function
    just handles the OSM side. Raises OsmPublishError on any failure
    (cap, missing tags, OAuth, HTTP). The caller decides whether to
    surface the error to the admin or fall back to "approved but not
    published."

    Returns the OsmPublication row recording what happened (or what
    would have happened, in dry-run mode)."""
    # ---- duplicate guard ----
    # Never publish the same place twice. Two redundant checks: the
    # cheap one (places.osm_published_node_id stamped earlier) and the
    # historical one (any non-dry-run row in osm_publications with this
    # place_id). Either rules out the publish.
    if place.osm_published_node_id is not None:
        raise OsmPublishError(
            f"this place is already on OSM (node {place.osm_published_node_id})."
        )

    # ---- tags ----
    tags = osm_tagging.tags_for_publish(
        category=place.category,
        place_name=place.name or "",
        description=(submission.description if submission else None),
        picker_choice=picker_choice,
        external_link=(submission.external_link if submission else None),
        place_osm_type=place.osm_type,
    )
    if tags is None:
        if osm_tagging.is_ambiguous(place.category):
            raise OsmPublishError(
                f"category {place.category!r} requires a subtype pick before publish."
            )
        raise OsmPublishError(
            f"no OSM tag mapping for category {place.category!r}."
        )

    # ---- cap (real publishes only) ----
    if not settings.osm_dry_run:
        count = await todays_real_publish_count(db)
        if count >= settings.osm_daily_publish_cap:
            raise OsmDailyCapReachedError(
                f"daily OSM publish cap reached "
                f"({count}/{settings.osm_daily_publish_cap}). "
                "Approve normally; try OSM again tomorrow UTC."
            )

    # ---- dry-run path: build XML, log, store, done ----
    if settings.osm_dry_run:
        changeset_xml = _build_changeset_xml(
            settings=settings, place_name=place.name or "", category=place.category,
        )
        # Use a fake changeset id (0) in the dry-run osmChange so the XML
        # still parses; the real path overwrites this with the value
        # OSM hands back.
        osmchange_xml = _build_osmchange_xml(
            changeset_id=0, lat=lat, lng=lng, tags=tags,
        )
        log.info(
            "OSM dry-run publish for %s\n"
            "--- changeset.xml ---\n%s\n"
            "--- osmChange.xml ---\n%s",
            f"submission {submission.id}" if submission else f"place {place.id}",
            changeset_xml.decode("utf-8"),
            osmchange_xml.decode("utf-8"),
        )
        return await _record_publication(
            db,
            submission_id=(submission.id if submission else None),
            place_id=place.id,
            changeset_id=None,
            node_id=None,
            tags=tags,
            lat=lat,
            lng=lng,
            reviewer=reviewer,
            dry_run=True,
        )

    # ---- live path ----
    access_token = await osm_oauth.get_fresh_access_token(db, settings)
    headers = {
        "User-Agent": settings.osm_user_agent,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "text/xml; charset=utf-8",
    }

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        # 1. Create changeset
        changeset_xml = _build_changeset_xml(
            settings=settings,
            place_name=place.name or "",
            category=place.category,
        )
        r = await client.put(
            f"{settings.osm_base_url}/api/0.6/changeset/create",
            content=changeset_xml,
        )
        if r.status_code != 200:
            log.error("OSM changeset create failed: %s %s", r.status_code, r.text)
            raise OsmPublishError(
                f"OSM changeset create failed ({r.status_code}): {r.text[:200]}"
            )
        try:
            changeset_id = int(r.text.strip())
        except ValueError as e:
            raise OsmPublishError(
                f"OSM returned a non-integer changeset id: {r.text!r}"
            ) from e

        # 2. Upload the node
        osmchange_xml = _build_osmchange_xml(
            changeset_id=changeset_id, lat=lat, lng=lng, tags=tags,
        )
        r = await client.post(
            f"{settings.osm_base_url}/api/0.6/changeset/{changeset_id}/upload",
            content=osmchange_xml,
        )
        if r.status_code != 200:
            log.error("OSM upload failed: %s %s", r.status_code, r.text)
            # Try to close the changeset so it doesn't linger open even on failure.
            try:
                await client.put(
                    f"{settings.osm_base_url}/api/0.6/changeset/{changeset_id}/close"
                )
            except httpx.HTTPError:
                pass
            raise OsmPublishError(
                f"OSM upload failed ({r.status_code}): {r.text[:200]}"
            )
        node_id = _parse_node_id_from_diff(r.text)
        if node_id is None:
            log.warning("OSM upload OK but could not parse node id from %r", r.text)

        # 3. Close changeset (separate request, OSM API style)
        r = await client.put(
            f"{settings.osm_base_url}/api/0.6/changeset/{changeset_id}/close"
        )
        if r.status_code not in (200, 404):
            # 404 happens if the changeset already auto-closed; not an error.
            log.warning("OSM changeset close non-200: %s %s", r.status_code, r.text)

    # Stamp the Place with the assigned OSM node ID. This is the fast
    # dedup check the admin queue uses to disable Submit-to-OSM on
    # already-published places.
    if node_id is not None:
        place.osm_published_node_id = node_id
        await db.commit()
        await db.refresh(place)

    return await _record_publication(
        db,
        submission_id=submission.id,
        place_id=place.id,
        changeset_id=changeset_id,
        node_id=node_id,
        tags=tags,
        lat=lat,
        lng=lng,
        reviewer=reviewer,
        dry_run=False,
    )


async def publish_submission_to_osm(
    *,
    db: AsyncSession,
    settings: Settings,
    submission: Submission,
    place: Place,
    lat: float,
    lng: float,
    reviewer: User,
    picker_choice: str | None = None,
) -> OsmPublication:
    """Thin wrapper preserving the prior signature — admin's
    approve-and-publish route still calls this. New callers should use
    publish_place_to_osm directly with optional submission."""
    return await publish_place_to_osm(
        db=db,
        settings=settings,
        submission=submission,
        place=place,
        lat=lat,
        lng=lng,
        reviewer=reviewer,
        picker_choice=picker_choice,
    )


async def _record_publication(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    place_id: uuid.UUID | None,
    changeset_id: int | None,
    node_id: int | None,
    tags: dict[str, str],
    lat: float,
    lng: float,
    reviewer: User,
    dry_run: bool,
) -> OsmPublication:
    pub = OsmPublication(
        id=uuid.uuid4(),
        submission_id=submission_id,
        place_id=place_id,
        changeset_id=changeset_id,
        node_id=node_id,
        tags_json=dict(tags),
        lat=lat,
        lng=lng,
        published_by_user_id=reviewer.id,
        dry_run=dry_run,
    )
    db.add(pub)
    await db.commit()
    await db.refresh(pub)
    return pub
