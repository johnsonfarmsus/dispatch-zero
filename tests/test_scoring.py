import pytest

from dispatchzero.models import PlaceCategory
from dispatchzero.services.scoring import ScoreInput, score_place


@pytest.mark.parametrize(
    "input_,expected_min,expected_max",
    [
        # Bare-bones place — no name, no description, no rating history
        (
            ScoreInput(
                name=None, description=None, has_wikidata=False,
                category=PlaceCategory.VIEWPOINT, thumbs_up=0, thumbs_down=0,
            ),
            0.0, 0.5,
        ),
        # Named, described, wikidata-linked, no ratings yet — should be high
        (
            ScoreInput(
                name="Example", description="A famous landmark.", has_wikidata=True,
                category=PlaceCategory.MURAL, thumbs_up=0, thumbs_down=0,
            ),
            2.0, 4.0,
        ),
        # Highly upvoted mural — top tier
        (
            ScoreInput(
                name="Beloved", description="Big mural.", has_wikidata=True,
                category=PlaceCategory.MURAL, thumbs_up=20, thumbs_down=0,
            ),
            4.0, 10.0,
        ),
        # Mostly-downvoted place — penalty
        (
            ScoreInput(
                name="Bad", description="Hard to find.", has_wikidata=False,
                category=PlaceCategory.HISTORIC, thumbs_up=1, thumbs_down=10,
            ),
            0.0, 1.5,
        ),
    ],
)
def test_score_within_expected_range(input_, expected_min, expected_max):
    s = score_place(input_)
    assert expected_min <= s <= expected_max, f"got {s}"


def test_category_priority_mural_beats_viewpoint_all_else_equal():
    base = dict(name="X", description="Y", has_wikidata=False, thumbs_up=0, thumbs_down=0)
    mural = score_place(ScoreInput(**base, category=PlaceCategory.MURAL))
    viewpoint = score_place(ScoreInput(**base, category=PlaceCategory.VIEWPOINT))
    assert mural > viewpoint


def test_named_beats_unnamed():
    base = dict(
        description=None, has_wikidata=False,
        category=PlaceCategory.SCULPTURE, thumbs_up=0, thumbs_down=0,
    )
    named = score_place(ScoreInput(name="Has a Name", **base))
    unnamed = score_place(ScoreInput(name=None, **base))
    assert named > unnamed
