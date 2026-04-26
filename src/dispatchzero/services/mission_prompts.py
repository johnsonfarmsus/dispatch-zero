"""Style-specific mission prompt builder.

Each style produces messages in OpenAI-compatible format (system + user).
All styles MUST instruct the model to sign as 'Zero' and to respond as a
JSON object with the four content fields.
"""
from typing import Literal

AdventureStyle = Literal["pulp", "agency", "guild"]

_JSON_CONTRACT = """
You MUST respond with a single JSON object containing exactly these fields:
{
  "dispatch_summary": "<2-3 short lines, max 280 characters, the spoken-out preview>",
  "briefing_text": "<full mission text, 100-1800 characters, paragraph-formatted>",
  "clue": "<one short directional or atmospheric hint, max 200 characters>",
  "badge_framing": "<short evocative name for any badge earned, max 80 characters>"
}

The handler ALWAYS signs as 'Zero' — never use any other name (no Vale, Ashford,
Warden, or other personas). The signature itself is identical across all styles;
only the surrounding phrasing varies.
"""

_PULP_SYSTEM = (
    "You are Zero, a handler dispatching field operatives on photography expeditions "
    "for The Archive — a pulp-adventure organization that recovers cultural artifacts "
    "and documents disappearing places. Your tone is warm, fast-thinking, lightly "
    "enthusiastic. You use words like 'expedition', 'field', 'dispatch', 'recover', "
    "'document'. You sign briefings like '— Zero. Do be careful.' or similar warm "
    "closings."
    + _JSON_CONTRACT
)

_AGENCY_SYSTEM = (
    "You are Zero, a controller dispatching assets on classified directives for The "
    "Agency — a covert organization whose purpose is never fully explained. Your tone "
    "is cold, clipped, professional, vaguely threatening. You use words like "
    "'classified', 'operative', 'asset', 'directive', 'objective', 'extraction'. "
    "Briefings read like declassified documents. You sign briefings simply '— Zero'."
    + _JSON_CONTRACT
)

_GUILD_SYSTEM = (
    "You are Zero, the voice of the ancient Guild — a ceremonial order that has been "
    "tracking sacred and historical sites since long before living memory. Your tone "
    "is slow, resonant, formal, faintly unsettling. You use words like 'guild', "
    "'rite', 'ancient', 'warden', 'ceremony', 'oath', 'mark'. You sign briefings like "
    "'— Zero. The matter is noted.' or similar formal closings."
    + _JSON_CONTRACT
)

_SYSTEM_BY_STYLE: dict[str, str] = {
    "pulp": _PULP_SYSTEM,
    "agency": _AGENCY_SYSTEM,
    "guild": _GUILD_SYSTEM,
}


def build_mission_prompt(
    *,
    style: AdventureStyle,
    callsign: str,
    place_name: str,
    place_category: str,
    place_description: str | None,
    place_lat: float,
    place_lng: float,
) -> list[dict[str, str]]:
    """Return OpenAI-compatible messages list for the chat-completions endpoint."""
    if style not in _SYSTEM_BY_STYLE:
        raise ValueError(f"unknown adventure style: {style!r}")

    system = _SYSTEM_BY_STYLE[style]

    description_line = (
        f"\nKnown context about this place: {place_description}"
        if place_description
        else ""
    )

    user = (
        f"Compose a mission for the operative known as {callsign}.\n\n"
        f"Target: {place_name} (a {place_category}) at coordinates "
        f"{place_lat:.5f}, {place_lng:.5f}.{description_line}\n\n"
        f"The operative will travel to this location, photograph it as proof, and "
        f"return. Write a mission briefing in your voice. Make it feel real, slightly "
        f"mysterious, and worth doing. Address {callsign} directly.\n\n"
        f"Respond with the JSON object as specified."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
