"""Conservative cross-source place de-duplication.

The discovery ladder reads from OSM (tiers 1-2, 4) and Wikipedia (tier 3).
A landmark that exists in BOTH ends up as two Place rows — an osm_type='node'
row and an osm_type='wp' row — at slightly different coordinates, because the
unique key is (osm_type, osm_id). Nothing reconciles them, so a user can be
dispatched to "the same place" twice.

Wikipedia runs AFTER the OSM tiers, so by the time we ingest a wp place the
OSM equivalent is usually already in the DB. The fix: before inserting a wp
place, look for an existing non-wp place within a tight radius whose name
strongly matches, and if found, reuse it instead of creating a duplicate.

"Conservative" (the chosen posture): few false merges. We require the same
set of *significant* name tokens (stopwords + the category word stripped),
not just proximity — so "First Presbyterian Church" and "First Baptist
Church" near each other do NOT merge (they share only the stopword-ish
tokens), while "Harrington Opera House" and "Opera House (Harrington)" do.
"""
import re

# Default merge radius. Tight on purpose: two POIs 50m apart with the same
# significant name are almost certainly the same real thing.
DEDUP_RADIUS_M = 50

# Tokens that carry no disambiguating signal for name matching. Includes
# generic category words so "<Name> Church" matches "<Name>".
_STOPWORDS = frozenset({
    "the", "of", "and", "a", "an", "at", "in", "on",
    "church", "chapel", "cathedral", "building", "house", "hall",
    "park", "trail", "memorial", "monument", "museum", "site", "historic",
    "national", "state", "county", "city", "old", "new",
    "mural", "sculpture", "statue", "bridge", "tower", "dam",
})

# Common abbreviation normalizations applied before tokenizing.
_ABBREV = {
    "st": "saint",
    "ste": "saint",
    "mt": "mount",
    "ft": "fort",
}


def _norm_tokens(name: str) -> list[str]:
    """Lowercased, punctuation-stripped, abbreviation-normalized tokens
    (stopwords retained). Single-character tokens are dropped: they carry
    no disambiguating signal and are usually possessive-'s debris
    ("Mary's" -> "mary s" -> "mary")."""
    if not name:
        return []
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return [_ABBREV.get(t, t) for t in cleaned.split() if len(t) > 1]


def _full_normalized(name: str) -> str:
    return " ".join(_norm_tokens(name))


def _significant_tokens(name: str) -> frozenset[str]:
    """Token set with stopwords + generic category words removed."""
    return frozenset(t for t in _norm_tokens(name) if t not in _STOPWORDS)


def names_match(a: str, b: str) -> bool:
    """Conservative name match. Matches when EITHER:
      - the full normalized names are identical (e.g. "Egypt Church" ~
        "egypt church"), OR
      - the two names share the exact same set of significant tokens AND
        that set has 2+ tokens.

    The 2-token floor on the token-set path prevents single-shared-token
    false merges ("Riverside Park" vs "Riverside Trail" both reduce to
    {riverside} but their full names differ, so they do NOT merge).

    MATCH:    "Harrington Opera House" ~ "Opera House, Harrington" ({harrington, opera})
              "St Mary's Church"       ~ "Saint Mary Church"       (st->saint; {saint, mary})
    NO MATCH: "First Presbyterian Church" ~ "First Baptist Church" ({first,presbyterian}!={first,baptist})
              "Riverside Park"           ~ "Riverside Trail"       (single token, full names differ)
    """
    if not a or not b:
        return False
    if _full_normalized(a) == _full_normalized(b):
        return True
    ta, tb = _significant_tokens(a), _significant_tokens(b)
    return len(ta) >= 2 and ta == tb
