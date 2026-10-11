from datetime import timedelta

from sqlmodel import select

from app.models import (
    Character,
    CharacterSnapshot,
    GearSlotAdvice,
    WeeklyTask,
    WeeklyTaskStatus,
)
from app.services.checklist import (
    evaluate_auto_key,
    mplus_runs_this_week,
    raid_progress_this_week,
    toggle_manual,
)
from app.services.planner import build_rows, summarize
from app.services.sync import sync_character
from app.weeks import week_id, week_start
from tests import samples
from tests.conftest import NOW

START = week_start(NOW)
WEEK = week_id(NOW)


def _completed(session, character, week=WEEK) -> dict[str, str]:
    """Name -> source of all completed tasks."""
    rows = session.exec(
        select(WeeklyTask.name, WeeklyTaskStatus.source)
        .join(WeeklyTaskStatus, WeeklyTaskStatus.task_id == WeeklyTask.id)
        .where(
            WeeklyTaskStatus.character_id == character.id,
            WeeklyTaskStatus.week_id == week,
            WeeklyTaskStatus.completed,
        )
    ).all()
    return dict(rows)


def test_raid_progress_counts_kills_since_reset_in_latest_expansion():
    progress = raid_progress_this_week(samples.raids(START), START)

    assert progress["NORMAL"] == {"instance": "New raid", "killed": 2, "total": 2}
    assert progress["HEROIC"] == {"instance": "New raid", "killed": 1, "total": 2}
    assert "MYTHIC" not in progress  # only in the old expansion


def test_raid_progress_handles_missing_data():
    assert raid_progress_this_week({}, START) == {}


def test_mplus_runs_ignore_runs_from_before_the_reset():
    assert mplus_runs_this_week(samples.keystones(START, runs_this_week=4), START) == 4
    assert mplus_runs_this_week(samples.keystones(START, runs_this_week=0), START) == 0
    assert mplus_runs_this_week({}, START) == 0


def test_evaluate_auto_key():
    progress = raid_progress_this_week(samples.raids(START), START)

    assert evaluate_auto_key("raid:NORMAL", progress, 0)
    assert not evaluate_auto_key("raid:HEROIC", progress, 0)  # 1/2 is not a full clear
    assert not evaluate_auto_key("raid:MYTHIC", progress, 0)
    assert evaluate_auto_key("mplus:4", progress, 4)
    assert not evaluate_auto_key("mplus:8", progress, 4)


async def test_sync_checks_off_what_the_api_shows(blizzard, session, character, respx_mock):
    samples.mock_profile_api(respx_mock, START)

    await sync_character(session, blizzard, character, "eu", "tok", NOW)

    assert _completed(session, character) == {
        "Raid – Normal": "api",
        "Mythic+ – 1 run": "api",
        "Mythic+ – 4 runs": "api",
    }


async def test_sync_stores_snapshot_and_gear_advice(blizzard, session, character, respx_mock):
    samples.mock_profile_api(respx_mock, START)

    await sync_character(session, blizzard, character, "eu", "tok", NOW)
    await sync_character(session, blizzard, character, "eu", "tok", NOW + timedelta(hours=1))

    snapshot = session.exec(select(CharacterSnapshot)).one()  # one per week
    assert snapshot.week_id == WEEK
    assert snapshot.item_level == 265
    assert snapshot.mythic_plus_score == 2450.4
    assert snapshot.mplus_runs == 4
    advice = session.exec(select(GearSlotAdvice).order_by(GearSlotAdvice.priority)).all()
    assert [(a.slot, a.priority) for a in advice] == [
        ("WRIST", 1),
        ("WAIST", 2),
        ("CHEST", 3),
        ("HEAD", 4),
    ]


async def test_sync_updates_auto_status_when_progress_changes(
    blizzard, session, character, respx_mock
):
    routes = samples.mock_profile_api(respx_mock, START, runs_this_week=1)
    await sync_character(session, blizzard, character, "eu", "tok", NOW)
    assert "Mythic+ – 4 runs" not in _completed(session, character)

    routes["keystones"].respond(json=samples.keystones(START, runs_this_week=4))
    await sync_character(session, blizzard, character, "eu", "tok", NOW)

    assert _completed(session, character)["Mythic+ – 4 runs"] == "api"


async def test_manual_choice_survives_sync(blizzard, session, user, character, respx_mock):
    samples.mock_profile_api(respx_mock, START)
    tasks = {t.name: t for t in session.exec(select(WeeklyTask)).all()}
    toggle_manual(session, character, tasks["Collect Great Vault"], WEEK)
    toggle_manual(session, character, tasks["Raid – Heroic"], WEEK)

    await sync_character(session, blizzard, character, "eu", "tok", NOW)

    completed = _completed(session, character)
    assert completed["Collect Great Vault"] == "manual"
    assert completed["Raid – Heroic"] == "manual"  # API says 1/2, manual wins


async def test_checklist_resets_after_weekly_reset(blizzard, session, user, character, respx_mock):
    samples.mock_profile_api(respx_mock, START)
    await sync_character(session, blizzard, character, "eu", "tok", NOW)
    this_week = build_rows(session, user, WEEK, START)[0]
    assert this_week.done == 3

    later = NOW + timedelta(days=7)
    next_week = build_rows(session, user, week_id(later), week_start(later))[0]

    assert next_week.done == 0
    assert next_week.open == next_week.total
    assert next_week.stale  # last login is before the new reset


async def test_planner_sorts_by_open_tasks_and_summarizes(
    blizzard, session, user, character, respx_mock
):
    samples.mock_profile_api(respx_mock, START)
    await sync_character(session, blizzard, character, "eu", "tok", NOW)
    idle = Character(
        user_id=user.id,
        blizzard_id=103,
        name="Aaa",
        realm_slug="draenor",
        realm_name="Draenor",
        class_name="Mage",
        level=80,
    )
    session.add(idle)
    session.commit()

    rows = build_rows(session, user, WEEK, START)

    assert [r.character.name for r in rows] == ["Aaa", "Thrallie"]
    assert rows[0].open == 7 and rows[1].open == 4
    assert summarize(rows) == {"characters": 2, "total": 14, "done": 3, "pct": 21}
    assert [r.character.name for r in build_rows(session, user, WEEK, START, class_name="Mage")] == ["Aaa"]
    assert [r.character.name for r in build_rows(session, user, WEEK, START, min_level=90)] == ["Thrallie"]
    assert build_rows(session, user, WEEK, START, completion="done") == []


async def test_task_details_show_progress(blizzard, session, user, character, respx_mock):
    samples.mock_profile_api(respx_mock, START)
    await sync_character(session, blizzard, character, "eu", "tok", NOW)

    row = build_rows(session, user, WEEK, START)[0]
    details = {t.task.name: t.detail for t in row.tasks}

    assert details["Raid – Heroic"] == "1/2"
    assert details["Mythic+ – 8 runs"] == "4/8"
    assert details["Collect Great Vault"] == ""
