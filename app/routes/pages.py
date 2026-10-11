from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models import Character, CharacterSnapshot, User, WeeklyTask, WeeklyTaskStatus
from app.services import Services
from app.services.checklist import TASK_TYPES, toggle_manual
from app.services.gear import advice_text, compute_advice
from app.services.planner import build_row, build_rows, enabled_tasks, summarize
from app.services.sync import sync_user
from app.web import CLASS_COLORS, flash, get_current_user, get_services, redirect, render
from app.weeks import next_reset, utcnow, week_id, week_start

router = APIRouter()


def _owned_character(session: Session, user: User, character_id: int) -> Character:
    character = session.get(Character, character_id)
    if character is None or character.user_id != user.id:
        raise HTTPException(status_code=404)
    return character


def _owned_task(session: Session, user: User, task_id: int) -> WeeklyTask:
    task = session.get(WeeklyTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404)
    return task


def _week(user: User) -> dict:
    now = utcnow()
    return {
        "week": week_id(now, user.region),
        "start": week_start(now, user.region),
        "next_reset": next_reset(now, user.region),
    }


@router.get("/")
def dashboard(
    request: Request,
    klass: str = "",
    min_level: str = "",
    status: str = "",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    week = _week(user)
    rows = build_rows(
        session,
        user,
        week["week"],
        week["start"],
        class_name=klass,
        min_level=int(min_level) if min_level.isdigit() else None,
        completion=status,
    )
    classes = sorted(
        set(
            session.exec(
                select(Character.class_name).where(Character.user_id == user.id, Character.active)
            ).all()
        )
    )
    return render(
        request,
        "dashboard.html",
        user=user,
        rows=rows,
        summary=summarize(rows),
        classes=classes,
        filters={"klass": klass, "min_level": min_level, "status": status},
        **week,
    )


@router.post("/sync")
async def sync_now(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
):
    result = await sync_user(session, services, user)
    flash(request, result.message(), "info" if result.ok else "error")
    return redirect("/")


@router.get("/characters")
def characters(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        select(Character)
        .where(Character.user_id == user.id)
        .order_by(Character.active.desc(), Character.level.desc(), Character.name)
    ).all()
    return render(request, "characters.html", user=user, characters=rows)


@router.post("/characters/{character_id}/active")
def toggle_active(
    character_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    character = _owned_character(session, user, character_id)
    character.active = not character.active
    session.add(character)
    session.commit()
    return redirect("/characters")


@router.get("/characters/{character_id}")
def character_detail(
    request: Request,
    character_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    character = _owned_character(session, user, character_id)
    week = _week(user)
    row = build_row(session, character, enabled_tasks(session, user), week["week"], week["start"])
    snapshot = session.exec(
        select(CharacterSnapshot)
        .where(CharacterSnapshot.character_id == character.id)
        .order_by(CharacterSnapshot.week_id.desc())
    ).first()
    advice = compute_advice(snapshot.gear) if snapshot else []
    return render(
        request,
        "character.html",
        user=user,
        row=row,
        character=character,
        advice=advice,
        advice_text=advice_text(advice),
        **week,
    )


@router.post("/characters/{character_id}/tasks/{task_id}/toggle")
def toggle_task(
    request: Request,
    character_id: int,
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    character = _owned_character(session, user, character_id)
    task = _owned_task(session, user, task_id)
    week = _week(user)
    toggle_manual(session, character, task, week["week"])
    row = build_row(session, character, enabled_tasks(session, user), week["week"], week["start"])
    return render(request, "_checklist.html", row=row)


@router.get("/tasks")
def tasks_page(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    tasks = session.exec(
        select(WeeklyTask).where(WeeklyTask.user_id == user.id).order_by(WeeklyTask.id)
    ).all()
    return render(request, "tasks.html", user=user, tasks=tasks)


@router.post("/tasks")
def add_task(
    request: Request,
    name: str = Form(...),
    type: str = Form("custom"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    name = name.strip()[:80]
    if not name:
        flash(request, "Give the task a name.", "error")
    else:
        session.add(
            WeeklyTask(user_id=user.id, name=name, type=type if type in TASK_TYPES else "custom")
        )
        session.commit()
    return redirect("/tasks")


@router.post("/tasks/{task_id}/toggle")
def toggle_task_enabled(
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = _owned_task(session, user, task_id)
    task.default_on = not task.default_on
    session.add(task)
    session.commit()
    return redirect("/tasks")


@router.post("/tasks/{task_id}/delete")
def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = _owned_task(session, user, task_id)
    session.exec(delete(WeeklyTaskStatus).where(WeeklyTaskStatus.task_id == task.id))
    session.delete(task)
    session.commit()
    return redirect("/tasks")


@router.get("/compare")
def compare(
    request: Request,
    a: str = "",
    b: str = "",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    characters = session.exec(
        select(Character)
        .where(Character.user_id == user.id, Character.active)
        .order_by(Character.name)
    ).all()
    return render(request, "compare.html", user=user, characters=characters, a=a, b=b)


@router.get("/api/history")
def history(
    ids: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Item level and M+ score per week for one or more characters."""
    characters = [
        _owned_character(session, user, int(i)) for i in ids.split(",") if i.strip().isdigit()
    ]
    per_character = []
    labels: set[str] = set()
    for character in characters[:4]:
        snapshots = {
            s.week_id: s
            for s in session.exec(
                select(CharacterSnapshot).where(CharacterSnapshot.character_id == character.id)
            ).all()
        }
        labels.update(snapshots)
        per_character.append((character, snapshots))
    weeks = sorted(labels)
    return {
        "labels": weeks,
        "series": [
            {
                "name": character.name,
                "color": CLASS_COLORS.get(character.class_name, "#f8b700"),
                "item_level": [getattr(snaps.get(w), "item_level", None) for w in weeks],
                "mplus_score": [getattr(snaps.get(w), "mythic_plus_score", None) for w in weeks],
            }
            for character, snaps in per_character
        ],
    }

