import pytest

from dispatchzero.services.mission_prompts import build_mission_prompt


def _ctx():
    return dict(
        callsign="Trevor_01",
        place_name="Garbage Goat",
        place_category="sculpture",
        place_description=None,
    )


def test_pulp_prompt_mentions_pulp_style_cues_and_callsign():
    msgs = build_mission_prompt(style="pulp", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert "Garbage Goat" in text
    assert any(w in text.lower() for w in ("expedition", "field", "dispatch"))
    # Persona names appear only as negations in the JSON contract — not as character names
    assert text.count("Vale") <= 1
    assert text.count("Ashford") <= 1
    assert text.count("Warden") <= 1


def test_agency_prompt_uses_clinical_register():
    msgs = build_mission_prompt(style="agency", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert any(w in text.lower() for w in ("classified", "operative", "asset", "directive"))


def test_guild_prompt_uses_ceremonial_register():
    msgs = build_mission_prompt(style="guild", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert any(w in text.lower() for w in ("guild", "ancient", "rite", "ceremony"))


def test_prompt_demands_json_response_format():
    msgs = build_mission_prompt(style="pulp", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "dispatch_summary" in text
    assert "briefing_text" in text
    assert "clue" in text
    assert "badge_framing" in text


def test_prompt_includes_description_when_present():
    msgs = build_mission_prompt(
        style="agency",
        callsign="X",
        place_name="Some Mural",
        place_category="mural",
        place_description="A 1974 fresco depicting the Spokane River.",
    )
    text = "\n".join(m["content"] for m in msgs)
    assert "1974 fresco" in text


def test_prompt_does_not_include_raw_coordinates():
    # Phase 4 leaked "0.00000, 0.00000" into briefings; verify that's gone
    msgs = build_mission_prompt(style="pulp", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "0.00000" not in text
    assert "coordinates" not in text.lower() or "do not invent" in text.lower()


def test_unknown_style_raises():
    with pytest.raises(ValueError):
        build_mission_prompt(
            style="ranger",
            callsign="X",
            place_name="X",
            place_category="mural",
            place_description=None,
        )
