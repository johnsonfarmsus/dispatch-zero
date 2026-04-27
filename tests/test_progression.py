from datetime import datetime, timezone

from dispatchzero.services.progression import week_start_utc


def test_week_start_utc_returns_monday_midnight_for_a_wednesday():
    wednesday = datetime(2026, 4, 29, 14, 30, 0, tzinfo=timezone.utc)
    monday = week_start_utc(wednesday)
    assert monday.weekday() == 0
    assert monday.hour == 0 and monday.minute == 0 and monday.second == 0
    assert (wednesday - monday).days == 2


def test_week_start_utc_returns_same_day_for_a_monday_morning():
    monday_am = datetime(2026, 4, 27, 6, 0, 0, tzinfo=timezone.utc)
    start = week_start_utc(monday_am)
    assert start.weekday() == 0
    assert start.hour == 0
    assert (monday_am - start).total_seconds() == 6 * 3600


def test_week_start_utc_promotes_naive_datetime_to_utc():
    naive = datetime(2026, 4, 29, 14, 30, 0)
    monday = week_start_utc(naive)
    assert monday.tzinfo == timezone.utc
