from __future__ import annotations

from dnd_sim.engine import _build_actor_from_character, short_rest
from tests.helpers import build_character


def test_multiclass_actor_builds_class_levels_and_recovers_slots_on_short_rest() -> None:
    character = build_character(
        character_id="mc_wiz_cleric",
        name="Multiclass Caster",
        max_hp=30,
        ac=14,
        to_hit=6,
        damage="1d8+3",
    )
    character["class_levels"] = {"wizard": 3, "cleric": 1}
    character["traits"] = ["Arcane Recovery"]
    character["resources"] = {}

    actor = _build_actor_from_character(character)

    assert actor.level == 4
    assert actor.class_levels == {"wizard": 3, "cleric": 1}
    assert actor.max_resources["spell_slot_1"] == 4
    assert actor.max_resources["spell_slot_2"] == 3
    assert actor.max_resources["arcane_recovery"] == 1

    actor.resources["spell_slot_2"] = 2
    short_rest(actor)

    assert actor.resources["spell_slot_2"] == 3
    assert actor.resources["arcane_recovery"] == 0
