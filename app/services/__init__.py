from dataclasses import dataclass

from app.blizzard.client import BlizzardClient
from app.blizzard.oauth import BattleNetOAuth


@dataclass
class Services:
    oauth: BattleNetOAuth
    blizzard: BlizzardClient
