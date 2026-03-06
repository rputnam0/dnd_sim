from __future__ import annotations

import json
import random
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.engine_runtime import _execute_action
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload
from dnd_sim.models import ActionDefinition, ActorRuntimeState

REPO_ROOT = Path(__file__).resolve().parents[1]
SPELLS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "spells"
BATCH_SLUGS = (
    "animal_friendship",
    "animal_shapes",
    "animate_objects",
    "beast_bond",
    "command",
    "conjure_animals",
    "conjure_celestial",
    "conjure_elemental",
    "conjure_fey",
    "conjure_minor_elementals",
)
CONDITION_SLUGS = (
    "animal_friendship",
    "beast_bond",
    "command",
)
CONJURE_SLUGS = (
    "conjure_animals",
    "conjure_celestial",
    "conjure_elemental",
    "conjure_fey",
    "conjure_minor_elementals",
)


def _spell_payload(slug: str) -> dict[str, object]:
    payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _batch_payloads() -> list[dict[str, object]]:
    return [_spell_payload(slug) for slug in BATCH_SLUGS]


def _find_effects(payload: dict[str, object], effect_type: str) -> list[dict[str, object]]:
    mechanics = payload.get("mechanics")
    assert isinstance(mechanics, list)
    return [
        row
        for row in mechanics
        if isinstance(row, dict) and str(row.get("effect_type", "")).strip().lower() == effect_type
    ]


def _actor(actor_id: str, team: str, *, hp: int = 30, max_hp: int = 30) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=max_hp,
        hp=hp,
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


def _action_from_payload(payload: dict[str, object]) -> ActionDefinition:
    return ActionDefinition(
        name=str(payload["name"]),
        action_type=str(payload.get("action_type", "utility")),
        action_cost="action",
        target_mode=str(payload.get("target_mode", "self")),
        range_ft=payload.get("range_ft") if isinstance(payload.get("range_ft"), int) else None,
        concentration=bool(payload.get("concentration", False)),
        effects=[],
        mechanics=list(payload.get("mechanics", [])),
        tags=["spell"],
    )


def test_j1_a_batch_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_batch_payloads())
    blocked = [record.content_id for record in manifest.records if record.states.blocked]

    assert blocked == []


def test_j1_a_batch_uses_canonical_rows() -> None:
    for slug in BATCH_SLUGS:
        payload = _spell_payload(slug)
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{slug} mechanics must be a list"
        assert mechanics, f"{slug} mechanics must not be empty"
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{slug} has schema issues: {issues}"

    for slug in CONDITION_SLUGS:
        payload = _spell_payload(slug)
        assert _find_effects(payload, "apply_condition"), f"{slug} should apply a condition"

    animal_shapes = _spell_payload("animal_shapes")
    assert _find_effects(animal_shapes, "transform"), "animal_shapes should use transform"

    animate_objects = _spell_payload("animate_objects")
    assert _find_effects(animate_objects, "summon"), "animate_objects should summon objects"
    assert _find_effects(
        animate_objects, "command_allied"
    ), "animate_objects should expose allied-command mechanics"

    for slug in CONJURE_SLUGS:
        payload = _spell_payload(slug)
        assert _find_effects(payload, "conjure"), f"{slug} should use conjure mechanics"


def test_j1_a_conjure_animals_runtime_creates_concentration_linked_ally() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("conjure_animals"))

    _execute_action(
        rng=random.Random(7),
        actor=caster,
        action=action,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    conjured = next(
        actor for actor_id, actor in actors.items() if actor_id not in {"caster", "enemy"}
    )
    assert conjured.team == caster.team
    assert conjured.traits["summoned"]["concentration_linked"] is True
    assert "conjured" in conjured.conditions
    assert conjured.companion_owner_id == caster.actor_id


def test_j1_a_animate_objects_runtime_requires_command() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("animate_objects"))

    _execute_action(
        rng=random.Random(11),
        actor=caster,
        action=action,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    animated = next(
        actor for actor_id, actor in actors.items() if actor_id not in {"caster", "enemy"}
    )
    assert animated.requires_command is True
    assert animated.companion_owner_id == caster.actor_id
