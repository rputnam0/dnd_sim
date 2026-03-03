from __future__ import annotations

from dnd_sim.engine import _build_actor_from_character, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=2,
        dex_mod=3,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 3, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _character_with_weapon_profiles() -> dict[str, object]:
    return {
        "character_id": "weapon_tester",
        "name": "Weapon Tester",
        "class_level": "Rogue 3 / Fighter 1",
        "max_hp": 38,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {
            "str": 14,
            "dex": 18,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 2, "dex": 6, "con": 2, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [
            {
                "id": "attack_heavy_blade",
                "weapon_id": "weapon_greatsword",
                "item_id": "item_greatsword",
                "name": "Executioner's Edge",
                "to_hit": 5,
                "damage": "1d1",
                "damage_type": "slashing",
                "weapon_properties": ["heavy", "reach", "magical"],
                "reach_ft": 10,
                "range_ft": 10,
                "range_normal_ft": 10,
                "range_long_ft": 10,
            },
            {
                "id": "attack_finesse_knife",
                "weapon_id": "weapon_dagger",
                "item_id": "item_dagger",
                "name": "Needle Fang",
                "to_hit": 7,
                "damage": "1d1",
                "damage_type": "piercing",
                "weapon_properties": ["finesse", "light", "thrown"],
                "range_ft": 20,
                "range_normal_ft": 20,
                "range_long_ft": 60,
            },
        ],
        "resources": {},
        "traits": ["Great Weapon Master", "Sneak Attack"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _run_attack_for_profile(profile_id: str) -> tuple[int, bool]:
    character = _character_with_weapon_profiles()
    actor = _build_actor_from_character(character, traits_db={})
    actor.position = (0.0, 0.0, 0.0)
    action = next(a for a in actor.actions if a.attack_profile_id == profile_id)

    ally = _actor("ally", "party")
    target = _actor("target", "enemy")
    ally.position = (5.0, 0.0, 0.0)
    target.position = (5.0, 0.0, 0.0)

    actors = {actor.actor_id: actor, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 1, 6, 5]),
        actor=actor,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    return damage_dealt[actor.actor_id], actor.sneak_attack_used_this_turn


def _run_named_heavy_attack(display_name: str) -> int:
    actor = _actor("attacker", "party")
    target = _actor("target", "enemy")
    actor.traits = {"great weapon master": {}}
    actor.position = (0.0, 0.0, 0.0)
    target.position = (5.0, 0.0, 0.0)
    action = ActionDefinition(
        name=display_name,
        action_type="attack",
        to_hit=5,
        damage="1d1",
        damage_type="slashing",
        attack_profile_id="attack_heavy_blade",
        weapon_id="weapon_greatsword",
        item_id="item_greatsword",
        weapon_properties=["heavy"],
    )

    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 1]),
        actor=actor,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    return damage_dealt[actor.actor_id]


def test_attack_action_retains_weapon_identity_and_properties() -> None:
    actor = _build_actor_from_character(_character_with_weapon_profiles(), traits_db={})
    heavy = next(
        action for action in actor.actions if action.attack_profile_id == "attack_heavy_blade"
    )

    assert heavy.attack_profile_id == "attack_heavy_blade"
    assert heavy.weapon_id == "weapon_greatsword"
    assert heavy.item_id == "item_greatsword"
    assert set(heavy.weapon_properties) == {"heavy", "reach", "magical"}
    assert heavy.reach_ft == 10
    assert heavy.range_normal_ft == 10
    assert heavy.range_long_ft == 10


def test_different_weapon_profiles_produce_different_legal_interactions() -> None:
    heavy_damage, heavy_used_sneak = _run_attack_for_profile("attack_heavy_blade")
    finesse_damage, finesse_used_sneak = _run_attack_for_profile("attack_finesse_knife")

    assert heavy_damage == 11
    assert heavy_used_sneak is False
    assert finesse_damage == 12
    assert finesse_used_sneak is True


def test_display_name_changes_do_not_change_rules_for_canonical_weapon() -> None:
    baseline_damage = _run_named_heavy_attack("greatsword")
    renamed_damage = _run_named_heavy_attack("festival blade")

    assert baseline_damage == renamed_damage == 11


def test_ranged_attack_with_partial_canonical_properties_stays_ranged() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    attacker.traits = {"sharpshooter": {}}
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    action = ActionDefinition(
        name="arcane_bolt",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="force",
        attack_profile_id="attack_arcane_bolt",
        weapon_id="weapon_arcane_focus",
        item_id="item_arcane_focus",
        weapon_properties=["magical"],
        range_ft=60,
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 1]),
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    # Sharpshooter power attack (+10) should still apply for ranged action.
    assert damage_dealt[attacker.actor_id] == 11
