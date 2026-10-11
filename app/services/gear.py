SLOT_NAMES = {
    "HEAD": "Head",
    "NECK": "Neck",
    "SHOULDER": "Shoulders",
    "BACK": "Back",
    "CHEST": "Chest",
    "WRIST": "Wrists",
    "HANDS": "Hands",
    "WAIST": "Waist",
    "LEGS": "Legs",
    "FEET": "Feet",
    "FINGER_1": "Ring 1",
    "FINGER_2": "Ring 2",
    "TRINKET_1": "Trinket 1",
    "TRINKET_2": "Trinket 2",
    "MAIN_HAND": "Main hand",
    "OFF_HAND": "Off hand",
}
COSMETIC_SLOTS = {"SHIRT", "TABARD"}


def parse_equipment(equipment: dict) -> list[dict]:
    """Converts the API's equipment response into a list of slots."""
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
    """Sorts slots from lowest to highest item level. Priority 1 = upgrade
    first; slots with the same item level share a priority."""
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
        return "No gear data yet. Sync this character first."
    if len(names) == 1:
        return f"Your lowest slot is {names[0]}"
    return f"Your lowest slots are {', '.join(names[:-1])} and {names[-1]}"
