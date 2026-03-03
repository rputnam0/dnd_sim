from __future__ import annotations

import random

from dnd_sim.engine import _build_feature_hook_registrations, _dispatch_combat_event
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=24,
        hp=24,
        temp_hp=0,
        ac=10,
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


def test_chr03_trait_hook_schema_accepts_type_alias_for_reaction_hook() -> None:
    issues = validate_rule_mechanics_payload(
        kind="trait",
        payload={
            "name": "Reflexive Strikes",
            "type": "subclass_feature",
            "mechanics": [
                {
                    "type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
    )

    assert issues == []


def test_chr03_dispatch_runs_subclass_reaction_attack_hook() -> None:
    rng = random.Random(12)
    attacker = _base_actor(actor_id="attacker", team="enemy")
    ally_target = _base_actor(actor_id="ally_target", team="party")
    reactor = _base_actor(actor_id="reactor", team="party")
    reactor.actions = [
        ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=100,
            damage="1",
            target_mode="single_enemy",
        )
    ]
    reactor.traits = {
        "battle_reflexes": {
            "name": "Battle Reflexes",
            "type": "subclass_feature",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        }
    }

    actors = {
        attacker.actor_id: attacker,
        ally_target.actor_id: ally_target,
        reactor.actor_id: reactor,
    }
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    trace: list[dict[str, object]] = []
    trigger_action = ActionDefinition(
        name="enemy_slash",
        action_type="attack",
        to_hit=5,
        damage="1",
        target_mode="single_enemy",
    )

    _dispatch_combat_event(
        rng=rng,
        event="after_action",
        trigger_actor=attacker,
        trigger_target=ally_target,
        trigger_action=trigger_action,
        actors=actors,
        round_number=1,
        turn_token="1:attacker",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    assert attacker.hp < attacker.max_hp
    assert reactor.reaction_available is False
    assert any(
        row.get("handler") == "feature_hook:reaction_attack"
        and row.get("result") == "executed"
        and row.get("hook_source") == "subclass"
        for row in trace
    )


def test_chr03_dispatch_reports_invalid_hook_trigger_and_skips() -> None:
    rng = random.Random(99)
    attacker = _base_actor(actor_id="attacker", team="enemy")
    ally_target = _base_actor(actor_id="ally_target", team="party")
    reactor = _base_actor(actor_id="reactor", team="party")
    reactor.actions = [
        ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=100,
            damage="1",
            target_mode="single_enemy",
        )
    ]
    reactor.traits = {
        "bad_hook_trait": {
            "name": "Bad Hook Trait",
            "type": "feat",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "unknown_trigger_name",
                }
            ],
        }
    }

    actors = {
        attacker.actor_id: attacker,
        ally_target.actor_id: ally_target,
        reactor.actor_id: reactor,
    }
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    trace: list[dict[str, object]] = []
    trigger_action = ActionDefinition(
        name="enemy_slash",
        action_type="attack",
        to_hit=5,
        damage="1",
        target_mode="single_enemy",
    )

    _dispatch_combat_event(
        rng=rng,
        event="after_action",
        trigger_actor=attacker,
        trigger_target=ally_target,
        trigger_action=trigger_action,
        actors=actors,
        round_number=1,
        turn_token="1:attacker",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    assert attacker.hp == attacker.max_hp
    assert any(
        row.get("handler") == "feature_hook:reaction_attack"
        and row.get("result") == "skipped"
        and row.get("reason") == "invalid_hook_trigger"
        and row.get("hook_source") == "feat"
        for row in trace
    )


def test_chr03_runtime_normalization_keeps_source_type_and_priority() -> None:
    reactor = _base_actor(actor_id="reactor", team="party")
    reactor.traits = {
        "v_feat": {
            "name": "Feat Hook",
            "source_type": "feat",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
        "z_species": {
            "name": "Species Hook",
            "source_type": "species",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
        "y_background": {
            "name": "Background Hook",
            "source_type": "background",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
        "x_subclass": {
            "name": "Subclass Hook",
            "source_type": "subclass",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
        "w_class": {
            "name": "Class Hook",
            "source_type": "class",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        },
    }

    hooks = _build_feature_hook_registrations(reactor)

    assert [hook.source_type for hook in hooks] == [
        "feat",
        "species",
        "background",
        "subclass",
        "class",
    ]
