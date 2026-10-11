from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.blizzard.client import BlizzardClient
from app.blizzard.oauth import BattleNetOAuth
from app.config import Settings
from app.main import create_app
from app.models import Character, User
from app.security import TokenCipher
from app.services import Services
from app.services.checklist import seed_default_tasks

# Donderdag in de week die woensdag 7 oktober 2026 04:00 UTC begon.
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = NOW):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class SleepRecorder:
    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        blizzard_client_id="client-id",
        blizzard_client_secret="client-secret",
        secret_key="test-secret",
        sync_interval_minutes=0,
    )


@pytest.fixture
def cipher(settings):
    return TokenCipher("", settings.secret_key)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sleeps():
    return SleepRecorder()


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def oauth(http, settings, cipher, clock):
    return BattleNetOAuth(http, settings, cipher, clock=clock)


@pytest.fixture
def blizzard(http, sleeps):
    return BlizzardClient(http, sleep=sleeps)


@pytest.fixture
def services(oauth, blizzard):
    return Services(oauth=oauth, blizzard=blizzard)


@pytest.fixture
def user(session):
    user = User(battlenet_id="424242", battletag="Tester#1234", region="eu")
    session.add(user)
    session.commit()
    session.refresh(user)
    seed_default_tasks(session, user)
    return user


@pytest.fixture
def character(session, user):
    character = Character(
        user_id=user.id,
        blizzard_id=101,
        name="Thrallie",
        realm_slug="draenor",
        realm_name="Draenor",
        class_name="Shaman",
        level=90,
    )
    session.add(character)
    session.commit()
    session.refresh(character)
    return character


@pytest.fixture
def client(settings, engine):
    with TestClient(create_app(settings, engine)) as client:
        yield client
