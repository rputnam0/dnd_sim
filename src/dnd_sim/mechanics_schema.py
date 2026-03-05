from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_EFFECT_TYPES = {
    "damage",
    "heal",
    "temp_hp",
    "apply_condition",
    "remove_condition",
    "resource_change",
    "next_attack_advantage",
    "next_attack_disadvantage",
    "forced_movement",
    "hazard",
    "note",
    "max_hp_increase",
    "speed_increase",
    "sense",
    "ignore_resistance",
    "reduce_damage_taken",
    "damage_roll_floor",
    "reaction_attack",
    "summon",
    "conjure",
    "transform",
    "command_allied",
    "mount",
    "dismount",
    "aoe",
    "ranged_spell_attack",
    "melee_spell_attack",
    "save",
}

SPELL_METADATA_EFFECT_TYPES = {
    "aoe",
    "ranged_spell_attack",
    "melee_spell_attack",
    "save",
}

EXECUTABLE_EFFECT_TYPES = {
    "damage",
    "heal",
    "temp_hp",
    "apply_condition",
    "remove_condition",
    "resource_change",
    "next_attack_advantage",
    "next_attack_disadvantage",
    "forced_movement",
    "hazard",
    "max_hp_increase",
    "speed_increase",
    "sense",
    "ignore_resistance",
    "reduce_damage_taken",
    "damage_roll_floor",
    "reaction_attack",
    "summon",
    "conjure",
    "transform",
    "command_allied",
    "mount",
    "dismount",
}

_REQUIRED_FIELDS: dict[str, set[str]] = {
    "damage": {"damage"},
    "heal": {"amount"},
    "temp_hp": {"amount"},
    "apply_condition": {"condition"},
    "remove_condition": {"condition"},
    "resource_change": {"resource", "amount"},
    "forced_movement": {"distance_ft"},
    "hazard": {"hazard_type"},
    "sense": {"sense", "range_ft"},
    "max_hp_increase": {"calculation"},
    "speed_increase": {"amount"},
    "ignore_resistance": {"damage_type"},
    "reduce_damage_taken": {"damage_types", "amount"},
    "damage_roll_floor": {"damage_type", "floor"},
    "reaction_attack": {"trigger"},
    "transform": {"condition"},
}

_SUPPORTED_REACTION_ATTACK_TRIGGERS = {
    "creature_attacks_ally_within_5ft",
    "spell_cast_within_5ft",
    "hit_by_melee_attack_within_5ft",
}
_SUPPORTED_DURATION_TIMING_ALIASES: dict[str, str] = {
    "turn_start": "turn_start",
    "turn_end": "turn_end",
    "end": "turn_end",
    "end_of_turn": "turn_end",
    "at_end": "turn_end",
}
_SUPPORTED_STACK_POLICY_ALIASES: dict[str, str] = {
    "independent": "independent",
    "replace": "replace",
    "overwrite": "replace",
    "exclusive": "replace",
    "refresh": "refresh",
    "refresh_by_source": "refresh",
    "by_source": "refresh",
}
_SUPPORTED_SAVE_ABILITIES = {"str", "dex", "con", "int", "wis", "cha"}

_ACTION_GROUPS = (
    "actions",
    "bonus_actions",
    "reactions",
    "legendary_actions",
    "lair_actions",
)


def _canonical_effect_type(effect_type: str) -> str:
    return str(effect_type).strip().lower()


def _iter_json_payloads(path: Path) -> list[tuple[Path, dict[str, Any]]]:
    payloads: list[tuple[Path, dict[str, Any]]] = []
    if not path.exists():
        return payloads

    for file_path in sorted(path.glob("*.json")):
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            payloads.append((file_path, raw))
    return payloads


def _validate_mechanics_list(mechanics: Any, *, prefix: str) -> list[str]:
    issues: list[str] = []
    if mechanics is None:
        return issues

    if not isinstance(mechanics, list):
        return [f"{prefix} must be a list"]

    for idx, row in enumerate(mechanics):
        path = f"{prefix}[{idx}]"
        if not isinstance(row, dict):
            issues.append(f"{path} must be an object")
            continue

        raw_effect_type = row.get("effect_type")
        if not isinstance(raw_effect_type, str) or not raw_effect_type.strip():
            raw_meta_type = row.get("meta_type")
            if isinstance(raw_meta_type, str) and raw_meta_type.strip():
                continue
            issues.append(f"{path}.effect_type or {path}.meta_type is required")
            continue

        normalized_effect = _canonical_effect_type(raw_effect_type)
        if normalized_effect not in KNOWN_EFFECT_TYPES:
            issues.append(f"{path}.effect_type '{normalized_effect}' is unsupported")
            continue

        required_fields = _REQUIRED_FIELDS.get(normalized_effect, set())
        for required_field in sorted(required_fields):
            if required_field not in row:
                issues.append(f"{path}.{required_field} is required for {normalized_effect}")

        if normalized_effect in {"summon", "conjure"}:
            has_identity = any(
                isinstance(row.get(key), str) and str(row.get(key)).strip()
                for key in ("actor_id", "creature", "name")
            )
            if not has_identity:
                issues.append(f"{path} summon effect requires actor_id, creature, or name")

        if normalized_effect == "reaction_attack":
            trigger = row.get("trigger")
            if isinstance(trigger, str) and trigger.strip():
                normalized_trigger = trigger.strip().lower()
                if normalized_trigger not in _SUPPORTED_REACTION_ATTACK_TRIGGERS:
                    issues.append(
                        f"{path}.trigger '{normalized_trigger}' is unsupported for reaction_attack"
                    )
            elif "trigger" in row:
                issues.append(f"{path}.trigger is required for reaction_attack")

        if normalized_effect == "apply_condition":
            if "duration_timing" in row:
                duration_timing = row.get("duration_timing")
                normalized_timing = _canonical_effect_type(duration_timing)
                if normalized_timing not in _SUPPORTED_DURATION_TIMING_ALIASES:
                    issues.append(
                        f"{path}.duration_timing '{normalized_timing}' is unsupported for apply_condition"
                    )

            if "stack_policy" in row:
                stack_policy = row.get("stack_policy")
                normalized_policy = _canonical_effect_type(stack_policy)
                if normalized_policy not in _SUPPORTED_STACK_POLICY_ALIASES:
                    issues.append(
                        f"{path}.stack_policy '{normalized_policy}' is unsupported for apply_condition"
                    )

            if "save_ability" in row:
                save_ability = row.get("save_ability")
                normalized_ability = _canonical_effect_type(save_ability)
                if normalized_ability not in _SUPPORTED_SAVE_ABILITIES:
                    issues.append(
                        f"{path}.save_ability '{normalized_ability}' is unsupported for apply_condition"
                    )

    return issues


def validate_rule_mechanics_payload(*, kind: str, payload: dict[str, Any]) -> list[str]:
    """Validate canonical trait/spell payload mechanics.

    Returns a deterministic list of issue strings. Empty list means valid.
    """
    del kind  # kept for future kind-specific validation policies.
    return _validate_mechanics_list(payload.get("mechanics"), prefix="mechanics")


def validate_monster_mechanics_payload(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    for group in _ACTION_GROUPS:
        actions = payload.get(group, [])
        if actions is None:
            continue
        if not isinstance(actions, list):
            issues.append(f"{group} must be a list")
            continue

        for action_idx, action in enumerate(actions):
            if not isinstance(action, dict):
                issues.append(f"{group}[{action_idx}] must be an object")
                continue

            for key in ("effects", "mechanics"):
                prefix = f"{group}[{action_idx}].{key}"
                issues.extend(_validate_mechanics_list(action.get(key), prefix=prefix))

    issues.extend(_validate_mechanics_list(payload.get("mechanics"), prefix="mechanics"))
    return issues


def _collect_rule_mechanics(payload: dict[str, Any]) -> list[Any]:
    mechanics = payload.get("mechanics", [])
    return mechanics if isinstance(mechanics, list) else []


def _collect_monster_mechanics(payload: dict[str, Any]) -> list[Any]:
    mechanics: list[Any] = []
    for group in _ACTION_GROUPS:
        actions = payload.get(group, [])
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            for key in ("effects", "mechanics"):
                raw = action.get(key, [])
                if isinstance(raw, list):
                    mechanics.extend(raw)

    root_mechanics = payload.get("mechanics", [])
    if isinstance(root_mechanics, list):
        mechanics.extend(root_mechanics)
    return mechanics


def _classify_effect_type(value: Any) -> str:
    if isinstance(value, dict):
        effect_type = value.get("effect_type")
        if isinstance(effect_type, str) and effect_type.strip():
            return _canonical_effect_type(effect_type)
        meta_type = value.get("meta_type")
        if isinstance(meta_type, str) and meta_type.strip():
            return "<meta>"
    return "<invalid>"


def build_mechanics_coverage_report(
    *,
    traits_dir: Path,
    spells_dir: Path,
    monsters_dir: Path,
) -> dict[str, Any]:
    """Build mechanics coverage report across canonical rule JSON directories."""

    report: dict[str, Any] = {
        "totals": {"ingested": 0, "executable": 0, "unsupported": 0},
        "by_kind": {},
        "unsupported_effect_types": [],
    }
    unsupported_effect_types: set[str] = set()

    sources = [
        ("trait", _iter_json_payloads(traits_dir), _collect_rule_mechanics),
        ("spell", _iter_json_payloads(spells_dir), _collect_rule_mechanics),
        ("monster", _iter_json_payloads(monsters_dir), _collect_monster_mechanics),
    ]

    for kind, payloads, collector in sources:
        ingested = 0
        executable = 0
        unsupported = 0

        for _path, payload in payloads:
            mechanics = collector(payload)
            for mechanic in mechanics:
                ingested += 1
                effect_type = _classify_effect_type(mechanic)
                if effect_type in EXECUTABLE_EFFECT_TYPES:
                    executable += 1
                elif effect_type == "<meta>":
                    continue
                else:
                    unsupported += 1
                    unsupported_effect_types.add(effect_type)

        report["by_kind"][kind] = {
            "ingested": ingested,
            "executable": executable,
            "unsupported": unsupported,
            "files": len(payloads),
        }
        report["totals"]["ingested"] += ingested
        report["totals"]["executable"] += executable
        report["totals"]["unsupported"] += unsupported

    report["unsupported_effect_types"] = sorted(unsupported_effect_types)
    return report


def validate_mechanics_directories(
    *,
    traits_dir: Path,
    spells_dir: Path,
    monsters_dir: Path,
) -> dict[str, dict[str, list[str]]]:
    """Validate mechanics JSON entries and return file-scoped issues."""

    out: dict[str, dict[str, list[str]]] = {"trait": {}, "spell": {}, "monster": {}}

    for file_path, payload in _iter_json_payloads(traits_dir):
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        if issues:
            out["trait"][str(file_path)] = issues

    for file_path, payload in _iter_json_payloads(spells_dir):
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        if issues:
            out["spell"][str(file_path)] = issues

    for file_path, payload in _iter_json_payloads(monsters_dir):
        issues = validate_monster_mechanics_payload(payload)
        if issues:
            out["monster"][str(file_path)] = issues

    return out
