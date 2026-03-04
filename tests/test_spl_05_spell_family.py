from __future__ import annotations

import random

from dnd_sim.engine import (
    _action_available,
    _build_spell_actions,
    _execute_action,
    _resolve_targets_for_action,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import TargetRef


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=2,
        str_mod=0,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
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


def test_build_spell_actions_adds_ritual_cast_variant_without_slot_cost() -> None:
    character = {
        "spells": [
            {
                "name": "detect_magic",
                "level": 1,
                "action_type": "utility",
                "target_mode": "self",
                "ritual": True,
                "casting_time": "1 action",
            }
        ],
        "resources": {"spell_slots": {"1": 1}},
    }

    actions = _build_spell_actions(character, character_level=5)
    by_name = {action.name: action for action in actions}

    assert "detect_magic" in by_name
    assert "detect_magic [Ritual]" in by_name
    assert by_name["detect_magic"].resource_cost == {"spell_slot_1": 1}
    assert by_name["detect_magic [Ritual]"].resource_cost == {}
    assert "ritual" in by_name["detect_magic [Ritual]"].tags
    assert "ritual_cast" in by_name["detect_magic [Ritual]"].tags


def test_ritual_cast_variant_is_unavailable_during_combat_turns() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_1": 1}

    ritual_spell = ActionDefinition(
        name="detect_magic [Ritual]",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        tags=["spell", "ritual", "ritual_cast"],
    )
    normal_spell = ActionDefinition(
        name="detect_magic",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )

    assert _action_available(caster, ritual_spell) is True
    assert _action_available(caster, ritual_spell, turn_token="1:caster") is False
    assert _action_available(caster, normal_spell, turn_token="1:caster") is True


def test_execute_action_blocks_ritual_cast_in_combat_but_allows_normal_spell() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_1": 1}
    target = _base_actor(actor_id="target", team="enemy")

    ritual_spell = ActionDefinition(
        name="binding_mark [Ritual]",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell", "ritual", "ritual_cast"],
        effects=[
            {"effect_type": "apply_condition", "condition": "ritual_marked", "target": "target"}
        ],
    )
    normal_spell = ActionDefinition(
        name="binding_mark",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        effects=[
            {"effect_type": "apply_condition", "condition": "combat_marked", "target": "target"}
        ],
    )

    actors = {a.actor_id: a for a in (caster, target)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(1),
        actor=caster,
        action=ritual_spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        round_number=1,
        turn_token="1:caster",
    )
    assert "ritual_marked" not in target.conditions

    _execute_action(
        rng=random.Random(2),
        actor=caster,
        action=normal_spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        round_number=1,
        turn_token="1:caster",
    )
    assert "combat_marked" in target.conditions


def test_dispel_magic_removes_non_concentration_spell_effect_on_success() -> None:
    rng = FixedRng([10])  # 10 + INT 4 => DC 14 success for a 4th-level effect.

    source = _base_actor(actor_id="source", team="enemy")
    source.resources = {"spell_slot_4": 1}
    dispeller = _base_actor(actor_id="dispeller", team="party")
    dispeller.int_mod = 4
    victim = _base_actor(actor_id="victim", team="party")

    binding_hex = ActionDefinition(
        name="binding_hex",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell", "spell_level:4"],
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "cursed",
                "target": "target",
                "duration_rounds": 10,
                "effect_id": "binding_hex",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {a.actor_id: a for a in (source, dispeller, victim)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, victim
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(2),
        actor=source,
        action=binding_hex,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "cursed" in victim.conditions

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_magic,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "cursed" not in victim.conditions


def test_antimagic_field_suppresses_spellcasting_and_breaks_concentration() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    hold_person = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "paralyzed", "target": "target"}],
    )
    antimagic_field = ActionDefinition(
        name="antimagic_field",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell", "antimagic"],
        effects=[
            {
                "effect_type": "antimagic_field",
                "target": "target",
                "radius_ft": 10,
                "duration_rounds": 10,
            }
        ],
    )
    followup_spell = ActionDefinition(
        name="arcane_mark",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "marked", "target": "target"}],
    )

    caster.position = (0.0, 0.0, 0.0)
    ally.position = (10.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, ally, enemy)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, ally, enemy)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=hold_person,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert caster.concentrating is True
    assert "paralyzed" in enemy.conditions

    _execute_action(
        rng=random.Random(4),
        actor=ally,
        action=antimagic_field,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.concentrating is False
    assert "paralyzed" not in enemy.conditions
    assert "antimagic_suppressed" in caster.conditions

    _execute_action(
        rng=random.Random(5),
        actor=caster,
        action=followup_spell,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "marked" not in enemy.conditions


def test_dispel_magic_respects_line_of_effect_total_cover() -> None:
    source = _base_actor(actor_id="source", team="enemy")
    dispeller = _base_actor(actor_id="dispeller", team="party")
    victim = _base_actor(actor_id="victim", team="party")
    source.position = (20.0, 0.0, 0.0)
    dispeller.position = (0.0, 0.0, 0.0)
    victim.position = (10.0, 0.0, 0.0)

    curse_spell = ActionDefinition(
        name="curse_mark",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "cursed", "target": "target"}],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    wall = AABB(min_pos=(4.0, -5.0, -5.0), max_pos=(6.0, 5.0, 5.0), cover_level="TOTAL")
    actors = {a.actor_id: a for a in (source, dispeller, victim)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, victim
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(6),
        actor=source,
        action=curse_spell,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "cursed" in victim.conditions

    resolved_targets = _resolve_targets_for_action(
        rng=random.Random(7),
        actor=dispeller,
        action=dispel_magic,
        actors=actors,
        requested=[TargetRef("victim")],
        obstacles=[wall],
    )
    assert resolved_targets == []


def test_dispel_magic_removes_spell_created_zone_at_target_location() -> None:
    rng = FixedRng([10])  # 10 + INT 4 => DC 14 success for a 4th-level zone.
    source = _base_actor(actor_id="source", team="enemy")
    source.int_mod = 3
    dispeller = _base_actor(actor_id="dispeller", team="party")
    dispeller.int_mod = 4
    victim = _base_actor(actor_id="victim", team="party")
    source.position = (20.0, 0.0, 0.0)
    dispeller.position = (0.0, 0.0, 0.0)
    victim.position = (10.0, 0.0, 0.0)

    zone_spell = ActionDefinition(
        name="freezing_mist",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell", "spell_level:4"],
        effects=[
            {
                "effect_type": "persistent_zone",
                "target": "target",
                "zone_type": "cloud",
                "radius_ft": 10,
                "duration_rounds": 10,
                "effect_id": "freezing_mist",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {a.actor_id: a for a in (source, dispeller, victim)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, victim
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(11),
        actor=source,
        action=zone_spell,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert len(active_hazards) == 1

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_magic,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert active_hazards == []


def test_dispel_magic_zone_path_syncs_concentration_using_zone_source_id() -> None:
    rng = FixedRng([10])  # 10 + INT 4 => DC 14 success for a 4th-level zone.
    source = _base_actor(actor_id="source", team="enemy")
    source.int_mod = 3
    dispeller = _base_actor(actor_id="dispeller", team="party")
    dispeller.int_mod = 4
    victim = _base_actor(actor_id="victim", team="party")
    source.position = (0.0, 0.0, 0.0)
    victim.position = (5.0, 0.0, 0.0)
    dispeller.position = (20.0, 0.0, 0.0)

    self_centered_zone = ActionDefinition(
        name="storm_aura",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        concentration=True,
        tags=["spell", "spell_level:4"],
        effects=[
            {
                "effect_type": "persistent_zone",
                "target": "target",
                "zone_type": "cloud",
                "radius_ft": 10,
                "duration_rounds": 10,
                "effect_id": "storm_aura",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {a.actor_id: a for a in (source, dispeller, victim)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, victim
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(15),
        actor=source,
        action=self_centered_zone,
        targets=[source],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert source.concentrating is True
    assert victim.actor_id not in source.concentrated_targets
    assert len(active_hazards) == 1
    # Simulate migrated/legacy zone payload that only carries source_id.
    active_hazards[0].pop("concentration_owner_id", None)

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_magic,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert active_hazards == []
    assert source.concentrating is False
    assert source.concentrated_spell is None
    assert source.concentrated_spell_level is None


def test_dispel_magic_only_removes_targeted_concentration_effect_not_whole_package() -> None:
    rng = FixedRng([20])  # Ensure dispel succeeds even for high-level effect.
    source = _base_actor(actor_id="source", team="enemy")
    source.int_mod = 3
    dispeller = _base_actor(actor_id="dispeller", team="party")
    ally_a = _base_actor(actor_id="ally_a", team="party")
    ally_b = _base_actor(actor_id="ally_b", team="party")

    twin_bind = ActionDefinition(
        name="twin_bind",
        action_type="utility",
        action_cost="action",
        target_mode="n_enemies",
        max_targets=2,
        concentration=True,
        tags=["spell", "spell_level:5"],
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "restrained",
                "target": "target",
                "duration_rounds": 10,
                "effect_id": "twin_bind",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {a.actor_id: a for a in (source, dispeller, ally_a, ally_b)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, ally_a, ally_b
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(12),
        actor=source,
        action=twin_bind,
        targets=[ally_a, ally_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert source.concentrating is True
    assert "restrained" in ally_a.conditions
    assert "restrained" in ally_b.conditions

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_magic,
        targets=[ally_a],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "restrained" not in ally_a.conditions
    assert "restrained" in ally_b.conditions
    assert source.concentrating is True


def test_dispel_magic_can_remove_casters_own_spell_effect() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    ward_spell = ActionDefinition(
        name="arcane_ward",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        tags=["spell", "spell_level:3"],
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "warded",
                "target": "target",
                "duration_rounds": 10,
                "effect_id": "arcane_ward",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {caster.actor_id: caster}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(13),
        actor=caster,
        action=ward_spell,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "warded" in caster.conditions

    _execute_action(
        rng=random.Random(14),
        actor=caster,
        action=dispel_magic,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "warded" not in caster.conditions
