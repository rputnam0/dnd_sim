from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import run_simulation
from dnd_sim.engine_runtime import (
    _build_actor_from_character,
    _build_actor_from_enemy,
    _build_construct_companion,
    _build_construct_companions,
)
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.io_models import EnemyConfig
from dnd_sim.replay import flatten_trial_result
from dnd_sim.rules_profiles import (
    DEFAULT_RULES_PROFILE_ID,
    DEFAULT_RULES_PROFILE_VERSION,
    load_supported_rules_profile,
)
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def _scenario_path(tmp_path: Path) -> Path:
    return _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 20, 14, 5, "1d6+2")],
        enemies=[build_enemy("guard", "Guard", 20, 14, 4, "1d6+1")],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )


def test_scenario_defaults_to_exact_canonical_rules_profile(tmp_path: Path) -> None:
    loaded = load_runtime_scenario(_scenario_path(tmp_path))

    assert loaded.config.rules_profile_id == DEFAULT_RULES_PROFILE_ID
    assert loaded.config.rules_profile_version == DEFAULT_RULES_PROFILE_VERSION
    assert loaded.rules_profile.profile_id == DEFAULT_RULES_PROFILE_ID
    assert loaded.rules_profile.profile_version == DEFAULT_RULES_PROFILE_VERSION


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("rules_profile_id", "missing_profile", "rules profile not found"),
        ("rules_profile_version", "9.9.9", "rules profile not found"),
    ],
)
def test_scenario_load_rejects_unknown_or_mismatched_rules_profile(
    tmp_path: Path,
    field_name: str,
    value: str,
    message: str,
) -> None:
    scenario_path = _scenario_path(tmp_path)
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload[field_name] = value
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_runtime_scenario(scenario_path)


def test_profile_drives_default_death_save_policy_with_explicit_actor_overrides() -> None:
    profile = load_supported_rules_profile()
    character = build_character("hero", "Hero", 20, 14, 5, "1d6+2")
    enemy_payload = build_enemy("guard", "Guard", 20, 14, 4, "1d6+1")

    player = _build_actor_from_character(character, traits_db={}, rules_profile=profile)
    monster = _build_actor_from_enemy(
        EnemyConfig.model_validate(enemy_payload),
        traits_db={},
        rules_profile=profile,
    )
    construct = _build_construct_companion(
        player,
        "steel_defender",
        rules_profile=profile,
    )

    assert player.uses_death_saves is True
    assert monster.uses_death_saves is False
    assert construct.uses_death_saves is False
    assert _build_construct_companions(player, rules_profile=profile) == []

    character["uses_death_saves"] = False
    enemy_payload["uses_death_saves"] = True
    overridden_player = _build_actor_from_character(
        character,
        traits_db={},
        rules_profile=profile,
    )
    overridden_monster = _build_actor_from_enemy(
        EnemyConfig.model_validate(enemy_payload),
        traits_db={},
        rules_profile=profile,
    )

    assert overridden_player.uses_death_saves is False
    assert overridden_monster.uses_death_saves is True


def test_trial_summary_and_flattened_replay_row_record_rules_profile(tmp_path: Path) -> None:
    loaded = load_runtime_scenario(_scenario_path(tmp_path))
    artifacts = run_simulation(
        loaded,
        load_character_db(Path(loaded.config.character_db_dir)),
        {},
        load_strategy_registry(loaded),
        trials=1,
        seed=11,
        run_id="rules_profile_trace",
    )

    trial = artifacts.trial_results[0]
    row = flatten_trial_result(trial)
    summary = artifacts.summary.to_dict()

    assert trial.rules_profile_id == DEFAULT_RULES_PROFILE_ID
    assert trial.rules_profile_version == DEFAULT_RULES_PROFILE_VERSION
    assert row["rules_profile_id"] == DEFAULT_RULES_PROFILE_ID
    assert row["rules_profile_version"] == DEFAULT_RULES_PROFILE_VERSION
    assert summary["rules_profile_id"] == DEFAULT_RULES_PROFILE_ID
    assert summary["rules_profile_version"] == DEFAULT_RULES_PROFILE_VERSION
