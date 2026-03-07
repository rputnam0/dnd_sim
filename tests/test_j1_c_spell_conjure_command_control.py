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
    "enthrall",
    "find_familiar",
    "find_greater_steed",
    "geas",
    "instant_summons",
    "phantom_steed",
    "summon_aberration",
    "summon_beast",
    "summon_celestial",
    "summon_construct",
)
EXPECTED_EFFECT_TYPES = {
    "enthrall": {"apply_condition"},
    "find_familiar": {"summon"},
    "find_greater_steed": {"summon"},
    "geas": {"apply_condition"},
    "instant_summons": {"transform"},
    "phantom_steed": {"summon"},
    "summon_aberration": {"summon"},
    "summon_beast": {"summon"},
    "summon_celestial": {"summon"},
    "summon_construct": {"summon"},
}


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


def test_j1_c_batch_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_batch_payloads())
    blocked = [record.content_id for record in manifest.records if record.states.blocked]

    assert blocked == []


def test_j1_c_batch_uses_canonical_rows() -> None:
    for slug in BATCH_SLUGS:
        payload = _spell_payload(slug)
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{slug} mechanics must be a list"
        assert mechanics, f"{slug} mechanics must not be empty"
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{slug} has schema issues: {issues}"

        seen_effect_types = {
            str(row.get("effect_type", "")).strip().lower()
            for row in mechanics
            if isinstance(row, dict)
        }
        assert EXPECTED_EFFECT_TYPES[slug].issubset(seen_effect_types), (
            f"{slug} should include {EXPECTED_EFFECT_TYPES[slug]}"
        )

    enthrall_effect = _find_effects(_spell_payload("enthrall"), "apply_condition")[0]
    assert enthrall_effect["apply_on"] == "save_fail"
    assert enthrall_effect["condition"] == "enthralled"
    assert enthrall_effect["duration_rounds"] == 10

    geas = _spell_payload("geas")
    geas_effect = _find_effects(geas, "apply_condition")[0]
    assert geas["save_ability"] == "wis"
    assert geas_effect["apply_on"] == "save_fail"
    assert geas_effect["condition"] == "geased"
    assert geas_effect["duration_rounds"] == 432000

    summons = _find_effects(_spell_payload("instant_summons"), "transform")
    assert {effect["condition"] for effect in summons} == {
        "instant_summons_marked_item",
        "instant_summons_recall",
    }

    greater_steed = _find_effects(_spell_payload("find_greater_steed"), "summon")[0]
    assert greater_steed["controller"] == "source"
    assert greater_steed["mount"] is True

    phantom_steed = _find_effects(_spell_payload("phantom_steed"), "summon")[0]
    assert phantom_steed["mount"] is True
    assert phantom_steed["speed_ft"] == 100

    for slug in (
        "find_familiar",
        "summon_aberration",
        "summon_beast",
        "summon_celestial",
        "summon_construct",
    ):
        summon_effect = _find_effects(_spell_payload(slug), "summon")[0]
        assert summon_effect["controller"] == "source"
        assert summon_effect.get("requires_command", False) is False


def test_j1_c_find_greater_steed_runtime_creates_mount_ready_for_rider() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("find_greater_steed"))

    _execute_action(
        rng=random.Random(13),
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

    steed = next(actor for actor_id, actor in actors.items() if actor_id not in {"caster", "enemy"})
    assert steed.team == caster.team
    assert steed.mount_controller_id == caster.actor_id
    assert steed.mounted_rider_id is None
    assert steed.traits["summoned"]["mount"] is True
    assert steed.companion_owner_id == caster.actor_id


def test_j1_c_summon_beast_runtime_creates_concentration_linked_companion() -> None:
    caster = _actor("caster", "party")
    enemy = _actor("enemy", "enemy")
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    action = _action_from_payload(_spell_payload("summon_beast"))

    _execute_action(
        rng=random.Random(17),
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
    assert summoned.companion_owner_id == caster.actor_id
    assert summoned.requires_command is False
    assert summoned.actor_id in caster.concentrated_targets
