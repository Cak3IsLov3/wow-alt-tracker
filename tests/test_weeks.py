from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.weeks import next_reset, week_id, week_start

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_week_starts_on_wednesday_morning_in_eu():
    assert week_start(utc(2026, 10, 8, 12, 0)) == utc(2026, 10, 7, 4, 0)
    assert week_id(utc(2026, 10, 8, 12, 0)) == "2026-W41"


def test_boundary_around_wednesday_reset():
    assert week_id(utc(2026, 10, 7, 3, 59, 59)) == "2026-W40"
    assert week_id(utc(2026, 10, 7, 4, 0, 0)) == "2026-W41"
    assert week_start(utc(2026, 10, 7, 3, 59, 59)) == utc(2026, 9, 30, 4, 0)


def test_tuesday_night_still_belongs_to_previous_week():
    assert week_id(utc(2026, 10, 6, 23, 59)) == "2026-W40"
    assert week_id(utc(2026, 10, 13, 12, 0)) == "2026-W41"


def test_next_reset_is_exactly_one_week_later():
    assert next_reset(utc(2026, 10, 8, 12, 0)) == utc(2026, 10, 14, 4, 0)
    assert next_reset(utc(2026, 10, 7, 4, 0)) == utc(2026, 10, 14, 4, 0)


def test_reset_in_summer_time_is_six_local():
    # 21 oktober 2026 valt nog in de zomertijd (CEST = UTC+2).
    before = datetime(2026, 10, 21, 5, 59, tzinfo=AMSTERDAM)
    after = datetime(2026, 10, 21, 6, 0, tzinfo=AMSTERDAM)
    assert week_id(before) == "2026-W42"
    assert week_id(after) == "2026-W43"


def test_reset_in_winter_time_is_five_local():
    # De klok gaat op 25 oktober 2026 terug (CET = UTC+1).
    before = datetime(2026, 10, 28, 4, 59, tzinfo=AMSTERDAM)
    after = datetime(2026, 10, 28, 5, 0, tzinfo=AMSTERDAM)
    assert week_id(before) == "2026-W43"
    assert week_id(after) == "2026-W44"


def test_week_stays_seven_days_across_dst_changes():
    for moment in (utc(2026, 10, 26, 12, 0), utc(2027, 3, 29, 12, 0)):
        start = week_start(moment)
        assert next_reset(moment) - start == timedelta(days=7)
        assert start.weekday() == 2 and start.hour == 4


def test_year_boundary_keeps_one_week_id():
    # De week van woensdag 30 december 2026 loopt door tot in januari.
    assert week_id(utc(2026, 12, 30, 4, 0)) == "2026-W53"
    assert week_id(utc(2026, 12, 31, 23, 59)) == "2026-W53"
    assert week_id(utc(2027, 1, 1, 0, 0)) == "2026-W53"
    assert week_id(utc(2027, 1, 6, 3, 59)) == "2026-W53"
    assert week_id(utc(2027, 1, 6, 4, 0)) == "2027-W01"


def test_week_ids_sort_chronologically():
    moment = utc(2026, 11, 1, 12, 0)
    ids = [week_id(moment + timedelta(weeks=i)) for i in range(20)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 20


def test_us_resets_on_tuesday_afternoon_utc():
    assert week_start(utc(2026, 10, 6, 14, 59), "us") == utc(2026, 9, 29, 15, 0)
    assert week_start(utc(2026, 10, 6, 15, 0), "us") == utc(2026, 10, 6, 15, 0)


def test_naive_datetimes_are_treated_as_utc():
    assert week_id(datetime(2026, 10, 7, 3, 59)) == "2026-W40"
    assert week_id(datetime(2026, 10, 7, 4, 0)) == "2026-W41"
