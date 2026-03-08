from __future__ import annotations

import random

from dnd_sim.engine_runtime import (
    _break_concentration,
    _execute_action,
    _force_end_concentration_if_needed,
    has_condition,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=1,
        str_mod=0,
        dex_mod=1,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 1, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    return (
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: {} for actor in actors},
    )


def test_concentration_save_on_damage_failed_breaks_and_clears_linked_effect() -> None:
    caster = _actor("caster", "party")
    attacker = _actor("attacker", "enemy")
    target = _actor("target", "enemy")
    actors = {a.actor_id: a for a in (caster, attacker, target)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, attacker, target)
    active_hazards: list[dict[str, object]] = []

    hold_person = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "target": "target", "condition": "paralyzed"}],
    )
    strike = ActionDefinition(
        name="mace",
        action_type="attack",
        to_hit=6,
        damage="1d4",
        damage_type="bludgeoning",
    )

    _execute_action(
        rng=random.Random(1),
        actor=caster,
        action=hold_person,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert caster.concentrating is True
    assert has_condition(target, "paralyzed")

    _execute_action(
        rng=FixedRng([15, 3, 1]),  # hit roll, damage roll, failed concentration save
        actor=attacker,
        action=strike,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.concentrating is False
    assert not has_condition(target, "paralyzed")


def test_new_concentration_spell_ends_previous_one_immediately() -> None:
    caster = _actor("caster", "party")
    target_a = _actor("target_a", "enemy")
    target_b = _actor("target_b", "enemy")
    actors = {a.actor_id: a for a in (caster, target_a, target_b)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, target_a, target_b
    )
    active_hazards: list[dict[str, object]] = []

    first_spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "target": "target", "condition": "paralyzed"}],
    )
    second_spell = ActionDefinition(
        name="suggestion",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "target": "target", "condition": "charmed"}],
    )

    _execute_action(
        rng=random.Random(2),
        actor=caster,
        action=first_spell,
        targets=[target_a],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert has_condition(target_a, "paralyzed")

    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=second_spell,
        targets=[target_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert not has_condition(target_a, "paralyzed")
    assert has_condition(target_b, "charmed")
    assert caster.concentrated_spell == "suggestion"


def test_breaking_concentration_ends_linked_effect_dependencies() -> None:
    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    actors = {a.actor_id: a for a in (caster, target)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    web_and_summon = ActionDefinition(
        name="web_and_summon",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[
            {"effect_type": "apply_condition", "target": "target", "condition": "restrained"},
            {
                "effect_type": "hazard",
                "target": "target",
                "hazard_type": "web",
                "effect_id": "web_field",
            },
            {"effect_type": "summon", "target": "self", "actor_id": "webling", "name": "Webling"},
        ],
    )

    _execute_action(
        rng=random.Random(4),
        actor=caster,
        action=web_and_summon,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert has_condition(target, "restrained")
    assert "webling" in actors
    assert any(h.get("source_id") == caster.actor_id for h in active_hazards)

    _break_concentration(caster, actors, active_hazards)

    assert caster.concentrating is False
    assert not has_condition(target, "restrained")
    assert "webling" not in actors
    assert not any(h.get("source_id") == caster.actor_id for h in active_hazards)


def test_non_concentration_spell_does_not_disturb_existing_concentration() -> None:
    caster = _actor("caster", "party")
    target_a = _actor("target_a", "enemy")
    target_b = _actor("target_b", "enemy")
    actors = {a.actor_id: a for a in (caster, target_a, target_b)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, target_a, target_b
    )
    active_hazards: list[dict[str, object]] = []

    concentration_spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "target": "target", "condition": "paralyzed"}],
    )
    non_concentration_spell = ActionDefinition(
        name="blindness_deafness",
        action_type="utility",
        concentration=False,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "target": "target", "condition": "blinded"}],
    )

    _execute_action(
        rng=random.Random(5),
        actor=caster,
        action=concentration_spell,
        targets=[target_a],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert caster.concentrating is True
    assert has_condition(target_a, "paralyzed")

    _execute_action(
        rng=random.Random(6),
        actor=caster,
        action=non_concentration_spell,
        targets=[target_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.concentrating is True
    assert caster.concentrated_spell == "hold_person"
    assert has_condition(target_a, "paralyzed")
    assert has_condition(target_b, "blinded")


def test_surprise_does_not_force_end_concentration() -> None:
    caster = _actor("caster", "party")
    caster.concentrating = True
    caster.concentrated_spell = "hex"
    caster.surprised = True
    caster.add_manual_condition("surprised")

    assert (
        _force_end_concentration_if_needed(
            caster,
            actors={caster.actor_id: caster},
            active_hazards=[],
        )
        is False
    )
    assert caster.concentrating is True
    assert caster.concentrated_spell == "hex"
