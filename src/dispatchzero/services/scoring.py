from dataclasses import dataclass

from dispatchzero.models import PlaceCategory

# Category priority bonus — matches the priority ordering in the spec.
_CATEGORY_BONUS: dict[PlaceCategory, float] = {
    PlaceCategory.MURAL: 1.5,
    PlaceCategory.SCULPTURE: 1.2,
    PlaceCategory.MEMORIAL: 1.0,
    PlaceCategory.HISTORIC: 0.8,
    PlaceCategory.VIEWPOINT: 0.4,
}


@dataclass(frozen=True)
class ScoreInput:
    name: str | None
    description: str | None
    has_wikidata: bool
    category: PlaceCategory
    thumbs_up: int
    thumbs_down: int


def score_place(p: ScoreInput) -> float:
    """Deterministic quest-worthiness score. Higher = better candidate."""
    score = 0.0

    if p.name:
        score += 1.0
    if p.description:
        score += 1.0
    if p.has_wikidata:
        score += 0.5

    score += _CATEGORY_BONUS.get(p.category, 0.0)

    total = p.thumbs_up + p.thumbs_down
    if total >= 1:
        ratio = p.thumbs_up / total
        # Centered around 0.5 → no effect when neutral, ±2.0 at extremes
        rating_effect = (ratio - 0.5) * 4.0
        # Confidence weight — single ratings count less than 10
        confidence = min(total, 10) / 10
        score += rating_effect * confidence

    return max(0.0, score)
