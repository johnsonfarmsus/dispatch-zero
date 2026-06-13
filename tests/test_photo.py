import io
from datetime import datetime, timedelta, timezone

import piexif
import pytest
from PIL import Image

from dispatchzero.services.photo import (
    haversine_distance_m,
    make_test_jpeg,
    read_exif_datetime,
    read_exif_has_gps,
    save_thumbnail,
)


def _jpeg_with_exif(dt: datetime | None, with_gps: bool = False) -> bytes:
    img = Image.new("RGB", (1200, 1200), color=(80, 90, 100))
    exif_dict: dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if dt is not None:
        ts = dt.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = ts.encode()
    if with_gps:
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = ((47, 1), (39, 1), (37, 1))
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N"
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()


def test_haversine_zero_distance_for_same_point():
    d = haversine_distance_m(47.6605, -117.4198, 47.6605, -117.4198)
    assert d < 0.5


def test_haversine_known_distance_one_degree_lat():
    d = haversine_distance_m(47.0, -117.0, 48.0, -117.0)
    assert 110_000 < d < 112_000


def test_haversine_short_distance_within_spokane():
    d = haversine_distance_m(47.6605, -117.4198, 47.6605, -117.4178)
    assert 140 < d < 160


def test_read_exif_datetime_returns_aware_datetime():
    target = datetime(2026, 4, 26, 14, 30, 15)
    raw = _jpeg_with_exif(target)
    parsed = read_exif_datetime(raw)
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 26
    assert parsed.hour == 14 and parsed.minute == 30 and parsed.second == 15


def test_read_exif_datetime_returns_none_when_missing():
    raw = _jpeg_with_exif(None)
    assert read_exif_datetime(raw) is None


def test_read_exif_datetime_returns_none_for_garbage_input():
    assert read_exif_datetime(b"not a jpeg") is None


def test_read_exif_has_gps_true_when_gps_present():
    raw = _jpeg_with_exif(datetime.now(timezone.utc), with_gps=True)
    assert read_exif_has_gps(raw) is True


def test_read_exif_has_gps_false_when_absent():
    raw = _jpeg_with_exif(datetime.now(timezone.utc), with_gps=False)
    assert read_exif_has_gps(raw) is False


def test_save_thumbnail_resizes_and_strips_exif(tmp_path):
    raw = _jpeg_with_exif(datetime.now(timezone.utc), with_gps=True)
    out = tmp_path / "out.jpg"
    save_thumbnail(raw, out, max_dim=600, quality=70)
    assert out.exists()
    written = out.read_bytes()
    img = Image.open(io.BytesIO(written))
    assert max(img.size) <= 600
    assert read_exif_datetime(written) is None
    assert read_exif_has_gps(written) is False


def test_save_thumbnail_creates_parent_dirs(tmp_path):
    raw = _jpeg_with_exif(datetime.now(timezone.utc))
    nested = tmp_path / "a" / "b" / "c" / "out.jpg"
    save_thumbnail(raw, nested, max_dim=600, quality=70)
    assert nested.exists()


def test_make_test_jpeg_round_trips_datetime():
    dt = datetime(2026, 4, 26, 12, 0, 0)
    raw = make_test_jpeg(captured_at=dt)
    assert read_exif_datetime(raw).hour == 12


# --- decode_image_guarded: upload abuse bounds -------------------------------

from dispatchzero.config import get_settings  # noqa: E402
from dispatchzero.services.photo import (  # noqa: E402
    PhotoTooLargeError,
    decode_image_guarded,
)


def test_decode_guarded_accepts_normal_image():
    raw = make_test_jpeg(size=(800, 600))
    img = decode_image_guarded(raw)
    assert img.size == (800, 600)


def test_decode_guarded_rejects_oversized_bytes(monkeypatch):
    monkeypatch.setenv("PHOTO_MAX_UPLOAD_BYTES", "1024")  # 1 KB
    get_settings.cache_clear()
    raw = make_test_jpeg(size=(1200, 1200))  # well over 1 KB encoded
    with pytest.raises(PhotoTooLargeError, match="too large"):
        decode_image_guarded(raw)


def test_decode_guarded_rejects_garbage_bytes():
    with pytest.raises(PhotoTooLargeError, match="could not read"):
        decode_image_guarded(b"this is not an image at all")


def test_decode_guarded_rejects_too_many_pixels(monkeypatch):
    # Lower the pixel cap below a 1200x1200 (1.44M px) image and confirm
    # the decompression-bomb guard fires.
    monkeypatch.setenv("PHOTO_MAX_PIXELS", "1000000")  # 1 MP
    get_settings.cache_clear()
    raw = make_test_jpeg(size=(1200, 1200))
    with pytest.raises(PhotoTooLargeError):
        decode_image_guarded(raw)


def test_save_thumbnail_rejects_garbage(tmp_path):
    with pytest.raises(PhotoTooLargeError):
        save_thumbnail(b"not an image", tmp_path / "x.jpg")
