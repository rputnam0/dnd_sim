from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dnd_sim.spells import lookup_spell_definition as _lookup_spell_definition

_RECHARGE_PATTERN = re.compile(
    r"^(?:recharge\s+)?(?P<low>[1-6])(?:\s*-\s*(?P<high>[1-6]))?$",
    flags=re.IGNORECASE,
)
_ATTACK_ACTION_SEQUENCE_EFFECT_TYPES = {"attack_sequence", "multiattack_sequence"}
_ATTACK_ACTION_REPLACEMENT_EFFECT_TYPES = {
    "attack_replacement",
    "replace_attack",
    "replacement_attack",
}


def _spell_root_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "rules" / "2014" / "spells"


def _is_known_spell_reference(name: str) -> bool:
    if not name.strip():
        return False
    return (
        _lookup_spell_definition(
            name,
            spells_dir=_spell_root_dir(),
            duplicate_policy="fail_fast",
        )
        is not None
    )


def _extract_action_reference_name(reference: Any) -> str | None:
    if isinstance(reference, str):
        name = reference.strip()
        return name or None
    if isinstance(reference, dict):
        name = str(reference.get("action_name") or reference.get("name") or "").strip()
        return name or None
    return None


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

    @field_validator("recharge", mode="before")
    @classmethod
    def normalize_recharge_spec(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.strip("()").replace("–", "-")
        text = re.sub(r"\s+", " ", text)
        match = _RECHARGE_PATTERN.fullmatch(text)
        if match is None:
            raise ValueError(
                "recharge must be one of: 'X-6', 'Recharge X-6', 'X', or 'Recharge X' (X=1..6)"
            )
        low = int(match.group("low"))
        high = int(match.group("high") or match.group("low"))
        if low > high:
            raise ValueError("recharge lower bound cannot exceed upper bound")
        return str(high) if low == high else f"{low}-{high}"

    @field_validator("mechanics", mode="before")
    @classmethod
    def validate_mechanics_payload(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("mechanics must be a list")

        normalized: list[dict[str, Any]] = []
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                raise ValueError(f"mechanics[{index}] must be an object")
            effect_type = str(row.get("effect_type", "")).strip().lower()
            if not effect_type:
                raise ValueError(f"mechanics[{index}] must define effect_type")
            payload = dict(row)
            payload["effect_type"] = effect_type
            normalized.append(payload)
        return normalized

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


class SummonEffectConfig(BaseModel):
    effect_type: Literal["summon", "conjure"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "source"
    actor_id: str | None = None
    name: str | None = None
    max_hp: int | None = None
    hp: int | None = None
    ac: int | None = None
    to_hit: int | None = None
    damage: str | None = None
    damage_type: str = "force"
    speed_ft: int | None = None
    concentration_linked: bool = True
    requires_command: bool = False
    controller: Literal["source", "target"] | None = None
    controller_id: str | None = None
    mount: bool = False

    @model_validator(mode="after")
    def validate_summon_identity(self) -> "SummonEffectConfig":
        actor_id = str(self.actor_id or "").strip()
        name = str(self.name or "").strip()
        if actor_id or name:
            return self
        raise ValueError("summon effect requires actor_id or name")


class TransformEffectConfig(BaseModel):
    effect_type: Literal["transform"] = "transform"
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    condition: str
    duration_rounds: int | None = None
    concentration_linked: bool = True
    stack_policy: Literal["independent", "refresh", "replace"] = "refresh"


class CommandAlliedEffectConfig(BaseModel):
    effect_type: Literal["command_allied"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    all_controlled: bool = False


class MountEffectConfig(BaseModel):
    effect_type: Literal["mount", "dismount"]
    apply_on: Literal["always", "hit", "miss", "save_fail", "save_success"] = "always"
    target: Literal["target", "source"] = "target"
    rider_id: str | None = None
    mount_id: str | None = None
    controller_id: str | None = None
    requires_command: bool = False


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
    | SummonEffectConfig
    | TransformEffectConfig
    | CommandAlliedEffectConfig
    | MountEffectConfig
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


class InnateSpellConfig(BaseModel):
    spell: str
    max_uses: int | None = None
    action_cost: Literal["action", "bonus", "reaction"] | None = None
    save_dc: int | None = None
    to_hit: int | None = None

    @field_validator("spell")
    @classmethod
    def validate_spell_name(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("spell must not be empty")
        return text

    @field_validator("max_uses")
    @classmethod
    def validate_max_uses(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("max_uses must be >= 1")
        return value

    @model_validator(mode="after")
    def validate_known_spell_reference(self) -> "InnateSpellConfig":
        if not _is_known_spell_reference(self.spell):
            raise ValueError(f"Unknown innate spell reference '{self.spell}'")
        return self


class EnemyConfig(BaseModel):
    identity: EnemyIdentityConfig
    stat_block: EnemyStatBlockConfig
    actions: list[ActionConfig]
    bonus_actions: list[ActionConfig] = Field(default_factory=list)
    reactions: list[ActionConfig] = Field(default_factory=list)
    legendary_actions: list[ActionConfig] = Field(default_factory=list)
    lair_actions: list[ActionConfig] = Field(default_factory=list)
    innate_spellcasting: list[InnateSpellConfig] = Field(default_factory=list)
    resources: dict[str, int] = Field(default_factory=dict)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    script_hooks: dict[str, Any] = Field(default_factory=dict)
    traits: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_custom_action_references(self) -> "EnemyConfig":
        all_actions: list[ActionConfig] = (
            list(self.actions)
            + list(self.bonus_actions)
            + list(self.reactions)
            + list(self.legendary_actions)
            + list(self.lair_actions)
        )
        action_types = {action.name: action.action_type for action in all_actions}

        for action in all_actions:
            for index, mechanic in enumerate(action.mechanics):
                effect_type = str(mechanic.get("effect_type", "")).strip().lower()
                context = f"{action.name}.mechanics[{index}]"
                if effect_type in _ATTACK_ACTION_SEQUENCE_EFFECT_TYPES:
                    sequence = mechanic.get("sequence", mechanic.get("attacks"))
                    if not isinstance(sequence, list) or not sequence:
                        raise ValueError(
                            f"{context} must include a non-empty sequence of attack references"
                        )
                    for entry_index, entry in enumerate(sequence):
                        ref_name = _extract_action_reference_name(entry)
                        if not ref_name:
                            raise ValueError(
                                f"{context}.sequence[{entry_index}] must define action_name"
                            )
                        if ref_name not in action_types:
                            raise ValueError(
                                f"{context}.sequence[{entry_index}] references unknown action "
                                f"'{ref_name}'"
                            )
                        if action_types[ref_name] != "attack":
                            raise ValueError(
                                f"{context}.sequence[{entry_index}] references non-attack action "
                                f"'{ref_name}'"
                            )
                if effect_type in _ATTACK_ACTION_REPLACEMENT_EFFECT_TYPES:
                    replacements = mechanic.get("replacements")
                    replacement_rows = replacements if replacements is not None else [mechanic]
                    if not isinstance(replacement_rows, list) or not replacement_rows:
                        raise ValueError(
                            f"{context} must include at least one replacement attack reference"
                        )
                    for entry_index, entry in enumerate(replacement_rows):
                        ref_name = _extract_action_reference_name(entry)
                        if not ref_name:
                            raise ValueError(
                                f"{context}.replacements[{entry_index}] must define action_name"
                            )
                        if ref_name not in action_types:
                            raise ValueError(
                                f"{context}.replacements[{entry_index}] references unknown action "
                                f"'{ref_name}'"
                            )
                        if action_types[ref_name] != "attack":
                            raise ValueError(
                                f"{context}.replacements[{entry_index}] references non-attack "
                                f"action '{ref_name}'"
                            )
        return self


class StrategyModuleConfig(BaseModel):
    name: str
    source: Literal["builtin", "encounter"]
    class_name: str
    module: str | None = None


class CustomSimulationConfig(BaseModel):
    source: Literal["builtin", "encounter"] = "encounter"
    module: str
    callable: str = "run_custom_simulation"


class StealthActorConfig(BaseModel):
    actor_id: str
    team: str
    hidden: bool = False
    detected_by: list[str] = Field(default_factory=list)
    surprised: bool = False
    stealth_total: int | None = None
    passive_perception: int | None = None

    @field_validator("stealth_total", "passive_perception")
    @classmethod
    def validate_non_negative_optional_values(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("stealth/passive values must be >= 0")
        return value


class InteractableConfig(BaseModel):
    object_id: str
    kind: Literal["trap", "lock", "container", "secret", "searchable"]
    location_id: str | None = None
    hidden: bool = False
    discovered: bool = False
    open: bool = False
    locked: bool = False
    trap_armed: bool = False
    disarmed: bool = False
    triggered: bool = False
    discovery_dc: int | None = None
    unlock_dc: int | None = None
    disarm_dc: int | None = None
    trigger_on_fail: bool = False
    key_item_id: str | None = None
    contents: list[str] = Field(default_factory=list)
    loot_transferred: bool = False

    @field_validator("discovery_dc", "unlock_dc", "disarm_dc")
    @classmethod
    def validate_non_negative_dc(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("DC values must be >= 0")
        return value

    @model_validator(mode="after")
    def validate_open_locked_state(self) -> "InteractableConfig":
        if self.open and self.locked:
            raise ValueError("interactable objects cannot be both open and locked")
        return self


class ExplorationActionConfig(BaseModel):
    action: Literal[
        "search",
        "disarm",
        "unlock",
        "open",
        "close",
        "transfer_loot",
        "contested_stealth",
        "surprise",
    ]
    actor_id: str | None = None
    object_id: str | None = None
    target_actor_ids: list[str] = Field(default_factory=list)
    target_object_ids: list[str] = Field(default_factory=list)
    check_total: int | None = None
    teams: dict[str, str] = Field(default_factory=dict)

    @field_validator("check_total")
    @classmethod
    def validate_non_negative_check_total(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("check_total must be >= 0")
        return value


class EncounterConfig(BaseModel):
    enemies: list[str] = Field(default_factory=list)
    short_rest_after: bool = False
    long_rest_after: bool = False
    branches: dict[str, int] = Field(default_factory=dict)
    checkpoint: str | None = None
    stealth_actors: list[StealthActorConfig] = Field(default_factory=list)
    interactables: list[InteractableConfig] = Field(default_factory=list)
    interaction_actions: list[ExplorationActionConfig] = Field(default_factory=list)

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

    @model_validator(mode="after")
    def validate_rest_flags(self) -> "EncounterConfig":
        if self.short_rest_after and self.long_rest_after:
            raise ValueError("Encounter cannot set both short_rest_after and long_rest_after")
        return self


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
    stealth_actors: list[StealthActorConfig] = Field(default_factory=list)
    interactables: list[InteractableConfig] = Field(default_factory=list)
    interaction_actions: list[ExplorationActionConfig] = Field(default_factory=list)
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

    @field_validator("resource_policy")
    @classmethod
    def validate_resource_policy(cls, resource_policy: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(resource_policy)
        short_rest_healing = normalized.get("short_rest_healing")
        if short_rest_healing is not None:
            try:
                healing = int(short_rest_healing)
            except (TypeError, ValueError) as exc:
                raise ValueError("resource_policy.short_rest_healing must be an integer") from exc
            if healing < 0:
                raise ValueError("resource_policy.short_rest_healing must be >= 0")
            normalized["short_rest_healing"] = healing
        return normalized

    @field_validator("exploration")
    @classmethod
    def validate_exploration(cls, exploration: dict[str, Any]) -> dict[str, Any]:
        legs = exploration.get("legs")
        if legs is None:
            return exploration
        if not isinstance(legs, list):
            raise ValueError("exploration.legs must be a list")
        for index, leg in enumerate(legs):
            if not isinstance(leg, dict):
                raise ValueError(f"exploration.legs[{index}] must be an object")
        return exploration


class LoadedScenario(BaseModel):
    scenario_path: str
    config: ScenarioConfig
    enemies: dict[str, EnemyConfig]
