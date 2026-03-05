from __future__ import annotations

import random

from dnd_sim.engine_runtime import (
    _apply_effect,
    _break_concentration,
    _execute_action,
    _remove_effect_instance,
    _tick_conditions_for_actor,
    actor_is_incapacitated,
    has_condition,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import apply_damage, resolve_death_save


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
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


def test_same_named_effects_from_multiple_sources_and_stack_policy() -> None:
    source_a = _actor("source_a", "party")
    source_b = _actor("source_b", "party")
    source_c = _actor("source_c", "party")
    target = _actor("target", "enemy")
    actors = {
        source_a.actor_id: source_a,
        source_b.actor_id: source_b,
        source_c.actor_id: source_c,
        target.actor_id: target,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source_a, source_b, source_c, target
    )

    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "restrained",
            "duration_rounds": 3,
            "effect_id": "web_source_a",
        },
        rng=random.Random(1),
        actor=source_a,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "restrained",
            "duration_rounds": 2,
            "effect_id": "web_source_b",
        },
        rng=random.Random(1),
        actor=source_b,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    restrained = [effect for effect in target.effect_instances if effect.condition == "restrained"]
    assert len(restrained) == 2
    assert has_condition(target, "restrained")

    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "restrained",
            "duration_rounds": 4,
            "effect_id": "web_source_c",
            "stack_policy": "replace",
        },
        rng=random.Random(1),
        actor=source_c,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    restrained = [effect for effect in target.effect_instances if effect.condition == "restrained"]
    assert len(restrained) == 1
    assert restrained[0].source_actor_id == source_c.actor_id


def test_end_of_turn_expiration_boundary() -> None:
    source = _actor("source", "party")
    target = _actor("target", "enemy")
    actors = {source.actor_id: source, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(source, target)

    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "distracted",
            "duration_rounds": 1,
            "duration_timing": "turn_end",
            "effect_id": "distracted_until_end",
        },
        rng=random.Random(1),
        actor=source,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    assert has_condition(target, "distracted")
    _tick_conditions_for_actor(random.Random(1), target, boundary="turn_start")
    assert has_condition(target, "distracted")
    _tick_conditions_for_actor(random.Random(1), target, boundary="turn_end")
    assert not has_condition(target, "distracted")


def test_concentration_break_removes_only_linked_effect_instances() -> None:
    caster = _actor("caster", "party")
    helper = _actor("helper", "enemy")
    target = _actor("target", "enemy")
    actors = {caster.actor_id: caster, helper.actor_id: helper, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, helper, target)
    active_hazards: list[dict[str, object]] = []

    hold_person = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "paralyzed",
                "duration_rounds": 10,
                "effect_id": "hold_person_effect",
            }
        ],
    )
    helper_debuff = ActionDefinition(
        name="stasis_gaze",
        action_type="utility",
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "paralyzed",
                "duration_rounds": 5,
                "effect_id": "stasis_gaze_effect",
            }
        ],
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
    _execute_action(
        rng=random.Random(1),
        actor=helper,
        action=helper_debuff,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert has_condition(target, "paralyzed")
    paralyzed = [effect for effect in target.effect_instances if effect.condition == "paralyzed"]
    assert len(paralyzed) == 2

    _break_concentration(caster, actors, active_hazards)

    assert caster.concentrating is False
    assert has_condition(target, "paralyzed")
    paralyzed = [effect for effect in target.effect_instances if effect.condition == "paralyzed"]
    assert len(paralyzed) == 1
    assert paralyzed[0].source_actor_id == helper.actor_id


def test_removing_one_effect_instance_does_not_remove_unrelated_effects() -> None:
    source_a = _actor("source_a", "party")
    source_b = _actor("source_b", "enemy")
    target = _actor("target", "enemy")
    actors = {source_a.actor_id: source_a, source_b.actor_id: source_b, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source_a, source_b, target
    )

    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "frightened",
            "duration_rounds": 3,
            "effect_id": "fear_a",
        },
        rng=random.Random(2),
        actor=source_a,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "frightened",
            "duration_rounds": 2,
            "effect_id": "fear_b",
        },
        rng=random.Random(2),
        actor=source_b,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    frightened = [effect for effect in target.effect_instances if effect.condition == "frightened"]
    assert len(frightened) == 2
    _remove_effect_instance(target, frightened[0].instance_id)
    frightened = [effect for effect in target.effect_instances if effect.condition == "frightened"]
    assert len(frightened) == 1
    assert has_condition(target, "frightened")


def test_turned_damage_cleanup_removes_effect_instances_and_clears_incapacitated() -> None:
    cleric = _actor("cleric", "party")
    target = _actor("target", "enemy")
    actors = {cleric.actor_id: cleric, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(cleric, target)

    _apply_effect(
        effect={"effect_type": "apply_condition", "condition": "turned", "duration_rounds": 3},
        rng=random.Random(1),
        actor=cleric,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    _apply_effect(
        effect={"effect_type": "apply_condition", "condition": "frightened", "duration_rounds": 3},
        rng=random.Random(1),
        actor=cleric,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    _apply_effect(
        effect={
            "effect_type": "apply_condition",
            "condition": "incapacitated",
            "duration_rounds": 3,
        },
        rng=random.Random(1),
        actor=cleric,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    assert has_condition(target, "turned")
    assert actor_is_incapacitated(target)

    apply_damage(target, 1, "radiant", source=cleric)

    assert not has_condition(target, "turned")
    assert not has_condition(target, "frightened")
    assert not has_condition(target, "incapacitated")
    assert not actor_is_incapacitated(target)
    lingering = {
        effect.condition
        for effect in target.effect_instances
        if effect.condition in {"turned", "frightened", "incapacitated"}
    }
    assert not lingering


def test_nat20_recovery_clears_lingering_unconscious_effect_instance() -> None:
    source = _actor("source", "enemy")
    target = _actor("target", "party")
    actors = {source.actor_id: source, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(source, target)

    _apply_effect(
        effect={"effect_type": "apply_condition", "condition": "unconscious", "duration_rounds": 5},
        rng=random.Random(2),
        actor=source,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )
    target.hp = 0
    target.dead = False
    target.stable = False
    assert has_condition(target, "unconscious")
    assert actor_is_incapacitated(target)

    class _Nat20:
        def randint(self, _a: int, _b: int) -> int:
            return 20

    result = resolve_death_save(_Nat20(), target)

    assert result.regained_consciousness is True
    assert target.hp == 1
    assert not has_condition(target, "unconscious")
    assert not has_condition(target, "incapacitated")
    assert not actor_is_incapacitated(target)
    assert all(effect.condition != "unconscious" for effect in target.effect_instances)


def test_break_concentration_preserves_unlinked_same_condition_from_same_source() -> None:
    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    concentration_hold = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "paralyzed",
                "duration_rounds": 10,
                "effect_id": "hold_person_concentration",
            }
        ],
    )
    non_concentration_debuff = ActionDefinition(
        name="stasis_echo",
        action_type="utility",
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "paralyzed",
                "duration_rounds": 4,
                "effect_id": "stasis_echo_non_concentration",
            }
        ],
    )

    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=concentration_hold,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=non_concentration_debuff,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    paralyzed = [effect for effect in target.effect_instances if effect.condition == "paralyzed"]
    assert len(paralyzed) == 2
    _break_concentration(caster, actors, active_hazards)

    assert has_condition(target, "paralyzed")
    paralyzed = [effect for effect in target.effect_instances if effect.condition == "paralyzed"]
    assert len(paralyzed) == 1
    assert paralyzed[0].effect_id == "stasis_echo_non_concentration"


def test_spell_metadata_effect_markers_are_runtime_noops() -> None:
    source = _actor("source", "party")
    target = _actor("target", "enemy")
    actors = {source.actor_id: source, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(source, target)

    for effect_type in (
        "aoe",
        "ranged_spell_attack",
        "melee_spell_attack",
        "save",
        "area",
        "aura",
        "audible_range",
    ):
        _apply_effect(
            effect={"effect_type": effect_type},
            rng=random.Random(7),
            actor=source,
            target=target,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            actors=actors,
            active_hazards=[],
        )

    assert source.hp == 30
    assert target.hp == 30
    assert target.temp_hp == 0
    assert target.position == (0.0, 0.0, 0.0)
    assert target.effect_instances == []
    assert damage_dealt == {"source": 0, "target": 0}
    assert damage_taken == {"source": 0, "target": 0}
    assert threat_scores == {"source": 0, "target": 0}


def test_push_effect_type_aliases_to_forced_movement() -> None:
    source = _actor("source", "party")
    target = _actor("target", "enemy")
    target.position = (5.0, 0.0, 0.0)
    actors = {source.actor_id: source, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(source, target)

    _apply_effect(
        effect={"effect_type": "push", "distance": 10, "direction": "away_from_source"},
        rng=random.Random(13),
        actor=source,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    assert target.position != (5.0, 0.0, 0.0)
    assert target.position[0] > 5.0
