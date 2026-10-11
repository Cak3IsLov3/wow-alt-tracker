SLOT_NAMES = {
    "HEAD": "Hoofd",
    "NECK": "Nek",
    "SHOULDER": "Schouders",
    "BACK": "Rug",
    "CHEST": "Borst",
    "WRIST": "Polsen",
    "HANDS": "Handen",
    "WAIST": "Riem",
    "LEGS": "Benen",
    "FEET": "Voeten",
    "FINGER_1": "Ring 1",
    "FINGER_2": "Ring 2",
    "TRINKET_1": "Trinket 1",
    "TRINKET_2": "Trinket 2",
    "MAIN_HAND": "Hoofdhand",
    "OFF_HAND": "Nevenhand",
}
COSMETIC_SLOTS = {"SHIRT", "TABARD"}


def parse_equipment(equipment: dict) -> list[dict]:
    """Zet het equipment-antwoord van de API om naar een lijst slots."""
    gear = []
    for item in equipment.get("equipped_items", []):
        slot = item.get("slot", {}).get("type", "")
        level = item.get("level", {}).get("value")
        if not slot or slot in COSMETIC_SLOTS or level is None:
            continue
        gear.append(
            {
                "slot": slot,
                "slot_name": SLOT_NAMES.get(slot, item.get("slot", {}).get("name", slot)),
                "item_level": int(level),
                "name": item.get("name", ""),
                "quality": item.get("quality", {}).get("type", ""),
            }
        )
    return gear


def compute_advice(gear: list[dict]) -> list[dict]:
    """Sorteert slots van laag naar hoog item level. Prioriteit 1 = eerst
    upgraden; slots met hetzelfde item level delen een prioriteit."""
    ordered = sorted(gear, key=lambda g: (g["item_level"], g["slot_name"]))
    advice = []
    priority = 0
    previous = None
    for item in ordered:
        if item["item_level"] != previous:
            priority += 1
            previous = item["item_level"]
        advice.append({**item, "priority": priority})
    return advice


def advice_text(advice: list[dict], count: int = 2) -> str:
    names = [a["slot_name"] for a in advice[:count]]
    if not names:
        return "Nog geen gear-data. Synchroniseer dit character eerst."
    if len(names) == 1:
        return f"Je laagste slot is {names[0]}"
    return f"Je laagste slots zijn {', '.join(names[:-1])} en {names[-1]}"
