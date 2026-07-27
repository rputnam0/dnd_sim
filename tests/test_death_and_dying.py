from __future__ import annotations

from dataclasses import asdict

import pytest

from dnd_sim.engine_runtime import (
    _enemies_defeated,
    _party_defeated,
    _team_metric_value,
    long_rest,
    short_rest,
)
from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import (
    advance_stable_recovery,
    apply_damage,
    resolve_death_save,
    stabilize_creature,
)


def _actor(
    *,
    uses_death_saves: bool = True,
    max_hp: int = 10,
    hp: int = 10,
    temp_hp: int = 0,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id="subject",
        team="party",
        name="Subject",
        max_hp=max_hp,
        hp=hp,
        temp_hp=temp_hp,
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
        uses_death_saves=uses_death_saves,
    )


def test_zero_hp_damage_without_mitigation_adds_one_failure() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=0)

    apply_damage(target, 1, "slashing")

    assert target.hp == 0
    assert target.death_failures == 1
    assert target.dead is False


def test_zero_hp_temp_hp_absorbs_damage_before_death_failures() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=5)

    apply_damage(target, 3, "slashing")

    assert target.hp == 0
    assert target.temp_hp == 2
    assert target.death_failures == 0
    assert target.dead is False


def test_stable_target_taking_damage_becomes_unstable() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=0)
    target.stable = True
    target.death_successes = 3

    apply_damage(target, 1, "piercing")

    assert target.stable is False
    assert target.death_successes == 0
    assert target.death_failures == 1
    assert target.dead is False


def test_critical_hit_at_zero_hp_adds_two_failures_when_damage_gets_through() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=1)

    apply_damage(target, 2, "bludgeoning", is_critical=True)

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.death_failures == 2
    assert target.dead is False


def test_instant_death_when_remaining_damage_from_zero_reaches_max_hp() -> None:
    target = _actor(max_hp=10, hp=4, temp_hp=0)

    apply_damage(target, 14, "necrotic")

    assert target.hp == 0
    assert target.dead is True


def test_instant_death_at_zero_hp_uses_remaining_damage_after_temp_hp() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=3)

    apply_damage(target, 13, "force")

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.dead is True


def test_wild_shape_like_overflow_does_not_false_trigger_instant_death() -> None:
    target = _actor(max_hp=12, hp=5, temp_hp=9)

    apply_damage(target, 20, "slashing")

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.dead is False


def test_zero_hp_disposition_is_resolved_when_damage_is_applied() -> None:
    no_saves = _actor(uses_death_saves=False)
    death_saves = _actor(uses_death_saves=True)

    apply_damage(no_saves, 10, "slashing")
    apply_damage(death_saves, 10, "slashing")

    assert no_saves.hp == 0
    assert no_saves.dead is True
    assert no_saves.death_failures == 3
    assert death_saves.hp == 0
    assert death_saves.dead is False
    assert {"unconscious", "incapacitated", "prone"} <= death_saves.conditions


@pytest.mark.parametrize("uses_death_saves", [False, True])
def test_massive_damage_kills_every_zero_hp_policy(uses_death_saves: bool) -> None:
    actor = _actor(uses_death_saves=uses_death_saves)

    apply_damage(actor, 20, "force")

    assert actor.hp == 0
    assert actor.dead is True


def test_third_success_stabilizes_and_resets_both_death_save_counters() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    actor.death_successes = 2
    actor.death_failures = 2

    class _Success:
        def randint(self, _low: int, _high: int) -> int:
            return 3 if _high == 4 else 10

    result = resolve_death_save(_Success(), actor)

    assert result.became_stable is True
    assert actor.stable is True
    assert actor.death_successes == 0
    assert actor.death_failures == 0
    assert actor.stable_recovery_hours_remaining == 3


def test_natural_twenty_resets_downed_lifecycle_for_a_future_drop() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    actor.was_downed = True
    actor.death_successes = 1
    actor.death_failures = 2

    class _NaturalTwenty:
        def randint(self, _low: int, _high: int) -> int:
            return 20

    result = resolve_death_save(_NaturalTwenty(), actor)

    assert result.regained_consciousness is True
    assert actor.hp == 1
    assert actor.was_downed is False
    assert actor.death_successes == 0
    assert actor.death_failures == 0


def test_no_save_actor_never_rolls_a_death_save() -> None:
    actor = _actor(uses_death_saves=False, hp=0)

    class _ForbiddenRng:
        def randint(self, _low: int, _high: int) -> int:
            raise AssertionError("no-save actor consumed death-save RNG")

    result = resolve_death_save(_ForbiddenRng(), actor)

    assert result.became_stable is False
    assert result.became_dead is True
    assert result.regained_consciousness is False


def test_long_rest_clears_transient_mortality_state_but_preserves_trial_count() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    actor.stable = True
    actor.was_downed = True
    actor.death_successes = 2
    actor.death_failures = 1
    actor.downed_count = 2

    long_rest(actor)

    assert actor.hp == actor.max_hp
    assert actor.stable is False
    assert actor.was_downed is False
    assert actor.death_successes == 0
    assert actor.death_failures == 0
    assert actor.downed_count == 2


def test_long_rest_does_not_resurrect_a_dead_actor() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    actor.dead = True
    actor.death_failures = 3
    before = asdict(actor)

    long_rest(actor)

    assert asdict(actor) == before


def test_short_rest_advances_stable_recovery_by_one_hour() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    stabilize_creature(actor, recovery_hours=1)

    short_rest(actor)

    assert actor.hp == 1
    assert actor.stable is False
    assert actor.stable_recovery_hours_remaining is None


def test_team_defeat_evaluation_is_pure() -> None:
    actor = _actor(uses_death_saves=False, hp=0)
    before = asdict(actor)

    assert _party_defeated({actor.actor_id: actor}) is True
    assert _party_defeated({actor.actor_id: actor}) is True
    assert asdict(actor) == before


def test_stable_knockout_is_alive_but_not_conscious_or_active() -> None:
    actor = _actor(uses_death_saves=False, hp=0)
    actor.team = "enemy"
    actor.stable = True
    actor.update_manual_conditions({"unconscious", "incapacitated", "prone"})

    assert _team_metric_value([actor], "alive_count") == 1
    assert _team_metric_value([actor], "conscious_count") == 0
    assert _team_metric_value([actor], "active_count") == 0
    assert _team_metric_value([actor], "downed_count") == 1
    assert _team_metric_value([actor], "dead_count") == 0


def test_default_enemy_defeat_neutralizes_knockouts_but_explicit_all_dead_does_not() -> None:
    actor = _actor(uses_death_saves=False, hp=0)
    actor.team = "enemy"
    actor.stable = True
    actor.update_manual_conditions({"unconscious", "incapacitated", "prone"})
    actors = {actor.actor_id: actor}

    assert _enemies_defeated(actors) is True
    assert _enemies_defeated(actors, "all_unconscious_or_dead") is True
    assert _enemies_defeated(actors, "all_dead") is False


def test_positive_hp_unconscious_creature_is_not_conscious_or_active() -> None:
    actor = _actor(uses_death_saves=True, hp=5)
    actor.update_manual_conditions({"unconscious", "incapacitated"})

    assert _team_metric_value([actor], "alive_count") == 1
    assert _team_metric_value([actor], "conscious_count") == 0
    assert _team_metric_value([actor], "active_count") == 0
    assert _party_defeated({actor.actor_id: actor}, "all_unconscious_or_dead") is True
    assert _party_defeated({actor.actor_id: actor}, "all_downed") is False


def test_stabilize_creature_resets_counters_and_schedules_recovery() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    actor.death_successes = 2
    actor.death_failures = 2
    actor.update_manual_conditions({"unconscious", "incapacitated", "prone"})

    assert stabilize_creature(actor, recovery_hours=3) is True
    assert actor.stable is True
    assert actor.death_successes == 0
    assert actor.death_failures == 0
    assert actor.stable_recovery_hours_remaining == 3

    assert advance_stable_recovery(actor, hours=2) is False
    assert actor.hp == 0
    assert actor.stable_recovery_hours_remaining == 1

    assert advance_stable_recovery(actor, hours=1) is True
    assert actor.hp == 1
    assert actor.stable is False
    assert actor.was_downed is False
    assert actor.stable_recovery_hours_remaining is None
    assert "unconscious" not in actor.conditions
    assert "incapacitated" not in actor.conditions
    assert "prone" in actor.conditions


def test_damage_to_stable_creature_cancels_recovery_and_causes_failure() -> None:
    actor = _actor(uses_death_saves=True, hp=0)
    stabilize_creature(actor, recovery_hours=4)

    apply_damage(actor, 1, "piercing")

    assert actor.stable is False
    assert actor.stable_recovery_hours_remaining is None
    assert actor.death_successes == 0
    assert actor.death_failures == 1


@pytest.mark.parametrize(
    "actor",
    [
        _actor(uses_death_saves=True, hp=1),
        _actor(uses_death_saves=False, hp=0),
    ],
)
def test_stabilization_rejects_inapplicable_targets(actor: ActorRuntimeState) -> None:
    assert stabilize_creature(actor, recovery_hours=1) is False
