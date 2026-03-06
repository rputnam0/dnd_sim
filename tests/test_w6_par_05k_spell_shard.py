from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.engine_runtime import (
    _apply_condition,
    _apply_pending_smite_on_hit,
    _arm_pending_smite,
    _break_concentration,
    _tick_conditions_for_actor,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_FILES = (
    "blinding_smite.json",
    "searing_smite.json",
    "thunderous_smite.json",
    "wrathful_smite.json",
)


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, a: int, b: int) -> int:
        assert self._values, "No RNG values remaining"
        value = self._values.pop(0)
        assert a <= value <= b
        return value


def _load_owned_spell_payloads() -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for filename in OWNED_SPELL_FILES:
        payload = json.loads((SPELLS_DIR / filename).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


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


def _searing_smite_action() -> ActionDefinition:
    payload_by_name = {payload["name"]: payload for payload in _load_owned_spell_payloads()}
    searing = payload_by_name["Searing Smite"]
    mechanics = searing["mechanics"]
    assert isinstance(mechanics, list)
    return ActionDefinition(
        name="Searing Smite",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        include_self=True,
        concentration=True,
        save_dc=14,
        save_ability="con",
        mechanics=mechanics,
        tags=["spell", "smite_variant"],
    )


def test_w6_par_05k_owned_smite_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_load_owned_spell_payloads())
    by_id = {record.content_id: record for record in manifest.records}

    for content_id in {
        "spell:blinding_smite",
        "spell:searing_smite",
        "spell:thunderous_smite",
        "spell:wrathful_smite",
    }:
        record = by_id[content_id]
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.executable is True
        assert record.states.unsupported_reason is None


def test_w6_par_05k_searing_smite_burn_applies_without_on_hit_save() -> None:
    paladin = _actor("paladin", "party")
    paladin.pending_smite = None
    target = _actor("target", "enemy")
    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    _arm_pending_smite(paladin, _searing_smite_action())
    _apply_pending_smite_on_hit(
        rng=FixedRng([4]),
        actor=paladin,
        target=target,
        roll_crit=False,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    assert "burning" in target.conditions
    assert any(effect.condition == "burning" for effect in target.effect_instances)


def test_w6_par_05k_searing_smite_burn_deals_damage_on_failed_turn_start_save() -> None:
    paladin = _actor("paladin", "party")
    target = _actor("target", "enemy")
    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    _arm_pending_smite(paladin, _searing_smite_action())
    _apply_pending_smite_on_hit(
        rng=FixedRng([4]),
        actor=paladin,
        target=target,
        roll_crit=False,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    _tick_conditions_for_actor(
        FixedRng([1, 6]),
        target,
        boundary="turn_start",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 24
    assert damage_dealt[paladin.actor_id] == 6
    assert damage_taken[target.actor_id] == 6
    assert "burning" in target.conditions


def test_w6_par_05k_searing_smite_burn_breaks_target_concentration_cleanly() -> None:
    paladin = _actor("paladin", "party")
    target = _actor("target", "enemy")
    target.concentrating = True
    target.concentrated_spell = "Bless"
    target.concentrated_spell_level = 1

    bless_effect_ids = _apply_condition(
        target,
        "blessed",
        duration_rounds=10,
        source_actor_id=target.actor_id,
        target_actor_id=target.actor_id,
        effect_id="bless",
        concentration_linked=True,
        internal_tags={"spell_effect", "spell_level:1"},
    )
    target.concentration_effect_instance_ids.update(bless_effect_ids)
    target.concentrated_targets.add(target.actor_id)

    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    _arm_pending_smite(paladin, _searing_smite_action())
    _apply_pending_smite_on_hit(
        rng=FixedRng([4]),
        actor=paladin,
        target=target,
        roll_crit=False,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=[],
    )

    _tick_conditions_for_actor(
        FixedRng([1, 6, 1]),
        target,
        boundary="turn_start",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.concentrating is False
    assert target.concentrated_spell is None
    assert target.concentration_effect_instance_ids == set()
    assert "blessed" not in target.conditions
    assert all(effect.condition != "blessed" for effect in target.effect_instances)


def test_w6_par_05k_searing_smite_burn_tracks_caster_concentration() -> None:
    paladin = _actor("paladin", "party")
    paladin.concentrating = True
    paladin.concentrated_spell = "Searing Smite"
    paladin.concentrated_spell_level = 1
    target = _actor("target", "enemy")
    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _arm_pending_smite(paladin, _searing_smite_action())
    _apply_pending_smite_on_hit(
        rng=FixedRng([4]),
        actor=paladin,
        target=target,
        roll_crit=False,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    burn = next(effect for effect in target.effect_instances if effect.condition == "burning")
    assert paladin.concentrating is True
    assert burn.concentration_linked is True
    assert burn.source_actor_id == paladin.actor_id

    _break_concentration(paladin, actors, active_hazards)

    assert "burning" not in target.conditions
    assert all(effect.condition != "burning" for effect in target.effect_instances)
