"""Computed-from-history badge system.

Two families (the ones chosen for v1):

- Category collection: a themed badge per place category (earned at a small
  threshold of completions in that category) plus "Cartographer" for
  documenting at least one of all nine categories.
- Cadence: rewards for activity within a week and across consecutive active
  weeks — gentle momentum, no punishing daily-streak cliff (matches the
  project's anti-coercion stance).

Badges are DERIVED from the user's verified completion history, not stored.
This keeps v1 simple (no migration, no award-write path) and always
accurate. The trade-off: there's no "you just earned X!" moment at debrief
and no earned-at timestamp. If we want those later, add an awarded-badges
table that records the first time compute_badges() reports each as earned;
the compute logic here stays the source of truth.

Each badge reports earned state plus progress (current/target) so the
dossier can render a fillable collection with progress on the locked ones.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import Completion, Place

# Completions of a category needed to earn that category's badge.
_CATEGORY_THRESHOLD = 3

# Themed name per category. Keys are PlaceCategory values.
_CATEGORY_BADGES: dict[str, str] = {
    "mural": "Muralist",
    "sculpture": "Sculptor's Eye",
    "memorial": "Monument Keeper",
    "historic": "Antiquarian",
    "viewpoint": "Vista Seeker",
    "church": "Steeple Chaser",
    "park": "Trailblazer",
    "infrastructure": "Structural Surveyor",
    "civic": "Civic Chronicler",
}

_CATEGORY_LABEL: dict[str, str] = {
    "mural": "murals",
    "sculpture": "sculptures",
    "memorial": "memorials",
    "historic": "historic sites",
    "viewpoint": "viewpoints",
    "church": "churches",
    "park": "parks",
    "infrastructure": "infrastructure",
    "civic": "civic landmarks",
}


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    family: str       # "category" | "cadence"
    description: str
    earned: bool
    current: int      # progress numerator
    target: int       # progress denominator


def _iso_week_key(dt) -> tuple[int, int]:
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def _longest_consecutive_weeks(week_keys: set[tuple[int, int]]) -> int:
    """Longest run of consecutive ISO weeks present in the set. Handles
    year boundaries by converting each (year, week) to an absolute week
    ordinal (year*53 + week is monotonic enough for adjacency since ISO
    weeks are 1..53)."""
    if not week_keys:
        return 0
    ordinals = sorted({y * 53 + w for (y, w) in week_keys})
    best = run = 1
    for prev, cur in zip(ordinals, ordinals[1:]):
        run = run + 1 if cur == prev + 1 else 1
        best = max(best, run)
    return best


async def compute_badges(db: AsyncSession, *, user_id) -> list[Badge]:
    """Compute the full badge set (earned + locked-with-progress) for a user
    from their verified completion history."""
    # Category counts: completions joined to their place's category.
    cat_rows = (
        await db.execute(
            select(Place.category, func.count(Completion.id))
            .join(Place, Place.id == Completion.place_id)
            .where(Completion.user_id == user_id, Completion.verified.is_(True))
            .group_by(Place.category)
        )
    ).all()
    category_counts: dict[str, int] = {cat: int(n) for cat, n in cat_rows}

    # Completion timestamps for cadence.
    ts_rows = (
        await db.execute(
            select(Completion.completed_at)
            .where(Completion.user_id == user_id, Completion.verified.is_(True))
        )
    ).scalars().all()
    weekly: dict[tuple[int, int], int] = {}
    for ts in ts_rows:
        k = _iso_week_key(ts)
        weekly[k] = weekly.get(k, 0) + 1
    max_in_week = max(weekly.values(), default=0)
    consecutive = _longest_consecutive_weeks(set(weekly.keys()))

    badges: list[Badge] = []

    # ---- Category-collection badges ----
    categories_documented = 0
    for cat, badge_name in _CATEGORY_BADGES.items():
        count = category_counts.get(cat, 0)
        if count > 0:
            categories_documented += 1
        badges.append(Badge(
            key=f"cat:{cat}",
            name=badge_name,
            family="category",
            description=f"Document {_CATEGORY_THRESHOLD} {_CATEGORY_LABEL[cat]}.",
            earned=count >= _CATEGORY_THRESHOLD,
            current=min(count, _CATEGORY_THRESHOLD),
            target=_CATEGORY_THRESHOLD,
        ))

    # "Cartographer" — one of each of the nine categories.
    total_cats = len(_CATEGORY_BADGES)
    badges.append(Badge(
        key="cat:cartographer",
        name="Cartographer",
        family="category",
        description="Document at least one of every category.",
        earned=categories_documented >= total_cats,
        current=categories_documented,
        target=total_cats,
    ))

    # ---- Cadence badges ----
    badges.append(Badge(
        key="cadence:active",
        name="Field Active",
        family="cadence",
        description="Complete 3 dispatches in a single week.",
        earned=max_in_week >= 3,
        current=min(max_in_week, 3),
        target=3,
    ))
    badges.append(Badge(
        key="cadence:relentless",
        name="Relentless",
        family="cadence",
        description="Complete 5 dispatches in a single week.",
        earned=max_in_week >= 5,
        current=min(max_in_week, 5),
        target=5,
    ))
    badges.append(Badge(
        key="cadence:steadfast",
        name="Steadfast",
        family="cadence",
        description="Stay active 2 weeks running.",
        earned=consecutive >= 2,
        current=min(consecutive, 2),
        target=2,
    ))
    badges.append(Badge(
        key="cadence:devoted",
        name="Devoted",
        family="cadence",
        description="Stay active 4 weeks running.",
        earned=consecutive >= 4,
        current=min(consecutive, 4),
        target=4,
    ))

    return badges
