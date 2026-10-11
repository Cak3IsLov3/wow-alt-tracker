from app.services.gear import advice_text, compute_advice, parse_equipment
from tests.samples import EQUIPMENT


def test_parse_equipment_skips_cosmetic_slots():
    gear = parse_equipment(EQUIPMENT)

    assert [g["slot"] for g in gear] == ["HEAD", "CHEST", "WRIST", "WAIST"]
    assert gear[2] == {
        "slot": "WRIST",
        "slot_name": "Polsen",
        "item_level": 250,
        "name": "Bracers",
        "quality": "",
    }


def test_lowest_slots_get_highest_priority():
    advice = compute_advice(parse_equipment(EQUIPMENT))

    assert [(a["slot_name"], a["priority"]) for a in advice] == [
        ("Polsen", 1),
        ("Riem", 2),
        ("Borst", 3),
        ("Hoofd", 4),
    ]


def test_equal_item_levels_share_a_priority():
    gear = [
        {"slot": "HEAD", "slot_name": "Hoofd", "item_level": 260},
        {"slot": "WRIST", "slot_name": "Polsen", "item_level": 250},
        {"slot": "WAIST", "slot_name": "Riem", "item_level": 250},
    ]

    assert [(a["slot_name"], a["priority"]) for a in compute_advice(gear)] == [
        ("Polsen", 1),
        ("Riem", 1),
        ("Hoofd", 2),
    ]


def test_advice_text_names_the_two_lowest_slots():
    advice = compute_advice(parse_equipment(EQUIPMENT))

    assert advice_text(advice) == "Je laagste slots zijn Polsen en Riem"
    assert advice_text(advice[:1]) == "Je laagste slot is Polsen"
    assert "Synchroniseer" in advice_text([])
