# WoW Alt Tracker

Webapp voor WoW-spelers met meerdere characters. Je logt in met Battle.net, de
app haalt je characters op en toont per character de wekelijkse to-do's, de
gear-status en de voortgang over tijd.

## Starten

1. Maak een client aan op <https://develop.battle.net/access/clients> en zet de
   redirect-URL op `http://localhost:8000/auth/callback`.
2. Kopieer `.env.example` naar `.env` en vul `BLIZZARD_CLIENT_ID`,
   `BLIZZARD_CLIENT_SECRET` en `SECRET_KEY` in.
3. Start de app:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open daarna <http://localhost:8000>. Tests draai je met `uv run pytest`.

## Functies

| Onderdeel | Wat het doet |
| --- | --- |
| Login | Battle.net OAuth (Authorization Code Flow), regio EU/US, tokens versleuteld opgeslagen, uitloggen en ontkoppelen |
| Characters | Alle characters van het account; verbergen/activeren per character |
| Weekly checklist | Standaardtaken, automatisch afvinken via de API, handmatig afvinken, eigen taken |
| Gear-analyse | Item level per slot; de laagste slots krijgen de hoogste prioriteit |
| Planner | Dashboard gesorteerd op meeste openstaande taken, met weeksamenvatting en filters |
| Geschiedenis | Eén snapshot per character per week; grafiek van item level en M+-score, vergelijking van twee characters |
| Sync | "Sync nu"-knop en geplande sync (standaard elk uur), met rate limiting, retries en ETag-cache |

## Architectuur

```
app/
  main.py            app-factory, lifespan, scheduler
  config.py          instellingen uit .env
  models.py          SQLModel-tabellen
  weeks.py           week-ID en reset-logica
  security.py        Fernet-versleuteling van tokens
  blizzard/
    oauth.py         authorize-URL, code-exchange, refresh, app-token
    client.py        rate limiter, retries met backoff, ETag-cache
  services/
    sync.py          characterlijst + per character: profiel, gear, M+, raids
    checklist.py     standaardtaken en automatisch afvinken
    gear.py          slots parsen en upgrade-prioriteit
    planner.py       dashboardrijen, sortering, filters, samenvatting
  routes/            auth.py (login/callback/logout) en pages.py (de rest)
  templates/, static/  Jinja2 + HTMX, Chart.js
tests/               pytest + respx
```

De routes zijn dun: ze halen data op via de services en renderen een template.
Alle logica die getest moet worden (weken, afvinken, gear, retries) staat in
pure functies of in klassen waar klok en `sleep` injecteerbaar zijn.

### Twee soorten tokens

- **User-token** (Authorization Code Flow): alleen nodig voor
  `/profile/user/wow`, de characterlijst van het account. Battle.net geeft
  hierbij normaal geen refresh token mee en het token is 24 uur geldig. Komt er
  toch een refresh token mee, dan wordt er 5 minuten voor verloop ververst.
  Anders vraagt de app je opnieuw in te loggen om de characterlijst te verversen.
- **App-token** (Client Credentials): voor de publieke characterprofielen. De
  app vernieuwt dit zelf, dus de geplande sync blijft werken als je user-token
  is verlopen.

### Week-ID en reset

De reset staat vast in UTC (`app/weeks.py`): EU woensdag 04:00, US dinsdag
15:00. In Nederland is dat 05:00 in de wintertijd en 06:00 in de zomertijd.
Het week-ID is het ISO-jaar en de ISO-week van de resetdag (`2026-W41`). Een
status hoort bij een `week_id`; na de reset bestaat er voor de nieuwe week nog
geen status en is de checklist dus vanzelf leeg. Er is geen resetjob nodig.

### Automatisch afvinken

| Taak | Afgevinkt als |
| --- | --- |
| Raid – LFR/Normal/Heroic/Mythic | alle bosses van de raid hebben een `last_kill_timestamp` na de reset |
| Mythic+ – 1/4/8 runs | zoveel runs in `current_period.best_runs` met een timestamp na de reset |

Bij een gedeeltelijke clear zie je de stand als badge (`3/8`). Wat je zelf
aan- of uitvinkt wordt door een sync niet overschreven.

## Gebruikte endpoints en beperkingen

| Endpoint | Gebruikt voor |
| --- | --- |
| `oauth.battle.net/authorize`, `/token`, `/userinfo` | login en tokens |
| `/profile/user/wow` | characterlijst |
| `/profile/wow/character/{realm}/{naam}` | level, item level, laatste login |
| `…/equipment` | item level per slot |
| `…/mythic-keystone-profile` | M+-score en runs van deze periode |
| `…/encounters/raids` | raid-kills per difficulty |

- **Great Vault**: de inhoud zit niet in de API. Het is een handmatig af te
  vinken taak.
- **Wekelijkse quests**: de API kent alleen "ooit voltooid", niet "deze week".
  Ook handmatig.
- **M+-runs zijn een ondergrens**: `best_runs` bevat de beste run per dungeon.
  Twee keer dezelfde dungeon telt als één run.
- **Raids**: er wordt gekeken naar de nieuwste expansion in het antwoord, en per
  difficulty naar de raid waarin deze week is gekilld (anders de nieuwste).
- **Verouderde data**: characters die sinds de reset niet zijn ingelogd krijgen
  een waarschuwing. Runs en kills van voor de reset tellen niet mee. Voor
  characters die heel lang niet zijn ingelogd geeft Blizzard een 404; dat staat
  dan bij het character.
- De endpoints, de resettijden en de aanname dat de API ETags teruggeeft zijn
  niet tegen de live API getest; de tests draaien op gemockte antwoorden.
  Blizzard past de API per expansion aan, dus controleer bij afwijkingen de
  [documentatie](https://develop.battle.net/documentation/world-of-warcraft/profile-apis).

## Nog niet gedaan

- Screenshots in deze README
- Docker Compose, PostgreSQL-test, Discord-meldingen, Raider.IO
- Databasemigraties: tabellen worden bij het opstarten aangemaakt met `create_all`
