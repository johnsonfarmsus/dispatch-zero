"""Operative-address cleanup for cached briefings.

Briefings are cached and SHARED across users (the library cache returns one
anonymous Mission row per place+style to everyone). Earlier regimes tried to
personalize the briefing with the viewer's call sign: first by baking it into
the text (which leaked one user's name to the next), then via a {operative}
placeholder the model was told to emit. Small models mangled that placeholder
into things like `{}` (which rendered as a literal "Operative {}, ..."), and the
forced word "operative" read wrong in the non-spy organizations (The Guild, The
Archive).

So briefings no longer name the operative at all. The prompt now writes in the
second person, and the player's call sign appears only where it is code-rendered
and reliable: the mission card header, ranks, and the dossier.

This module is the cleanup safety net for briefings generated under the old
regimes that are still cached or sitting in someone's history. It strips any
leftover placeholder token and the vocative built around it, so nothing ever
renders as "{}" or a stale "{operative}". Text with no such artifact passes
through untouched, so every current briefing is a no-op.
"""
import re

# A placeholder/token artifact the old prompt produced: {operative}, {},
# [operative], < operative >, etc.
_TOKEN = r"[\{\[<][^\}\]>]*[\}\]>]"

# Fast gate: only briefings that actually contain a brace/bracket token get
# rewritten. Everything else (every briefing generated under the current prompt)
# returns unchanged, so well-formed text is never touched.
_HAS_TOKEN_RE = re.compile(_TOKEN)

# The token plus the vocative scaffolding around it: an optional leading role
# word and a trailing comma. Matches "Operative {}, ", "{operative}, ", and a
# bare "{operative}".
_VOCATIVE_RE = re.compile(
    r"(?:\b(?:Operative|Agent|Warden|Asset|Acolyte)\s+)?" + _TOKEN + r"\s*,?\s*",
    re.IGNORECASE,
)


def clean_operative_address(text: str | None) -> str | None:
    """Strip leftover {operative}-style placeholders (and the vocative built
    around them) from an old-regime briefing.

    No-op on text without a token artifact, so all current briefings pass
    straight through untouched.
    """
    if not text or _HAS_TOKEN_RE.search(text) is None:
        return text
    out = _VOCATIVE_RE.sub("", text)
    # Tidy the seams a removed vocative leaves behind.
    out = re.sub(r"\s+([,;:.])", r"\1", out)      # " ," -> ","
    out = re.sub(r"[ \t]{2,}", " ", out)           # collapse runs of spaces
    out = re.sub(r"^[\s,;:.\-]+", "", out)          # leading punctuation/space
    # Recapitalize sentence starts we may have lowercased by removing a vocative.
    out = re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        out,
    )
    return out.strip()
