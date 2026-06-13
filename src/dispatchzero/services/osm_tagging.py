"""Map a Dispatch Zero submission to a bundle of OSM tags.

Our 9 categories don't map 1:1 to OSM. Two have multiple valid OSM
encodings depending on the specific subject (historic, infrastructure)
and need a secondary picker. The other 7 have a single sensible
mapping and publish straight through.

References:
- tourism=artwork: https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dartwork
- historic=*: https://wiki.openstreetmap.org/wiki/Key:historic
- amenity=place_of_worship: https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dplace_of_worship
- leisure=park: https://wiki.openstreetmap.org/wiki/Tag:leisure%3Dpark
- man_made=*: https://wiki.openstreetmap.org/wiki/Key:man_made
- waterway=dam: https://wiki.openstreetmap.org/wiki/Tag:waterway%3Ddam

The conservative posture: only publish tags we're confident are correct.
Anything ambiguous bubbles up to the reviewer as a picker before publish.
"""
import re
from datetime import datetime, timezone

from dispatchzero.services.url_parsing import normalize_url, parse_wikipedia_link

# OSM wikidata= values are a Q followed by digits.
_WIKIDATA_QID_RE = re.compile(r"^Q[0-9]+$")


# Categories that resolve to one tag bundle. The reviewer just clicks
# Approve+OSM and we publish.
_SIMPLE_TAGS: dict[str, list[tuple[str, str]]] = {
    "mural": [("tourism", "artwork"), ("artwork_type", "mural")],
    "sculpture": [("tourism", "artwork"), ("artwork_type", "sculpture")],
    "memorial": [("historic", "memorial")],
    "viewpoint": [("tourism", "viewpoint")],
    # religion= is added in tags_for_publish from config.osm_default_religion
    # (default "christian" for rural-US coverage; set "" to omit), not baked
    # in here, so non-US instances can change it without a code edit.
    "church": [("amenity", "place_of_worship")],
    "park": [("leisure", "park")],
    # The "civic" category is loosely defined in our schema; the example
    # given (post office) is the most common case. Pick that as default.
    # If we ever broaden civic to libraries/town halls/etc., this gets a
    # picker.
    "civic": [("amenity", "post_office")],
}


# Categories where the reviewer must pick a specific subtype before
# we publish. Keys are our category; values are pickable options the
# UI renders as a dropdown.
AMBIGUOUS_CHOICES: dict[str, list[dict]] = {
    "historic": [
        {
            "value": "building",
            "label": "Historic building (general)",
            "tags": [("historic", "building")],
        },
        {
            "value": "monument",
            "label": "Monument",
            "tags": [("historic", "monument")],
        },
        {
            "value": "memorial",
            "label": "Memorial",
            "tags": [("historic", "memorial")],
        },
        {
            "value": "ruins",
            "label": "Ruins",
            "tags": [("historic", "ruins")],
        },
        {
            "value": "manor",
            "label": "Historic house",
            "tags": [("historic", "manor")],
        },
        {
            "value": "archaeological_site",
            "label": "Archaeological site",
            "tags": [("historic", "archaeological_site")],
        },
    ],
    "infrastructure": [
        {
            "value": "bridge",
            "label": "Bridge",
            "tags": [("man_made", "bridge")],
        },
        {
            "value": "tower",
            "label": "Tower (water / observation / other)",
            "tags": [("man_made", "tower")],
        },
        {
            "value": "dam",
            "label": "Dam",
            "tags": [("waterway", "dam")],
        },
        {
            "value": "silo",
            "label": "Silo / grain elevator",
            "tags": [("man_made", "silo")],
        },
        {
            "value": "windmill",
            "label": "Windmill",
            "tags": [("man_made", "windmill")],
        },
        {
            "value": "pumping_station",
            "label": "Pumping station",
            "tags": [("man_made", "pumping_station")],
        },
    ],
}


def is_ambiguous(category: str) -> bool:
    """Category requires a reviewer subtype pick before we can publish."""
    return category in AMBIGUOUS_CHOICES


def picker_choices(category: str) -> list[dict] | None:
    """List of options the admin UI renders for an ambiguous category.

    Returns None for unambiguous categories. Each option is a dict with
    `value` (form value), `label` (human text), and `tags` (list of
    (key, value) — the tag bundle we attach if the reviewer picks this).
    """
    return AMBIGUOUS_CHOICES.get(category)


def auto_wiki_tag_for_place(
    *, osm_type: str, name: str | None,
) -> str | None:
    """Return a wikipedia= tag value derived from the place's own data, if
    one is implied by where the place came from. Used for completion-driven
    publishes where there's no user-typed external_link to consult.

    Wikipedia-sourced places (osm_type='wp') always have `name` set to the
    article title and were ingested from en.wikipedia. Anything else: no
    derived wiki tag (the user-typed external_link is the only path).

    Output format matches the wikipedia= tag convention: '<lang>:<title>'.
    """
    if osm_type == "wp" and name:
        from dispatchzero.config import get_settings
        lang = (get_settings().wikipedia_language or "en").strip().lower() or "en"
        return f"{lang}:{name}"
    return None


def tags_for_publish(
    *,
    category: str,
    place_name: str,
    description: str | None = None,
    picker_choice: str | None = None,
    external_link: str | None = None,
    place_osm_type: str | None = None,
    wikidata_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, str] | None:
    """Return the full tag dict we'll send to OSM, or None if we can't
    publish this category without more input.

    Adds the common metadata (name, source, source:date) on top of the
    category-specific tags. For ambiguous categories, the caller must
    pass picker_choice (one of the `value` keys from picker_choices());
    if not, returns None.

    external_link, if provided, becomes either:
      - wikipedia=<lang>:<title>   when the URL is a Wikipedia article
      - website=<url>              for any other valid http(s) URL
    Invalid / blank links are silently dropped (the user typed something
    that wasn't a URL — better to skip than to emit a broken tag).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    primary: list[tuple[str, str]]
    if category in _SIMPLE_TAGS:
        primary = list(_SIMPLE_TAGS[category])
    elif category in AMBIGUOUS_CHOICES:
        if picker_choice is None:
            return None
        match = next(
            (c for c in AMBIGUOUS_CHOICES[category] if c["value"] == picker_choice),
            None,
        )
        if match is None:
            return None
        primary = list(match["tags"])
    else:
        # Unknown category — we don't have a mapping; bail rather than
        # ship something wrong to OSM.
        return None

    tags: dict[str, str] = {}
    # Name first so it lands at the top of the changeset XML for
    # human reviewers who happen to look at the raw output.
    if place_name:
        tags["name"] = place_name[:255]
    for k, v in primary:
        tags[k] = v
    # place_of_worship gets the configured default religion (if any). Kept
    # here rather than in _SIMPLE_TAGS so it's instance-configurable.
    if tags.get("amenity") == "place_of_worship":
        from dispatchzero.config import get_settings
        religion = (get_settings().osm_default_religion or "").strip()
        if religion:
            tags["religion"] = religion
    # External link → wikipedia= or website=. We prefer the wikipedia tag
    # when applicable because it's the strongest semantic link; website is
    # the catch-all for everything else (official sites, local history
    # pages, news articles).
    wiki_tag_set = False
    if external_link:
        wiki = parse_wikipedia_link(external_link)
        if wiki is not None:
            lang, title = wiki
            tags["wikipedia"] = f"{lang}:{title}"
            wiki_tag_set = True
        else:
            normalized = normalize_url(external_link)
            if normalized:
                tags["website"] = normalized[:255]
    # Fallback: when the place itself came from Wikipedia (osm_type='wp'),
    # auto-derive the wikipedia= tag from its name. The user-supplied
    # external_link wins if present; otherwise the auto-derivation fills
    # the slot. Submission paths usually have an explicit link or none;
    # completion-candidate paths (Wikipedia places) rely on this fallback.
    if not wiki_tag_set and place_osm_type:
        auto = auto_wiki_tag_for_place(
            osm_type=place_osm_type, name=place_name,
        )
        if auto:
            tags["wikipedia"] = auto
    # wikidata= is the strongest semantic link in OSM (stable across article
    # renames) and the tag mappers most want. Resolved by the caller from
    # the place's Wikipedia title at publish time. Only attach a well-formed
    # Q-id (Q followed by digits) so a malformed value never ships.
    if wikidata_id and _WIKIDATA_QID_RE.match(wikidata_id):
        tags["wikidata"] = wikidata_id
    # Common provenance metadata — OSM mappers can identify Dispatch Zero
    # nodes at a glance, and source=survey signals on-the-ground
    # verification (which is true: every submission is GPS-stamped at
    # the photo location).
    tags["source"] = "survey;Dispatch Zero"
    tags["source:date"] = now.strftime("%Y-%m-%d")
    return tags


def changeset_comment(*, place_name: str, category: str) -> str:
    """The comment= tag on the changeset itself. OSM lists changesets
    in feeds, and this is what shows up next to the timestamp and the
    account username. Keep it short and accurate."""
    if place_name:
        return f"Add {category}: {place_name} (via Dispatch Zero)"
    return f"Add {category} (via Dispatch Zero)"
