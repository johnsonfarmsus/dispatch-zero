"""Mission card composition.

Renders a 4:5 JPEG suitable for sharing or saving from the Debrief screen.
Composed from the user's saved capture thumbnail plus a dossier-styled
frame: wordmark + style tag at the top, square photo in the middle, place
name + callsign + date + in-character sign-off at the bottom, all with a
thin style-color accent border.

Stored once at /uploads/cards/{completion_id}.jpg at capture time, served
thereafter by GET /completions/{id}/card.jpg. Regenerating is just rerunning
this function — no DB state to update.
"""
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 4:5 portrait. Friendly to social feeds (1080×1350 is Instagram portrait).
_WIDTH = 1080
_HEIGHT = 1350

_OUTER_MARGIN = 30
_HEADER_HEIGHT = 90
_PHOTO_SIZE = 1020  # square; centered in the 1080-wide canvas with side margins

# Palette — matches the frontend tokens.css so the card looks like the app.
_BG = (14, 12, 10)
_TEXT = (232, 225, 216)
_TEXT_MUTED = (133, 125, 114)

# Per-style accent — matches the frontend style accents.
_ACCENT = {
    "pulp": (214, 138, 60),    # amber
    "agency": (78, 197, 214),  # cyan
    "guild": (164, 114, 214),  # purple
}

# Per-style sign-off — matches the in-character voices used in mission_prompts.
_SIGN_OFF = {
    "pulp": "— Professor Zero",
    "agency": "— Director Zero. End of dispatch.",
    "guild": "— Guildmaster Zero. The matter is noted.",
}

# DejaVu Sans Mono is installed via apt (fonts-dejavu-core) in the prod image.
# Fall back to PIL's bitmap default if missing — keeps tests runnable on any host.
_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONT_REGULAR = _FONT_DIR / "DejaVuSansMono.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSansMono-Bold.ttf"


def _font(path: Path, size: int) -> ImageFont.ImageFont:
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def compose_mission_card(
    *,
    photo_path: Path,
    place_name: str,
    callsign: str,
    completed_at: datetime,
    adventure_style: str,
    output_path: Path,
) -> None:
    """Compose the 4:5 mission card JPEG and save it to output_path."""
    accent = _ACCENT.get(adventure_style, _ACCENT["agency"])
    sign_off = _SIGN_OFF.get(adventure_style, _SIGN_OFF["agency"])

    canvas = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(canvas)

    # Outer accent border.
    draw.rectangle(
        [(15, 15), (_WIDTH - 15, _HEIGHT - 15)],
        outline=accent, width=2,
    )

    # ----- Header strip -----
    header_y = _OUTER_MARGIN
    header_font = _font(_FONT_REGULAR, 30)
    draw.text(
        (_OUTER_MARGIN + 20, header_y + 20),
        "// dispatch zero //",
        font=header_font, fill=_TEXT_MUTED,
    )
    style_tag = f"[ {adventure_style.upper()} ]"
    bbox = draw.textbbox((0, 0), style_tag, font=header_font)
    style_w = bbox[2] - bbox[0]
    draw.text(
        (_WIDTH - _OUTER_MARGIN - 20 - style_w, header_y + 20),
        style_tag,
        font=header_font, fill=accent,
    )

    # ----- Photo (square crop, centered) -----
    photo_top = _OUTER_MARGIN + _HEADER_HEIGHT
    photo_x = (_WIDTH - _PHOTO_SIZE) // 2
    photo = Image.open(photo_path)
    if photo.mode != "RGB":
        photo = photo.convert("RGB")
    short_side = min(photo.size)
    left = (photo.size[0] - short_side) // 2
    top = (photo.size[1] - short_side) // 2
    photo = photo.crop((left, top, left + short_side, top + short_side))
    photo = photo.resize((_PHOTO_SIZE, _PHOTO_SIZE), Image.LANCZOS)
    canvas.paste(photo, (photo_x, photo_top))

    # ----- Footer strip -----
    footer_top = photo_top + _PHOTO_SIZE + 30
    title_font = _font(_FONT_BOLD, 38)
    meta_font = _font(_FONT_REGULAR, 24)
    sign_off_font = _font(_FONT_REGULAR, 22)

    draw.text(
        (_OUTER_MARGIN + 20, footer_top),
        _truncate(place_name, 38),
        font=title_font, fill=_TEXT,
    )

    date_str = completed_at.strftime("%Y-%m-%d")
    meta = f"{callsign.upper()}  ·  {date_str}"
    draw.text(
        (_OUTER_MARGIN + 20, footer_top + 50),
        meta,
        font=meta_font, fill=_TEXT_MUTED,
    )

    bbox = draw.textbbox((0, 0), sign_off, font=sign_off_font)
    sign_w = bbox[2] - bbox[0]
    draw.text(
        (_WIDTH - _OUTER_MARGIN - 20 - sign_w, footer_top + 95),
        sign_off,
        font=sign_off_font, fill=accent,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=85, optimize=True)
