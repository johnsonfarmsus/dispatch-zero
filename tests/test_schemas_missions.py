import uuid

import pytest
from pydantic import ValidationError

from dispatchzero.schemas.missions import MissionContent, MissionGenerateIn


def test_mission_content_accepts_valid():
    c = MissionContent(
        dispatch_summary="Two short lines.",
        briefing_text="A full paragraph of the briefing text.",
        clue="Look for the brass plaque.",
        badge_framing="First Documented Sculpture",
    )
    assert c.dispatch_summary == "Two short lines."


def test_mission_content_rejects_overlong_dispatch_summary():
    with pytest.raises(ValidationError):
        MissionContent(
            dispatch_summary="x" * 500,
            briefing_text="ok",
            clue=None,
            badge_framing=None,
        )


def test_mission_content_rejects_empty_briefing():
    with pytest.raises(ValidationError):
        MissionContent(
            dispatch_summary="ok",
            briefing_text="",
            clue=None,
            badge_framing=None,
        )


def test_mission_generate_in_requires_place_id():
    with pytest.raises(ValidationError):
        MissionGenerateIn()


def test_mission_generate_in_accepts_optional_style():
    g = MissionGenerateIn(place_id=uuid.uuid4(), adventure_style="agency")
    assert g.adventure_style == "agency"


def test_mission_generate_in_rejects_unknown_style():
    with pytest.raises(ValidationError):
        MissionGenerateIn(place_id=uuid.uuid4(), adventure_style="ranger")
