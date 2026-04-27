from datetime import datetime, timedelta

from dispatchzero.services.photo import make_test_jpeg
from dispatchzero.services.verification import verify_capture


def _now_utc() -> datetime:
    return datetime.utcnow()


def test_verify_passes_for_in_radius_fresh_photo():
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4198,
        target_lat=47.6605, target_lng=-117.4198,
        radius_m=80, freshness_window_seconds=600,
    )
    assert result.verified is True
    assert result.fail_reason is None
    assert result.distance_m < 1.0


def test_verify_passes_at_edge_of_radius():
    # ~70m east of target, well within 80m
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.41887,
        target_lat=47.6605, target_lng=-117.4198,
        radius_m=80, freshness_window_seconds=600,
    )
    assert result.verified is True
    assert 60 < result.distance_m < 80


def test_verify_fails_outside_80m_radius():
    # ~150m east of target, well outside 80m
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4178,
        target_lat=47.6605, target_lng=-117.4198,
        radius_m=80, freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "out_of_radius"
    assert result.distance_m > 100


def test_verify_fails_for_stale_exif():
    old = _now_utc() - timedelta(hours=2)
    raw = make_test_jpeg(captured_at=old)
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4198,
        target_lat=47.6605, target_lng=-117.4198,
        radius_m=80, freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "stale_capture"


def test_verify_fails_when_exif_missing_entirely():
    raw = make_test_jpeg(captured_at=None)
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4198,
        target_lat=47.6605, target_lng=-117.4198,
        radius_m=80, freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "no_exif"


def test_verify_default_radius_is_80m():
    # Don't pass radius_m — verify the default
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4178,  # ~150m
        target_lat=47.6605, target_lng=-117.4198,
    )
    assert result.verified is False
    assert result.fail_reason == "out_of_radius"
