"""Mission card composition.

Renders a 4:5 JPEG sized for social-feed sharing and styled like a trading
card. Layout, top to bottom:

  ┌─────────────────────────────────────────────┐
  │ // DISPATCH ZERO //              42JULIET   │  header (callsign right)
  ├─────────────────────────┬───────────────────┤
  │   THE ARCHIVE           │                   │
  │   [HANDLER AVATAR]      │                   │
  │   Professor Zero        │     [PHOTO]       │  hero
  │   YOUR HANDLER          │                   │
  │   ─                     │                   │
  │   42JULIET              │                   │
  │   VOLUNTEER             │                   │
  │   This week     1       │                   │
  │   Completions   1       │                   │
  ├─────────────────────────┴───────────────────┤
  │ Place name                                  │  title
  │ 2026-05-03                                  │
  ├─────────────────────────────────────────────┤
  │ Mission flavor text from dispatch summary   │  flavor
  │                                  — Handler  │
  └─────────────────────────────────────────────┘

Each completion's card preserves the organization that completed it via
mission.adventure_style — switching organizations later doesn't re-theme
old cards. The user stats (rank, completions, this-week count) are a
snapshot at the moment of THAT completion, not the user's current state.
"""
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from dispatchzero.services.rank import HANDLER_NAMES, ORG_NAMES, rank_name

# 4:5 portrait. Friendly to social feeds (1080×1350 is Instagram portrait).
_WIDTH = 1080
_HEIGHT = 1350

_OUTER_MARGIN = 30
_INNER_PAD = 20

# Section heights — sum = _HEIGHT - 2*_OUTER_MARGIN = 1290
_HEADER_H = 90
_HERO_H = 720
_TITLE_H = 130
_FLAVOR_H = 1290 - _HEADER_H - _HERO_H - _TITLE_H  # 350

# Hero panel inner geometry
_PHOTO_SIZE = 720
_HANDLER_COL_W = _WIDTH - 2 * _OUTER_MARGIN - _PHOTO_SIZE - _INNER_PAD  # 270

# Palette — matches frontend tokens.css.
_BG = (14, 12, 10)
_TEXT = (232, 225, 216)
_TEXT_MUTED = (133, 125, 114)
_TEXT_FAINT = (90, 82, 73)

# Per-style accent.
_ACCENT = {
    "pulp": (214, 138, 60),    # amber
    "agency": (78, 197, 214),  # cyan
    "guild": (164, 114, 214),  # purple
}

_SIGN_OFF = {
    "pulp": "— Professor Zero",
    "agency": "— Director Zero",
    "guild": "— Guildmaster Zero",
}

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONT_REGULAR = _FONT_DIR / "DejaVuSansMono.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSansMono-Bold.ttf"

_AVATAR_DIR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "avatars"


def _font(path: Path, size: int) -> ImageFont.ImageFont:
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _square_crop(img: Image.Image, size: int) -> Image.Image:
    if img.mode != "RGB":
        img = img.convert("RGB")
    short_side = min(img.size)
    left = (img.size[0] - short_side) // 2
    top = (img.size[1] - short_side) // 2
    img = img.crop((left, top, left + short_side, top + short_side))
    return img.resize((size, size), Image.LANCZOS)


def _avatar_for_style(style: str) -> Image.Image | None:
    path = _AVATAR_DIR / f"zero-{style}.png"
    if not path.exists():
        path = _AVATAR_DIR / "zero-agency.png"
    if not path.exists():
        return None
    return Image.open(path).convert("RGBA")


def _draw_avatar(canvas: Image.Image, avatar: Image.Image, x: int, y: int, size: int) -> None:
    a = avatar.copy()
    if a.mode != "RGBA":
        a = a.convert("RGBA")
    short_side = min(a.size)
    left = (a.size[0] - short_side) // 2
    top = (a.size[1] - short_side) // 2
    a = a.crop((left, top, left + short_side, top + short_side))
    a = a.resize((size, size), Image.LANCZOS)
    canvas.paste(a, (x, y), a)


def _wrap_to_lines(text: str, width_chars: int, max_lines: int) -> list[str]:
    wrapped = textwrap.wrap(text, width=width_chars, break_long_words=False)
    if len(wrapped) > max_lines:
        wrapped = wrapped[:max_lines]
        last = wrapped[-1]
        if len(last) + 1 <= width_chars:
            wrapped[-1] = last + "…"
        else:
            wrapped[-1] = last[: width_chars - 1] + "…"
    return wrapped


def _draw_centered(draw: ImageDraw.ImageDraw, x: int, w: int, y: int, text: str,
                    font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y), text, font=font, fill=fill)


def compose_mission_card(
    *,
    photo_path: Path,
    place_name: str,
    callsign: str,
    completed_at: datetime,
    adventure_style: str,
    rank_at_completion: int,
    completions_total: int,
    completions_this_week: int,
    dispatch_summary: str,
    output_path: Path,
) -> None:
    """Compose the trading-card-style mission JPEG and save it to output_path."""
    accent = _ACCENT.get(adventure_style, _ACCENT["agency"])
    sign_off = _SIGN_OFF.get(adventure_style, _SIGN_OFF["agency"])
    org_name = ORG_NAMES.get(adventure_style, ORG_NAMES["agency"])
    handler_name = HANDLER_NAMES.get(adventure_style, HANDLER_NAMES["agency"])
    rank_label = rank_name(adventure_style, rank_at_completion)
    callsign_upper = callsign.upper()

    canvas = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(canvas)

    draw.rectangle(
        [(15, 15), (_WIDTH - 15, _HEIGHT - 15)],
        outline=accent, width=2,
    )

    inner_left = _OUTER_MARGIN
    inner_right = _WIDTH - _OUTER_MARGIN

    # ----- Header band: wordmark left, callsign right -----
    header_top = _OUTER_MARGIN
    header_bottom = header_top + _HEADER_H
    header_font = _font(_FONT_BOLD, 28)

    draw.text(
        (inner_left + _INNER_PAD, header_top + 30),
        "// DISPATCH ZERO //",
        font=header_font, fill=_TEXT_MUTED,
    )
    bbox = draw.textbbox((0, 0), callsign_upper, font=header_font)
    cs_w = bbox[2] - bbox[0]
    draw.text(
        (inner_right - _INNER_PAD - cs_w, header_top + 30),
        callsign_upper,
        font=header_font, fill=accent,
    )
    draw.line(
        [(inner_left, header_bottom), (inner_right, header_bottom)],
        fill=accent, width=1,
    )

    # ----- Hero band: handler/stats column (left) + photo (right) -----
    hero_top = header_bottom
    hero_bottom = hero_top + _HERO_H
    handler_col_x = inner_left
    photo_x = handler_col_x + _HANDLER_COL_W + _INNER_PAD

    # --- Left column: top-to-bottom layout ---
    org_font = _font(_FONT_BOLD, 22)
    handler_name_font = _font(_FONT_BOLD, 22)
    role_font = _font(_FONT_REGULAR, 16)
    callsign_font = _font(_FONT_BOLD, 24)
    rank_font = _font(_FONT_REGULAR, 18)
    stats_label_font = _font(_FONT_REGULAR, 16)
    stats_value_font = _font(_FONT_BOLD, 18)

    cursor_y = hero_top + 18
    avatar_size = 160

    # ORG NAME above avatar
    _draw_centered(draw, handler_col_x, _HANDLER_COL_W, cursor_y,
                   org_name.upper(), org_font, accent)
    cursor_y += 32

    # AVATAR
    avatar = _avatar_for_style(adventure_style)
    if avatar is not None:
        avatar_x = handler_col_x + (_HANDLER_COL_W - avatar_size) // 2
        _draw_avatar(canvas, avatar, avatar_x, cursor_y, avatar_size)
    cursor_y += avatar_size + 14

    # HANDLER NAME
    _draw_centered(draw, handler_col_x, _HANDLER_COL_W, cursor_y,
                   handler_name, handler_name_font, _TEXT)
    cursor_y += 28

    # YOUR HANDLER label
    _draw_centered(draw, handler_col_x, _HANDLER_COL_W, cursor_y,
                   "YOUR HANDLER", role_font, _TEXT_MUTED)
    cursor_y += 30

    # Divider between handler block and agent stats
    div_pad = 18
    draw.line(
        [(handler_col_x + div_pad, cursor_y),
         (handler_col_x + _HANDLER_COL_W - div_pad, cursor_y)],
        fill=_TEXT_FAINT, width=1,
    )
    cursor_y += 16

    # CALLSIGN (the agent's name)
    _draw_centered(draw, handler_col_x, _HANDLER_COL_W, cursor_y,
                   callsign_upper, callsign_font, _TEXT)
    cursor_y += 30

    # RANK
    _draw_centered(draw, handler_col_x, _HANDLER_COL_W, cursor_y,
                   rank_label.upper(), rank_font, accent)
    cursor_y += 28

    # STATS rows: label left, value right (within the column)
    stat_pad = 22
    row_left = handler_col_x + stat_pad
    row_right = handler_col_x + _HANDLER_COL_W - stat_pad

    def stat_row(label: str, value: str, y: int) -> None:
        draw.text((row_left, y), label, font=stats_label_font, fill=_TEXT_MUTED)
        bbox = draw.textbbox((0, 0), value, font=stats_value_font)
        vw = bbox[2] - bbox[0]
        draw.text((row_right - vw, y), value, font=stats_value_font, fill=_TEXT)

    stat_row("This week", str(completions_this_week), cursor_y)
    cursor_y += 26
    stat_row("Completions", str(completions_total), cursor_y)

    # --- Right side: photo ---
    photo_y = hero_top + (_HERO_H - _PHOTO_SIZE) // 2
    photo = Image.open(photo_path)
    photo = _square_crop(photo, _PHOTO_SIZE)
    canvas.paste(photo, (photo_x, photo_y))

    draw.line(
        [(inner_left, hero_bottom), (inner_right, hero_bottom)],
        fill=accent, width=1,
    )

    # ----- Title band: place name + date only -----
    title_top = hero_bottom
    place_font = _font(_FONT_BOLD, 40)
    date_font = _font(_FONT_REGULAR, 22)

    draw.text(
        (inner_left + _INNER_PAD, title_top + 18),
        _truncate(place_name, 30),
        font=place_font, fill=_TEXT,
    )
    date_str = completed_at.strftime("%Y-%m-%d")
    draw.text(
        (inner_left + _INNER_PAD, title_top + 70),
        date_str,
        font=date_font, fill=_TEXT_MUTED,
    )

    title_bottom = title_top + _TITLE_H
    draw.line(
        [(inner_left, title_bottom), (inner_right, title_bottom)],
        fill=accent, width=1,
    )

    # ----- Flavor band: dispatch summary + sign-off -----
    flavor_top = title_bottom
    flavor_text = (dispatch_summary or "").strip()
    flavor_font = _font(_FONT_REGULAR, 22)
    sign_font = _font(_FONT_REGULAR, 20)

    lines = _wrap_to_lines(flavor_text, width_chars=42, max_lines=8)
    line_y = flavor_top + 28
    for line in lines:
        draw.text(
            (inner_left + _INNER_PAD, line_y),
            line,
            font=flavor_font, fill=_TEXT,
        )
        line_y += 32

    bbox = draw.textbbox((0, 0), sign_off, font=sign_font)
    sign_w = bbox[2] - bbox[0]
    sign_y = _HEIGHT - _OUTER_MARGIN - 50
    draw.text(
        (inner_right - _INNER_PAD - sign_w, sign_y),
        sign_off,
        font=sign_font, fill=accent,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=85, optimize=True)
