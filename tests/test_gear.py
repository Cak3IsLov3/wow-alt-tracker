from app.services.gear import advice_text, compute_advice, parse_equipment
from tests.samples import EQUIPMENT


def test_parse_equipment_skips_cosmetic_slots():
    gear = parse_equipment(EQUIPMENT)

    assert [g["slot"] for g in gear] == ["HEAD", "CHEST", "WRIST", "WAIST"]
    assert gear[2] == {
        "slot": "WRIST",
        "slot_name": "Wrists",
        "item_level": 250,
        "name": "Bracers",
        "quality": "",
    }


def test_lowest_slots_get_highest_priority():
    advice = compute_advice(parse_equipment(EQUIPMENT))

    assert [(a["slot_name"], a["priority"]) for a in advice] == [
        ("Wrists", 1),
        ("Waist", 2),
        ("Chest", 3),
        ("Head", 4),
    ]


def test_equal_item_levels_share_a_priority():
    gear = [
        {"slot": "HEAD", "slot_name": "Head", "item_level": 260},
        {"slot": "WRIST", "slot_name": "Wrists", "item_level": 250},
        {"slot": "WAIST", "slot_name": "Waist", "item_level": 250},
    ]

    assert [(a["slot_name"], a["priority"]) for a in compute_advice(gear)] == [
        ("Waist", 1),
        ("Wrists", 1),
        ("Head", 2),
    ]


def test_advice_text_names_the_two_lowest_slots():
    advice = compute_advice(parse_equipment(EQUIPMENT))

    assert advice_text(advice) == "Your lowest slots are Wrists and Waist"
    assert advice_text(advice[:1]) == "Your lowest slot is Wrists"
    assert "Sync this character" in advice_text([])
