from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlmodel import select

from app.blizzard.oauth import AUTHORIZE_URL, ReauthRequired, TokenResponse
from app.models import Character, OAuthToken, User
from app.weeks import utcnow, week_start
from tests.samples import mock_battlenet, mock_profile_api


def _form(request: httpx.Request) -> dict:
    return dict(httpx.QueryParams(request.content.decode()))


def _login(client, respx_mock) -> dict:
    routes = mock_battlenet(respx_mock)
    routes.update(mock_profile_api(respx_mock, week_start(utcnow())))
    response = client.get("/auth/login?region=eu", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    routes["response"] = client.get(
        f"/auth/callback?code=the-code&state={state}", follow_redirects=False
    )
    return routes


def test_login_redirects_to_battlenet(client):
    response = client.get("/auth/login?region=eu", follow_redirects=False)

    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert response.headers["location"].startswith(AUTHORIZE_URL)
    assert query["client_id"] == ["client-id"]
    assert query["response_type"] == ["code"]
    assert "wow.profile" in query["scope"][0]
    assert query["state"][0]


def test_callback_exchanges_code_and_stores_encrypted_token(client, respx_mock, session, cipher):
    routes = _login(client, respx_mock)

    assert routes["response"].status_code == 303
    assert routes["response"].headers["location"] == "/"
    exchange = _form(routes["token"].calls[0].request)
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code"] == "the-code"

    user = session.exec(select(User)).one()
    assert user.battletag == "Tester#1234"
    assert user.region == "eu"
    token = session.exec(select(OAuthToken)).one()
    assert token.access_token != "authorization_code-token"
    assert cipher.decrypt(token.access_token) == "authorization_code-token"


def test_callback_fetches_characters_with_the_user_token(client, respx_mock, session):
    routes = _login(client, respx_mock)

    request = routes["account"].calls[0].request
    assert request.headers["Authorization"] == "Bearer authorization_code-token"
    characters = {c.name: c for c in session.exec(select(Character)).all()}
    assert characters["Thrallie"].active
    assert not characters["Bankalt"].active  # geen max level: standaard verborgen
    # Publieke profielen gaan via het app-token.
    assert routes["summary"].calls[0].request.headers["Authorization"] == (
        "Bearer client_credentials-token"
    )


def test_callback_rejects_unknown_state(client, respx_mock, session):
    routes = mock_battlenet(respx_mock)
    client.get("/auth/login?region=eu", follow_redirects=False)

    response = client.get("/auth/callback?code=the-code&state=forged", follow_redirects=False)

    assert response.headers["location"] == "/login"
    assert not routes["token"].called
    assert session.exec(select(User)).first() is None


def test_pages_require_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_unlink_deletes_tokens(client, respx_mock, session):
    _login(client, respx_mock)

    response = client.post("/auth/unlink", follow_redirects=False)

    assert response.headers["location"] == "/login"
    assert session.exec(select(OAuthToken)).first() is None
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"


async def test_valid_token_is_not_refreshed(oauth, session, user, respx_mock):
    routes = mock_battlenet(respx_mock)
    oauth.store_token(session, user, TokenResponse("current", 86400, "refresh-me"))

    assert await oauth.get_user_token(session, user) == "current"
    assert not routes["token"].called


async def test_token_is_refreshed_just_before_expiry(oauth, clock, session, user, respx_mock, cipher):
    routes = mock_battlenet(respx_mock)
    oauth.store_token(session, user, TokenResponse("current", 86400, "refresh-me"))
    clock.now += timedelta(hours=23, minutes=58)  # nog 2 minuten geldig

    token = await oauth.get_user_token(session, user)

    assert token == "refresh_token-token"
    form = _form(routes["token"].calls[0].request)
    assert form == {"grant_type": "refresh_token", "refresh_token": "refresh-me"}
    stored = session.exec(select(OAuthToken)).one()
    assert cipher.decrypt(stored.access_token) == "refresh_token-token"
    # Het nieuwe token is weer 24 uur geldig en wordt niet opnieuw ververst.
    assert await oauth.get_user_token(session, user) == "refresh_token-token"
    assert routes["token"].call_count == 1


async def test_expired_token_without_refresh_token_requires_login(oauth, clock, session, user):
    oauth.store_token(session, user, TokenResponse("current", 86400))
    clock.now += timedelta(days=2)

    with pytest.raises(ReauthRequired):
        await oauth.get_user_token(session, user)


async def test_failed_refresh_requires_login(oauth, clock, session, user, respx_mock):
    respx_mock.post("https://oauth.battle.net/token").respond(400, json={"error": "invalid_grant"})
    oauth.store_token(session, user, TokenResponse("current", 86400, "revoked"))
    clock.now += timedelta(days=2)

    with pytest.raises(ReauthRequired):
        await oauth.get_user_token(session, user)


async def test_app_token_is_cached_until_it_expires(oauth, clock, respx_mock):
    routes = mock_battlenet(respx_mock)

    assert await oauth.get_app_token() == "client_credentials-token"
    assert await oauth.get_app_token() == "client_credentials-token"
    assert routes["token"].call_count == 1

    clock.now += timedelta(hours=24)
    await oauth.get_app_token()
    assert routes["token"].call_count == 2
