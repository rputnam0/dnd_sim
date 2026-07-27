from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_sim.engine_runtime import _build_actor_from_character, _clone_action
from dnd_sim.io_models import ActionConfig
from dnd_sim.models import ActionDefinition
from dnd_sim.spells import SpellDatabaseValidationError, canonicalize_spell_payload
from tests.helpers import with_class_levels


@pytest.mark.parametrize(
    "attack_delivery",
    [
        "melee_weapon_attack",
        "ranged_weapon_attack",
        "melee_spell_attack",
        "ranged_spell_attack",
    ],
)
def test_action_schema_accepts_explicit_attack_delivery(attack_delivery: str) -> None:
    action = ActionConfig.model_validate(
        {
            "name": "strike",
            "action_type": "attack",
            "to_hit": 5,
            "damage": "1d6",
            "attack_delivery": attack_delivery,
        }
    )

    assert action.attack_delivery == attack_delivery


def test_action_schema_rejects_delivery_on_non_attack_action() -> None:
    with pytest.raises(ValidationError, match="attack_delivery requires action_type='attack'"):
        ActionConfig.model_validate(
            {
                "name": "explosion",
                "action_type": "save",
                "save_dc": 13,
                "save_ability": "dex",
                "attack_delivery": "ranged_spell_attack",
            }
        )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "name": "Thorn Whip",
                "type": "spell",
                "level": 0,
                "casting_time": "action",
                "range_ft": 30,
                "description": "Make a melee spell attack against the target.",
                "mechanics": [{"effect_type": "melee_spell_attack", "range_ft": 30}],
            },
            "melee_spell_attack",
        ),
        (
            {
                "name": "Fire Bolt",
                "type": "spell",
                "level": 0,
                "casting_time": "action",
                "range_ft": 120,
                "description": "Make a ranged spell attack against the target.",
                "mechanics": [{"effect_type": "ranged_spell_attack"}],
            },
            "ranged_spell_attack",
        ),
        (
            {
                "name": "Inflict Wounds",
                "type": "spell",
                "level": 1,
                "casting_time": "action",
                "range_ft": 0,
                "description": "Make a melee spell attack against a creature you can reach.",
                "mechanics": [],
            },
            "melee_spell_attack",
        ),
    ],
)
def test_spell_canonicalization_materializes_attack_delivery(
    payload: dict[str, object], expected: str
) -> None:
    canonical = canonicalize_spell_payload(payload)

    assert canonical["action_type"] == "attack"
    assert canonical["attack_delivery"] == expected


def test_spell_canonicalization_rejects_conflicting_attack_delivery_metadata() -> None:
    with pytest.raises(SpellDatabaseValidationError, match="conflicting attack delivery"):
        canonicalize_spell_payload(
            {
                "name": "Contradictory Bolt",
                "type": "spell",
                "level": 0,
                "casting_time": "action",
                "description": "An invalid attack.",
                "mechanics": [
                    {"effect_type": "melee_spell_attack"},
                    {"effect_type": "ranged_spell_attack"},
                ],
            }
        )


def test_character_attack_profiles_preserve_distinct_delivery_for_thrown_weapon() -> None:
    character = with_class_levels(
        {
            "character_id": "knife_fighter",
            "name": "Knife Fighter",
            "class_level": "Fighter 1",
            "max_hp": 12,
            "ac": 14,
            "speed_ft": 30,
            "ability_scores": {
                "str": 12,
                "dex": 16,
                "con": 12,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
            "save_mods": {},
            "skill_mods": {},
            "attacks": [
                {
                    "id": "dagger_stab",
                    "weapon_id": "weapon_dagger",
                    "name": "Dagger (Melee)",
                    "to_hit": 5,
                    "damage": "1d4+3",
                    "damage_type": "piercing",
                    "weapon_properties": ["finesse", "light", "thrown"],
                    "attack_delivery": "melee_weapon_attack",
                    "reach_ft": 5,
                },
                {
                    "id": "dagger_throw",
                    "weapon_id": "weapon_dagger",
                    "name": "Dagger (Thrown)",
                    "to_hit": 5,
                    "damage": "1d4+3",
                    "damage_type": "piercing",
                    "weapon_properties": ["finesse", "light", "thrown"],
                    "attack_delivery": "ranged_weapon_attack",
                    "range_normal_ft": 20,
                    "range_long_ft": 60,
                },
            ],
            "resources": {},
            "traits": [],
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )

    actor = _build_actor_from_character(character, traits_db={})

    by_id = {action.attack_profile_id: action for action in actor.actions}
    assert by_id["dagger_stab"].attack_delivery == "melee_weapon_attack"
    assert by_id["dagger_throw"].attack_delivery == "ranged_weapon_attack"


def test_action_clone_preserves_attack_delivery() -> None:
    action = ActionDefinition(
        name="thorn_whip",
        action_type="attack",
        to_hit=6,
        damage="1d6",
        attack_delivery="melee_spell_attack",
        range_ft=30,
        tags=["spell"],
    )

    cloned = _clone_action(action, name="thorn_whip_upcast")

    assert cloned.attack_delivery == "melee_spell_attack"
