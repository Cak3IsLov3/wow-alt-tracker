import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import Engine
from sqlmodel import Session, delete, select

from app.blizzard.client import (
    BlizzardAuthError,
    BlizzardClient,
    BlizzardError,
    BlizzardNotFound,
    BlizzardUnavailable,
)
from app.blizzard.oauth import OAuthError, ReauthRequired
from app.models import Character, CharacterSnapshot, GearSlotAdvice, User
from app.services import Services
from app.services.checklist import (
    apply_auto_checks,
    mplus_runs_this_week,
    raid_progress_this_week,
)
from app.services.gear import compute_advice, parse_equipment
from app.weeks import as_utc, utcnow, week_id, week_start

log = logging.getLogger(__name__)

UNAVAILABLE = "De Blizzard API is even niet beschikbaar. Probeer het later opnieuw."


@dataclass
class SyncResult:
    synced: int = 0
    notes: list[str] = field(default_factory=list)
    ok: bool = True

    def message(self) -> str:
        parts = [f"{self.synced} character(s) gesynchroniseerd."] if self.ok else []
        return " ".join(parts + self.notes)


async def sync_account_characters(
    session: Session, client: BlizzardClient, user: User, token: str
) -> int:
    """Haalt de characterlijst van het account op (vereist het user-token)."""
    data = await client.get(user.region, "/profile/user/wow", token)
    found = [c for account in data.get("wow_accounts", []) for c in account.get("characters", [])]
    existing = {
        c.blizzard_id: c
        for c in session.exec(select(Character).where(Character.user_id == user.id)).all()
    }
    max_level = max((c.get("level", 0) for c in found), default=0)
    for entry in found:
        character = existing.get(entry["id"])
        if character is None:
            # Nieuwe characters staan alleen aan als ze op het hoogste level zitten;
            # de rest kan de gebruiker zelf aanzetten.
            character = Character(
                user_id=user.id,
                blizzard_id=entry["id"],
                name="",
                realm_slug="",
                realm_name="",
                class_name="",
                level=0,
                active=entry.get("level", 0) == max_level,
            )
        character.name = entry["name"]
        character.realm_slug = entry["realm"]["slug"]
        character.realm_name = entry["realm"].get("name", entry["realm"]["slug"])
        character.class_name = entry.get("playable_class", {}).get("name", "")
        character.level = entry.get("level", 0)
        character.faction = entry.get("faction", {}).get("type", "")
        session.add(character)
    session.commit()
    return len(found)


async def _optional(client: BlizzardClient, region: str, path: str, token: str, **kwargs) -> dict:
    try:
        return await client.get(region, path, token, **kwargs)
    except BlizzardNotFound:
        return {}


async def sync_character(
    session: Session,
    client: BlizzardClient,
    character: Character,
    region: str,
    token: str,
    now: datetime | None = None,
) -> CharacterSnapshot:
    now = now or utcnow()
    start = week_start(now, region)
    week = week_id(now, region)
    base = f"/profile/wow/character/{character.realm_slug}/{quote(character.name.lower())}"

    summary = await client.get(region, base, token, session=session, endpoint="character")
    equipment = await _optional(
        client, region, f"{base}/equipment", token, session=session, endpoint="equipment"
    )
    keystones = await _optional(
        client,
        region,
        f"{base}/mythic-keystone-profile",
        token,
        session=session,
        endpoint="mythic-keystone-profile",
    )
    raids = await _optional(
        client, region, f"{base}/encounters/raids", token, session=session, endpoint="raids"
    )

    rating = (keystones.get("current_mythic_rating") or {}).get("rating")
    character.level = summary.get("level", character.level)
    character.item_level = summary.get("equipped_item_level", character.item_level)
    character.mplus_score = round(rating, 1) if rating is not None else character.mplus_score
    if summary.get("last_login_timestamp"):
        character.last_login = as_utc(
            datetime.fromtimestamp(summary["last_login_timestamp"] / 1000, UTC)
        )
    character.last_synced = as_utc(now)
    character.sync_error = None
    session.add(character)

    raid_progress = raid_progress_this_week(raids, start)
    runs = mplus_runs_this_week(keystones, start)
    gear = parse_equipment(equipment)

    snapshot = session.exec(
        select(CharacterSnapshot).where(
            CharacterSnapshot.character_id == character.id, CharacterSnapshot.week_id == week
        )
    ).first()
    if snapshot is None:
        snapshot = CharacterSnapshot(character_id=character.id, week_id=week)
    snapshot.item_level = character.item_level
    snapshot.mythic_plus_score = character.mplus_score
    snapshot.mplus_runs = runs
    snapshot.raid_progress = raid_progress
    snapshot.gear = gear
    snapshot.taken_at = as_utc(now)
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)

    session.exec(delete(GearSlotAdvice).where(GearSlotAdvice.snapshot_id == snapshot.id))
    for item in compute_advice(gear):
        session.add(
            GearSlotAdvice(
                snapshot_id=snapshot.id,
                slot=item["slot"],
                item_level=item["item_level"],
                priority=item["priority"],
            )
        )
    session.commit()

    apply_auto_checks(session, character, week, raid_progress, runs)
    return snapshot


async def sync_user(
    session: Session, services: Services, user: User, now: datetime | None = None
) -> SyncResult:
    result = SyncResult()

    try:
        user_token = await services.oauth.get_user_token(session, user)
        await sync_account_characters(session, services.blizzard, user, user_token)
    except (ReauthRequired, BlizzardAuthError):
        result.notes.append(
            "Je Battle.net-sessie is verlopen; log opnieuw in om de characterlijst te verversen."
        )
    except BlizzardUnavailable:
        result.ok = False
        result.notes.append(UNAVAILABLE)
        return result
    except BlizzardError as exc:
        log.warning("Characterlijst ophalen mislukt: %s", exc)
        result.notes.append("De characterlijst kon niet worden opgehaald.")

    try:
        app_token = await services.oauth.get_app_token()
    except OAuthError:
        result.ok = False
        result.notes.append(UNAVAILABLE)
        return result

    characters = session.exec(
        select(Character).where(Character.user_id == user.id, Character.active)
    ).all()
    failed = 0
    for character in characters:
        try:
            await sync_character(
                session, services.blizzard, character, user.region, app_token, now
            )
            result.synced += 1
        except BlizzardNotFound:
            # Blizzard geeft 404 voor characters die lang niet zijn ingelogd.
            character.sync_error = "Geen profieldata (lang niet ingelogd?)"
            session.add(character)
            session.commit()
            failed += 1
        except BlizzardUnavailable:
            result.ok = result.synced > 0
            result.notes.append(UNAVAILABLE)
            return result
        except BlizzardError as exc:
            log.warning("Sync van %s mislukt: %s", character.name, exc)
            character.sync_error = "Synchronisatie mislukt"
            session.add(character)
            session.commit()
            failed += 1
    if failed:
        result.notes.append(f"{failed} character(s) konden niet worden opgehaald.")
    return result


async def sync_all_users(engine: Engine, services: Services) -> None:
    """Geplande sync. Werkt ook als het user-token is verlopen, want de
    characterprofielen gaan via het app-token."""
    with Session(engine) as session:
        for user in session.exec(select(User)).all():
            try:
                result = await sync_user(session, services, user)
                log.info("Sync %s: %s", user.battletag, result.message())
            except Exception:
                log.exception("Sync van %s mislukt", user.battletag)
                session.rollback()
