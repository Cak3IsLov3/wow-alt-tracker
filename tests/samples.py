"""Voorbeeldantwoorden van Battle.net en de Blizzard Profile API."""

from datetime import datetime, timedelta

import httpx

from app.blizzard.oauth import TOKEN_URL, USERINFO_URL

API = "https://eu.api.blizzard.com"
CHARACTER = f"{API}/profile/wow/character/draenor/thrallie"

USERINFO = {"sub": "424242", "id": 424242, "battletag": "Tester#1234"}

ACCOUNT = {
    "wow_accounts": [
        {
            "id": 1,
            "characters": [
                {
                    "name": "Thrallie",
                    "id": 101,
                    "realm": {"name": "Draenor", "slug": "draenor"},
                    "playable_class": {"name": "Shaman"},
                    "faction": {"type": "HORDE"},
                    "level": 90,
                },
                {
                    "name": "Bankalt",
                    "id": 102,
                    "realm": {"name": "Draenor", "slug": "draenor"},
                    "playable_class": {"name": "Mage"},
                    "faction": {"type": "HORDE"},
                    "level": 12,
                },
            ],
        }
    ]
}

EQUIPMENT = {
    "equipped_items": [
        {"slot": {"type": "HEAD"}, "level": {"value": 270}, "name": "Helm"},
        {"slot": {"type": "CHEST"}, "level": {"value": 268}, "name": "Robe"},
        {"slot": {"type": "WRIST"}, "level": {"value": 250}, "name": "Bracers"},
        {"slot": {"type": "WAIST"}, "level": {"value": 252}, "name": "Belt"},
        {"slot": {"type": "TABARD"}, "level": {"value": 1}, "name": "Guild Tabard"},
    ]
}


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def summary(start: datetime) -> dict:
    return {
        "level": 90,
        "equipped_item_level": 265,
        "last_login_timestamp": _ms(start + timedelta(hours=5)),
    }


def keystones(start: datetime, runs_this_week: int = 4) -> dict:
    this_week = [
        {"completed_timestamp": _ms(start + timedelta(hours=i + 1)), "keystone_level": 10}
        for i in range(runs_this_week)
    ]
    # Een oude run die de API nog kan teruggeven voor een character dat niet is ingelogd.
    stale = [{"completed_timestamp": _ms(start - timedelta(days=3)), "keystone_level": 12}]
    return {
        "current_mythic_rating": {"rating": 2450.37},
        "current_period": {"period": {"id": 1000}, "best_runs": this_week + stale},
    }


def raids(start: datetime) -> dict:
    this_week = _ms(start + timedelta(hours=20))
    last_week = _ms(start - timedelta(days=2))

    def mode(difficulty: str, kills: list[int]) -> dict:
        return {
            "difficulty": {"type": difficulty},
            "progress": {
                "total_count": len(kills),
                "encounters": [
                    {"encounter": {"name": f"Boss {i}"}, "last_kill_timestamp": ts}
                    for i, ts in enumerate(kills)
                ],
            },
        }

    return {
        "expansions": [
            {
                # Oude content telt niet mee, ook niet met kills van deze week.
                "expansion": {"id": 500, "name": "Vorige expansion"},
                "instances": [
                    {"instance": {"name": "Oude raid"}, "modes": [mode("MYTHIC", [this_week])]}
                ],
            },
            {
                "expansion": {"id": 600, "name": "Huidige expansion"},
                "instances": [
                    {
                        "instance": {"name": "Nieuwe raid"},
                        "modes": [
                            mode("NORMAL", [this_week, this_week]),
                            mode("HEROIC", [this_week, last_week]),
                        ],
                    }
                ],
            },
        ]
    }


def mock_battlenet(respx_mock) -> dict:
    """Mockt de OAuth-endpoints. Elk tokenverzoek krijgt een eigen token terug."""

    def token(request: httpx.Request) -> httpx.Response:
        grant = dict(httpx.QueryParams(request.content.decode()))["grant_type"]
        body = {"access_token": f"{grant}-token", "expires_in": 86400, "token_type": "bearer"}
        return httpx.Response(200, json=body)

    return {
        "token": respx_mock.post(TOKEN_URL).mock(side_effect=token),
        "userinfo": respx_mock.get(USERINFO_URL).respond(json=USERINFO),
    }


def mock_profile_api(respx_mock, start: datetime, runs_this_week: int = 4) -> dict:
    return {
        "account": respx_mock.get(f"{API}/profile/user/wow").respond(json=ACCOUNT),
        "summary": respx_mock.get(CHARACTER).respond(json=summary(start)),
        "equipment": respx_mock.get(f"{CHARACTER}/equipment").respond(json=EQUIPMENT),
        "keystones": respx_mock.get(f"{CHARACTER}/mythic-keystone-profile").respond(
            json=keystones(start, runs_this_week)
        ),
        "raids": respx_mock.get(f"{CHARACTER}/encounters/raids").respond(json=raids(start)),
    }
