from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.weeks import utcnow


class User(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("battlenet_id", "region"),)

    id: int | None = Field(default=None, primary_key=True)
    battlenet_id: str = Field(index=True)
    battletag: str
    region: str
    created_at: datetime = Field(default_factory=utcnow)


class OAuthToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    access_token: str  # encrypted
    refresh_token: str | None = None  # encrypted
    expires_at: datetime


class Character(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "blizzard_id"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    blizzard_id: int
    name: str
    realm_slug: str
    realm_name: str
    class_name: str
    level: int
    faction: str = ""
    active: bool = True
    item_level: int | None = None
    mplus_score: float | None = None
    last_login: datetime | None = None
    last_synced: datetime | None = None
    sync_error: str | None = None


class CharacterSnapshot(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("character_id", "week_id"),)

    id: int | None = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    week_id: str = Field(index=True)
    item_level: int | None = None
    mythic_plus_score: float | None = None
    mplus_runs: int = 0
    raid_progress: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    gear: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    taken_at: datetime = Field(default_factory=utcnow)


class WeeklyTask(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    type: str  # raid / mplus / quest / custom
    default_on: bool = True
    # 'raid:HEROIC' or 'mplus:4'; empty = can only be checked off manually
    auto_key: str | None = None


class WeeklyTaskStatus(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("character_id", "task_id", "week_id"),)

    id: int | None = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    task_id: int = Field(foreign_key="weeklytask.id", index=True)
    week_id: str = Field(index=True)
    completed: bool = False
    source: str = "manual"  # api / manual


class GearSlotAdvice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="charactersnapshot.id", index=True)
    slot: str
    item_level: int
    priority: int  # 1 = upgrade first


class CachedResponse(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("endpoint", "key"),)

    id: int | None = Field(default=None, primary_key=True)
    endpoint: str
    key: str
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    etag: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
