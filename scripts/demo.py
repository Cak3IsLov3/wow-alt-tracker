"""Starts the app with made-up data, without a Battle.net client.

    uv run python -m scripts.demo

Then open http://127.0.0.1:8000/demo-login. The database lives in memory and
nothing is synced.
"""

import os
import random
from datetime import timedelta

import uvicorn
from fastapi import Request
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.main import create_app
from app.models import (
    Character,
    CharacterSnapshot,
    GearSlotAdvice,
    User,
    WeeklyTask,
    WeeklyTaskStatus,
)
from app.services.checklist import apply_auto_checks, seed_default_tasks
from app.services.gear import SLOT_NAMES, compute_advice
from app.web import redirect
from app.weeks import utcnow, week_id

WEEKS = 10

# name, class, level, item level, M+ score, runs this week, raid kills (normal, heroic), manually done
CHARACTERS = [
    ("Thrallie", "Shaman", 90, 272, 2810.5, 8, (8, 8), ["Weekly quest", "Collect Great Vault", "Profession weekly"]),
    ("Moonfeather", "Druid", 90, 266, 2344.0, 4, (8, 5), ["Weekly quest", "Collect Great Vault"]),
    ("Zappyboi", "Mage", 90, 259, 1820.3, 2, (8, 0), ["Collect Great Vault"]),
    ("Holycow", "Paladin", 90, 251, 1205.8, 1, (3, 0), []),
    ("Stabbington", "Rogue", 90, 244, 640.0, 0, (0, 0), []),
    ("Felicia", "Warlock", 88, 221, 0.0, 0, (0, 0), []),
]


def _gear(item_level: int, rng: random.Random) -> list[dict]:
    return [
        {
            "slot": slot,
            "slot_name": name,
            "item_level": item_level + rng.choice([-13, -10, -6, -3, 0, 0, 3, 3, 6]),
            "name": "",
            "quality": "EPIC",
        }
        for slot, name in SLOT_NAMES.items()
    ]


def seed(session: Session) -> User:
    rng = random.Random(7)
    now = utcnow()
    user = User(battlenet_id="demo", battletag="Demo#0000", region="eu")
    session.add(user)
    session.commit()
    session.refresh(user)
    seed_default_tasks(session, user)
    session.add(WeeklyTask(user_id=user.id, name="Profession weekly", type="custom"))
    session.commit()
    tasks = {t.name: t for t in session.exec(select(WeeklyTask)).all()}

    for index, (name, klass, level, ilvl, score, runs, kills, manual) in enumerate(CHARACTERS):
        character = Character(
            user_id=user.id,
            blizzard_id=1000 + index,
            name=name,
            realm_slug="draenor",
            realm_name="Draenor",
            class_name=klass,
            level=level,
            item_level=ilvl,
            mplus_score=score,
            # The last character has not logged in this week.
            last_login=now - (timedelta(days=12) if index == len(CHARACTERS) - 1 else timedelta(hours=3)),
            last_synced=now,
        )
        session.add(character)
        session.commit()
        session.refresh(character)

        for weeks_ago in range(WEEKS - 1, -1, -1):
            current = weeks_ago == 0
            snapshot = CharacterSnapshot(
                character_id=character.id,
                week_id=week_id(now - timedelta(weeks=weeks_ago)),
                item_level=ilvl - weeks_ago * (3 + index % 3) - rng.randint(0, 2) * (not current),
                mythic_plus_score=round(max(score - weeks_ago * score / 12, 0), 1),
                taken_at=now - timedelta(weeks=weeks_ago),
            )
            if current:
                snapshot.mplus_runs = runs
                snapshot.gear = _gear(ilvl, rng)
                snapshot.raid_progress = {
                    difficulty: {"instance": "Demo raid", "killed": killed, "total": 8}
                    for difficulty, killed in zip(("NORMAL", "HEROIC"), kills)
                    if killed
                }
            session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        for item in compute_advice(snapshot.gear):
            session.add(
                GearSlotAdvice(
                    snapshot_id=snapshot.id,
                    slot=item["slot"],
                    item_level=item["item_level"],
                    priority=item["priority"],
                )
            )
        for task_name in manual:
            session.add(
                WeeklyTaskStatus(
                    character_id=character.id,
                    task_id=tasks[task_name].id,
                    week_id=snapshot.week_id,
                    completed=True,
                )
            )
        session.commit()
        apply_auto_checks(session, character, snapshot.week_id, snapshot.raid_progress, runs)
    return user


def build():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user_id = seed(session).id

    settings = Settings(_env_file=None, secret_key="demo", sync_interval_minutes=0)
    app = create_app(settings, engine)

    @app.get("/demo-login")
    def demo_login(request: Request, next: str = "/"):
        request.session["user_id"] = user_id
        return redirect(next if next.startswith("/") and not next.startswith("//") else "/")

    return app


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
