from datetime import datetime, timedelta, timezone


def week_start_utc(now: datetime) -> datetime:
    """Return Monday 00:00 UTC of the week containing `now`."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)
