from datetime import datetime

from sqlmodel import Session, select

from app.models import Character, User, WeeklyTask, WeeklyTaskStatus

TASK_TYPES = {"raid": "Raid", "mplus": "Mythic+", "quest": "Quest", "custom": "Custom"}

# (name, type, default_on, auto_key)
DEFAULT_TASKS = [
    ("Raid – LFR", "raid", False, "raid:LFR"),
    ("Raid – Normal", "raid", True, "raid:NORMAL"),
    ("Raid – Heroic", "raid", True, "raid:HEROIC"),
    ("Raid – Mythic", "raid", False, "raid:MYTHIC"),
    ("Mythic+ – 1 run", "mplus", True, "mplus:1"),
    ("Mythic+ – 4 runs", "mplus", True, "mplus:4"),
    ("Mythic+ – 8 runs", "mplus", True, "mplus:8"),
    ("Weekly quest", "quest", True, None),
    # The Great Vault's contents are not in the API: manual only.
    ("Collect Great Vault", "quest", True, None),
]


def seed_default_tasks(session: Session, user: User) -> None:
    if session.exec(select(WeeklyTask).where(WeeklyTask.user_id == user.id)).first():
        return
    for name, type_, default_on, auto_key in DEFAULT_TASKS:
        session.add(
            WeeklyTask(
                user_id=user.id, name=name, type=type_, default_on=default_on, auto_key=auto_key
            )
        )
    session.commit()


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def raid_progress_this_week(raids: dict, week_start: datetime) -> dict[str, dict]:
    """Per difficulty (LFR/NORMAL/HEROIC/MYTHIC) the number of bosses killed
    since the reset in the latest expansion.

    The API only exposes a total per boss plus `last_kill_timestamp`; a kill
    counts for this week if that timestamp is after the reset. Per difficulty
    we pick the raid with kills this week, or otherwise the newest raid.
    """
    expansions = raids.get("expansions") or []
    if not expansions:
        return {}
    latest = max(expansions, key=lambda e: e.get("expansion", {}).get("id", 0))
    start = _ms(week_start)
    result: dict[str, dict] = {}
    for instance in latest.get("instances", []):
        for mode in instance.get("modes", []):
            difficulty = mode.get("difficulty", {}).get("type")
            if not difficulty:
                continue
            progress = mode.get("progress", {})
            encounters = progress.get("encounters", [])
            killed = sum(1 for e in encounters if e.get("last_kill_timestamp", 0) >= start)
            entry = {
                "instance": instance.get("instance", {}).get("name", ""),
                "killed": killed,
                "total": progress.get("total_count", len(encounters)),
            }
            current = result.get(difficulty)
            if current is None or killed > 0 or current["killed"] == 0:
                result[difficulty] = entry
    return result


def mplus_runs_this_week(profile: dict, week_start: datetime) -> int:
    """Number of runs in the current period. The timestamp check keeps runs
    from a character that has not logged in for a while out of this week.

    `best_runs` holds the best run per dungeon, so this is a lower bound:
    running the same dungeon twice counts as one run.
    """
    runs = (profile.get("current_period") or {}).get("best_runs") or []
    start = _ms(week_start)
    return sum(1 for run in runs if run.get("completed_timestamp", 0) >= start)


def evaluate_auto_key(auto_key: str, raid_progress: dict[str, dict], mplus_runs: int) -> bool:
    kind, _, arg = auto_key.partition(":")
    if kind == "raid":
        progress = raid_progress.get(arg)
        return bool(progress and progress["total"] > 0 and progress["killed"] >= progress["total"])
    if kind == "mplus":
        return mplus_runs >= int(arg)
    return False


def apply_auto_checks(
    session: Session,
    character: Character,
    week_id: str,
    raid_progress: dict[str, dict],
    mplus_runs: int,
) -> None:
    """Checks off tasks based on API data. Whatever the user set manually is
    left alone."""
    tasks = session.exec(
        select(WeeklyTask).where(
            WeeklyTask.user_id == character.user_id, WeeklyTask.auto_key.is_not(None)
        )
    ).all()
    for task in tasks:
        completed = evaluate_auto_key(task.auto_key, raid_progress, mplus_runs)
        status = session.exec(
            select(WeeklyTaskStatus).where(
                WeeklyTaskStatus.character_id == character.id,
                WeeklyTaskStatus.task_id == task.id,
                WeeklyTaskStatus.week_id == week_id,
            )
        ).first()
        if status is None:
            if completed:
                session.add(
                    WeeklyTaskStatus(
                        character_id=character.id,
                        task_id=task.id,
                        week_id=week_id,
                        completed=True,
                        source="api",
                    )
                )
        elif status.source == "api":
            status.completed = completed
            session.add(status)
    session.commit()


def toggle_manual(
    session: Session, character: Character, task: WeeklyTask, week_id: str
) -> WeeklyTaskStatus:
    status = session.exec(
        select(WeeklyTaskStatus).where(
            WeeklyTaskStatus.character_id == character.id,
            WeeklyTaskStatus.task_id == task.id,
            WeeklyTaskStatus.week_id == week_id,
        )
    ).first()
    if status is None:
        status = WeeklyTaskStatus(
            character_id=character.id, task_id=task.id, week_id=week_id, completed=False
        )
    status.completed = not status.completed
    status.source = "manual"
    session.add(status)
    session.commit()
    return status
