"""Week-ID en reset-logica.

De wekelijkse reset staat vast in UTC en schuift dus niet mee met zomer- en
wintertijd: in Nederland is de EU-reset 05:00 (CET) of 06:00 (CEST).
"""

from datetime import UTC, datetime, timedelta

# regio -> (weekdag met maandag = 0, uur in UTC)
RESETS: dict[str, tuple[int, int]] = {
    "eu": (2, 4),  # woensdag 04:00 UTC
    "us": (1, 15),  # dinsdag 15:00 UTC
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Naive datetimes behandelen we als UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def week_start(now: datetime, region: str = "eu") -> datetime:
    """Het moment van de laatste reset op of voor `now`."""
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
    """ISO-jaar en -week van de resetdag, bv. '2026-W41'. Sorteert chronologisch."""
    iso = week_start(now, region).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
