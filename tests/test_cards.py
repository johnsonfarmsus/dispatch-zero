"""Tests for mission card composition.

These verify the composer produces a valid JPEG of the right dimensions and
swallows obvious failures gracefully. Visual quality is reviewed by eye, not
by tests.
"""
from datetime import datetime
from pathlib import Path

from PIL import Image

from dispatchzero.services.cards import compose_mission_card
from dispatchzero.services.photo import make_test_jpeg, save_thumbnail


def _make_capture(tmp_path: Path) -> Path:
    """Save a synthetic 600px JPEG to disk like capture_mission would."""
    raw = make_test_jpeg(captured_at=datetime.utcnow())
    photo_path = tmp_path / "captures" / "x.jpg"
    save_thumbnail(raw, photo_path, max_dim=600, quality=70)
    return photo_path


def test_compose_writes_4x5_jpeg(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "cards" / "card-001.jpg"
    compose_mission_card(
        photo_path=photo,
        place_name="Riverfront Park",
        callsign="HUNTER",
        completed_at=datetime(2026, 4, 27, 12, 30),
        adventure_style="agency",
        output_path=out,
    )
    assert out.exists()
    img = Image.open(out)
    assert img.format == "JPEG"
    assert img.size == (1080, 1350)


def test_compose_runs_for_all_three_styles(tmp_path: Path):
    photo = _make_capture(tmp_path)
    for style in ("pulp", "agency", "guild"):
        out = tmp_path / f"card-{style}.jpg"
        compose_mission_card(
            photo_path=photo,
            place_name="Garbage Goat",
            callsign="OPERATIVE_42",
            completed_at=datetime.utcnow(),
            adventure_style=style,
            output_path=out,
        )
        assert out.exists(), f"no card written for style={style}"


def test_compose_unknown_style_falls_back_to_agency_palette(tmp_path: Path):
    """An unrecognized style shouldn't crash; we use the agency defaults."""
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-bogus.jpg"
    compose_mission_card(
        photo_path=photo,
        place_name="X",
        callsign="X",
        completed_at=datetime.utcnow(),
        adventure_style="not-a-real-style",
        output_path=out,
    )
    assert out.exists()


def test_compose_truncates_very_long_place_names(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-long.jpg"
    compose_mission_card(
        photo_path=photo,
        place_name="X" * 200,  # absurdly long; must not break the layout
        callsign="HUNTER",
        completed_at=datetime.utcnow(),
        adventure_style="pulp",
        output_path=out,
    )
    assert out.exists()
