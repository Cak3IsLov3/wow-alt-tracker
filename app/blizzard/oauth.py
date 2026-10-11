"""Battle.net OAuth 2.0: Authorization Code Flow voor gebruikers en
Client Credentials voor de app zelf.

Let op: Battle.net geeft bij de Authorization Code Flow normaal gesproken geen
refresh token mee; een user-token is 24 uur geldig. Krijgen we er toch een,
dan verversen we vlak voor verloop. Zonder refresh token moet de gebruiker
opnieuw inloggen (ReauthRequired). Characterprofielen zijn publiek en worden
daarom met het app-token opgehaald, dat we zelf altijd kunnen vernieuwen.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlmodel import Session, select

from app.config import Settings
from app.models import OAuthToken, User
from app.security import TokenCipher
from app.weeks import as_utc, utcnow

AUTHORIZE_URL = "https://oauth.battle.net/authorize"
TOKEN_URL = "https://oauth.battle.net/token"
USERINFO_URL = "https://oauth.battle.net/userinfo"
SCOPE = "openid wow.profile"
REFRESH_MARGIN = timedelta(minutes=5)


class OAuthError(Exception):
    pass


class ReauthRequired(OAuthError):
    """Het user-token is verlopen en kan niet ververst worden."""


@dataclass
class TokenResponse:
    access_token: str
    expires_in: int
    refresh_token: str | None = None


class BattleNetOAuth:
    def __init__(
        self,
        http: httpx.AsyncClient,
        settings: Settings,
        cipher: TokenCipher,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.http = http
        self.settings = settings
        self.cipher = cipher
        self.clock = clock
        self._app_token: str | None = None
        self._app_token_expires: datetime | None = None

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.settings.blizzard_client_id,
                "redirect_uri": self.settings.redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def _token_request(self, data: dict[str, str]) -> TokenResponse:
        auth = (self.settings.blizzard_client_id, self.settings.blizzard_client_secret)
        try:
            response = await self.http.post(TOKEN_URL, data=data, auth=auth)
        except httpx.TransportError as exc:
            raise OAuthError(f"Battle.net is niet bereikbaar: {exc}") from exc
        if response.status_code != 200:
            raise OAuthError(f"Battle.net weigerde het tokenverzoek ({response.status_code})")
        body = response.json()
        return TokenResponse(
            access_token=body["access_token"],
            expires_in=int(body.get("expires_in", 0)),
            refresh_token=body.get("refresh_token"),
        )

    async def exchange_code(self, code: str) -> TokenResponse:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def userinfo(self, access_token: str) -> dict:
        try:
            response = await self.http.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.TransportError as exc:
            raise OAuthError(f"Battle.net is niet bereikbaar: {exc}") from exc
        if response.status_code != 200:
            raise OAuthError(f"Kon je Battle.net-profiel niet ophalen ({response.status_code})")
        return response.json()

    def store_token(self, session: Session, user: User, token: TokenResponse) -> OAuthToken:
        row = session.exec(select(OAuthToken).where(OAuthToken.user_id == user.id)).first()
        if row is None:
            row = OAuthToken(user_id=user.id, access_token="", expires_at=as_utc(self.clock()))
        row.access_token = self.cipher.encrypt(token.access_token)
        if token.refresh_token:
            row.refresh_token = self.cipher.encrypt(token.refresh_token)
        row.expires_at = as_utc(self.clock() + timedelta(seconds=token.expires_in))
        session.add(row)
        session.commit()
        return row

    async def get_user_token(self, session: Session, user: User) -> str:
        """Geeft een geldig user-token terug en ververst het vlak voor verloop."""
        row = session.exec(select(OAuthToken).where(OAuthToken.user_id == user.id)).first()
        if row is None:
            raise ReauthRequired("Geen token opgeslagen")
        if as_utc(row.expires_at) - REFRESH_MARGIN > self.clock():
            return self.cipher.decrypt(row.access_token)
        if not row.refresh_token:
            raise ReauthRequired("Token verlopen")
        try:
            token = await self.refresh(self.cipher.decrypt(row.refresh_token))
        except OAuthError as exc:
            raise ReauthRequired(str(exc)) from exc
        self.store_token(session, user, token)
        return token.access_token

    async def get_app_token(self) -> str:
        """Client Credentials-token, in het geheugen gecachet tot vlak voor verloop."""
        now = self.clock()
        if self._app_token and self._app_token_expires and self._app_token_expires > now:
            return self._app_token
        token = await self._token_request({"grant_type": "client_credentials"})
        self._app_token = token.access_token
        self._app_token_expires = now + timedelta(seconds=token.expires_in) - REFRESH_MARGIN
        return token.access_token
