"""Rank derivation from completion count.

Ranks are integers 0-10. Names are picked on the frontend using the user's
adventure style — backend stays style-agnostic so name changes never need a
backend deploy.

Thresholds grow non-linearly: early ranks come fast, later ones reward
sustained play. Easy to extend later by appending entries here.
"""
from bisect import bisect_right

# Index = rank number, value = minimum completions to reach it.
_THRESHOLDS: tuple[int, ...] = (0, 2, 4, 8, 12, 20, 30, 40, 50, 60, 70)

MAX_RANK = len(_THRESHOLDS) - 1


def completions_to_rank(completions: int) -> int:
    """Return the highest rank whose threshold ≤ completions, clamped to [0, MAX_RANK]."""
    return max(0, bisect_right(_THRESHOLDS, completions) - 1)
