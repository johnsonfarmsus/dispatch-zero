from dataclasses import dataclass
from datetime import datetime, timezone

from dispatchzero.services.photo import (
    haversine_distance_m,
    read_exif_datetime,
    read_exif_has_gps,
)


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    fail_reason: str | None  # 'out_of_radius' | 'no_exif' | 'stale_capture' | None
    distance_m: float
    exif_delta_seconds: int | None
    had_exif: bool
    had_exif_gps: bool


def verify_capture(
    *,
    raw_bytes: bytes,
    capture_lat: float,
    capture_lng: float,
    target_lat: float,
    target_lng: float,
    radius_m: float = 80,
    freshness_window_seconds: int = 600,
    now: datetime | None = None,
) -> VerificationResult:
    """Apply GPS-radius (hard) + EXIF-freshness (soft) gates.

    Per the photo-capture spec: GPS is the verification primitive; EXIF
    DateTimeOriginal is a soft anti-cheat heuristic. iOS Safari often strips
    EXIF when photos go through `<input type=file capture=environment>`, so
    we cannot require it. Behavior:

    - distance > radius_m → fail (out_of_radius)
    - EXIF DateTimeOriginal present AND outside freshness window → fail
      (stale_capture; obvious replay of an old photo)
    - EXIF missing entirely OR present-and-fresh → pass
    """
    distance_m = haversine_distance_m(capture_lat, capture_lng, target_lat, target_lng)
    exif_dt = read_exif_datetime(raw_bytes)
    had_exif_gps = read_exif_has_gps(raw_bytes)
    had_exif = exif_dt is not None or had_exif_gps

    if distance_m > radius_m:
        return VerificationResult(
            verified=False, fail_reason="out_of_radius",
            distance_m=distance_m, exif_delta_seconds=None,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )

    if exif_dt is None:
        return VerificationResult(
            verified=True, fail_reason=None,
            distance_m=distance_m, exif_delta_seconds=None,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )

    now_naive = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    delta = int((now_naive - exif_dt).total_seconds())
    if delta < 0 or delta > freshness_window_seconds:
        return VerificationResult(
            verified=False, fail_reason="stale_capture",
            distance_m=distance_m, exif_delta_seconds=delta,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )

    return VerificationResult(
        verified=True, fail_reason=None,
        distance_m=distance_m, exif_delta_seconds=delta,
        had_exif=had_exif, had_exif_gps=had_exif_gps,
    )
