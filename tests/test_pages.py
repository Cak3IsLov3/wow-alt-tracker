from urllib.parse import parse_qs, urlparse

import pytest
from sqlmodel import select

from app.models import Character, WeeklyTask
from app.weeks import utcnow, week_id, week_start
from tests.samples import mock_battlenet, mock_profile_api


@pytest.fixture
def logged_in(client, respx_mock):
    mock_battlenet(respx_mock)
    client.api_routes = mock_profile_api(respx_mock, week_start(utcnow()))
    response = client.get("/auth/login?region=eu", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    client.get(f"/auth/callback?code=the-code&state={state}", follow_redirects=False)
    return client


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Inloggen met Battle.net" in response.text


def test_dashboard_shows_active_characters_and_summary(logged_in):
    response = logged_in.get("/")

    assert response.status_code == 200
    assert "Thrallie" in response.text
    assert "Bankalt" not in response.text
    assert f"Week {week_id(utcnow())}" in response.text
    assert "3/7" in response.text
    assert "1 character(s) gesynchroniseerd." in response.text


def test_dashboard_filters(logged_in):
    assert "Thrallie" not in logged_in.get("/?klass=Mage").text
    assert "Thrallie" in logged_in.get("/?klass=Shaman&min_level=90&status=open").text
    assert "Thrallie" not in logged_in.get("/?status=done").text


def test_character_page_shows_gear_advice(logged_in):
    response = logged_in.get("/characters/1")

    assert response.status_code == 200
    assert "Je laagste slots zijn Polsen en Riem" in response.text


def test_toggle_task_returns_updated_checklist(logged_in, session):
    vault = session.exec(select(WeeklyTask).where(WeeklyTask.name == "Great Vault ophalen")).one()

    response = logged_in.post(f"/characters/1/tasks/{vault.id}/toggle")

    assert response.status_code == 200
    assert "4/7 voltooid" in response.text
    assert "<html" not in response.text  # alleen het HTMX-fragment
    assert "3/7 voltooid" in logged_in.post(f"/characters/1/tasks/{vault.id}/toggle").text


def test_hide_and_show_character(logged_in, session):
    logged_in.post("/characters/1/active")
    assert "Thrallie" not in logged_in.get("/").text
    assert "Thrallie" in logged_in.get("/characters").text

    logged_in.post("/characters/1/active")
    session.expire_all()
    assert session.get(Character, 1).active


def test_custom_task_can_be_added_disabled_and_deleted(logged_in, session):
    logged_in.post("/tasks", data={"name": "Alchemy cooldown", "type": "custom"})
    assert "Alchemy cooldown" in logged_in.get("/").text
    task = session.exec(select(WeeklyTask).where(WeeklyTask.name == "Alchemy cooldown")).one()

    logged_in.post(f"/tasks/{task.id}/toggle")
    assert "Alchemy cooldown" not in logged_in.get("/").text
    assert "Alchemy cooldown" in logged_in.get("/tasks").text

    logged_in.post(f"/tasks/{task.id}/delete")
    assert "Alchemy cooldown" not in logged_in.get("/tasks").text


def test_history_api_and_compare_page(logged_in):
    data = logged_in.get("/api/history?ids=1").json()

    assert data["labels"] == [week_id(utcnow())]
    assert data["series"][0]["name"] == "Thrallie"
    assert data["series"][0]["item_level"] == [265]
    assert data["series"][0]["mplus_score"] == [2450.4]
    assert 'data-ids="1,2"' in logged_in.get("/compare?a=1&b=2").text


def test_other_users_characters_are_not_accessible(logged_in):
    assert logged_in.get("/characters/999").status_code == 404
    assert logged_in.get("/api/history?ids=999").status_code == 404


def test_sync_now_reports_api_outage(logged_in):
    for route in logged_in.api_routes.values():
        route.respond(503)
    logged_in.app.state.services.blizzard.sleep = _no_sleep

    response = logged_in.post("/sync")

    assert "De Blizzard API is even niet beschikbaar" in response.text


async def _no_sleep(delay: float) -> None:
    return None
