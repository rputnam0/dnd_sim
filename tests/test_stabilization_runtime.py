from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine_runtime import (
    _actor_state_snapshot,
    _apply_effect,
    _build_spell_actions,
    _execute_action,
    _get_standard_actions,
    _load_spell_definition,
    _resolve_targets_for_action,
    _run_exploration_leg,
)
from dnd_sim.io_models import ActionConfig
from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import stabilize_creature
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import TargetRef


def _actor(
    actor_id: str,
    *,
    hp: int,
    medicine: int = 0,
    creature_type: str = "humanoid",
    team: str = "party",
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ActorRuntimeState:
    actor = ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
        max_hp=10,
        hp=hp,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={},
        actions=[],
        skill_mods={"medicine": medicine},
        creature_type=creature_type,
        uses_death_saves=True,
        position=position,
    )
    if hp == 0:
        actor.update_manual_conditions({"unconscious", "incapacitated", "prone"})
        actor.was_downed = True
    return actor


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _low: int, _high: int) -> int:
        return self.values.pop(0)


def _trackers(*actors: ActorRuntimeState) -> tuple[dict, dict, dict, dict]:
    ids = [actor.actor_id for actor in actors]
    return (
        {actor_id: 0 for actor_id in ids},
        {actor_id: 0 for actor_id in ids},
        {actor_id: 0 for actor_id in ids},
        {actor_id: {} for actor_id in ids},
    )


def test_standard_stabilize_action_uses_dc_ten_medicine_check() -> None:
    healer = _actor("healer", hp=10, medicine=9)
    target = _actor("target", hp=0)
    action = next(action for action in _get_standard_actions() if action.name == "stabilize")
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(healer, target)

    _execute_action(
        rng=_SequenceRng([1, 3]),
        actor=healer,
        action=action,
        targets=[target],
        actors={healer.actor_id: healer, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is True
    assert target.stable_recovery_hours_remaining == 3
    snapshot = _actor_state_snapshot(target)
    assert {
        key: snapshot[key]
        for key in (
            "stable",
            "uses_death_saves",
            "death_successes",
            "death_failures",
            "stable_recovery_hours_remaining",
        )
    } == {
        "stable": True,
        "uses_death_saves": True,
        "death_successes": 0,
        "death_failures": 0,
        "stable_recovery_hours_remaining": 3,
    }


def test_failed_medicine_check_does_not_stabilize() -> None:
    healer = _actor("healer", hp=10, medicine=0)
    target = _actor("target", hp=0)
    action = next(action for action in _get_standard_actions() if action.name == "stabilize")
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(healer, target)

    _execute_action(
        rng=_SequenceRng([9]),
        actor=healer,
        action=action,
        targets=[target],
        actors={healer.actor_id: healer, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is False
    assert target.stable_recovery_hours_remaining is None


def test_standard_stabilize_can_target_an_unstable_creature_on_another_team() -> None:
    healer = _actor("healer", hp=10)
    target = _actor("target", hp=0, team="enemy")
    action = next(action for action in _get_standard_actions() if action.name == "stabilize")

    resolved = _resolve_targets_for_action(
        rng=_SequenceRng([]),
        actor=healer,
        action=action,
        actors={healer.actor_id: healer, target.actor_id: target},
        requested=[TargetRef(actor_id=target.actor_id)],
    )

    assert resolved == [target]


def test_standard_stabilize_cannot_reach_through_total_cover() -> None:
    healer = _actor("healer", hp=10)
    target = _actor("target", hp=0, position=(5.0, 0.0, 0.0))
    action = next(action for action in _get_standard_actions() if action.name == "stabilize")
    wall = AABB(
        min_pos=(2.0, -1.0, -1.0),
        max_pos=(3.0, 1.0, 1.0),
        cover_level="TOTAL",
    )

    resolved = _resolve_targets_for_action(
        rng=_SequenceRng([]),
        actor=healer,
        action=action,
        actors={healer.actor_id: healer, target.actor_id: target},
        requested=[TargetRef(actor_id=target.actor_id)],
        obstacles=[wall],
    )

    assert resolved == []


def test_stabilize_effect_models_spare_the_dying_without_a_check() -> None:
    caster = _actor("caster", hp=10)
    target = _actor("target", hp=0)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _apply_effect(
        effect={"effect_type": "stabilize", "target": "target"},
        rng=_SequenceRng([2]),
        actor=caster,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors={caster.actor_id: caster, target.actor_id: target},
        active_hazards=[],
    )

    assert target.stable is True
    assert target.stable_recovery_hours_remaining == 2


def test_stabilize_effect_skips_excluded_creature_type_without_rolling() -> None:
    caster = _actor("caster", hp=10)
    target = _actor("target", hp=0, creature_type="construct")
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _apply_effect(
        effect={
            "effect_type": "stabilize",
            "target": "target",
            "excluded_creature_types": ["undead", "construct"],
        },
        rng=_SequenceRng([]),
        actor=caster,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors={caster.actor_id: caster, target.actor_id: target},
        active_hazards=[],
    )

    assert target.stable is False
    assert target.stable_recovery_hours_remaining is None


def test_canonical_spare_the_dying_uses_typed_stabilization_semantics() -> None:
    spell_path = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "rules"
        / "2014"
        / "spells"
        / "spare_the_dying.json"
    )
    payload = json.loads(spell_path.read_text(encoding="utf-8"))
    action = ActionConfig.model_validate(
        {
            "name": payload["name"],
            "action_type": payload["action_type"],
            "target_mode": payload["target_mode"],
            "range_ft": payload["range_ft"],
            "mechanics": payload["mechanics"],
        }
    )

    assert action.action_type == "utility"
    assert action.target_mode == "single_creature"
    assert action.range_ft == 5
    assert action.mechanics == [
        {
            "effect_type": "stabilize",
            "target": "target",
            "apply_on": "always",
            "excluded_creature_types": ["undead", "construct"],
        }
    ]


def _canonical_spare_the_dying_action():
    spell = _load_spell_definition("Spare the Dying")
    assert spell is not None
    actions = _build_spell_actions(
        {
            "class_levels": {"cleric": 1},
            "spells": [spell],
            "resources": {"spell_slots": {}},
        },
        character_level=1,
    )
    return next(action for action in actions if action.name == "Spare the Dying")


def test_canonical_spare_the_dying_hydrates_and_stabilizes_living_zero_hp_target() -> None:
    caster = _actor("caster", hp=10)
    target = _actor("target", hp=0)
    action = _canonical_spare_the_dying_action()
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    rng = _SequenceRng([2])

    _execute_action(
        rng=rng,
        actor=caster,
        action=action,
        targets=[target],
        actors={caster.actor_id: caster, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is True
    assert target.stable_recovery_hours_remaining == 2
    assert rng.values == []


@pytest.mark.parametrize("creature_type", ["undead", "construct"])
def test_canonical_spare_the_dying_rejects_undead_and_construct_targets_without_rng(
    creature_type: str,
) -> None:
    caster = _actor("caster", hp=10)
    target = _actor("target", hp=0, creature_type=creature_type)
    action = _canonical_spare_the_dying_action()
    rng = _SequenceRng([])

    resolved = _resolve_targets_for_action(
        rng=rng,
        actor=caster,
        action=action,
        actors={caster.actor_id: caster, target.actor_id: target},
        requested=[TargetRef(actor_id=target.actor_id)],
    )

    assert resolved == []
    assert target.stable is False
    assert rng.values == []


def test_action_schema_rejects_malformed_stabilization_mechanic() -> None:
    with pytest.raises(ValueError, match="check_dc must be an integer"):
        ActionConfig.model_validate(
            {
                "name": "broken_stabilizer",
                "action_type": "utility",
                "target_mode": "single_creature",
                "mechanics": [
                    {
                        "effect_type": "stabilize",
                        "target": "target",
                        "check_skill": "medicine",
                        "check_dc": "ten",
                    }
                ],
            }
        )


def test_exploration_elapsed_hours_advance_stable_recovery() -> None:
    target = _actor("target", hp=0)
    stabilize_creature(target, recovery_hours=3)
    actors = {target.actor_id: target}
    damage_taken = {target.actor_id: 0}
    resources_spent = {target.actor_id: {}}

    _run_exploration_leg(
        rng=_SequenceRng([]),
        actors=actors,
        damage_taken=damage_taken,
        resources_spent=resources_spent,
        leg_config={"duration_hours": 2},
    )
    assert target.hp == 0
    assert target.stable_recovery_hours_remaining == 1

    _run_exploration_leg(
        rng=_SequenceRng([]),
        actors=actors,
        damage_taken=damage_taken,
        resources_spent=resources_spent,
        leg_config={"duration_hours": 1},
    )
    assert target.hp == 1
    assert target.stable is False
