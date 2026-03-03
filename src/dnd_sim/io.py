from __future__ import annotations

import csv
import importlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from dnd_sim.characters import (
    validate_class_level_representation,
    validate_multiclass_prerequisites,
)
from dnd_sim.strategy_api import BaseStrategy, validate_strategy_instance

_FEATURE_SOURCE_TYPE_MAP = {
    "feat": "feat",
    "racial_trait": "species",
    "species_trait": "species",
    "background_feature": "background",
    "subclass_feature": "subclass",
    "class_feature": "class",
}


class ActionConfig(BaseModel):
    name: str
    action_type: Literal["attack", "save", "utility"] = "attack"
    attack_profile_id: str | None = None
    weapon_id: str | None = None
    item_id: str | None = None
    weapon_properties: list[str] = Field(default_factory=list)
    to_hit: int | None = None
    damage: str | None = None
    damage_type: str = "bludgeoning"
    attack_count: int = 1
    save_dc: int | None = None
    save_ability: str | None = None
    half_on_save: bool = False
    resource_cost: dict[str, int] = Field(default_factory=dict)
    recharge: str | None = None
    max_uses: int | None = None
    action_cost: Literal["action", "bonus", "reaction", "legendary", "lair"] = "action"
    event_trigger: str | None = None
    trigger_duration_rounds: int | None = None
    trigger_limit_per_turn: int | None = None
    trigger_once_per_round: bool = False
    target_mode: Literal[
        "single_enemy",
        "single_ally",
        "self",
        "all_enemies",
        "all_allies",
        "all_creatures",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    ] = "single_enemy"
    reach_ft: int | None = None
    range_ft: int | None = None
    range_normal_ft: int | None = None
    range_long_ft: int | None = None
    aoe_type: str | None = None
    aoe_size_ft: int | None = None
    max_targets: int | None = None
    concentration: bool = False
    include_self: bool = False
    effects: list["EffectConfig"] = Field(default_factory=list)
    mechanics: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("max_targets")
    @classmethod
    def validate_max_targets(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("max_targets must be >= 1")
        return value

    @field_validator("trigger_duration_rounds", "trigger_limit_per_turn")
    @classmethod
    def validate_positive_trigger_limits(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("trigger limits must be >= 1")
        return value

    @field_validator("save_ability")
    @classmethod
    def normalize_save_ability(cls, value: str | None) -> str | None:
        return value.lower() if isinstance(value, str) else value

    @field_validator("weapon_properties", mode="before")
    @classmethod
    def normalize_weapon_properties(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = value
        else:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = str(candidate).strip().lower().replace("-", "_").replace(" ", "_")
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized


class DamageEffectConfig(BaseModel):
    effect_type: Literal["damage"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    damage: str
    damage_type: str = "bludgeoning"


class HealEffectConfig(BaseModel):
    effect_type: Literal["heal"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "source"
    amount: str


class TempHPEffectConfig(BaseModel):
    effect_type: Literal["temp_hp"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "source"
    amount: str


class ApplyConditionEffectConfig(BaseModel):
    effect_type: Literal["apply_condition"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    condition: str
    duration_rounds: int | None = None
    save_dc: int | None = None
    save_ability: str | None = None


class RemoveConditionEffectConfig(BaseModel):
    effect_type: Literal["remove_condition"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    condition: str


class ResourceChangeEffectConfig(BaseModel):
    effect_type: Literal["resource_change"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    resource: str
    amount: int
    min_value: int = 0


class NextAttackAdvantageEffectConfig(BaseModel):
    effect_type: Literal["next_attack_advantage"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"


class NextAttackDisadvantageEffectConfig(BaseModel):
    effect_type: Literal["next_attack_disadvantage"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"


class ForcedMovementEffectConfig(BaseModel):
    effect_type: Literal["forced_movement"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    distance_ft: int
    direction: Literal["away_from_source", "toward_source", "custom"] = "away_from_source"


class NoteEffectConfig(BaseModel):
    effect_type: Literal["note"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    text: str


EffectConfig = Annotated[
    DamageEffectConfig
    | HealEffectConfig
    | TempHPEffectConfig
    | ApplyConditionEffectConfig
    | RemoveConditionEffectConfig
    | ResourceChangeEffectConfig
    | NextAttackAdvantageEffectConfig
    | NextAttackDisadvantageEffectConfig
    | ForcedMovementEffectConfig
    | NoteEffectConfig,
    Field(discriminator="effect_type"),
]


class EnemyIdentityConfig(BaseModel):
    enemy_id: str
    name: str
    team: str = "enemy"


class EnemyStatBlockConfig(BaseModel):
    max_hp: int
    ac: int
    speed_ft: int = 30
    initiative_mod: int = 0
    str_mod: int | None = None
    dex_mod: int = 0
    con_mod: int = 0
    int_mod: int | None = None
    wis_mod: int | None = None
    cha_mod: int | None = None
    save_mods: dict[str, int] = Field(default_factory=dict)


class EnemyConfig(BaseModel):
    identity: EnemyIdentityConfig
    stat_block: EnemyStatBlockConfig
    actions: list[ActionConfig]
    bonus_actions: list[ActionConfig] = Field(default_factory=list)
    reactions: list[ActionConfig] = Field(default_factory=list)
    legendary_actions: list[ActionConfig] = Field(default_factory=list)
    lair_actions: list[ActionConfig] = Field(default_factory=list)
    resources: dict[str, int] = Field(default_factory=dict)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    script_hooks: dict[str, Any] = Field(default_factory=dict)
    traits: list[str] = Field(default_factory=list)


class StrategyModuleConfig(BaseModel):
    name: str
    source: Literal["builtin", "encounter"]
    class_name: str
    module: str | None = None


class CustomSimulationConfig(BaseModel):
    source: Literal["builtin", "encounter"] = "encounter"
    module: str
    callable: str = "run_custom_simulation"


class EncounterConfig(BaseModel):
    enemies: list[str] = Field(default_factory=list)
    short_rest_after: bool = False
    branches: dict[str, int] = Field(default_factory=dict)
    checkpoint: str | None = None

    @field_validator("branches")
    @classmethod
    def validate_branches(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, target_index in value.items():
            idx = int(target_index)
            if idx < 0:
                raise ValueError("Encounter branch target index must be >= 0")
            normalized[str(key)] = idx
        return normalized


class ScenarioConfig(BaseModel):
    scenario_id: str
    encounter_id: str
    ruleset: str
    character_db_dir: str
    party: list[str]
    enemies: list[str] = Field(default_factory=list)
    encounters: list[EncounterConfig] = Field(default_factory=list)
    initiative_mode: Literal["individual", "grouped"] = "individual"
    battlefield: dict[str, Any] = Field(default_factory=dict)
    exploration: dict[str, Any] = Field(default_factory=dict)
    termination_rules: dict[str, Any]
    strategy_modules: list[StrategyModuleConfig]
    resource_policy: dict[str, Any] = Field(default_factory=dict)
    assumption_overrides: dict[str, Any] = Field(default_factory=dict)
    custom_simulation: CustomSimulationConfig | None = None

    @field_validator("ruleset")
    @classmethod
    def validate_ruleset(cls, value: str) -> str:
        if value != "5e-2014":
            raise ValueError("ruleset must be '5e-2014'")
        return value

    @field_validator("encounters")
    @classmethod
    def validate_encounter_branch_targets(
        cls, encounters: list[EncounterConfig]
    ) -> list[EncounterConfig]:
        encounter_count = len(encounters)
        for encounter_index, encounter in enumerate(encounters):
            branches = encounter.branches if isinstance(encounter.branches, dict) else {}
            for branch_key, target_index in branches.items():
                if target_index >= encounter_count:
                    raise ValueError(
                        "Encounter branch target index out of bounds: "
                        f"encounter {encounter_index} branch '{branch_key}' -> {target_index}, "
                        f"max allowed {encounter_count - 1}"
                    )
        return encounters


class LoadedScenario(BaseModel):
    scenario_path: str
    config: ScenarioConfig
    enemies: dict[str, EnemyConfig]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenario(scenario_path: Path) -> LoadedScenario:
    raw = _load_json(scenario_path)
    try:
        scenario = ScenarioConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid scenario schema at {scenario_path}: {exc}") from exc

    enemies: dict[str, EnemyConfig] = {}
    enemy_dir = scenario_path.parent.parent / "enemies"

    # Normalize single encounter into the campaign array if used
    if scenario.enemies and not scenario.encounters:
        scenario.encounters.append(EncounterConfig(enemies=scenario.enemies))

    all_enemy_ids = set()
    for enc in scenario.encounters:
        all_enemy_ids.update(enc.enemies)

    from .db import execute_query

    for enemy_id in all_enemy_ids:
        # 1. Check local file first (for tests running via tmp_path or local overrides)
        path = enemy_dir / f"{enemy_id}.json"

        enemy_payload = None
        if path.exists():
            enemy_payload = _load_json(path)
        else:
            # 2. Fallback to SQLite Database for built-ins
            rows = execute_query("SELECT data_json FROM enemies WHERE enemy_id = ?", (enemy_id,))
            if rows:
                enemy_payload = json.loads(rows[0]["data_json"])
            else:
                raise ValueError(f"Enemy definition not found on disk or SQLite DB: {enemy_id}")

        try:
            enemy = EnemyConfig.model_validate(enemy_payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid enemy schema for {enemy_id}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON blob for {enemy_id}: {exc}") from exc

        enemies[enemy_id] = enemy

    return LoadedScenario(
        scenario_path=str(scenario_path),
        config=scenario,
        enemies=enemies,
    )


def load_character_db(db_dir: Path) -> dict[str, dict[str, Any]]:
    from .db import execute_query

    out: dict[str, dict[str, Any]] = {}

    def _normalize_character_progression(
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        class_level_text = str(payload.get("class_level", "") or "")
        class_levels_payload = payload.get("class_levels")
        progression = validate_class_level_representation(
            class_level_text=class_level_text,
            class_levels=class_levels_payload if isinstance(class_levels_payload, dict) else None,
        )
        payload["class_level"] = progression.class_level_text
        payload["class_levels"] = progression.class_levels
        payload["character_level"] = progression.total_level
        prereq_errors = validate_multiclass_prerequisites(
            class_levels=progression.class_levels,
            ability_scores=payload.get("ability_scores") if isinstance(payload, dict) else {},
        )
        if prereq_errors:
            payload["multiclass_prerequisite_errors"] = prereq_errors
        return payload

    # 1. Base load from SQLite
    rows = execute_query("SELECT character_id, data_json FROM characters")
    for row in rows:
        try:
            payload = json.loads(row["data_json"])
            if isinstance(payload, dict):
                out[row["character_id"]] = _normalize_character_progression(
                    payload=payload,
                )
        except json.JSONDecodeError:
            pass
        except ValueError:
            # Keep loading when a persisted SQLite row has malformed class progression data.
            pass

    # 2. Local overriding from db_dir (crucial for pytests using tmp_path configurations)
    index_path = db_dir / "index.json"
    if index_path.exists():
        index = _load_json(index_path)
        for row in index.get("characters", []):
            character_id = row["character_id"]
            character_path = db_dir / f"{character_id}.json"
            if character_path.exists():
                payload = _load_json(character_path)
                try:
                    out[character_id] = _normalize_character_progression(
                        payload=payload,
                    )
                except ValueError as exc:
                    raise ValueError(f"invalid class_level for {character_id}: {exc}") from exc

    return out


def _normalize_trait_source_type(raw_type: Any) -> str:
    key = str(raw_type or "").strip().lower()
    if key in {"feat", "species", "background", "subclass", "class", "other"}:
        return key
    return _FEATURE_SOURCE_TYPE_MAP.get(key, "other")


def _normalize_trait_mechanics(raw_mechanics: Any) -> list[Any]:
    if not isinstance(raw_mechanics, list):
        return []

    normalized: list[Any] = []
    for mechanic in raw_mechanics:
        if not isinstance(mechanic, dict):
            normalized.append(mechanic)
            continue

        payload = dict(mechanic)
        effect_type = payload.get("effect_type")
        if not isinstance(effect_type, str) or not effect_type.strip():
            alias = payload.get("type")
            if isinstance(alias, str) and alias.strip():
                payload["effect_type"] = alias.strip().lower()
        else:
            payload["effect_type"] = effect_type.strip().lower()

        trigger = payload.get("trigger")
        if not isinstance(trigger, str) or not trigger.strip():
            alias = payload.get("event_trigger")
            if isinstance(alias, str) and alias.strip():
                payload["trigger"] = alias.strip().lower()
        else:
            payload["trigger"] = trigger.strip().lower()
        normalized.append(payload)
    return normalized


def _normalize_trait_payload(trait_data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(trait_data)
    payload["source_type"] = _normalize_trait_source_type(
        payload.get("source_type", payload.get("type"))
    )
    payload["mechanics"] = _normalize_trait_mechanics(payload.get("mechanics"))
    return payload


def load_traits_db(traits_dir: Path) -> dict[str, dict[str, Any]]:
    from .db import execute_query

    out: dict[str, dict[str, Any]] = {}

    # 1. Base SQLite load
    rows = execute_query("SELECT id, data_json FROM traits")
    for row in rows:
        try:
            trait_data = json.loads(row["data_json"])
            trait_name = trait_data.get("name", "").lower()
            if trait_name:
                out[trait_name] = _normalize_trait_payload(trait_data)
        except json.JSONDecodeError:
            pass

    # 2. Local Path Load overriding
    if traits_dir.exists():
        for path in traits_dir.glob("*.json"):
            trait_data = _load_json(path)
            trait_name = trait_data.get("name", "").lower()
            if trait_name:
                out[trait_name] = _normalize_trait_payload(trait_data)

    return out


def _import_encounter_strategy(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load strategy module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_strategy_registry(
    scenario: LoadedScenario,
) -> dict[str, BaseStrategy]:
    scenario_path = Path(scenario.scenario_path)
    strategy_dir = scenario_path.parent.parent / "strategies"

    registry: dict[str, BaseStrategy] = {}
    default_module = importlib.import_module("dnd_sim.strategies.defaults")
    default_classes = {
        "focus_fire_lowest_hp": "FocusFireLowestHPStrategy",
        "boss_highest_threat_target": "BossHighestThreatTargetStrategy",
        "conserve_resources_then_burst": "ConserveResourcesThenBurstStrategy",
        "always_use_signature_ability_if_ready": "AlwaysUseSignatureAbilityStrategy",
        "optimal_expected_damage": "OptimalExpectedDamageStrategy",
        "pack_tactics": "PackTacticsStrategy",
        "healer": "HealerStrategy",
        "skirmisher": "SkirmisherStrategy",
    }
    for name, class_name in default_classes.items():
        cls = getattr(default_module, class_name)
        instance = cls()
        validate_strategy_instance(instance)
        registry[name] = instance

    for cfg in scenario.config.strategy_modules:
        if cfg.source == "builtin":
            module_name = cfg.module or "dnd_sim.strategies.defaults"
            module = importlib.import_module(module_name)
        else:
            if not cfg.module:
                raise ValueError(
                    f"Strategy module name is required for encounter strategy: {cfg.name}"
                )
            module_path = strategy_dir / f"{cfg.module}.py"
            if not module_path.exists():
                raise ValueError(f"Strategy module file not found: {module_path}")
            module = _import_encounter_strategy(cfg.module, module_path)

        cls = getattr(module, cfg.class_name, None)
        if cls is None:
            raise ValueError(
                f"Strategy class {cfg.class_name} not found in module "
                f"{cfg.module or 'dnd_sim.strategies.defaults'}"
            )

        strategy = cls()
        validate_strategy_instance(strategy)
        registry[cfg.name] = strategy

    return registry


def load_custom_simulation_runner(scenario: LoadedScenario) -> Any | None:
    cfg = scenario.config.custom_simulation
    if cfg is None:
        return None

    scenario_path = Path(scenario.scenario_path)
    strategy_dir = scenario_path.parent.parent / "strategies"

    if cfg.source == "builtin":
        module = importlib.import_module(cfg.module)
    else:
        module_path = strategy_dir / f"{cfg.module}.py"
        if not module_path.exists():
            raise ValueError(f"Custom simulation module file not found: {module_path}")
        module = _import_encounter_strategy(cfg.module, module_path)

    runner = getattr(module, cfg.callable, None)
    if runner is None or not callable(runner):
        raise ValueError(
            f"Custom simulation callable '{cfg.callable}' not found in module '{cfg.module}'"
        )
    return runner


def default_results_dir() -> Path:
    """Canonical results root for all simulation outputs."""
    return Path(__file__).resolve().parents[2] / "river_line" / "results"


def _slugify_run_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "simulation_run"


def build_run_dir(base_out_dir: Path, scenario_id: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = base_out_dir / f"{stamp}_{_slugify_run_name(scenario_id)}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "plots").mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_trial_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame(rows)
        parquet_path = path.with_suffix(".parquet")
        df.to_parquet(parquet_path, index=False)
        return parquet_path
    except Exception:
        csv_path = path.with_suffix(".csv")
        if not rows:
            csv_path.write_text("", encoding="utf-8")
            return csv_path

        fieldnames = sorted(rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return csv_path


def load_summary(path: Path) -> dict[str, Any]:
    return _load_json(path)
