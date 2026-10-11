"""Week ID and reset logic.

The weekly reset is fixed in UTC, so it does not move with daylight saving
time: in Central Europe the EU reset is at 05:00 (CET) or 06:00 (CEST).
"""

from datetime import UTC, datetime, timedelta

# region -> (weekday with Monday = 0, hour in UTC)
RESETS: dict[str, tuple[int, int]] = {
    "eu": (2, 4),  # Wednesday 04:00 UTC
    "us": (1, 15),  # Tuesday 15:00 UTC
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Naive datetimes are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def week_start(now: datetime, region: str = "eu") -> datetime:
    """The most recent reset at or before `now`."""
    weekday, hour = RESETS[region]
    now = as_utc(now)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate -= timedelta(days=(now.weekday() - weekday) % 7)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


def next_reset(now: datetime, region: str = "eu") -> datetime:
    return week_start(now, region) + timedelta(days=7)


def week_id(now: datetime, region: str = "eu") -> str:
    """ISO year and week of the reset day, e.g. '2026-W41'. Sorts chronologically."""
    iso = week_start(now, region).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
