"""Operative call-sign tokenization.

Briefings are cached and SHARED across users (the library cache in
services.missions returns one Mission row per place+style to everyone). So the
operative's call sign must never be baked into the stored briefing text — if it
were, the first generator's call sign would leak to every later viewer.

Instead the model writes a placeholder token wherever it addresses the
operative, and we substitute the *viewing* operative's call sign at every read
surface. This keeps briefings personalized without coupling the cached text to
one user. It mirrors the code-controlled sign-off: identity is owned by code,
not the model.

The "viewing operative" differs by surface:
  - live dispatch (services.missions / _mission_to_out): the requesting user
  - mission card (capture, history, public share): the COMPLETER
"""
import re

# The literal token the model is told to emit wherever it would name or address
# the operative. Stored verbatim in the cached briefing; substituted on read.
OPERATIVE_TOKEN = "{operative}"

# Render-time matcher. Deliberately forgiving: small models mangle the token
# into [operative], <operative>, { operative }, {OPERATIVE}, etc. — all of those
# resolve to the viewer's call sign. A bare word "operative" with no delimiters
# is left untouched (it's a valid generic address, no name to inject).
_TOKEN_RE = re.compile(r"[\{\[<]\s*operative\s*[\}\]>]", re.IGNORECASE)


def personalize_operative(text: str | None, callsign: str) -> str | None:
    """Replace the operative placeholder token with `callsign`.

    Idempotent and safe on text that has no token (returns it unchanged), so it
    can be applied unconditionally at every output surface — including old
    pre-token briefings, which simply pass through.
    """
    if not text:
        return text
    return _TOKEN_RE.sub(callsign, text)
