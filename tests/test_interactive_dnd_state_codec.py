from __future__ import annotations

import copy
from dataclasses import fields
from typing import get_origin, get_type_hints

import pytest

from dnd_sim.engine_runtime import _revert_wild_shape
from dnd_sim.interactive.dnd_state_codec import (
    ActorStateCodecError,
    decode_actor_runtime_state,
    decode_actor_runtime_state_map,
    encode_actor_runtime_state,
    encode_actor_runtime_state_map,
)
from dnd_sim.inventory import CurrencyWallet, InventoryItem, InventoryState
from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    ConditionTracker,
    EffectInstance,
    FeatureHookRegistration,
    SpellComponents,
    SpellDefinition,
    SpellRoll,
    SpellScaling,
)


def _base_action() -> ActionDefinition:
    return ActionDefinition(
        name="quarterstaff",
        action_type="attack",
        to_hit=5,
        damage="1d8+3",
        damage_type="bludgeoning",
        attack_count=2,
        attack_profile_id="quarterstaff_versatile",
        weapon_id="quarterstaff",
        item_id="staff_of_testing",
        weapon_properties=["versatile"],
        reach_ft=5,
        mechanics=[{"effect_type": "note", "text": "base form attack"}],
        tags=["weapon", "magical"],
    )


def _spell_action() -> ActionDefinition:
    return ActionDefinition(
        name="moon bolt",
        action_type="spell",
        to_hit=7,
        damage="2d6",
        damage_type="radiant",
        save_dc=15,
        save_ability="dex",
        half_on_save=True,
        resource_cost={"spell_slot_2": 1},
        action_cost="bonus",
        target_mode="single_enemy",
        range_ft=60,
        concentration=True,
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "glowing",
                "duration_rounds": 2,
            }
        ],
        mechanics=[{"effect_type": "extra_damage", "damage": "1d6"}],
        spell=SpellDefinition(
            name="moon bolt",
            level=2,
            school="evocation",
            casting_time="1 bonus action",
            concentration=True,
            duration="up to 1 minute",
            target_mode="single_enemy",
            roll=SpellRoll(
                attack_bonus=7,
                save_dc=15,
                save_ability="dex",
                half_on_save=True,
            ),
            scaling=SpellScaling(
                upcast_dice_per_level="1d6",
                upcast_healing_per_level=None,
                upcast_effects={3: {"damage": "3d6", "targets": 2}},
            ),
            components=SpellComponents(
                verbal=True,
                somatic=True,
                material=True,
                material_detail="a silver thread",
                raw="V, S, M",
            ),
        ),
        tags=["spell", "radiant"],
    )


def _feature_rich_actor() -> ActorRuntimeState:
    inventory = InventoryState(
        items={
            "staff_of_testing": InventoryItem(
                item_id="staff_of_testing",
                name="Staff of Testing",
                content_id="item:staff_of_testing|TEST",
                quantity=1,
                value_cp=12_500,
                weight_lb=4.0,
                requires_attunement=True,
                attuned=True,
                equip_slots=("main_hand", "off_hand"),
                equipped_slot="main_hand",
                max_charges=7,
                current_charges=4,
                charge_recovery={"rest": "dawn", "dice": "1d6+1"},
                metadata={"rarity": "rare", "granted_actions": [{"name": "moon bolt"}]},
            )
        },
        currency=CurrencyWallet(cp=4, sp=3, ep=2, gp=11, pp=1),
        attunement_limit=4,
    )
    actor = ActorRuntimeState(
        actor_id="hero",
        team="party",
        name="Codec Hero",
        max_hp=42,
        hp=31,
        temp_hp=5,
        ac=17,
        initiative_mod=4,
        str_mod=3,
        dex_mod=4,
        con_mod=2,
        int_mod=1,
        wis_mod=3,
        cha_mod=-1,
        save_mods={"str": 3, "dex": 7, "con": 2, "int": 1, "wis": 6, "cha": -1},
        actions=[_spell_action()],
        proficiencies={"perception", "athletics"},
        expertise={"stealth", "survival"},
        damage_resistances={"cold", "fire"},
        damage_immunities={"poison"},
        damage_vulnerabilities={"thunder"},
        condition_immunities={"charmed", "frightened"},
        conditions={"wild_shaped", "glowing"},
        intrinsic_conditions={"wild_shaped"},
        exhaustion_level=1,
        resources={"spell_slot_2": 2, "wild_shape": 1},
        max_resources={"spell_slot_2": 3, "wild_shape": 2},
        concentrating=True,
        concentration_dc=12,
        death_successes=1,
        death_failures=1,
        downed_count=2,
        was_downed=True,
        reaction_available=False,
        bonus_available=False,
        per_action_uses={"moon bolt": 1},
        recharge_ready={"moon bolt": False},
        legendary_actions_remaining=1,
        lair_action_used_this_round=True,
        traits={"darkvision": {"range_ft": 60.0}, "lucky": {"uses": 1}},
        feature_hooks=[
            FeatureHookRegistration(
                feature_name="Moon Retort",
                source_type="trait",
                hook_type="reaction",
                trigger="damage_taken",
                trait_key="moon_retort",
                mechanic_index=2,
                registration_order=1,
            )
        ],
        inventory=inventory,
        condition_durations={
            "glowing": ConditionTracker(remaining_rounds=2, save_dc=15, save_ability="dex")
        },
        effect_instances=[
            EffectInstance(
                instance_id="effect_1",
                effect_id="moon_glow",
                condition="glowing",
                source_actor_id="hero",
                target_actor_id="enemy",
                duration_remaining=2,
                duration_boundary="turn_end",
                save_dc=15,
                save_ability="dex",
                save_to_end=True,
                concentration_linked=True,
                stack_policy="refresh",
                internal_tags={"spell_effect", "spell_level:2"},
            )
        ],
        effect_instance_seq=3,
        next_attack_advantage=True,
        speed_ft=40,
        movement_modes={"walk": 40.0, "fly": 60.0},
        movement_remaining=15.0,
        position=(10.0, 15.0, 5.0),
        took_attack_action_this_turn=True,
        bonus_action_spell_restriction_active=True,
        non_action_cantrip_spell_cast_this_turn=True,
        rage_sustained_since_last_turn=True,
        sneak_attack_used_this_turn=True,
        sneak_attack_turn_token="round-3:hero",
        colossus_slayer_used_this_turn=True,
        horde_breaker_used_this_turn=True,
        gwm_bonus_trigger_available=True,
        concentrated_targets={"enemy", "enemy_2"},
        concentration_conditions={"glowing"},
        concentration_effect_instance_ids={"effect_1"},
        concentrated_spell="moon bolt",
        readied_action_name="quarterstaff",
        readied_trigger="enemy approaches",
        readied_reaction_reserved=True,
        readied_spell_slot_level=2,
        readied_spell_held=True,
        concentrated_spell_level=2,
        active_zone_ids={"moon_zone", "mist_zone"},
        class_levels={"druid": 5, "ranger": 2},
        level=7,
        wild_shape_active=True,
        wild_shape_form_name="dire wolf",
        wild_shape_base_snapshot={
            "max_hp": 42,
            "hp": 31,
            "ac": 17,
            "speed_ft": 30,
            "str_mod": 3,
            "dex_mod": 4,
            "con_mod": 2,
            "actions": [_base_action()],
            "traits": {"darkvision": {"range_ft": 60.0}},
            "movement_modes": {"walk": 30.0},
        },
        pending_smite={
            "name": "searing smite",
            "save_dc": 15,
            "save_ability": "con",
            "extra_damage": [("1d6", "fire"), ("2d6", "radiant")],
            "rider_effects": [
                {
                    "effect_type": "apply_condition",
                    "condition": "burning",
                    "internal_tags": ["spell_effect"],
                }
            ],
            "is_magical": True,
        },
        companion_owner_id="owner",
        allied_controller_id="controller",
        mount_controller_id="rider",
        mounted_on_id="mount",
        mounted_rider_id="passenger",
        requires_command=True,
        commanded_this_round=True,
        hidden=True,
        detected_by={"enemy", "enemy_2"},
        surprised=True,
        uses_death_saves=True,
        summon_uses_death_saves_default=True,
        death_save_overrides_allowed=False,
        stable_recovery_hours_remaining=3,
        skill_mods={"perception": 6, "stealth": 10},
        creature_type="humanoid",
    )
    return actor


def test_actor_runtime_state_codec_round_trips_full_typed_graph() -> None:
    actor = _feature_rich_actor()

    payload = encode_actor_runtime_state(actor)
    restored = decode_actor_runtime_state(payload)

    assert set(payload) == {field.name for field in fields(ActorRuntimeState)}
    assert payload["conditions"] == ["glowing", "wild_shaped"]
    assert payload["effect_instances"][0]["internal_tags"] == [
        "spell_effect",
        "spell_level:2",
    ]
    assert payload["actions"][0]["spell"]["scaling"]["upcast_effects"] == {
        "3": {"damage": "3d6", "targets": 2}
    }
    assert restored == actor
    assert isinstance(restored.actions[0], ActionDefinition)
    assert isinstance(restored.actions[0].spell, SpellDefinition)
    assert isinstance(restored.inventory, InventoryState)
    assert isinstance(restored.inventory.items["staff_of_testing"], InventoryItem)
    assert isinstance(restored.effect_instances[0], EffectInstance)
    assert isinstance(restored.wild_shape_base_snapshot["actions"][0], ActionDefinition)
    assert isinstance(restored.pending_smite["extra_damage"][0], tuple)
    assert encode_actor_runtime_state(restored) == payload


def test_actor_runtime_state_codec_restores_wild_shape_base_actions_for_revert() -> None:
    restored = decode_actor_runtime_state(encode_actor_runtime_state(_feature_rich_actor()))

    _revert_wild_shape(restored)

    assert restored.wild_shape_active is False
    assert restored.max_hp == 42
    assert restored.hp == 31
    assert restored.actions[0].name == "quarterstaff"
    assert isinstance(restored.actions[0], ActionDefinition)


def test_actor_runtime_state_codec_sorts_every_declared_set_field() -> None:
    actor = _feature_rich_actor()

    payload = encode_actor_runtime_state(actor)

    hints = get_type_hints(ActorRuntimeState)
    set_field_names = {
        field.name for field in fields(ActorRuntimeState) if get_origin(hints[field.name]) is set
    }
    assert set_field_names
    for field_name in set_field_names:
        assert payload[field_name] == sorted(getattr(actor, field_name))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload.pop("hidden"),
        lambda payload: payload["actions"][0].update({"unexpected": True}),
        lambda payload: payload["inventory"]["items"]["staff_of_testing"].update(
            {"unexpected": True}
        ),
        lambda payload: payload.update({"hp": "31"}),
        lambda payload: payload.update({"hp": True}),
        lambda payload: payload.update({"hp": 31.0}),
        lambda payload: payload.update({"conditions": ["wild_shaped", "glowing"]}),
    ],
)
def test_actor_runtime_state_codec_rejects_noncanonical_payloads(mutate) -> None:
    payload = copy.deepcopy(encode_actor_runtime_state(_feature_rich_actor()))
    mutate(payload)

    with pytest.raises(ActorStateCodecError):
        decode_actor_runtime_state(payload)


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
def test_actor_runtime_state_codec_rejects_non_finite_numbers(invalid_number: float) -> None:
    payload = copy.deepcopy(encode_actor_runtime_state(_feature_rich_actor()))
    payload["movement_remaining"] = invalid_number

    with pytest.raises(ActorStateCodecError):
        decode_actor_runtime_state(payload)


def test_actor_runtime_state_codec_rejects_actor_map_identity_mismatch() -> None:
    actor = _feature_rich_actor()

    with pytest.raises(ActorStateCodecError, match="actor map key"):
        encode_actor_runtime_state_map({"not_hero": actor})

    payload = encode_actor_runtime_state_map({"hero": actor})
    payload["not_hero"] = payload.pop("hero")
    with pytest.raises(ActorStateCodecError, match="actor map key"):
        decode_actor_runtime_state_map(payload)


def test_actor_runtime_state_codec_rejects_inventory_map_identity_mismatch() -> None:
    actor = _feature_rich_actor()
    item = actor.inventory.items.pop("staff_of_testing")
    actor.inventory.items["alias"] = item

    with pytest.raises(ActorStateCodecError, match="inventory item key"):
        encode_actor_runtime_state(actor)

    actor = _feature_rich_actor()
    payload = encode_actor_runtime_state(actor)
    payload["inventory"]["items"]["alias"] = payload["inventory"]["items"].pop("staff_of_testing")
    with pytest.raises(ActorStateCodecError, match="inventory item key"):
        decode_actor_runtime_state(payload)


def test_actor_runtime_state_codec_rejects_untyped_sets_in_json_bags() -> None:
    actor = _feature_rich_actor()
    actor.traits["invalid"] = {"unordered": {"a", "b"}}

    with pytest.raises(ActorStateCodecError, match="JSON value tree"):
        encode_actor_runtime_state(actor)
