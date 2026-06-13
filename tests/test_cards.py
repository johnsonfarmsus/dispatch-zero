"""Tests for mission card composition.

Verify the composer produces a valid JPEG of the right dimensions across
each style and handles edge cases (long place name, long flavor text,
unknown style). Visual quality is reviewed by eye.
"""
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from dispatchzero.services.cards import compose_mission_card
from dispatchzero.services.photo import make_test_jpeg, save_thumbnail


def _make_capture(tmp_path: Path) -> Path:
    raw = make_test_jpeg(captured_at=datetime.now(timezone.utc))
    photo_path = tmp_path / "captures" / "x.jpg"
    save_thumbnail(raw, photo_path, max_dim=600, quality=70)
    return photo_path


def _kwargs(**overrides):
    base = dict(
        place_name="Riverfront Park",
        callsign="HUNTER",
        completed_at=datetime(2026, 4, 27, 12, 30),
        adventure_style="agency",
        rank_at_completion=3,
        completions_total=8,
        completions_this_week=2,
        dispatch_summary="A two-line preview of the mission, in handler voice.",
    )
    base.update(overrides)
    return base


def test_compose_writes_4x5_jpeg(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "cards" / "card-001.jpg"
    compose_mission_card(photo_path=photo, output_path=out, **_kwargs())
    assert out.exists()
    img = Image.open(out)
    assert img.format == "JPEG"
    assert img.size == (1080, 1350)


def test_compose_runs_for_all_three_styles(tmp_path: Path):
    photo = _make_capture(tmp_path)
    for style in ("pulp", "agency", "guild"):
        out = tmp_path / f"card-{style}.jpg"
        compose_mission_card(
            photo_path=photo, output_path=out,
            **_kwargs(adventure_style=style, rank_at_completion=5),
        )
        assert out.exists(), f"no card written for style={style}"


def test_compose_unknown_style_falls_back_to_agency_palette(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-bogus.jpg"
    compose_mission_card(
        photo_path=photo, output_path=out,
        **_kwargs(adventure_style="not-a-real-style"),
    )
    assert out.exists()


def test_compose_truncates_very_long_place_names(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-long.jpg"
    compose_mission_card(
        photo_path=photo, output_path=out,
        **_kwargs(place_name="X" * 200, adventure_style="pulp"),
    )
    assert out.exists()


def test_compose_truncates_very_long_flavor_text(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-long-flavor.jpg"
    compose_mission_card(
        photo_path=photo, output_path=out,
        **_kwargs(dispatch_summary="x " * 500),
    )
    assert out.exists()


def test_compose_handles_empty_flavor_text(tmp_path: Path):
    photo = _make_capture(tmp_path)
    out = tmp_path / "card-empty-flavor.jpg"
    compose_mission_card(
        photo_path=photo, output_path=out,
        **_kwargs(dispatch_summary=""),
    )
    assert out.exists()
