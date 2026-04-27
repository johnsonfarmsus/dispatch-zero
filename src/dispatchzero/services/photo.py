import io
import math
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image, ImageOps


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in meters."""
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def read_exif_datetime(raw_bytes: bytes) -> datetime | None:
    """Return EXIF DateTimeOriginal as a naive datetime (UTC by convention), or None."""
    try:
        exif = piexif.load(raw_bytes)
    except Exception:
        return None
    raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if raw is None:
        return None
    try:
        s = raw.decode() if isinstance(raw, bytes) else str(raw)
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def read_exif_has_gps(raw_bytes: bytes) -> bool:
    """Whether the EXIF carries any GPS tag."""
    try:
        exif = piexif.load(raw_bytes)
    except Exception:
        return False
    return bool(exif.get("GPS", {}))


def save_thumbnail(
    raw_bytes: bytes,
    path: Path,
    *,
    max_dim: int = 600,
    quality: int = 70,
) -> None:
    """Decode, auto-orient, resize to fit (max_dim x max_dim), strip EXIF, save JPEG."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_dim, max_dim))
    if img.mode != "RGB":
        img = img.convert("RGB")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=quality, optimize=True, exif=b"")


def make_test_jpeg(
    *,
    captured_at: datetime | None = None,
    size: tuple[int, int] = (1200, 1200),
    color: tuple[int, int, int] = (80, 90, 100),
) -> bytes:
    """Helper used by downstream tests — synthesize a JPEG with controlled EXIF."""
    img = Image.new("RGB", size, color=color)
    exif_dict: dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if captured_at is not None:
        ts = captured_at.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = ts.encode()
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()
