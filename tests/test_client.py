import httpx
import pytest
from sqlmodel import select

from app.blizzard.client import (
    BlizzardClient,
    BlizzardNotFound,
    BlizzardUnavailable,
    RateLimiter,
)
from app.models import CachedResponse
from app.services.sync import UNAVAILABLE, sync_user
from tests.samples import API, CHARACTER, mock_battlenet

PATH = "/profile/wow/character/draenor/thrallie"


async def test_sends_token_namespace_and_locale(blizzard, respx_mock):
    route = respx_mock.get(CHARACTER).respond(json={"level": 90})

    assert await blizzard.get("eu", PATH, "tok") == {"level": 90}

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.url.params["namespace"] == "profile-eu"
    assert request.url.params["locale"] == "en_GB"


async def test_429_waits_for_retry_after_and_retries(blizzard, sleeps, respx_mock):
    route = respx_mock.get(CHARACTER).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    assert await blizzard.get("eu", PATH, "tok") == {"ok": True}
    assert route.call_count == 2
    assert sleeps.delays == [2.0]


async def test_5xx_retries_with_exponential_backoff(blizzard, sleeps, respx_mock):
    route = respx_mock.get(CHARACTER).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    assert await blizzard.get("eu", PATH, "tok") == {"ok": True}
    assert route.call_count == 3
    assert sleeps.delays == [0.5, 1.0]


async def test_network_errors_are_retried(blizzard, sleeps, respx_mock):
    respx_mock.get(CHARACTER).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": True})]
    )

    assert await blizzard.get("eu", PATH, "tok") == {"ok": True}
    assert sleeps.delays == [0.5]


async def test_gives_up_after_max_retries(blizzard, sleeps, respx_mock):
    route = respx_mock.get(CHARACTER).respond(503)

    with pytest.raises(BlizzardUnavailable):
        await blizzard.get("eu", PATH, "tok")

    assert route.call_count == 4  # 1 poging + 3 retries
    assert sleeps.delays == [0.5, 1.0, 2.0]


async def test_404_is_not_retried(blizzard, sleeps, respx_mock):
    route = respx_mock.get(CHARACTER).respond(404)

    with pytest.raises(BlizzardNotFound):
        await blizzard.get("eu", PATH, "tok")

    assert route.call_count == 1
    assert sleeps.delays == []


async def test_second_call_uses_etag_and_serves_cached_data(blizzard, session, respx_mock):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json={"level": 90}, headers={"ETag": '"v1"'})

    route = respx_mock.get(CHARACTER).mock(side_effect=respond)

    first = await blizzard.get("eu", PATH, "tok", session=session, endpoint="character")
    second = await blizzard.get("eu", PATH, "tok", session=session, endpoint="character")

    assert first == second == {"level": 90}
    assert "If-None-Match" not in route.calls[0].request.headers
    assert route.calls[1].request.headers["If-None-Match"] == '"v1"'
    assert route.calls[1].response.status_code == 304
    cached = session.exec(select(CachedResponse)).one()
    assert cached.etag == '"v1"'
    assert cached.key == f"eu:{PATH}"


async def test_changed_etag_replaces_cached_data(blizzard, session, respx_mock):
    respx_mock.get(CHARACTER).mock(
        side_effect=[
            httpx.Response(200, json={"level": 89}, headers={"ETag": '"v1"'}),
            httpx.Response(200, json={"level": 90}, headers={"ETag": '"v2"'}),
        ]
    )

    await blizzard.get("eu", PATH, "tok", session=session, endpoint="character")
    assert await blizzard.get("eu", PATH, "tok", session=session, endpoint="character") == {
        "level": 90
    }
    cached = session.exec(select(CachedResponse)).one()
    assert (cached.etag, cached.data) == ('"v2"', {"level": 90})


async def test_rate_limiter_waits_when_window_is_full():
    now = 0.0
    waits = []

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    limiter = RateLimiter(max_calls=2, period=1.0, clock=lambda: now, sleep=sleep)

    await limiter.acquire()
    await limiter.acquire()
    assert waits == []
    await limiter.acquire()
    assert waits == [1.0]


async def test_client_acquires_the_limiter_for_every_attempt(http, sleeps, respx_mock):
    class CountingLimiter:
        calls = 0

        async def acquire(self) -> None:
            self.calls += 1

    limiter = CountingLimiter()
    respx_mock.get(CHARACTER).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={})]
    )

    await BlizzardClient(http, limiter=limiter, sleep=sleeps).get("eu", PATH, "tok")

    assert limiter.calls == 2


async def test_sync_reports_clear_message_when_api_is_down(
    services, session, user, character, respx_mock
):
    mock_battlenet(respx_mock)
    respx_mock.get(url__startswith=API).respond(503)

    result = await sync_user(session, services, user)

    assert not result.ok
    assert result.synced == 0
    assert UNAVAILABLE in result.message()
