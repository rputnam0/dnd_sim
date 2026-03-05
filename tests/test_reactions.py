from __future__ import annotations

import random

from dnd_sim.engine_runtime import _execute_action, _tick_conditions_for_actor, has_condition
from dnd_sim.models import ActionDefinition, ActorRuntimeState

_SHIELD_WARD_CONDITION = "shield_spell_warded"


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def _shield_reaction_action() -> ActionDefinition:
    return ActionDefinition(
        name="shield",
        action_type="utility",
        action_cost="reaction",
        target_mode="self",
        tags=["reaction", "shield_spell"],
    )


def test_shield_bonus_persists_for_multiple_attacks_in_same_round() -> None:
    rng = _FixedRng([11, 11])
    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.resources = {"spell_slot_1": 1}
    defender.actions = [_shield_reaction_action()]

    attack = ActionDefinition(
        name="multiattack_longsword",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=5,
        damage="4",
        damage_type="slashing",
        attack_count=2,
    )

    actors = {attacker.actor_id: attacker, defender.actor_id: defender}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, defender)

    _execute_action(
        rng=rng,
        actor=attacker,
        action=attack,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:attacker",
    )

    assert defender.hp == defender.max_hp
    assert defender.resources["spell_slot_1"] == 0
    assert defender.reaction_available is False


def test_shield_bonus_ends_at_start_of_caster_next_turn() -> None:
    rng = _FixedRng([11])
    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.resources = {"spell_slot_1": 1}
    defender.actions = [_shield_reaction_action()]

    attack = ActionDefinition(
        name="longsword",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=5,
        damage="4",
        damage_type="slashing",
    )

    actors = {attacker.actor_id: attacker, defender.actor_id: defender}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, defender)

    _execute_action(
        rng=rng,
        actor=attacker,
        action=attack,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:attacker",
    )
    assert has_condition(defender, _SHIELD_WARD_CONDITION)

    _tick_conditions_for_actor(random.Random(1), defender, boundary="turn_start")

    assert not has_condition(defender, _SHIELD_WARD_CONDITION)


def test_shield_blocks_magic_missile() -> None:
    caster = _base_actor(actor_id="caster", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.resources = {"spell_slot_1": 1}
    defender.actions = [_shield_reaction_action()]

    magic_missile = ActionDefinition(
        name="magic_missile",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell"],
        effects=[
            {
                "effect_type": "damage",
                "target": "target",
                "damage": "6",
                "damage_type": "force",
                "apply_on": "always",
            }
        ],
    )

    actors = {caster.actor_id: caster, defender.actor_id: defender}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, defender)

    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=magic_missile,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
    )

    assert defender.hp == defender.max_hp
    assert defender.resources["spell_slot_1"] == 0
    assert defender.reaction_available is False


def test_shield_ac_bonus_does_not_persist_after_expiry() -> None:
    first_rng = _FixedRng([11])
    second_rng = _FixedRng([11])
    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.resources = {"spell_slot_1": 1}
    defender.actions = [_shield_reaction_action()]

    attack = ActionDefinition(
        name="longsword",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=5,
        damage="4",
        damage_type="slashing",
    )

    actors = {attacker.actor_id: attacker, defender.actor_id: defender}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, defender)

    _execute_action(
        rng=first_rng,
        actor=attacker,
        action=attack,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:attacker",
    )
    assert defender.hp == defender.max_hp

    _tick_conditions_for_actor(random.Random(2), defender, boundary="turn_start")
    assert not has_condition(defender, _SHIELD_WARD_CONDITION)

    _execute_action(
        rng=second_rng,
        actor=attacker,
        action=attack,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=2,
        turn_token="2:attacker",
    )

    assert defender.hp == defender.max_hp - 4
