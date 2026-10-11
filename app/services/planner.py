from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.models import Character, CharacterSnapshot, User, WeeklyTask, WeeklyTaskStatus
from app.weeks import as_utc


@dataclass
class TaskView:
    task: WeeklyTask
    completed: bool
    source: str
    detail: str


@dataclass
class CharacterRow:
    character: Character
    tasks: list[TaskView]
    stale: bool

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.completed)

    @property
    def open(self) -> int:
        return self.total - self.done

    @property
    def pct(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0


def _detail(task: WeeklyTask, snapshot: CharacterSnapshot | None) -> str:
    if not task.auto_key or snapshot is None:
        return ""
    kind, _, arg = task.auto_key.partition(":")
    if kind == "raid":
        progress = (snapshot.raid_progress or {}).get(arg)
        return f"{progress['killed']}/{progress['total']}" if progress else ""
    if kind == "mplus":
        return f"{min(snapshot.mplus_runs, int(arg))}/{arg}"
    return ""


def enabled_tasks(session: Session, user: User) -> list[WeeklyTask]:
    return list(
        session.exec(
            select(WeeklyTask)
            .where(WeeklyTask.user_id == user.id, WeeklyTask.default_on)
            .order_by(WeeklyTask.id)
        ).all()
    )


def build_row(
    session: Session,
    character: Character,
    tasks: list[WeeklyTask],
    week: str,
    start: datetime,
) -> CharacterRow:
    statuses = {
        s.task_id: s
        for s in session.exec(
            select(WeeklyTaskStatus).where(
                WeeklyTaskStatus.character_id == character.id, WeeklyTaskStatus.week_id == week
            )
        ).all()
    }
    snapshot = session.exec(
        select(CharacterSnapshot).where(
            CharacterSnapshot.character_id == character.id, CharacterSnapshot.week_id == week
        )
    ).first()
    views = []
    for task in tasks:
        status = statuses.get(task.id)
        views.append(
            TaskView(
                task=task,
                completed=bool(status and status.completed),
                source=status.source if status else "",
                detail=_detail(task, snapshot),
            )
        )
    # Not logged in since the reset: the API data may be stale.
    stale = character.last_login is not None and as_utc(character.last_login) < start
    return CharacterRow(character=character, tasks=views, stale=stale)


def build_rows(
    session: Session,
    user: User,
    week: str,
    start: datetime,
    *,
    class_name: str = "",
    min_level: int | None = None,
    completion: str = "",
) -> list[CharacterRow]:
    """Active characters, sorted by most open tasks."""
    query = select(Character).where(Character.user_id == user.id, Character.active)
    if class_name:
        query = query.where(Character.class_name == class_name)
    if min_level is not None:
        query = query.where(Character.level >= min_level)
    tasks = enabled_tasks(session, user)
    rows = [build_row(session, c, tasks, week, start) for c in session.exec(query).all()]
    if completion == "open":
        rows = [r for r in rows if r.open > 0]
    elif completion == "done":
        rows = [r for r in rows if r.open == 0]
    rows.sort(key=lambda r: (-r.open, r.character.name))
    return rows


def summarize(rows: list[CharacterRow]) -> dict:
    total = sum(r.total for r in rows)
    done = sum(r.done for r in rows)
    return {
        "characters": len(rows),
        "total": total,
        "done": done,
        "pct": round(100 * done / total) if total else 0,
    }
