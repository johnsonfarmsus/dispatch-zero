"""Rank derivation from completion count, plus style-themed display names.

Ranks are integers 0-10. The frontend has its own copy of the names (in
style-meta.js) for live UI; the backend copy here is used by the mission
card composer, which renders the rank name into the JPEG.

Thresholds grow non-linearly: early ranks come fast, later ones reward
sustained play. Easy to extend later by appending entries.
"""
from bisect import bisect_right

# Index = rank number, value = minimum completions to reach it.
_THRESHOLDS: tuple[int, ...] = (0, 2, 4, 8, 12, 20, 30, 40, 50, 60, 70)

MAX_RANK = len(_THRESHOLDS) - 1


def completions_to_rank(completions: int) -> int:
    """Return the highest rank whose threshold ≤ completions, clamped to [0, MAX_RANK]."""
    return max(0, bisect_right(_THRESHOLDS, completions) - 1)


# Rank names per adventure style. Index = rank integer (0..10). Mirror of
# RANKS in frontend/static/js/style-meta.js — keep them aligned when
# either changes.
_RANK_NAMES: dict[str, tuple[str, ...]] = {
    "pulp": (
        "Volunteer", "Junior Cataloguer", "Cataloguer", "Senior Cataloguer",
        "Junior Curator", "Curator", "Senior Curator",
        "Junior Expeditioner", "Expeditioner", "Senior Expeditioner",
        "Antiquarian",
    ),
    "agency": (
        "Intern", "Junior Analyst", "Analyst", "Field Analyst",
        "Junior Operative", "Operative", "Field Operative",
        "Junior Specialist", "Specialist", "Field Specialist",
        "Officer",
    ),
    "guild": (
        "Aspirant", "Initiate", "Sworn", "Acolyte",
        "Junior Warden", "Warden", "Senior Warden",
        "Junior Keeper", "Keeper", "Senior Keeper",
        "Magister",
    ),
}


def rank_name(style: str, rank: int) -> str:
    """Style-themed rank name for display. Falls back to agency on unknown style."""
    names = _RANK_NAMES.get(style, _RANK_NAMES["agency"])
    i = max(0, min(rank, len(names) - 1))
    return names[i]


# Org display names + handler names per style — used by the card composer
# to render the header bar and the handler portrait label.
ORG_NAMES: dict[str, str] = {
    "pulp": "The Archive",
    "agency": "The Agency",
    "guild": "The Guild",
}

HANDLER_NAMES: dict[str, str] = {
    "pulp": "Professor Zero",
    "agency": "Director Zero",
    "guild": "Guildmaster Zero",
}
