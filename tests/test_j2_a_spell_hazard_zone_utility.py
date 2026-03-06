from __future__ import annotations

import json
import random
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.engine_runtime import _apply_effect
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload
from dnd_sim.models import ActorRuntimeState
from dnd_sim.spatial import can_see

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_PATHS = {
    "spell:antimagic_field": SPELLS_DIR / "antimagic_field.json",
    "spell:arcanist_s_magic_aura": SPELLS_DIR / "arcanist’s_magic_aura.json",
    "spell:blade_barrier": SPELLS_DIR / "blade_barrier.json",
    "spell:blight": SPELLS_DIR / "blight.json",
    "spell:cloudkill": SPELLS_DIR / "cloudkill.json",
    "spell:continual_flame": SPELLS_DIR / "continual_flame.json",
    "spell:create_food_and_water": SPELLS_DIR / "create_food_and_water.json",
    "spell:create_or_destroy_water": SPELLS_DIR / "create_or_destroy_water.json",
    "spell:create_spelljamming_helm": SPELLS_DIR / "create_spelljamming_helm.json",
    "spell:darkness": SPELLS_DIR / "darkness.json",
}


def _load_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_owned_payloads() -> list[dict[str, object]]:
    return [_load_payload(path) for path in OWNED_SPELL_PATHS.values()]


def _find_effect(
    payload: dict[str, object],
    effect_type: str,
    *,
    predicate: object | None = None,
) -> dict[str, object]:
    mechanics = payload.get("mechanics", [])
    assert isinstance(mechanics, list)
    for row in mechanics:
        if not isinstance(row, dict):
            continue
        if row.get("effect_type") != effect_type:
            continue
        if predicate is None or predicate(row):
            return row
    raise AssertionError(f"missing {effect_type!r} mechanic in {payload.get('name')!r}")


def _runtime_actor(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
) -> ActorRuntimeState:
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


def _runtime_trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_j2_a_owned_spell_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_load_owned_payloads())
    by_id = {record.content_id: record for record in manifest.records}

    assert set(by_id) == set(OWNED_SPELL_PATHS)
    for content_id in OWNED_SPELL_PATHS:
        record = by_id[content_id]
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.schema_valid is True
        assert record.states.executable is True
        assert record.states.tested is True
        assert record.states.unsupported_reason is None


def test_j2_a_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_a_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    darkness = _load_payload(OWNED_SPELL_PATHS["spell:darkness"])
    darkness_hazard = _find_effect(darkness, "hazard")
    assert darkness_hazard["hazard_type"] == "magical_darkness"
    assert darkness_hazard["radius_ft"] == 15
    assert darkness_hazard["duration_rounds"] == 100
    assert darkness_hazard["obscures_vision"] is True

    continual_flame = _load_payload(OWNED_SPELL_PATHS["spell:continual_flame"])
    continual_flame_hazard = _find_effect(continual_flame, "hazard")
    assert continual_flame_hazard["hazard_type"] == "light"
    assert continual_flame_hazard["radius_ft"] == 20
    assert continual_flame_hazard["duration"] == "permanent"
    assert continual_flame_hazard["can_be_smothered"] is False

    create_food_and_water = _load_payload(OWNED_SPELL_PATHS["spell:create_food_and_water"])
    create_food_effect = _find_effect(create_food_and_water, "transform")
    assert create_food_effect["condition"] == "create_food_and_water_resolved"
    assert create_food_effect["food_lb"] == 45
    assert create_food_effect["water_gallons"] == 30
    assert create_food_effect["food_spoils_after_rounds"] == 14400

    antimagic_field = _load_payload(OWNED_SPELL_PATHS["spell:antimagic_field"])
    antimagic_hazard = _find_effect(antimagic_field, "hazard")
    assert antimagic_hazard["target"] == "source"
    assert antimagic_hazard["hazard_type"] == "antimagic_field"
    assert antimagic_hazard["radius_ft"] == 10
    assert antimagic_hazard["suppresses_magic"] is True

    arcanists_magic_aura = _load_payload(OWNED_SPELL_PATHS["spell:arcanist_s_magic_aura"])
    aura_transform = _find_effect(arcanists_magic_aura, "transform")
    assert aura_transform["condition"] == "arcanist_s_magic_aura"
    assert aura_transform["false_aura"] is True
    assert aura_transform["mask"] is True

    blade_barrier = _load_payload(OWNED_SPELL_PATHS["spell:blade_barrier"])
    barrier_hazard = _find_effect(blade_barrier, "hazard")
    assert barrier_hazard["difficult_terrain"] is True
    assert barrier_hazard["save_ability"] == "dex"
    assert barrier_hazard["on_enter"][0]["damage"] == "6d10"
    assert barrier_hazard["on_start_turn"][0]["damage_type"] == "slashing"

    blight = _load_payload(OWNED_SPELL_PATHS["spell:blight"])
    blight_damage = _find_effect(blight, "damage")
    assert blight_damage["damage"] == "8d8"
    assert blight_damage["damage_type"] == "necrotic"
    assert blight_damage["save_ability"] == "con"
    assert blight_damage["plant_targets_take_max_damage"] is True

    cloudkill = _load_payload(OWNED_SPELL_PATHS["spell:cloudkill"])
    cloudkill_hazard = _find_effect(cloudkill, "hazard")
    assert cloudkill_hazard["obscures_vision"] is True
    assert cloudkill_hazard["moves_away_from_source_ft"] == 10
    assert cloudkill_hazard["on_enter"][0]["damage"] == "5d8"
    assert cloudkill_hazard["on_start_turn"][0]["save_ability"] == "con"

    create_or_destroy_water = _load_payload(OWNED_SPELL_PATHS["spell:create_or_destroy_water"])
    create_water = _find_effect(
        create_or_destroy_water,
        "transform",
        predicate=lambda row: row.get("condition") == "create_water",
    )
    destroy_water = _find_effect(
        create_or_destroy_water,
        "transform",
        predicate=lambda row: row.get("condition") == "destroy_water",
    )
    assert create_water["extinguishes_unprotected_flames"] is True
    assert destroy_water["destroys_fog"] is True

    create_spelljamming_helm = _load_payload(OWNED_SPELL_PATHS["spell:create_spelljamming_helm"])
    helm_transform = _find_effect(create_spelljamming_helm, "transform")
    assert helm_transform["condition"] == "spelljamming_helm"
    assert helm_transform["duration"] == "permanent"
    assert helm_transform["max_target_size"] == "large"


def test_j2_a_darkness_and_antimagic_use_existing_runtime_shapes() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    ally = _runtime_actor(actor_id="ally", team="party")
    enemy = _runtime_actor(actor_id="enemy", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    ally.position = (5.0, 0.0, 0.0)
    enemy.position = (15.0, 0.0, 0.0)
    caster.concentrating = True
    caster.concentrated_spell = "hold_person"

    actors = {actor.actor_id: actor for actor in (caster, ally, enemy)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _runtime_trackers(
        caster, ally, enemy
    )
    active_hazards: list[dict[str, object]] = []

    antimagic_effect = dict(_find_effect(_load_payload(OWNED_SPELL_PATHS["spell:antimagic_field"]), "hazard"))
    _apply_effect(
        effect=antimagic_effect,
        rng=random.Random(7),
        actor=caster,
        target=caster,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    assert active_hazards
    assert active_hazards[0]["hazard_type"] == "antimagic_field"
    assert caster.concentrating is False
    assert "antimagic_suppressed" in caster.conditions

    darkness_effect = dict(_find_effect(_load_payload(OWNED_SPELL_PATHS["spell:darkness"]), "hazard"))
    darkness_effect["position"] = (5.0, 0.0, 0.0)
    darkness_effect["radius_ft"] = 15
    _apply_effect(
        effect=darkness_effect,
        rng=random.Random(8),
        actor=ally,
        target=enemy,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    darkness_hazard = next(
        zone for zone in active_hazards if zone.get("hazard_type") == "magical_darkness"
    )
    assert can_see(
        observer_pos=enemy.position,
        target_pos=caster.position,
        observer_traits={},
        target_conditions=set(caster.conditions),
        active_hazards=[darkness_hazard],
    ) is False
