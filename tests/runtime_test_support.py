from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.helpers import with_class_levels, write_json


def _setup_env(
    tmp_path: Path,
    *,
    party: list[dict],
    enemies: list[dict],
    assumption_overrides: dict,
    burst_threshold: int = 3,
    max_rounds: int = 30,
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    canonical_party: list[dict[str, Any]] = []
    for character in party:
        canonical_party.append(with_class_levels(character))

    index = {
        "characters": [
            {
                "character_id": character["character_id"],
                "name": character["name"],
                "class_levels": character["class_levels"],
                "source_pdf": "fixture.pdf",
            }
            for character in canonical_party
        ]
    }
    write_json(db_dir / "index.json", index)
    for character in canonical_party:
        write_json(db_dir / f"{character['character_id']}.json", character)

    encounter_dir = tmp_path / "encounters" / "fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    for enemy in enemies:
        write_json(enemy_dir / f"{enemy['identity']['enemy_id']}.json", enemy)

    scenario = {
        "scenario_id": "fixture_scenario",
        "encounter_id": "fixture",
        "ruleset": "5e-2014",
        "character_db_dir": "../../../db/characters",
        "party": [character["character_id"] for character in party],
        "enemies": [enemy["identity"]["enemy_id"] for enemy in enemies],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": max_rounds,
        },
        "internal_harness": {"strategy_modules": [
            {
                "name": "focus_fire_lowest_hp",
                "source": "builtin",
                "class_name": "FocusFireLowestHPStrategy",
            },
            {
                "name": "boss_highest_threat_target",
                "source": "builtin",
                "class_name": "BossHighestThreatTargetStrategy",
            },
            {
                "name": "conserve_resources_then_burst",
                "source": "builtin",
                "class_name": "ConserveResourcesThenBurstStrategy",
            },
            {
                "name": "always_use_signature_ability_if_ready",
                "source": "builtin",
                "class_name": "AlwaysUseSignatureAbilityStrategy",
            },
            ]
        },
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": burst_threshold,
        },
        "assumption_overrides": assumption_overrides,
    }

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path
