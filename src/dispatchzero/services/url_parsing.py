"""Tiny URL classifier — decide which OSM tag a user-provided link becomes.

Used by the submission → OSM publish path. The user's "Link (optional)"
field can hold any URL; what we do with it on OSM depends on whether it's
a Wikipedia article (gets the wikipedia= tag) or any other URL (gets the
website= tag).

Kept deliberately conservative: we don't try to follow redirects, look up
Wikidata IDs, or normalize Wikipedia article titles. If the URL parses
cleanly and matches the wikipedia.org host pattern, we extract the
language + title. Otherwise it stays a plain URL.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

# Matches the language-coded Wikipedia host pattern (en, de, simple, etc.).
# Captures the language code. Allows the `www.wikipedia.org` and bare
# `wikipedia.org` forms as fallbacks (rare, but a user might paste them).
_WIKI_HOST = re.compile(r"^(?:([a-z-]{2,16})\.)?wikipedia\.org$", re.IGNORECASE)
# /wiki/Article_Title  — the standard Wikipedia article path. Anything else
# (Special:Search, talk pages, etc.) is excluded; those aren't useful as
# wikipedia= tag values on OSM.
_WIKI_PATH = re.compile(r"^/wiki/([^/?#]+)$")

# Non-mainspace namespace prefixes. A "/wiki/<title>" whose title begins
# with one of these (case-insensitively) followed by a colon is a Special
# page, talk page, category, etc. — not an article — and must NOT become a
# wikipedia= tag. We check a known prefix list rather than "any colon"
# because legitimate mainspace article titles can contain colons
# (e.g. "Dune: Part Two").
_WIKI_NAMESPACE_PREFIXES = (
    "special", "talk", "user", "wikipedia", "file", "mediawiki",
    "template", "help", "category", "portal", "draft", "timedtext",
    "module", "media", "book",
)


def parse_wikipedia_link(url: str) -> tuple[str, str] | None:
    """Return (lang, article_title) for a valid Wikipedia article URL,
    or None for anything else.

    Examples:
        en.wikipedia.org/wiki/Harrington_Bank_Block → ("en", "Harrington Bank Block")
        de.wikipedia.org/wiki/Berlin               → ("de", "Berlin")
        wikipedia.org/wiki/Foo                     → ("en", "Foo")  [default lang]
        en.wikipedia.org/wiki/Special:Search       → None  [non-article path]
        google.com/maps/...                        → None
    """
    if not url or not isinstance(url, str):
        return None
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https"):
        return None
    host_match = _WIKI_HOST.match(u.hostname or "")
    if host_match is None:
        return None
    lang = (host_match.group(1) or "en").lower()
    path_match = _WIKI_PATH.match(u.path or "")
    if path_match is None:
        return None
    # Wikipedia uses underscores in URLs; the wikipedia= tag wants
    # spaces. Also URL-decode for things like %27 (apostrophes).
    title = unquote(path_match.group(1)).replace("_", " ")
    if not title:
        return None
    # Reject non-article namespaces (Special:, Talk:, Category:, etc.).
    prefix, sep, _rest = title.partition(":")
    if sep and prefix.strip().lower() in _WIKI_NAMESPACE_PREFIXES:
        return None
    return lang, title


def normalize_url(url: str | None) -> str | None:
    """Trim whitespace + sanity-check. Returns None for blank input or for
    anything that doesn't parse to an http/https URL with a host."""
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    return url
