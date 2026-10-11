"""HTTP-client voor de Blizzard Profile API met rate limiting, retries met
backoff en een ETag-cache in de database."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

import httpx
from sqlmodel import Session, select

from app.models import CachedResponse
from app.weeks import as_utc, utcnow

LOCALES = {"eu": "en_GB", "us": "en_US"}


class BlizzardError(Exception):
    pass


class BlizzardNotFound(BlizzardError):
    pass


class BlizzardAuthError(BlizzardError):
    pass


class BlizzardUnavailable(BlizzardError):
    """De API bleef 429/5xx geven of was onbereikbaar, ook na retries."""


class RateLimiter:
    """Sliding window: maximaal `max_calls` per `period` seconden."""

    def __init__(
        self,
        max_calls: int = 50,
        period: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.max_calls = max_calls
        self.period = period
        self.clock = clock
        self.sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self.clock()
                while self._calls and self._calls[0] <= now - self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                await self.sleep(self._calls[0] + self.period - now)


class BlizzardClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: RateLimiter | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        max_backoff: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.http = http
        self.limiter = limiter or RateLimiter()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.sleep = sleep

    async def get(
        self,
        region: str,
        path: str,
        token: str,
        *,
        session: Session | None = None,
        endpoint: str = "",
    ) -> dict:
        """Haalt `path` op. Met `session` en `endpoint` loopt het verzoek via de
        ETag-cache: bij een 304 komt de data uit de database."""
        url = f"https://{region}.api.blizzard.com{path}"
        params = {"namespace": f"profile-{region}", "locale": LOCALES.get(region, "en_US")}
        headers = {"Authorization": f"Bearer {token}"}

        cached = None
        if session is not None and endpoint:
            cached = session.exec(
                select(CachedResponse).where(
                    CachedResponse.endpoint == endpoint, CachedResponse.key == f"{region}:{path}"
                )
            ).first()
            if cached and cached.etag:
                headers["If-None-Match"] = cached.etag

        response = await self._request(url, params, headers)
        if response.status_code == 304 and cached is not None:
            return cached.data

        data = response.json()
        if session is not None and endpoint:
            if cached is None:
                cached = CachedResponse(endpoint=endpoint, key=f"{region}:{path}")
            cached.data = data
            cached.etag = response.headers.get("ETag")
            cached.fetched_at = as_utc(utcnow())
            session.add(cached)
            session.commit()
        return data

    async def _request(self, url: str, params: dict, headers: dict) -> httpx.Response:
        problem = ""
        for attempt in range(self.max_retries + 1):
            await self.limiter.acquire()
            delay = min(self.backoff_base * 2**attempt, self.max_backoff)
            try:
                response = await self.http.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                problem = f"netwerkfout: {exc!r}"
            else:
                status = response.status_code
                if status in (200, 304):
                    return response
                if status == 404:
                    raise BlizzardNotFound(url)
                if status in (401, 403):
                    raise BlizzardAuthError(f"{status} voor {url}")
                if status != 429 and status < 500:
                    raise BlizzardError(f"Onverwachte status {status} voor {url}")
                problem = f"status {status}"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), self.max_backoff)
            if attempt < self.max_retries:
                await self.sleep(delay)
        raise BlizzardUnavailable(f"{url} niet beschikbaar ({problem})")
