import pytest

from dispatchzero.services.rank import MAX_RANK, completions_to_rank


@pytest.mark.parametrize(
    "completions,expected",
    [
        (-5, 0),  # negative clamps to 0
        (0, 0),
        (1, 0),
        (2, 1),
        (3, 1),
        (4, 2),
        (7, 2),
        (8, 3),
        (11, 3),
        (12, 4),
        (19, 4),
        (20, 5),
        (29, 5),
        (30, 6),
        (39, 6),
        (40, 7),
        (49, 7),
        (50, 8),
        (59, 8),
        (60, 9),
        (69, 9),
        (70, 10),
        (1000, 10),  # caps at MAX_RANK
    ],
)
def test_completions_to_rank(completions: int, expected: int) -> None:
    assert completions_to_rank(completions) == expected


def test_max_rank_constant():
    assert MAX_RANK == 10
