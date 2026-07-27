from __future__ import annotations

import json
from pathlib import Path

import dnd_sim.engine_runtime as engine_runtime
import pytest
from dnd_sim import report as report_cli
from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.models import TrialResult
from dnd_sim.reporting import build_report_markdown
from dnd_sim.reporting_runtime import build_simulation_summary
from dnd_sim.replay import flatten_trial_result
from dnd_sim.strategy_api import BaseStrategy
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def _run_single_trial(
    scenario_path: Path,
    *,
    seed: int = 7,
    strategy_overrides: dict[str, object] | None = None,
) -> TrialResult:
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    registry.update(strategy_overrides or {})
    character_db = load_character_db(Path(loaded.config.character_db_dir))
    return run_simulation(
        loaded,
        character_db,
        {},
        registry,
        trials=1,
        seed=seed,
        run_id="terminal_outcome_regression",
    ).trial_results[0]


class _KnockoutStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        declaration = super().declare_turn(actor, state)
        if declaration is not None and declaration.action is not None:
            declaration.action.zero_hp_intent = "knock_out"
        return declaration


def _configure_encounters(scenario_path: Path, encounters: list[dict]) -> None:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["enemies"] = []
    scenario["encounters"] = encounters
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")


def _one_attack_character(*, hp: int, damage: str) -> dict:
    character = build_character(
        character_id="hero",
        name="Hero",
        max_hp=hp,
        ac=14,
        to_hit=100,
        damage=damage,
    )
    character["class_levels"] = {"fighter": 1}
    character["traits"] = []
    character["initiative_mod"] = 100
    return character


def _last_initiative_enemy(*, hp: int, damage: str) -> dict:
    enemy = build_enemy(
        enemy_id="npc",
        name="NPC",
        hp=hp,
        ac=10,
        to_hit=100,
        damage=damage,
    )
    enemy["stat_block"]["initiative_mod"] = -100
    return enemy


def test_enemy_death_save_policy_and_objective_control_zero_hp_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    death_save_actor_ids: list[str] = []

    def _record_death_save(_rng, actor):
        death_save_actor_ids.append(actor.actor_id)
        actor.death_successes += 1
        return None

    monkeypatch.setattr(engine_runtime, "resolve_death_save", _record_death_save)

    ordinary_enemy = _last_initiative_enemy(hp=10, damage="0")
    ordinary_path = _setup_env(
        tmp_path / "ordinary",
        party=[_one_attack_character(hp=20, damage="10")],
        enemies=[ordinary_enemy],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    ordinary_trial = _run_single_trial(ordinary_path)

    assert death_save_actor_ids == []
    assert ordinary_trial.winner == "party"
    assert ordinary_trial.outcome == "party_victory"
    assert ordinary_trial.termination_reason == "enemy_defeated"
    assert ordinary_trial.censored is False
    assert ordinary_trial.death_counts["npc"] == 1

    special_enemy = _last_initiative_enemy(hp=10, damage="0")
    special_enemy["uses_death_saves"] = True
    special_path = _setup_env(
        tmp_path / "special",
        party=[_one_attack_character(hp=20, damage="10")],
        enemies=[special_enemy],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    special_trial = _run_single_trial(special_path)

    assert death_save_actor_ids == []
    assert special_trial.winner == "party"
    assert special_trial.outcome == "party_victory"
    assert special_trial.termination_reason == "enemy_defeated"
    assert special_trial.censored is False
    assert special_trial.death_counts["npc"] == 0

    kill_objective = json.loads(special_path.read_text(encoding="utf-8"))
    kill_objective["termination_rules"]["enemy_defeat"] = "all_dead"
    special_path.write_text(json.dumps(kill_objective, indent=2), encoding="utf-8")
    kill_trial = _run_single_trial(special_path)

    assert death_save_actor_ids == ["npc"]
    assert kill_trial.winner == "draw"
    assert kill_trial.outcome == "timeout"
    assert kill_trial.termination_reason == "max_rounds"
    assert kill_trial.censored is True
    assert kill_trial.death_counts["npc"] == 0


def test_nonlethal_knockout_is_a_resolved_party_victory_with_distinct_metrics(
    tmp_path: Path,
) -> None:
    hero = _one_attack_character(hp=20, damage="10")
    hero["attacks"][0]["attack_delivery"] = "melee_weapon_attack"
    scenario_path = _setup_env(
        tmp_path,
        party=[hero],
        enemies=[_last_initiative_enemy(hp=10, damage="0")],
        assumption_overrides={
            "party_strategy": "knock_out",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["termination_rules"].pop("enemy_defeat")
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")

    trial = _run_single_trial(
        scenario_path,
        strategy_overrides={"knock_out": _KnockoutStrategy()},
    )

    assert trial.winner == "party"
    assert trial.outcome == "party_victory"
    assert trial.termination_reason == "enemy_defeated"
    assert trial.censored is False
    assert trial.downed_counts["npc"] == 1
    assert trial.death_counts["npc"] == 0
    assert trial.remaining_hp["npc"] == 0
    enemy_state = trial.state_snapshots[-1]["enemies"]["npc"]
    assert enemy_state["stable"] is True
    assert enemy_state["dead"] is False
    assert enemy_state["stable_recovery_hours_remaining"] in {1, 2, 3, 4}
    assert {"unconscious", "incapacitated", "prone"} <= set(enemy_state["conditions"])
    assert any(
        event.get("telemetry_type") == "knockout_resolution"
        and event.get("target_id") == "npc"
        and event.get("applied") is True
        for event in trial.telemetry
    )


def test_explicit_all_dead_objective_is_not_satisfied_by_knockout(tmp_path: Path) -> None:
    hero = _one_attack_character(hp=20, damage="10")
    hero["attacks"][0]["attack_delivery"] = "melee_weapon_attack"
    scenario_path = _setup_env(
        tmp_path,
        party=[hero],
        enemies=[_last_initiative_enemy(hp=10, damage="0")],
        assumption_overrides={
            "party_strategy": "knock_out",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["termination_rules"]["enemy_defeat"] = "all_dead"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")

    trial = _run_single_trial(
        scenario_path,
        strategy_overrides={"knock_out": _KnockoutStrategy()},
    )

    assert trial.winner == "draw"
    assert trial.outcome == "timeout"
    assert trial.termination_reason == "max_rounds"
    assert trial.censored is True
    assert trial.death_counts["npc"] == 0


def test_simultaneous_party_and_enemy_defeat_is_a_resolved_draw(tmp_path: Path) -> None:
    enemy = _last_initiative_enemy(hp=10, damage="0")
    enemy["stat_block"]["initiative_mod"] = 1000
    enemy["actions"] = [
        {
            "name": "self_destruct",
            "action_type": "save",
            "save_dc": 100,
            "save_ability": "dex",
            "half_on_save": False,
            "damage": "10",
            "damage_type": "force",
            "target_mode": "single_enemy",
            "effects": [
                {
                    "effect_type": "damage",
                    "apply_on": "always",
                    "target": "source",
                    "damage": "10",
                    "damage_type": "force",
                }
            ],
            "resource_cost": {},
        }
    ]
    scenario_path = _setup_env(
        tmp_path,
        party=[_one_attack_character(hp=10, damage="0")],
        enemies=[enemy],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )

    trial = _run_single_trial(scenario_path)

    assert trial.winner == "draw"
    assert trial.outcome == "draw"
    assert trial.termination_reason == "mutual_defeat"
    assert trial.censored is False
    assert trial.encounter_outcomes[-1]["outcome"] == "mutual_defeat"
    assert trial.encounter_outcomes[-1]["winner"] == "draw"


def test_max_rounds_is_censored_timeout_not_remaining_hp_tiebreak(tmp_path: Path) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[_one_attack_character(hp=10, damage="0")],
        enemies=[_last_initiative_enemy(hp=100, damage="0")],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )

    trial = _run_single_trial(scenario_path)

    assert trial.winner == "draw"
    assert trial.outcome == "timeout"
    assert trial.termination_reason == "max_rounds"
    assert trial.censored is True
    assert trial.encounter_outcomes == [
        {
            "encounter_index": 0,
            "encounter_step": 0,
            "outcome": "timeout",
            "winner": "draw",
            "termination_reason": "max_rounds",
            "censored": True,
            "branch_key": None,
            "next_encounter_index": None,
        }
    ]


def test_timeout_does_not_implicitly_advance_to_the_next_encounter(tmp_path: Path) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[_one_attack_character(hp=20, damage="10")],
        enemies=[
            _last_initiative_enemy(hp=100, damage="0")
            | {"identity": {"enemy_id": "stall", "name": "Stall", "team": "enemy"}},
            _last_initiative_enemy(hp=5, damage="0")
            | {"identity": {"enemy_id": "next", "name": "Next", "team": "enemy"}},
        ],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    _configure_encounters(
        scenario_path,
        [{"enemies": ["stall"]}, {"enemies": ["next"]}],
    )

    trial = _run_single_trial(scenario_path)

    assert trial.winner == "draw"
    assert trial.outcome == "timeout"
    assert trial.censored is True
    assert len(trial.encounter_outcomes) == 1
    assert trial.encounter_outcomes[0]["next_encounter_index"] is None


def test_explicit_timeout_branch_can_continue_to_a_resolved_encounter(
    tmp_path: Path,
) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[_one_attack_character(hp=20, damage="10")],
        enemies=[
            _last_initiative_enemy(hp=100, damage="0")
            | {"identity": {"enemy_id": "stall", "name": "Stall", "team": "enemy"}},
            _last_initiative_enemy(hp=5, damage="0")
            | {"identity": {"enemy_id": "next", "name": "Next", "team": "enemy"}},
        ],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    _configure_encounters(
        scenario_path,
        [
            {"enemies": ["stall"], "branches": {"timeout": 1}},
            {"enemies": ["next"]},
        ],
    )

    trial = _run_single_trial(scenario_path)

    assert trial.winner == "party"
    assert trial.outcome == "party_victory"
    assert trial.censored is False
    assert [outcome["outcome"] for outcome in trial.encounter_outcomes] == [
        "timeout",
        "enemy_defeat",
    ]
    assert trial.encounter_outcomes[0]["censored"] is True
    assert trial.encounter_outcomes[0]["branch_key"] == "timeout"
    assert trial.encounter_outcomes[1]["censored"] is False


def _trial(*, trial_index: int, winner: str, outcome: str, censored: bool = False) -> TrialResult:
    return TrialResult(
        trial_index=trial_index,
        rounds=2,
        winner=winner,
        damage_taken={"hero": 0, "npc": 0},
        damage_dealt={"hero": 0, "npc": 0},
        resources_spent={"hero": {}, "npc": {}},
        downed_counts={"hero": 0, "npc": 0},
        death_counts={"hero": 0, "npc": 0},
        remaining_hp={"hero": 10, "npc": 10},
        outcome=outcome,
        termination_reason="max_rounds" if censored else f"{winner}_result",
        censored=censored,
    )


def test_summary_and_report_separate_draws_timeouts_and_resolved_results() -> None:
    trial_results = [
        _trial(trial_index=0, winner="party", outcome="party_victory"),
        _trial(trial_index=1, winner="enemy", outcome="enemy_victory"),
        _trial(trial_index=2, winner="draw", outcome="draw"),
        _trial(trial_index=3, winner="draw", outcome="timeout", censored=True),
    ]

    summary = build_simulation_summary(
        run_id="outcomes",
        scenario_id="fixture",
        trials=4,
        trial_results=trial_results,
        tracked_resource_names={"hero": set(), "npc": set()},
    )

    assert summary.party_win_rate == 0.25
    assert summary.enemy_win_rate == 0.25
    assert summary.draw_rate == 0.25
    assert summary.timeout_rate == 0.25
    assert summary.censored_rate == 0.25
    assert summary.resolved_rate == 0.75

    report = build_report_markdown(
        summary=summary.to_dict(),
        run_config={"scenario_id": "fixture", "seed": 7},
        plot_paths={},
    )
    assert "- Draw rate: `0.250`" in report
    assert "- Timeout rate: `0.250`" in report
    assert "- Censored rate: `0.250`" in report
    assert "- Resolved rate: `0.750`" in report


def test_summary_rejects_a_trial_count_that_disagrees_with_results() -> None:
    with pytest.raises(ValueError, match=r"trials must equal len\(trial_results\)"):
        build_simulation_summary(
            run_id="bad_denominator",
            scenario_id="fixture",
            trials=2,
            trial_results=[_trial(trial_index=0, winner="party", outcome="party_victory")],
            tracked_resource_names={},
        )


@pytest.mark.parametrize(
    "trial",
    [
        _trial(trial_index=0, winner="party", outcome="unknown_result"),
        _trial(trial_index=0, winner="enemy", outcome="party_victory"),
        _trial(trial_index=0, winner="draw", outcome="timeout", censored=False),
        _trial(trial_index=0, winner="party", outcome="party_victory", censored=True),
    ],
)
def test_summary_rejects_unknown_or_contradictory_terminal_states(
    trial: TrialResult,
) -> None:
    with pytest.raises(ValueError, match="invalid terminal state"):
        build_simulation_summary(
            run_id="bad_terminal_state",
            scenario_id="fixture",
            trials=1,
            trial_results=[trial],
            tracked_resource_names={},
        )


def test_trial_row_round_trip_preserves_additive_outcome_fields() -> None:
    timeout = _trial(
        trial_index=0,
        winner="draw",
        outcome="timeout",
        censored=True,
    )

    row = flatten_trial_result(timeout)
    restored = report_cli._trial_result_from_row(row)
    restored_from_csv = report_cli._trial_result_from_row({**row, "censored": "True"})

    assert row["outcome"] == "timeout"
    assert row["termination_reason"] == "max_rounds"
    assert row["censored"] is True
    assert restored.outcome == "timeout"
    assert restored.termination_reason == "max_rounds"
    assert restored.censored is True
    assert restored_from_csv.censored is True
