"""Gedeelde helpers voor de routes: templates, flash-meldingen en de ingelogde gebruiker."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.db import get_session
from app.models import User
from app.services import Services
from app.services.checklist import TASK_TYPES

BASE_DIR = Path(__file__).parent

CLASS_COLORS = {
    "Death Knight": "#C41E3A",
    "Demon Hunter": "#A330C9",
    "Druid": "#FF7C0A",
    "Evoker": "#33937F",
    "Hunter": "#AAD372",
    "Mage": "#3FC7EB",
    "Monk": "#00FF98",
    "Paladin": "#F48CBA",
    "Priest": "#FFFFFF",
    "Rogue": "#FFF468",
    "Shaman": "#0070DD",
    "Warlock": "#8788EE",
    "Warrior": "#C69B6D",
}

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["class_colors"] = CLASS_COLORS
templates.env.globals["task_types"] = TASK_TYPES


def flash(request: Request, text: str, kind: str = "info") -> None:
    request.session["flash"] = [*request.session.get("flash", []), {"kind": kind, "text": text}]


def render(request: Request, name: str, **context):
    context["messages"] = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, context)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id else None
    if user is None:
        request.session.pop("user_id", None)
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user
