from __future__ import annotations

from pathlib import Path

from dnd_sim.io import load_character_db, load_custom_simulation_runner, load_scenario


def test_phase1_custom_sim_outputs_damage_metrics(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    scenario_path = (
        root / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)

    out = runner(
        scenario=loaded,
        character_db=db,
        trials=5,
        seed=1,
        run_dir=tmp_path / "run",
    )

    summary = out["summary"]
    assert "damage_dealt" in summary
    assert "damage_taken" in summary
    assert set(summary["damage_dealt"].keys()) == {"isak", "fury", "druid"}
    assert set(summary["damage_taken"].keys()) == {"isak", "fury", "druid"}
    assert "procedure_attempts" in summary
    assert "procedure_successes" in summary
    assert "death_probabilities" in summary
    assert "pylon_kill_rounds" in summary
    assert set(summary["pylon_kill_rounds"].keys()) == {"past", "present", "future"}


def test_phase1_custom_sim_accepts_breakpoint_threshold_overrides(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    scenario_path = (
        root / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
    )
    loaded = load_scenario(scenario_path)
    loaded.config.assumption_overrides["custom_sim"]["breakpoint_thresholds"] = [20, 0]
    db = load_character_db(Path(loaded.config.character_db_dir))
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)

    out = runner(
        scenario=loaded,
        character_db=db,
        trials=5,
        seed=2,
        run_dir=tmp_path / "run_bp",
    )

    summary = out["summary"]
    assert summary["breakpoint_thresholds"] == [20, 0]


def test_phase1_custom_sim_tracks_boss_phase1_metrics(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    scenario_path = (
        root / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)

    out = runner(
        scenario=loaded,
        character_db=db,
        trials=8,
        seed=7,
        run_dir=tmp_path / "run_boss",
    )

    summary = out["summary"]
    assert "boss_damage_dealt" in summary
    assert "boss_turns" in summary
    assert "boss_lair_turns" in summary
    assert summary["boss_turns"]["mean"] > 0
    assert set(summary["boss_action_usage"].keys()) == {
        "harpoon_winch",
        "guilt_fog",
        "boiler_vent",
        "time_shear",
        "slam",
    }
    assert set(summary["boss_lair_usage"].keys()) == {"undertow", "arc_flash", "phase_flicker"}
    assert set(summary["boss_legendary_usage"].keys()) == {
        "temporal_reversal",
        "winch_pull",
        "tail_tap",
    }


def test_phase1_custom_sim_allows_disabling_boss_phase1(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    scenario_path = (
        root / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
    )
    loaded = load_scenario(scenario_path)
    loaded.config.assumption_overrides["custom_sim"]["boss_phase_1"] = {"enabled": False}
    db = load_character_db(Path(loaded.config.character_db_dir))
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)

    out = runner(
        scenario=loaded,
        character_db=db,
        trials=8,
        seed=9,
        run_dir=tmp_path / "run_no_boss",
    )

    summary = out["summary"]
    assert summary["boss_turns"]["mean"] == 0
    assert summary["boss_lair_turns"]["mean"] == 0
    assert summary["boss_damage_dealt"]["isak"]["mean"] == 0
    assert summary["boss_damage_dealt"]["fury"]["mean"] == 0
    assert summary["boss_damage_dealt"]["druid"]["mean"] == 0
