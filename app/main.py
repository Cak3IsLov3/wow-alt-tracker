import logging
from contextlib import asynccontextmanager

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlmodel import SQLModel
from starlette.middleware.sessions import SessionMiddleware

from app.blizzard.client import BlizzardClient
from app.blizzard.oauth import BattleNetOAuth
from app.config import Settings, get_settings
from app.db import make_engine
from app.routes import auth, pages
from app.security import TokenCipher
from app.services import Services
from app.services.sync import sync_all_users
from app.web import BASE_DIR

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        SQLModel.metadata.create_all(engine)
        http = httpx.AsyncClient(timeout=15)
        cipher = TokenCipher(settings.token_encryption_key, settings.secret_key)
        app.state.services = Services(
            oauth=BattleNetOAuth(http, settings, cipher), blizzard=BlizzardClient(http)
        )
        scheduler = None
        if settings.sync_interval_minutes > 0:
            scheduler = AsyncIOScheduler(timezone="UTC")
            scheduler.add_job(
                sync_all_users,
                "interval",
                minutes=settings.sync_interval_minutes,
                args=[engine, app.state.services],
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        await http.aclose()

    app = FastAPI(title="WoW Alt Tracker", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(auth.router)
    app.include_router(pages.router)
    return app


app = create_app()
