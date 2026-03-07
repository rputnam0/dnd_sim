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
    "summon_draconic_spirit",
    "summon_dragon",
    "summon_elemental",
    "summon_fey",
    "summon_fiend",
    "summon_greater_demon",
    "summon_lesser_demons",
    "summon_shadowspawn",
    "summon_undead",
)
HOSTILE_SUMMON_SLUGS = (
    "summon_lesser_demons",
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


def test_j1_d_batch_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_batch_payloads())
    blocked = [record.content_id for record in manifest.records if record.states.blocked]

    assert blocked == []


def test_j1_d_batch_uses_canonical_summon_rows() -> None:
    for slug in BATCH_SLUGS:
        payload = _spell_payload(slug)
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{slug} mechanics must be a list"
        assert mechanics, f"{slug} mechanics must not be empty"
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{slug} has schema issues: {issues}"

        summon_effects = _find_effects(payload, "summon")
        assert summon_effects, f"{slug} should use summon mechanics"

        for effect in summon_effects:
            assert str(effect.get("name", "")).strip(), f"{slug} summon should name the creature"
            assert str(effect.get("controller", "")).strip().lower() == "source", (
                f"{slug} should link control to the caster"
            )
            assert "concentration_linked" in effect and effect["concentration_linked"] is True, (
                f"{slug} summon should be concentration-linked"
            )

        if slug in HOSTILE_SUMMON_SLUGS:
            assert any(
                str(effect.get("team", "")).strip().lower() == "enemy"
                for effect in summon_effects
            ), f"{slug} should keep the summon hostile"


def test_j1_d_summon_draconic_spirit_runtime_creates_concentration_linked_ally() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("summon_draconic_spirit"))

    _execute_action(
        rng=random.Random(5),
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

    summoned = next(
        actor for actor_id, actor in actors.items() if actor_id not in {"caster", "enemy"}
    )
    assert summoned.team == caster.team
    assert summoned.traits["summoned"]["concentration_linked"] is True
    assert "summoned" in summoned.conditions
    assert summoned.companion_owner_id == caster.actor_id


def test_j1_d_summon_lesser_demons_runtime_stays_hostile() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("summon_lesser_demons"))

    _execute_action(
        rng=random.Random(9),
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

    summoned = next(
        actor for actor_id, actor in actors.items() if actor_id not in {"caster", "enemy"}
    )
    assert summoned.team == "enemy"
    assert summoned.companion_owner_id == caster.actor_id
    assert summoned.allied_controller_id is None
    assert summoned.requires_command is False
