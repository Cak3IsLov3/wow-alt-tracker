import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, delete, select

from app.blizzard.oauth import OAuthError
from app.config import REGIONS
from app.db import get_session
from app.models import OAuthToken, User
from app.services import Services
from app.services.checklist import seed_default_tasks
from app.services.sync import sync_user
from app.web import flash, get_current_user, get_services, redirect, render

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    settings = request.app.state.settings
    return render(
        request,
        "login.html",
        user=None,
        regions=REGIONS,
        default_region=settings.default_region,
        configured=bool(settings.blizzard_client_id and settings.blizzard_client_secret),
    )


@router.get("/auth/login")
def auth_login(
    request: Request, region: str = "eu", services: Services = Depends(get_services)
):
    if region not in REGIONS:
        region = request.app.state.settings.default_region
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_region"] = region
    return RedirectResponse(services.oauth.authorize_url(state), status_code=302)


@router.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
):
    expected = request.session.pop("oauth_state", None)
    region = request.session.pop("oauth_region", request.app.state.settings.default_region)
    if not code or not expected or not secrets.compare_digest(state, expected):
        flash(request, "Inloggen mislukt: ongeldige of verlopen aanvraag.", "error")
        return redirect("/login")

    try:
        token = await services.oauth.exchange_code(code)
        info = await services.oauth.userinfo(token.access_token)
    except OAuthError as exc:
        flash(request, f"Inloggen mislukt: {exc}", "error")
        return redirect("/login")

    battlenet_id = str(info.get("id") or info.get("sub"))
    user = session.exec(
        select(User).where(User.battlenet_id == battlenet_id, User.region == region)
    ).first()
    if user is None:
        user = User(battlenet_id=battlenet_id, battletag="", region=region)
    user.battletag = info.get("battletag", battlenet_id)
    session.add(user)
    session.commit()
    session.refresh(user)

    services.oauth.store_token(session, user, token)
    seed_default_tasks(session, user)
    request.session["user_id"] = user.id

    result = await sync_user(session, services, user)
    flash(request, result.message(), "info" if result.ok else "error")
    return redirect("/")


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@router.post("/auth/unlink")
def unlink(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Verwijdert de opgeslagen tokens; de characters en geschiedenis blijven staan."""
    session.exec(delete(OAuthToken).where(OAuthToken.user_id == user.id))
    session.commit()
    request.session.clear()
    flash(request, "Je Battle.net-account is ontkoppeld en de tokens zijn verwijderd.")
    return redirect("/login")
