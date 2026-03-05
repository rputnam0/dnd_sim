from __future__ import annotations

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import (
    evaluate_war_caster_opportunity_window,
    run_concentration_check,
)


class FixedRng:
    def __init__(self, rolls: list[int]) -> None:
        self._rolls = list(rolls)

    def randint(self, _a: int, _b: int) -> int:
        if not self._rolls:
            raise AssertionError("No rolls remaining")
        return self._rolls.pop(0)


def _actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=14,
        initiative_mod=0,
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_war_caster_window_allows_one_action_single_target_spell() -> None:
    caster = _actor(actor_id="caster", team="party")
    caster.traits = {"war caster": {}}
    mover = _actor(actor_id="enemy", team="enemy")
    booming_blade = ActionDefinition(
        name="booming_blade",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell"],
    )

    result = evaluate_war_caster_opportunity_window(
        reactor=caster,
        trigger_actor=mover,
        trigger_distance_ft=5.0,
        reach_ft=5.0,
        mover_disengaged=False,
        forced_movement=False,
        reaction_spell=booming_blade,
    )

    assert result.allowed is True
    assert result.reason is None


def test_war_caster_window_rejects_disengage_and_forced_movement_triggers() -> None:
    caster = _actor(actor_id="caster", team="party")
    caster.traits = {"war caster": {}}
    mover = _actor(actor_id="enemy", team="enemy")
    shocking_grasp = ActionDefinition(
        name="shocking_grasp",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell"],
    )

    disengage_result = evaluate_war_caster_opportunity_window(
        reactor=caster,
        trigger_actor=mover,
        trigger_distance_ft=5.0,
        reach_ft=5.0,
        mover_disengaged=True,
        forced_movement=False,
        reaction_spell=shocking_grasp,
    )
    forced_result = evaluate_war_caster_opportunity_window(
        reactor=caster,
        trigger_actor=mover,
        trigger_distance_ft=5.0,
        reach_ft=5.0,
        mover_disengaged=False,
        forced_movement=True,
        reaction_spell=shocking_grasp,
    )

    assert disengage_result.allowed is False
    assert disengage_result.reason == "no_opportunity_trigger"
    assert forced_result.allowed is False
    assert forced_result.reason == "forced_movement"


def test_war_caster_window_rejects_illegal_spell_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    caster.traits = {"war caster": {}}
    mover = _actor(actor_id="enemy", team="enemy")
    thunderwave = ActionDefinition(
        name="thunderwave",
        action_type="save",
        action_cost="action",
        target_mode="all_enemies",
        tags=["spell"],
    )

    result = evaluate_war_caster_opportunity_window(
        reactor=caster,
        trigger_actor=mover,
        trigger_distance_ft=5.0,
        reach_ft=5.0,
        mover_disengaged=False,
        forced_movement=False,
        reaction_spell=thunderwave,
    )

    assert result.allowed is False
    assert result.reason == "illegal_spell_target"


def test_concentration_check_applies_war_caster_advantage() -> None:
    caster = _actor(actor_id="caster", team="party")
    caster.concentrating = True
    caster.traits = {"war_caster": {}}

    result = run_concentration_check(FixedRng([1, 20]), caster, damage_taken=10)

    assert result is True
    assert caster.concentrating is True
