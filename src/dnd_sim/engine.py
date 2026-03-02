from __future__ import annotations

import json
import math
import random
import re
import statistics
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dnd_sim.io import EnemyConfig, LoadedScenario
from dnd_sim.models import (
    ABILITY_KEYS,
    ActionDefinition,
    ActorRuntimeState,
    ConditionTracker,
    SimulationSummary,
    SummaryMetric,
    TrialResult,
)
from dnd_sim.spatial import AABB, distance_chebyshev, find_path
from dnd_sim.rules_2014 import (
    AttackRollResult,
    apply_damage,
    attack_roll,
    parse_damage_expression,
    resolve_death_save,
    roll_damage,
    run_concentration_check,
)
from dnd_sim.strategy_api import ActorView, BattleStateView, TargetRef

_CONTROL_BLOCKING_CONDITIONS = {"incapacitated", "stunned", "unconscious", "paralyzed"}
_CONCENTRATION_FORCED_END_CONDITIONS = _CONTROL_BLOCKING_CONDITIONS
_DISADVANTAGE_CONDITIONS = {"poisoned", "frightened", "restrained", "blinded", "prone"}
_ATTACKER_ADVANTAGE_CONDITIONS = {
    "blinded",
    "paralyzed",
    "stunned",
    "unconscious",
    "restrained",
    "reckless_attacking",
}
_AUTO_CRIT_CONDITIONS = {"paralyzed", "stunned", "unconscious"}
_IMPLIED_CONDITION_MAP: dict[str, set[str]] = {
    "stunned": {"incapacitated"},
    "unconscious": {"incapacitated"},
    "paralyzed": {"incapacitated"},
}
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")
_TRAIT_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_SPELL_NORMALIZE_RE = re.compile(r"[\s_-]+")
_SPELL_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_SPELL_COMPONENT_TOKEN_RE = re.compile(r"\b([vsm])\b", flags=re.IGNORECASE)
_SPELL_INDEX_CACHE: tuple[Path, dict[str, Path]] | None = None
_RANGED_ATTACK_KEYWORDS = (
    "bow",
    "crossbow",
    "sling",
    "dart",
    "blowgun",
    "javelin",
    "net",
    "thrown",
)


@dataclass(slots=True)
class SimulationArtifacts:
    trial_results: list[TrialResult]
    trial_rows: list[dict[str, Any]]
    summary: SimulationSummary


def _metric(values: list[float]) -> SummaryMetric:
    ordered = sorted(values)
    return SummaryMetric(
        mean=float(statistics.mean(ordered)),
        median=float(statistics.median(ordered)),
        p10=float(ordered[int(0.10 * (len(ordered) - 1))]),
        p90=float(ordered[int(0.90 * (len(ordered) - 1))]),
        p95=float(ordered[int(0.95 * (len(ordered) - 1))]),
    )


def _normalize_trait_name(name: str) -> str:
    return _TRAIT_NORMALIZE_RE.sub(" ", str(name).strip().lower())


def _trait_lookup_key(name: str) -> str:
    text = _normalize_trait_name(name)
    text = (
        text.replace("’", "'")
        .replace("`", "'")
        .replace("'", "")
        .replace("[r]", "")
        .replace("[c]", "")
        .replace("[x]", "")
    )
    text = _TRAIT_PUNCT_RE.sub(" ", text)
    return _TRAIT_NORMALIZE_RE.sub(" ", text).strip()


def _trait_name_variants(name: str) -> list[str]:
    raw = str(name).strip()
    variants = {raw}
    normalized = raw.replace("’", "'")
    variants.add(normalized)
    variants.add(re.sub(r"^\d+\s*:\s*", "", normalized).strip())
    variants.add(re.sub(r"\([^)]*\)", "", normalized).strip())
    variants.add(re.sub(r"\[[^]]*\]", "", normalized).strip())
    collapsed = re.sub(r"^\d+\s*:\s*", "", re.sub(r"\([^)]*\)", "", normalized)).strip()
    variants.add(collapsed)
    stripped_markers = re.sub(r"\[[^]]*\]", "", collapsed).strip()
    variants.add(stripped_markers)
    if re.search(r"ability score improvements?$", stripped_markers, flags=re.IGNORECASE):
        variants.add("Ability Score Improvement")
    if re.search(r"lineage spells$", stripped_markers, flags=re.IGNORECASE):
        variants.add(re.sub(r"\s+spells$", "", stripped_markers, flags=re.IGNORECASE).strip())
    if re.search(r"^core .+ traits$", stripped_markers, flags=re.IGNORECASE):
        variants.add(
            re.sub(
                r"^core\s+", "", re.sub(r"\s+traits$", "", stripped_markers, flags=re.IGNORECASE)
            ).strip()
        )
    return [value for value in variants if value]


def _is_non_feature_sheet_section(name: str) -> bool:
    key = _trait_lookup_key(name)
    if key in {"hit points", "proficiencies", "skills"}:
        return True
    if re.fullmatch(r"core .+ traits", key):
        return True
    return False


def _extract_trait_candidates_from_raw_fields(character: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for row in character.get("raw_fields", []) or []:
        field = str(row.get("field", ""))
        if not field.startswith("FeaturesTraits"):
            continue
        text = str(row.get("value", ""))
        for line in text.splitlines():
            stripped = line.strip()
            # Primary bullet headings: "* Trait Name • Source"
            if stripped.startswith("* "):
                title = stripped[2:].split("•", 1)[0].strip()
                if title:
                    candidates.add(title)
                continue
            # Nested bullet selections: "| Blind Fighting • TCoE 41"
            pipe_line = stripped.lstrip("\\").strip()
            if pipe_line.startswith("|"):
                title = pipe_line[1:].strip().split("•", 1)[0].strip()
                if title:
                    candidates.add(title)
    return candidates


def _resolve_character_traits(
    character: dict[str, Any], traits_db: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Resolve character traits/features to canonical DB traits where possible.

    Keeps unresolved traits as empty dict entries so existing name-based hooks still work.
    """
    db_index: dict[str, dict[str, Any]] = {}
    for key, data in traits_db.items():
        if not isinstance(data, dict):
            continue
        name = str(data.get("name", key))
        db_index[_trait_lookup_key(name)] = data
        db_index[_trait_lookup_key(key)] = data

    resolved: dict[str, dict[str, Any]] = {}

    def find_match(candidate: str) -> dict[str, Any] | None:
        match: dict[str, Any] | None = None
        for variant in _trait_name_variants(candidate):
            matched = db_index.get(_trait_lookup_key(variant))
            if matched is not None:
                match = matched
                break
        return match

    explicit_candidates: set[str] = set(str(value) for value in (character.get("traits", []) or []))
    for candidate in explicit_candidates:
        match = find_match(candidate)
        if match is not None:
            canonical_name = _normalize_trait_name(str(match.get("name", candidate)))
            resolved[canonical_name] = match
        else:
            if _is_non_feature_sheet_section(candidate):
                continue
            resolved[_normalize_trait_name(candidate)] = {}

    # Raw feature bullets are only used to discover selected sub-options that exist in the
    # canonical trait DB (e.g. "Blind Fighting" under Fighting Initiate).
    for candidate in _extract_trait_candidates_from_raw_fields(character):
        match = find_match(candidate)
        if match is None:
            continue
        canonical_name = _normalize_trait_name(str(match.get("name", candidate)))
        resolved[canonical_name] = match

    return resolved


def _has_trait(actor: ActorRuntimeState, trait_name: str) -> bool:
    needle = _normalize_trait_name(trait_name)
    return any(_normalize_trait_name(key) == needle for key in actor.traits.keys())


def _has_any_trait(actor: ActorRuntimeState, names: list[str]) -> bool:
    return any(_has_trait(actor, name) for name in names)


def _has_trait_marker(actor: ActorRuntimeState, marker: str) -> bool:
    needle = _trait_lookup_key(marker)
    if not needle:
        return False
    for trait_name in actor.traits.keys():
        normalized = _trait_lookup_key(trait_name)
        if normalized == needle:
            return True
        if needle in normalized.split():
            return True
    return False


def _is_channel_divinity_resource_name(name: str) -> bool:
    key = _trait_lookup_key(name)
    words = set(key.split())
    return "channel" in words and "divinity" in words


def _find_channel_divinity_resource_key(resources: dict[str, Any]) -> str | None:
    for key in resources.keys():
        if _is_channel_divinity_resource_name(str(key)):
            return str(key)
    return None


def _channel_divinity_uses_for_level(level: int) -> int:
    if level >= 18:
        return 3
    if level >= 6:
        return 2
    if level >= 2:
        return 1
    return 0


def _infer_spell_save_dc(
    character: dict[str, Any],
    *,
    character_level: int,
    default_ability: str = "wis",
) -> int:
    explicit = character.get("spell_save_dc")
    if isinstance(explicit, int):
        return explicit

    profile = _extract_spellcasting_profile_from_raw_fields(character)
    dc_from_profile = profile.get("save_dc")
    if isinstance(dc_from_profile, int):
        return dc_from_profile

    ability_scores = character.get("ability_scores", {}) or {}
    ability_mod = (int(ability_scores.get(default_ability, 10)) - 10) // 2
    return 8 + _calculate_proficiency_bonus(character_level) + ability_mod


def _spend_channel_divinity(
    actor: ActorRuntimeState,
    resources_spent: dict[str, dict[str, int]],
    *,
    amount: int = 1,
) -> bool:
    if amount <= 0:
        return True
    resource_key = _find_channel_divinity_resource_key(actor.resources)
    if resource_key is None:
        return False
    current = int(actor.resources.get(resource_key, 0))
    if current < amount:
        return False
    actor.resources[resource_key] = current - amount
    resources_spent[actor.actor_id][resource_key] = (
        resources_spent[actor.actor_id].get(resource_key, 0) + amount
    )
    return True


def _has_destructive_wrath(actor: ActorRuntimeState) -> bool:
    return _has_any_trait(
        actor,
        [
            "destructive wrath",
            "channel divinity: destructive wrath",
        ],
    )


def _max_damage_expression(expr: str, *, crit: bool = False) -> int:
    n_dice, dice_size, flat = parse_damage_expression(expr)
    die_count = n_dice * (2 if crit else 1)
    return max(0, (die_count * dice_size) + flat)


def _roll_damage_with_channel_divinity_hooks(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    expr: str,
    damage_type: str,
    resources_spent: dict[str, dict[str, int]],
    crit: bool = False,
    empowered_rerolls: int = 0,
) -> int:
    normalized_type = str(damage_type).lower()
    if normalized_type in {"lightning", "thunder"} and _has_destructive_wrath(actor):
        if _spend_channel_divinity(actor, resources_spent):
            return _max_damage_expression(expr, crit=crit)
    return roll_damage(
        rng,
        expr,
        crit=crit,
        empowered_rerolls=empowered_rerolls,
        source=actor,
        damage_type=damage_type,
    )


def _parse_character_level(class_level: str) -> int:
    """Extract the numeric level from a class_level string like 'Fighter 8' or 'Wizard 5 / Cleric 3'."""
    import re

    numbers = re.findall(r"\d+", class_level)
    return sum(int(n) for n in numbers) if numbers else 1


# Cantrip damage scaling: at level 5, 11, 17 add an extra die
_CANTRIP_SCALE_TIERS = [(17, 4), (11, 3), (5, 2), (1, 1)]


def _calculate_proficiency_bonus(level: int) -> int:
    """5e proficiency bonus progression by character level."""
    return 2 + max(0, (max(level, 1) - 1) // 4)


def _is_smite_spell_name(name: str) -> bool:
    key = _trait_lookup_key(name)
    return key.endswith("smite") and key != "divine smite"


def _is_smite_setup_action(action: ActionDefinition) -> bool:
    return "spell" in action.tags and _is_smite_spell_name(action.name)


def _aura_of_protection_radius(actor: ActorRuntimeState) -> float:
    radius = 10.0
    trait_payload = actor.traits.get(_normalize_trait_name("aura of protection"), {})
    mechanics = trait_payload.get("mechanics", []) if isinstance(trait_payload, dict) else []
    for mechanic in mechanics:
        if not isinstance(mechanic, dict):
            continue
        if str(mechanic.get("type", "")).lower() != "aura":
            continue
        raw_base = mechanic.get("range")
        if isinstance(raw_base, (int, float)):
            radius = float(raw_base)
        raw_at_level = mechanic.get("range_at_level")
        if isinstance(raw_at_level, dict):
            for level_text, ranged in raw_at_level.items():
                try:
                    threshold = int(level_text)
                except (TypeError, ValueError):
                    continue
                if actor.level >= threshold and isinstance(ranged, (int, float)):
                    radius = float(ranged)
    if actor.level >= 18:
        radius = max(radius, 30.0)
    return radius


def _smite_of_protection_half_cover_bonus(
    target: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
) -> int:
    from .spatial import distance_chebyshev

    for ally in actors.values():
        if ally.team != target.team:
            continue
        if ally.dead or ally.hp <= 0:
            continue
        if "smite_of_protection_window" not in ally.conditions:
            continue
        if not _has_trait(ally, "smite of protection"):
            continue
        if not _has_trait(ally, "aura of protection"):
            continue
        if distance_chebyshev(ally.position, target.position) <= _aura_of_protection_radius(ally):
            return 2
    return 0


def _smite_extra_damage_components(action: ActionDefinition) -> list[tuple[str, str]]:
    components: list[tuple[str, str]] = []
    for mechanic in action.mechanics:
        if not isinstance(mechanic, dict):
            continue
        effect_type = str(mechanic.get("effect_type", "")).lower()
        if effect_type == "extra_damage":
            raw_expr = mechanic.get("damage", mechanic.get("dice"))
            if isinstance(raw_expr, str) and raw_expr.strip():
                components.append(
                    (
                        raw_expr.strip().replace(" ", ""),
                        str(mechanic.get("damage_type", action.damage_type or "radiant")).lower(),
                    )
                )
            continue
        raw_inline = mechanic.get("extra_damage")
        if isinstance(raw_inline, str):
            match = re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", raw_inline, flags=re.IGNORECASE)
            if not match:
                continue
            expr = match.group(1).replace(" ", "")
            dtype_match = re.search(
                r"\d+d\d+(?:\s*[+-]\s*\d+)?\s+([a-z]+)",
                raw_inline,
                flags=re.IGNORECASE,
            )
            dtype = (
                dtype_match.group(1).lower()
                if dtype_match
                else str(action.damage_type or "radiant").lower()
            )
            components.append((expr, dtype))
    if not components and action.damage and _is_smite_setup_action(action):
        components.append((action.damage, str(action.damage_type or "radiant").lower()))
    return components


def _smite_rider_effects(action: ActionDefinition) -> list[dict[str, Any]]:
    riders: list[dict[str, Any]] = []
    for mechanic in action.mechanics:
        if not isinstance(mechanic, dict):
            continue
        effect_type = str(mechanic.get("effect_type", "")).lower()
        if effect_type == "apply_condition":
            duration = mechanic.get("duration_rounds")
            if duration is None and mechanic.get("duration") is not None:
                duration = mechanic.get("duration")
            parsed_duration: int | None = None
            if duration is not None:
                try:
                    parsed_duration = int(duration)
                except (TypeError, ValueError):
                    parsed_duration = None
            if parsed_duration is not None and parsed_duration <= 0:
                parsed_duration = 1
            riders.append(
                {
                    "effect_type": "apply_condition",
                    "target": "target",
                    "condition": str(mechanic.get("condition", "")),
                    "duration_rounds": parsed_duration,
                }
            )
            continue
        if effect_type == "push":
            distance = mechanic.get("distance", 0)
            riders.append(
                {
                    "effect_type": "forced_movement",
                    "target": "target",
                    "distance_ft": int(distance) if distance else 0,
                    "direction": str(mechanic.get("direction", "away_from_source")),
                }
            )
            continue
        if effect_type == "forced_movement":
            riders.append(dict(mechanic))
    return riders


def _arm_pending_smite(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    actor.pending_smite = {
        "name": action.name,
        "save_dc": action.save_dc,
        "save_ability": action.save_ability.lower() if action.save_ability else None,
        "extra_damage": _smite_extra_damage_components(action),
        "rider_effects": _smite_rider_effects(action),
    }


def _apply_pending_smite_on_hit(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    target: ActorRuntimeState,
    roll_crit: bool,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> int:
    pending = actor.pending_smite
    if not pending:
        return 0

    extra_damage = 0
    for payload in pending.get("extra_damage", []):
        if (
            not isinstance(payload, (list, tuple))
            or len(payload) != 2
            or not isinstance(payload[0], str)
        ):
            continue
        expr = payload[0]
        dtype = str(payload[1]).lower()
        extra_damage += roll_damage(rng, expr, crit=roll_crit, source=actor, damage_type=dtype)

    rider_effects = [
        effect for effect in pending.get("rider_effects", []) if isinstance(effect, dict)
    ]
    save_dc = pending.get("save_dc")
    save_ability = pending.get("save_ability")
    rider_saved = False
    if rider_effects and save_dc is not None and isinstance(save_ability, str):
        save_mod = int(target.save_mods.get(save_ability, 0))
        rider_saved = (rng.randint(1, 20) + save_mod) >= int(save_dc)
    if not rider_saved:
        for effect in rider_effects:
            _apply_effect(
                effect=effect,
                rng=rng,
                actor=actor,
                target=target,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                actors=actors,
                active_hazards=active_hazards,
            )

    actor.pending_smite = None
    if actor.concentrating and _is_smite_spell_name(actor.concentrated_spell or ""):
        _break_concentration(actor, actors, active_hazards)
    return extra_damage


def _to_position3(value: Any) -> tuple[float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def _build_battlefield_obstacles(raw_obstacles: Any) -> list[AABB]:
    if not isinstance(raw_obstacles, list):
        return []

    obstacles: list[AABB] = []
    for row in raw_obstacles:
        if not isinstance(row, dict):
            continue
        min_pos = _to_position3(row.get("min_pos") or row.get("min"))
        max_pos = _to_position3(row.get("max_pos") or row.get("max"))
        if min_pos is None or max_pos is None:
            continue
        cover_level = str(row.get("cover_level", "NONE")).upper()
        if cover_level not in {"HALF", "THREE_QUARTERS", "TOTAL"}:
            continue
        obstacles.append(AABB(min_pos=min_pos, max_pos=max_pos, cover_level=cover_level))
    return obstacles


def _scale_cantrip_dice(base_dice: str, character_level: int) -> str:
    """Scale cantrip dice by character level. E.g., '1d10' at level 11 -> '3d10'."""
    dice_count = 1
    for tier_level, count in _CANTRIP_SCALE_TIERS:
        if character_level >= tier_level:
            dice_count = count
            break
    import re

    match = re.match(r"(\d+)d(\d+)(.*)", base_dice)
    if match:
        return f"{dice_count}d{match.group(2)}{match.group(3)}"
    return base_dice


def _upcast_damage(base_damage: str, per_level_damage: str, extra_levels: int) -> str:
    if extra_levels <= 0:
        return base_damage
    base_num, base_die, base_flat = parse_damage_expression(base_damage)
    up_num, up_die, up_flat = parse_damage_expression(per_level_damage)
    if base_num <= 0 or up_num <= 0 or base_die != up_die or up_flat != 0:
        return base_damage
    total_num = base_num + (up_num * extra_levels)
    if base_flat:
        sign = "+" if base_flat > 0 else "-"
        return f"{total_num}d{base_die}{sign}{abs(base_flat)}"
    return f"{total_num}d{base_die}"


def _component_tags_from_components(components: str) -> set[str]:
    tags: set[str] = set()
    if not components:
        return tags
    for token in _SPELL_COMPONENT_TOKEN_RE.findall(components):
        if token.lower() == "v":
            tags.add("component:verbal")
        elif token.lower() == "s":
            tags.add("component:somatic")
        elif token.lower() == "m":
            tags.add("component:material")
    return tags
def _critical_bonus_dice_expr(base_damage: str, extra_dice: int) -> str | None:
    if extra_dice <= 0:
        return None
    num_dice, die_size, _flat = parse_damage_expression(base_damage)
    if num_dice <= 0:
        return None
    return f"{num_dice * extra_dice}d{die_size}"


def _slugify_spell_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _spell_lookup_key(name: str) -> str:
    text = str(name).strip().lower()
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"\[[^]]*\]", " ", text)
    text = re.sub(r"\((?:ritual|concentration|materials?|somatic|verbal|v,s,m)[^)]*\)", " ", text)
    text = text.replace("'", "")
    text = _SPELL_PUNCT_RE.sub(" ", text)
    return _SPELL_NORMALIZE_RE.sub(" ", text).strip()


def _spell_name_variants(name: str) -> list[str]:
    raw = str(name).strip()
    variants = {raw}
    normalized = raw.replace("’", "'")
    variants.add(normalized)
    variants.add(re.sub(r"\[[^]]*\]", "", normalized).strip())
    variants.add(re.sub(r"\([^)]*\)", "", normalized).strip())
    collapsed = re.sub(r"\[[^]]*\]", "", re.sub(r"\([^)]*\)", "", normalized)).strip()
    variants.add(collapsed)
    variants.add(re.sub(r"\s+", " ", collapsed).strip())
    return [v for v in variants if v]


def _build_spell_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.glob("*.json"):
        # Index by stem immediately; this does not require JSON parsing.
        stem_key = _spell_lookup_key(path.stem)
        if stem_key and stem_key not in index:
            index[stem_key] = path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(payload.get("name", "")).strip()
        if not name:
            continue
        for variant in _spell_name_variants(name):
            key = _spell_lookup_key(variant)
            if key and key not in index:
                index[key] = path
    return index


def _get_spell_index(root: Path) -> dict[str, Path]:
    global _SPELL_INDEX_CACHE
    if _SPELL_INDEX_CACHE is None or _SPELL_INDEX_CACHE[0] != root:
        _SPELL_INDEX_CACHE = (root, _build_spell_index(root))
    return _SPELL_INDEX_CACHE[1]


def _spell_root_dir() -> Path:
    # repo_root/db/rules/2014/spells
    return Path(__file__).resolve().parents[2] / "db" / "rules" / "2014" / "spells"


def _load_spell_definition(name: str) -> dict[str, Any] | None:
    root = _spell_root_dir()
    candidate_paths: list[Path] = []
    for variant in _spell_name_variants(name):
        slug = _slugify_spell_name(variant)
        if slug:
            candidate_paths.append(root / f"{slug}.json")
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

    index = _get_spell_index(root)
    for variant in _spell_name_variants(name):
        key = _spell_lookup_key(variant)
        path = index.get(key)
        if path is None or not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return None


_LEVEL_HEADER_RE = re.compile(r"===\s*(CANTRIPS|\d+\w{2}\s+LEVEL)\s*===", re.IGNORECASE)
_LEVEL_NUMBER_RE = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)


def _parse_spell_level_from_header(header: str) -> int | None:
    text = header.strip()
    match = _LEVEL_HEADER_RE.search(text)
    if not match:
        return None
    value = match.group(1).strip().lower()
    if "cantrip" in value:
        return 0
    num = _LEVEL_NUMBER_RE.search(value)
    if not num:
        return None
    try:
        return int(num.group(1))
    except ValueError:
        return None


_SAVE_HIT_RE = re.compile(
    r"(?:(STR|DEX|CON|INT|WIS|CHA)\s*(\d+))?\s*(?:/\s*)?(\+\d+)?",
    re.IGNORECASE,
)


def _parse_save_hit_field(value: str) -> tuple[str | None, int | None, int | None]:
    raw = value.strip()
    if not raw or raw == "--":
        return None, None, None
    match = _SAVE_HIT_RE.fullmatch(raw.replace(" ", ""))
    if not match:
        # Fallback: attempt to recover components from messy strings.
        ability = None
        dc = None
        to_hit = None
        for ab in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
            if ab in raw.upper():
                ability = ab.lower()
                break
        numbers = re.findall(r"\d+", raw)
        if numbers:
            try:
                dc = int(numbers[0])
            except ValueError:
                dc = None
        hit = re.search(r"\+(\d+)", raw)
        if hit:
            to_hit = int(hit.group(1))
        return ability, dc, to_hit
    ability_code, dc_raw, to_hit_raw = match.groups()
    ability = ability_code.lower() if ability_code else None
    dc = int(dc_raw) if dc_raw else None
    to_hit = int(to_hit_raw) if to_hit_raw else None
    return ability, dc, to_hit


def _extract_spellcasting_profile_from_raw_fields(character: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    raw_fields = character.get("raw_fields", []) or []
    for row in raw_fields:
        field = str(row.get("field", ""))
        value = str(row.get("value", ""))
        if field == "spellCastingAbility0":
            out["casting_ability"] = value.strip().lower()
        elif field == "spellSaveDC0":
            try:
                out["save_dc"] = int(value.strip())
            except ValueError:
                pass
        elif field == "spellAtkBonus0":
            hit = re.search(r"\+?(\d+)", value)
            if hit:
                out["to_hit"] = int(hit.group(1))
    return out


def _character_has_magical_secrets(character: dict[str, Any]) -> bool:
    for trait in character.get("traits", []) or []:
        key = _trait_lookup_key(str(trait))
        if key in {"magical secrets", "additional magical secrets", "magical discoveries"}:
            return True
    return False


def _is_magical_secrets_spell_entry(entry: dict[str, Any]) -> bool:
    source = str(entry.get("source", "") or "").lower()
    notes = str(entry.get("notes", "") or "").lower()
    blob = f"{source} {notes}"
    return "magical secret" in blob or "magical discover" in blob


def _classify_casting_time_action_cost(casting_time: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", casting_time.strip().lower())
    if compact in {"ba", "1ba", "bonusaction", "1bonusaction"}:
        return "bonus"
    if compact in {"r", "1r", "reaction", "1reaction"}:
        return "reaction"
    return "action"


def _extract_spells_from_raw_fields(character: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a minimal spell list from PDF raw_fields.

    This produces spell dicts compatible with `_build_spell_actions`, but it relies on
    the local spell definition DB to infer damage/healing/mechanics when possible.
    """
    raw_fields = character.get("raw_fields", []) or []
    profile = _extract_spellcasting_profile_from_raw_fields(character)
    has_magical_secrets = _character_has_magical_secrets(character)
    global_to_hit = profile.get("to_hit")
    global_save_dc = profile.get("save_dc")

    current_level: int | None = None
    entries: dict[int, dict[str, Any]] = {}

    field_re = re.compile(
        r"^spell(Name|Prepared|SaveHit|CastingTime|Range|Duration|Components|Notes|Source)(\d+)$"
    )

    for row in raw_fields:
        field = str(row.get("field", ""))
        value = str(row.get("value", "") or "")
        if field.startswith("spellHeader"):
            parsed = _parse_spell_level_from_header(value)
            if parsed is not None:
                current_level = parsed
            continue

        match = field_re.match(field)
        if not match:
            continue
        key = match.group(1).lower()
        idx = int(match.group(2))
        entry = entries.setdefault(idx, {})
        entry[key] = value
        if key == "name" and "level" not in entry:
            entry["level"] = current_level if current_level is not None else 0

    spells: list[dict[str, Any]] = []
    for idx, entry in sorted(entries.items()):
        name = str(entry.get("name", "")).strip()
        if not name or name == "--":
            continue

        spell_level = int(entry.get("level", 0))
        prepared = str(entry.get("prepared", "") or "").strip()
        magical_secrets_entry = _is_magical_secrets_spell_entry(entry)
        if (
            spell_level > 0
            and not prepared
            and not magical_secrets_entry
            and not has_magical_secrets
        ):
            continue

        save_hit = str(entry.get("savehit", "") or "").strip()
        save_ability, save_dc, to_hit = _parse_save_hit_field(save_hit)

        casting_time = str(entry.get("castingtime", "") or "").strip()
        range_text = str(entry.get("range", "") or "").strip()
        duration = str(entry.get("duration", "") or "").strip()
        components = str(entry.get("components", "") or "").strip()

        spell_def = _load_spell_definition(name)
        hydrated: dict[str, Any] = {
            "name": name,
            "level": (
                int(spell_def.get("level"))
                if isinstance(spell_def, dict) and "level" in spell_def
                else spell_level
            ),
            "to_hit": to_hit if to_hit is not None else global_to_hit,
            "save_dc": save_dc if save_dc is not None else global_save_dc,
            "save_ability": save_ability,
            "concentration": "concentration" in duration.lower() if duration else False,
        }
        if magical_secrets_entry:
            hydrated["tags"] = ["magical_secrets"]

        range_ft = None
        range_match = re.search(r"(\d+)\s*ft", range_text.lower())
        if range_match:
            range_ft = int(range_match.group(1))
        else:
            feet_match = re.search(r"(\d+)\s*feet", range_text.lower())
            if feet_match:
                range_ft = int(feet_match.group(1))
        if range_ft is not None:
            hydrated["range_ft"] = range_ft
        if components:
            hydrated["components"] = components

        # Try to infer combat-relevant fields from the spell definition.
        if isinstance(spell_def, dict):
            hydrated.setdefault("level", spell_def.get("level"))
            if "save_ability" in spell_def:
                hydrated["save_ability"] = str(
                    spell_def.get("save_ability") or ""
                ).lower() or hydrated.get("save_ability")
            if "components" in spell_def:
                hydrated["components"] = str(spell_def.get("components") or "")
            if "damage_type" in spell_def:
                hydrated["damage_type"] = str(spell_def.get("damage_type") or "fire").lower()
            if "range_ft" in spell_def and isinstance(spell_def.get("range_ft"), (int, float)):
                hydrated["range_ft"] = int(spell_def["range_ft"])
            if "concentration" in spell_def:
                hydrated["concentration"] = bool(spell_def["concentration"])
            if "mechanics" in spell_def and isinstance(spell_def.get("mechanics"), list):
                hydrated["mechanics"] = list(spell_def["mechanics"])

            description = str(
                spell_def.get("description") or spell_def.get("description_raw") or ""
            )
            if not description and "meta" in spell_def and "description" in spell_def:
                description = str(spell_def.get("description", ""))

            # Damage: "take 8d6 fire damage"
            if "damage" not in hydrated:
                dmg = re.search(
                    r"take[s]?\s+(\d+d\d+(?:\s*[+-]\s*\d+)?)\s+([a-z]+)\s+damage",
                    description,
                    re.IGNORECASE,
                )
                if dmg:
                    hydrated["damage"] = dmg.group(1).replace(" ", "")
                    hydrated.setdefault("damage_type", dmg.group(2).lower())

            # Save ability: "make a Dexterity saving throw"
            if not hydrated.get("save_ability"):
                sv = re.search(
                    r"make\s+a\s+(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+saving throw",
                    description,
                    re.IGNORECASE,
                )
                if sv:
                    hydrated["save_ability"] = sv.group(1)[:3].lower()

            # Half on save hints.
            if "half as much" in description.lower():
                hydrated["half_on_save"] = True

            # Healing: Cure Wounds / Healing Word baseline parsing.
            if re.search(
                r"regains?(?:\s+a\s+number\s+of)?\s+hit\s+points?\s+equal\s+to\s+(\d+d\d+)",
                description,
                re.IGNORECASE,
            ):
                # Use spellcasting mod from the sheet if known.
                casting = str(profile.get("casting_ability") or "wis").lower()
                ability_scores = character.get("ability_scores", {}) or {}
                mod = (int(ability_scores.get(casting, 10)) - 10) // 2
                dice = re.search(r"(\d+d\d+)", description, re.IGNORECASE)
                if dice:
                    hydrated["healing"] = f"{dice.group(1)}+{mod}"

        # Determine action_cost from casting_time abbreviations used in raw fields.
        if casting_time:
            action_cost = _classify_casting_time_action_cost(casting_time)
            if action_cost == "bonus":
                hydrated["action_cost"] = "bonus"
            elif action_cost == "reaction":
                hydrated["action_cost"] = "reaction"
            else:
                hydrated["action_cost"] = "action"

        # Determine action_type if missing.
        if "action_type" not in hydrated:
            if hydrated.get("save_ability") and hydrated.get("save_dc"):
                hydrated["action_type"] = "save"
            elif hydrated.get("to_hit") is not None:
                hydrated["action_type"] = "attack"
            else:
                hydrated["action_type"] = "utility"

        spells.append(hydrated)

    # Dedupe by spell name while preserving the richest available payload.
    by_name: dict[str, dict[str, Any]] = {}
    for spell in spells:
        key = _trait_lookup_key(str(spell.get("name", "")))
        if not key:
            continue
        if key not in by_name:
            by_name[key] = dict(spell)
            continue
        existing = by_name[key]
        for field in (
            "damage",
            "damage_type",
            "healing",
            "save_ability",
            "save_dc",
            "to_hit",
            "action_type",
            "action_cost",
            "range_ft",
            "aoe_type",
            "aoe_size_ft",
            "concentration",
            "components",
        ):
            existing_value = existing.get(field)
            candidate_value = spell.get(field)
            if field == "concentration":
                existing_missing = existing_value is None
                candidate_present = candidate_value is not None
            else:
                existing_missing = existing_value in (None, "", 0)
                candidate_present = candidate_value not in (None, "", 0)
            if existing_missing and candidate_present:
                existing[field] = spell.get(field)
        existing_level = int(existing.get("level", 0))
        candidate_level = int(spell.get("level", 0))
        if existing_level <= 0 and candidate_level > 0:
            existing["level"] = candidate_level

    return list(by_name.values())


def _build_spell_actions(
    character: dict[str, Any],
    *,
    character_level: int,
) -> list[ActionDefinition]:
    """Build ActionDefinition entries from a character's spell list.

    Each spell in character['spells'] should be a dict with:
      name: str
      level: int (0 = cantrip)
      action_type: 'attack' | 'save' | 'utility'
      damage: str | None (e.g. '8d6')
      damage_type: str (default 'fire')
      to_hit: int | None (for attack spells, uses spellcasting mod)
      save_dc: int | None
      save_ability: str | None (e.g. 'dex')
      half_on_save: bool (default True for save spells)
      healing: str | None (e.g. '1d4+4' for Healing Word)
      action_cost: 'action' | 'bonus' | 'reaction' (default 'action')
      target_mode: str (default 'single_enemy')
      max_targets: int | None
      upcast_dice_per_level: str | None (e.g. '1d6' for Fireball)
      tags: list[str]
    """
    spells = character.get("spells", [])
    if not spells:
        spells = _extract_spells_from_raw_fields(character)
    if not spells:
        return []

    actions: list[ActionDefinition] = []
    resources = character.get("resources", {})
    available_slots = {}
    if isinstance(resources.get("spell_slots"), dict):
        available_slots = resources["spell_slots"]

    for spell in spells:
        name = str(spell.get("name", "unknown_spell"))
        spell_level = int(spell.get("level", 0))
        action_type = str(spell.get("action_type", "attack"))
        damage = spell.get("damage")
        damage_type = str(spell.get("damage_type", "fire"))
        to_hit = spell.get("to_hit")
        save_dc = spell.get("save_dc")
        save_ability = spell.get("save_ability")
        half_on_save = bool(spell.get("half_on_save", action_type == "save"))
        healing_expr = spell.get("healing")
        action_cost = str(spell.get("action_cost", "action"))
        target_mode = str(spell.get("target_mode", "single_enemy"))
        max_targets = spell.get("max_targets")
        mechanics = spell.get("mechanics", [])
        tags = list(spell.get("tags", []))
        tags.append("spell")
        components = str(spell.get("components") or "")
        if components:
            tags.extend(sorted(_component_tags_from_components(components)))
        tags = list(dict.fromkeys(tags))

        resource_cost: dict[str, int] = {}

        if spell_level == 0:
            # Cantrip: no slot cost, scale damage by level
            if damage:
                damage = _scale_cantrip_dice(str(damage), character_level)
        else:
            # Leveled spell: consume a spell slot
            slot_key = f"spell_slot_{spell_level}"
            resource_cost[slot_key] = 1

        # Build effects for healing spells
        effects: list[dict[str, Any]] = []
        if healing_expr:
            effects.append(
                {
                    "effect_type": "heal",
                    "target": "target",
                    "amount": str(healing_expr),
                    "apply_on": "always",
                }
            )
            if action_type == "utility":
                target_mode = spell.get("target_mode", "single_ally")

        action = ActionDefinition(
            name=name,
            action_type=action_type,
            to_hit=int(to_hit) if to_hit is not None else None,
            damage=str(damage) if damage else None,
            damage_type=damage_type,
            save_dc=int(save_dc) if save_dc is not None else None,
            save_ability=str(save_ability) if save_ability else None,
            half_on_save=half_on_save,
            resource_cost=resource_cost,
            action_cost=action_cost,
            target_mode=target_mode,
            range_ft=int(spell.get("range_ft")) if spell.get("range_ft") is not None else None,
            aoe_type=spell.get("aoe_type"),
            aoe_size_ft=spell.get("aoe_size_ft"),
            max_targets=max_targets,
            concentration=bool(spell.get("concentration", False)),
            include_self=smite_setup,
            effects=effects,
            mechanics=mechanics,
            tags=tags,
        )
        actions.append(action)

        upcast_step = str(spell.get("upcast_dice_per_level") or "").strip()
        if spell_level > 0 and damage and upcast_step and isinstance(available_slots, dict):
            for slot_level in sorted(int(level) for level in available_slots.keys()):
                if slot_level <= spell_level:
                    continue
                if int(available_slots.get(str(slot_level), 0)) <= 0:
                    continue
                extra_levels = slot_level - spell_level
                upcast_damage = _upcast_damage(str(damage), upcast_step, extra_levels)
                if upcast_damage == str(damage):
                    continue
                actions.append(
                    ActionDefinition(
                        name=f"{name} ({slot_level}th level)",
                        action_type=action_type,
                        to_hit=int(to_hit) if to_hit is not None else None,
                        damage=upcast_damage,
                        damage_type=damage_type,
                        save_dc=int(save_dc) if save_dc is not None else None,
                        save_ability=str(save_ability) if save_ability else None,
                        half_on_save=half_on_save,
                        resource_cost={f"spell_slot_{slot_level}": 1},
                        action_cost=action_cost,
                        target_mode=target_mode,
                        range_ft=(
                            int(spell.get("range_ft"))
                            if spell.get("range_ft") is not None
                            else None
                        ),
                        aoe_type=spell.get("aoe_type"),
                        aoe_size_ft=spell.get("aoe_size_ft"),
                        max_targets=max_targets,
                        concentration=bool(spell.get("concentration", False)),
                        effects=list(effects),
                        mechanics=list(mechanics),
                        tags=list(tags) + [f"upcast_level:{slot_level}"],
                    )
                )

    return actions


def _build_cleric_channel_divinity_actions(
    *,
    character: dict[str, Any],
    character_level: int,
    traits: set[str],
) -> list[ActionDefinition]:
    def has_trait(name: str) -> bool:
        return _normalize_trait_name(name) in traits

    def has_any_trait(*names: str) -> bool:
        return any(has_trait(name) for name in names)

    channel_resource_key = _find_channel_divinity_resource_key(character.get("resources", {}))
    if channel_resource_key is None:
        channel_resource_key = "channel_divinity"
    channel_cost = {channel_resource_key: 1}
    cleric_save_dc = _infer_spell_save_dc(
        character, character_level=character_level, default_ability="wis"
    )

    actions: list[ActionDefinition] = []

    if has_any_trait("turn undead", "channel divinity: turn undead"):
        actions.append(
            ActionDefinition(
                name="turn_undead",
                action_type="save",
                save_dc=cleric_save_dc,
                save_ability="wis",
                half_on_save=False,
                resource_cost=dict(channel_cost),
                target_mode="all_enemies",
                range_ft=30,
                effects=[
                    {
                        "effect_type": "apply_condition",
                        "apply_on": "save_fail",
                        "target": "target",
                        "condition": "turned",
                        "duration_rounds": 10,
                    },
                    {
                        "effect_type": "apply_condition",
                        "apply_on": "save_fail",
                        "target": "target",
                        "condition": "frightened",
                        "duration_rounds": 10,
                    },
                    {
                        "effect_type": "apply_condition",
                        "apply_on": "save_fail",
                        "target": "target",
                        "condition": "incapacitated",
                        "duration_rounds": 10,
                    },
                ],
                tags=["channel_divinity", "turn_undead", "requires_target_trait:undead"],
            )
        )

    if has_any_trait("preserve life", "channel divinity: preserve life"):
        actions.append(
            ActionDefinition(
                name="preserve_life",
                action_type="utility",
                resource_cost=dict(channel_cost),
                target_mode="single_ally",
                include_self=True,
                range_ft=30,
                effects=[
                    {
                        "effect_type": "heal",
                        "target": "target",
                        "amount": str(max(1, 5 * character_level)),
                        "apply_on": "always",
                    }
                ],
                tags=["channel_divinity", "domain_life"],
            )
        )

    if has_any_trait("radiance of the dawn", "channel divinity: radiance of the dawn"):
        actions.append(
            ActionDefinition(
                name="radiance_of_the_dawn",
                action_type="save",
                save_dc=cleric_save_dc,
                save_ability="con",
                half_on_save=True,
                damage=f"2d10+{character_level}",
                damage_type="radiant",
                resource_cost=dict(channel_cost),
                target_mode="all_enemies",
                range_ft=30,
                tags=["channel_divinity", "domain_light"],
            )
        )

    if has_any_trait("twilight sanctuary", "channel divinity: twilight sanctuary"):
        actions.append(
            ActionDefinition(
                name="twilight_sanctuary",
                action_type="utility",
                resource_cost=dict(channel_cost),
                target_mode="all_allies",
                include_self=True,
                range_ft=30,
                effects=[
                    {
                        "effect_type": "temp_hp",
                        "target": "target",
                        "amount": f"1d6+{character_level}",
                        "apply_on": "always",
                    },
                    {
                        "effect_type": "remove_condition",
                        "target": "target",
                        "condition": "charmed",
                        "apply_on": "always",
                    },
                    {
                        "effect_type": "remove_condition",
                        "target": "target",
                        "condition": "frightened",
                        "apply_on": "always",
                    },
                ],
                tags=["channel_divinity", "domain_twilight"],
            )
        )

    return actions


def _build_character_actions(character: dict[str, Any]) -> list[ActionDefinition]:
    attacks = character.get("attacks", [])
    resources = character.get("resources", {})
    traits = {_normalize_trait_name(trait) for trait in character.get("traits", [])}
    character_level = _parse_character_level(character.get("class_level", "1"))

    def has_trait(name: str) -> bool:
        return _normalize_trait_name(name) in traits

    def resource_pool_max(resource_name: str) -> int:
        value = resources.get(resource_name, 0)
        if isinstance(value, dict):
            raw = value.get("max", 0)
            return int(raw) if isinstance(raw, (int, float)) else 0
        return int(value) if isinstance(value, int) else 0

    if attacks:

        def avg_damage(expr: str) -> float:
            n_dice, dice_size, flat = parse_damage_expression(expr)
            if n_dice == 0:
                return float(flat)
            return n_dice * ((dice_size + 1) / 2.0) + flat

        best_attack = max(
            attacks,
            key=lambda attack: (
                avg_damage(str(attack.get("damage", "1"))),
                int(attack.get("to_hit", 0)),
            ),
        )
        attack_count = 2 if has_trait("extra attack") else 1
        actions = [
            ActionDefinition(
                name="basic",
                action_type="attack",
                to_hit=int(best_attack.get("to_hit", 0)),
                damage=str(best_attack.get("damage", "1")),
                damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                attack_count=attack_count,
                tags=["basic"],
            )
        ]

        for idx, attack in enumerate(attacks, start=1):
            actions.append(
                ActionDefinition(
                    name=f"attack_{idx}",
                    action_type="attack",
                    to_hit=int(attack.get("to_hit", 0)),
                    damage=str(attack.get("damage", "1")),
                    damage_type=str(attack.get("damage_type", "bludgeoning")),
                    attack_count=attack_count,
                    tags=["attack_option"],
                )
            )

        if "ki" in resources and resources["ki"].get("max", 0) > 0:
            actions.append(
                ActionDefinition(
                    name="signature",
                    action_type="attack",
                    to_hit=int(best_attack.get("to_hit", 0)),
                    damage=str(best_attack.get("damage", "1")),
                    damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                    attack_count=attack_count + 1,
                    resource_cost={"ki": 1},
                    tags=["signature"],
                )
            )
        elif len(attacks) > 1:
            secondary = attacks[1]
            actions.append(
                ActionDefinition(
                    name="signature",
                    action_type="attack",
                    to_hit=int(secondary.get("to_hit", best_attack.get("to_hit", 0))),
                    damage=str(secondary.get("damage", best_attack.get("damage", "1"))),
                    damage_type=str(
                        secondary.get("damage_type", best_attack.get("damage_type", "bludgeoning"))
                    ),
                    attack_count=attack_count,
                    tags=["signature"],
                )
            )

        # --- Bonus actions ---
        if has_trait("martial arts"):
            actions.append(
                ActionDefinition(
                    name="martial_arts_bonus",
                    action_type="attack",
                    to_hit=int(best_attack.get("to_hit", 0)),
                    damage=str(best_attack.get("damage", "1")),
                    damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                    attack_count=1,
                    action_cost="bonus",
                    tags=["bonus", "martial_arts"],
                )
            )
            if has_trait("flurry of blows") and resources.get("ki", {}).get("max", 0) > 0:
                tags = ["bonus", "martial_arts", "flurry_of_blows"]
                if has_trait("open hand technique"):
                    tags.append("open_hand_technique")
                actions.append(
                    ActionDefinition(
                        name="flurry_of_blows",
                        action_type="attack",
                        to_hit=int(best_attack.get("to_hit", 0)),
                        damage=str(best_attack.get("damage", "1")),
                        damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                        attack_count=2,
                        resource_cost={"ki": 1},
                        action_cost="bonus",
                        tags=tags,
                    )
                )

        if has_trait("polearm master"):
            weapon_name = best_attack.get("name", "").lower()
            if any(
                w in weapon_name for w in ["glaive", "halberd", "quarterstaff", "spear", "pike"]
            ):
                flat_mod_match = re.search(r"([+-]\s*\d+)", str(best_attack.get("damage", "")))
                flat_mod = flat_mod_match.group(1).replace(" ", "") if flat_mod_match else ""
                actions.append(
                    ActionDefinition(
                        name="polearm_master_bonus",
                        action_type="attack",
                        to_hit=int(best_attack.get("to_hit", 0)),
                        damage=f"1d4{flat_mod}",
                        damage_type="bludgeoning",
                        action_cost="bonus",
                        tags=["bonus", "polearm_master"],
                    )
                )

        if has_trait("two-weapon fighting") and len(attacks) >= 2:
            off_hand = attacks[1]
            actions.append(
                ActionDefinition(
                    name="off_hand_attack",
                    action_type="attack",
                    to_hit=int(off_hand.get("to_hit", 0)),
                    damage=str(off_hand.get("damage", "1")),
                    damage_type=str(off_hand.get("damage_type", "bludgeoning")),
                    attack_count=1,
                    action_cost="bonus",
                    tags=["bonus", "off_hand"],
                )
            )

        if has_trait("great weapon master"):
            actions.append(
                ActionDefinition(
                    name="gwm_bonus_attack",
                    action_type="attack",
                    to_hit=int(best_attack.get("to_hit", 0)),
                    damage=str(best_attack.get("damage", "1")),
                    damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                    action_cost="bonus",
                    tags=["bonus", "gwm_bonus"],
                )
            )

        if has_trait("bardic inspiration") and resource_pool_max("bardic_inspiration") > 0:
            actions.append(
                ActionDefinition(
                    name="bardic_inspiration",
                    action_type="utility",
                    action_cost="bonus",
                    target_mode="single_ally",
                    range_ft=60,
                    resource_cost={"bardic_inspiration": 1},
                    tags=["bonus", "bardic_inspiration"],
                )
            )

        # --- Reactions ---
        if has_trait("shield"):
            actions.append(
                ActionDefinition(
                    name="shield",
                    action_type="utility",
                    action_cost="reaction",
                    tags=["reaction", "shield_spell"],
                )
            )
        if has_trait("lay on hands"):
            actions.append(
                ActionDefinition(
                    name="lay_on_hands",
                    action_type="utility",
                    action_cost="action",
                    target_mode="single_ally",
                    include_self=True,
                    tags=["healing", "lay_on_hands"],
                )
            )
        # --- Spell actions ---
        actions.extend(_build_spell_actions(character, character_level=character_level))
        actions.extend(
            _build_cleric_channel_divinity_actions(
                character=character,
                character_level=character_level,
                traits=traits,
            )
        )

        return actions

    # Fallback: no attacks defined
    spell_actions = _build_spell_actions(character, character_level=character_level)
    cleric_actions = _build_cleric_channel_divinity_actions(
        character=character,
        character_level=character_level,
        traits=traits,
    )
    base = [
        ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=0,
            damage="1",
            damage_type="bludgeoning",
            tags=["basic"],
        )
    ]
    if has_trait("bardic inspiration") and resource_pool_max("bardic_inspiration") > 0:
        base.append(
            ActionDefinition(
                name="bardic_inspiration",
                action_type="utility",
                action_cost="bonus",
                target_mode="single_ally",
                range_ft=60,
                resource_cost={"bardic_inspiration": 1},
                tags=["bonus", "bardic_inspiration"],
            )
        )
    return base + spell_actions + cleric_actions


def _get_standard_actions() -> list[ActionDefinition]:
    return [
        ActionDefinition(
            name="dodge",
            action_type="utility",
            action_cost="action",
            target_mode="self",
            tags=["standard_action"],
        ),
        ActionDefinition(
            name="dash",
            action_type="utility",
            action_cost="action",
            target_mode="self",
            tags=["standard_action"],
        ),
        ActionDefinition(
            name="disengage",
            action_type="utility",
            action_cost="action",
            target_mode="self",
            tags=["standard_action"],
        ),
        ActionDefinition(
            name="ready",
            action_type="utility",
            action_cost="action",
            target_mode="self",
            tags=["standard_action"],
        ),
    ]


def _extract_flat_resources(character: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    raw = character.get("resources", {})
    for key, value in raw.items():
        if isinstance(value, dict):
            max_value = value.get("max")
            if isinstance(max_value, int):
                result[key] = max_value
            elif key == "spell_slots":
                for level, slots in value.items():
                    result[f"spell_slot_{level}"] = int(slots)
            else:
                for name, amount in value.items():
                    if isinstance(amount, int):
                        result[f"{key}_{name}"] = amount
        elif isinstance(value, int):
            result[key] = value
    traits = {_normalize_trait_name(trait) for trait in (character.get("traits", []) or [])}
    if _normalize_trait_name("lay on hands") in traits and "lay_on_hands_pool" not in result:
        result["lay_on_hands_pool"] = max(
            0, _parse_character_level(character.get("class_level", "1")) * 5
        )
    if _normalize_trait_name("paladin's smite") in traits and "paladins_smite_free" not in result:
        result["paladins_smite_free"] = 1
    return result


def _apply_passive_traits(actor: ActorRuntimeState) -> None:
    for trait_data in list(actor.traits.values()):
        for mechanic in trait_data.get("mechanics", []):
            etype = mechanic.get("effect_type")
            if etype == "max_hp_increase":
                calc = mechanic.get("calculation", "")
                if "character_level" in calc:
                    try:
                        mult = int(calc.split("*")[1].strip())
                        added_hp = actor.level * mult
                        actor.max_hp += added_hp
                        actor.hp += added_hp
                    except Exception:
                        pass
            elif etype == "speed_increase":
                actor.speed_ft += mechanic.get("amount", 0)
            elif etype == "sense":
                # Promote senses into trait keys used by spatial.can_see().
                sense = str(mechanic.get("sense", "")).lower().strip()
                if not sense:
                    continue
                raw_range = mechanic.get(
                    "range_ft", mechanic.get("range", mechanic.get("distance"))
                )
                if isinstance(raw_range, (int, float)):
                    actor.traits[sense] = {"range_ft": float(raw_range)}


def _ensure_channel_divinity_resource(actor: ActorRuntimeState) -> None:
    has_channel_divinity_feature = _has_trait(actor, "channel divinity") or any(
        _normalize_trait_name(name).startswith("channel divinity:") for name in actor.traits.keys()
    )
    if not has_channel_divinity_feature:
        return

    resource_key = _find_channel_divinity_resource_key(actor.max_resources)
    if resource_key is None:
        resource_key = _find_channel_divinity_resource_key(actor.resources)
    if resource_key is None:
        resource_key = "channel_divinity"

    existing_max = int(actor.max_resources.get(resource_key, 0))
    if existing_max > 0:
        return

    uses = _channel_divinity_uses_for_level(actor.level)
    if uses <= 0:
        return

    actor.max_resources[resource_key] = uses
    if actor.resources.get(resource_key, 0) <= 0:
        actor.resources[resource_key] = uses


def _build_actor_from_character(
    character: dict[str, Any], traits_db: dict[str, dict[str, Any]] = None
) -> ActorRuntimeState:
    normalized_traits_db = {
        _normalize_trait_name(key): value for key, value in (traits_db or {}).items()
    }
    ability_scores = character.get("ability_scores", {})
    dex_mod = (int(ability_scores.get("dex", 10)) - 10) // 2
    con_mod = (int(ability_scores.get("con", 10)) - 10) // 2
    initiative_mod = character.get("initiative_mod", None)
    if initiative_mod is None:
        initiative_mod = dex_mod
    ability_mods = {k: (int(ability_scores.get(k, 10)) - 10) // 2 for k in ABILITY_KEYS}
    explicit_saves = {k: int(v) for k, v in character.get("save_mods", {}).items()}
    save_mods = {k: explicit_saves.get(k, ability_mods.get(k, 0)) for k in ABILITY_KEYS}
    max_hp = int(character.get("max_hp", 1))
    actor = ActorRuntimeState(
        actor_id=character["character_id"],
        team="party",
        name=character["name"],
        max_hp=max_hp,
        hp=max_hp,
        temp_hp=0,
        ac=int(character.get("ac", 10)),
        initiative_mod=int(initiative_mod),
        str_mod=ability_mods.get("str", 0),
        dex_mod=dex_mod,
        con_mod=con_mod,
        int_mod=ability_mods.get("int", 0),
        wis_mod=ability_mods.get("wis", 0),
        cha_mod=ability_mods.get("cha", 0),
        save_mods=save_mods,
        actions=_build_character_actions(character) + _get_standard_actions(),
        proficiencies={str(v).lower() for v in character.get("proficiencies", [])},
        expertise={str(v).lower() for v in character.get("expertise", [])},
        resources=_extract_flat_resources(character),
        max_resources=_extract_flat_resources(character),
        traits=_resolve_character_traits(character, traits_db),
        level=_parse_character_level(character.get("class_level", "1")),
    )
    _ensure_channel_divinity_resource(actor)
    _apply_passive_traits(actor)
    current_hp = character.get("current_hp")
    if current_hp is not None:
        try:
            actor.hp = max(0, min(actor.max_hp, int(current_hp)))
        except (TypeError, ValueError):
            pass

    current_resources = character.get("current_resources")
    if isinstance(current_resources, dict):
        for resource_name, resource_amount in current_resources.items():
            if not isinstance(resource_amount, int):
                continue
            if resource_name not in actor.max_resources:
                continue
            actor.resources[resource_name] = max(
                0, min(int(actor.max_resources[resource_name]), resource_amount)
            )
    return actor


def _build_actor_from_enemy(
    enemy: EnemyConfig, traits_db: dict[str, dict[str, Any]] = None
) -> ActorRuntimeState:
    normalized_traits_db = {
        _normalize_trait_name(key): value for key, value in (traits_db or {}).items()
    }
    actions: list[ActionDefinition] = []

    def append_actions(source_actions: list[Any], default_cost: str) -> None:
        for action in source_actions:
            resolved_cost = (
                default_cost
                if default_cost != "action" and action.action_cost == "action"
                else action.action_cost
            )
            actions.append(
                ActionDefinition(
                    name=action.name,
                    action_type=action.action_type,
                    to_hit=action.to_hit,
                    damage=action.damage,
                    damage_type=action.damage_type,
                    attack_count=action.attack_count,
                    save_dc=action.save_dc,
                    save_ability=action.save_ability,
                    half_on_save=action.half_on_save,
                    resource_cost=dict(action.resource_cost),
                    recharge=action.recharge,
                    max_uses=action.max_uses,
                    action_cost=resolved_cost,
                    target_mode=action.target_mode,
                    max_targets=action.max_targets,
                    event_trigger=getattr(action, "event_trigger", None),
                    trigger_duration_rounds=getattr(action, "trigger_duration_rounds", None),
                    trigger_limit_per_turn=getattr(action, "trigger_limit_per_turn", None),
                    trigger_once_per_round=bool(getattr(action, "trigger_once_per_round", False)),
                    concentration=action.concentration,
                    include_self=action.include_self,
                    effects=[effect.model_dump() for effect in action.effects],
                    tags=list(action.tags),
                )
            )

    append_actions(enemy.actions, "action")
    append_actions(enemy.bonus_actions, "bonus")
    append_actions(enemy.reactions, "reaction")
    append_actions(enemy.legendary_actions, "legendary")
    append_actions(enemy.lair_actions, "lair")
    if not actions:
        actions.append(ActionDefinition(name="basic", action_type="attack", to_hit=0, damage="1"))

    legendary_pool = int(enemy.resources.get("legendary_actions", 0))
    if legendary_pool == 0 and enemy.legendary_actions:
        legendary_pool = 3

    recharge_ready = {action.name: True for action in actions if action.recharge}

    def _enemy_ability_mod(key: str) -> int:
        explicit = getattr(enemy.stat_block, f"{key}_mod", None)
        return (
            int(explicit) if explicit is not None else int(enemy.stat_block.save_mods.get(key, 0))
        )

    actor = ActorRuntimeState(
        actor_id=enemy.identity.enemy_id,
        team=enemy.identity.team,
        name=enemy.identity.name,
        max_hp=enemy.stat_block.max_hp,
        hp=enemy.stat_block.max_hp,
        temp_hp=0,
        ac=enemy.stat_block.ac,
        initiative_mod=enemy.stat_block.initiative_mod,
        str_mod=_enemy_ability_mod("str"),
        dex_mod=_enemy_ability_mod("dex"),
        con_mod=_enemy_ability_mod("con"),
        int_mod=_enemy_ability_mod("int"),
        wis_mod=_enemy_ability_mod("wis"),
        cha_mod=_enemy_ability_mod("cha"),
        save_mods=dict(enemy.stat_block.save_mods),
        actions=actions,
        damage_resistances={v.lower() for v in enemy.damage_resistances},
        damage_immunities={v.lower() for v in enemy.damage_immunities},
        damage_vulnerabilities={v.lower() for v in enemy.damage_vulnerabilities},
        condition_immunities={v.lower() for v in enemy.condition_immunities},
        resources=dict(enemy.resources),
        max_resources=dict(enemy.resources),
        recharge_ready=recharge_ready,
        legendary_actions_remaining=legendary_pool,
        proficiencies={str(v).lower() for v in enemy.script_hooks.get("proficiencies", [])},
        expertise={str(v).lower() for v in enemy.script_hooks.get("expertise", [])},
        traits={
            _normalize_trait_name(trait): normalized_traits_db.get(_normalize_trait_name(trait), {})
            for trait in enemy.traits
        },
    )
    _apply_passive_traits(actor)
    return actor


def short_rest(actor: ActorRuntimeState, healing: int = 0) -> None:
    if actor.hp > 0 and not actor.dead:
        actor.hp = min(actor.max_hp, actor.hp + healing)

    short_rest_resources = {"action_surge", "ki", "channel_divinity"}
    for res_key in list(actor.resources.keys()):
        if (
            res_key in short_rest_resources
            or "warlock_spell_slot" in res_key
            or _is_channel_divinity_resource_name(res_key)
        ):
            actor.resources[res_key] = actor.max_resources.get(res_key, 0)

    for action in actor.actions:
        if action.name in {"action_surge", "second_wind"} or "short_rest" in action.tags:
            actor.per_action_uses.pop(action.name, None)


def long_rest(actor: ActorRuntimeState) -> None:
    actor.hp = actor.max_hp
    actor.temp_hp = 0
    actor.resources = dict(actor.max_resources)
    actor.per_action_uses.clear()
    actor.conditions.clear()
    actor.condition_durations.clear()
    actor.death_failures = 0
    actor.death_successes = 0
    actor.downed_count = 0
    actor.concentrating = False
    actor.concentrated_targets.clear()
    actor.concentration_conditions.clear()
    actor.concentrated_spell = None
    actor.concentrated_spell_level = None
    actor.movement_remaining = float(actor.speed_ft)


def _build_actor_views(
    actors: dict[str, ActorRuntimeState],
    actor_order: list[str],
    round_number: int,
    metadata: dict[str, Any],
) -> BattleStateView:
    return BattleStateView(
        round_number=round_number,
        actors={
            actor_id: ActorView(
                actor_id=actor.actor_id,
                team=actor.team,
                hp=actor.hp,
                max_hp=actor.max_hp,
                ac=actor.ac,
                save_mods=dict(actor.save_mods),
                resources=dict(actor.resources),
                conditions=set(actor.conditions),
                speed_ft=actor.speed_ft,
                movement_remaining=actor.movement_remaining,
                position=actor.position,
                traits=dict(actor.traits),
            )
            for actor_id, actor in actors.items()
        },
        actor_order=actor_order,
        metadata=metadata,
    )


def _actor_defeated(actor: ActorRuntimeState) -> bool:
    return actor.dead or actor.hp <= 0


def _party_defeated(actors: dict[str, ActorRuntimeState]) -> bool:
    party = [actor for actor in actors.values() if actor.team == "party"]
    return bool(party) and all(_actor_defeated(actor) for actor in party)


def _enemies_defeated(actors: dict[str, ActorRuntimeState]) -> bool:
    enemies = [actor for actor in actors.values() if actor.team != "party"]
    return bool(enemies) and all(_actor_defeated(actor) for actor in enemies)


def _build_initiative_order(
    rng: random.Random, actors: dict[str, ActorRuntimeState], mode: str
) -> list[str]:
    if mode == "grouped":
        party = [actor for actor in actors.values() if actor.team == "party"]
        enemies = [actor for actor in actors.values() if actor.team != "party"]
        party_score = statistics.mean(rng.randint(1, 20) + actor.initiative_mod for actor in party)
        enemy_score = statistics.mean(
            rng.randint(1, 20) + actor.initiative_mod for actor in enemies
        )
        party_order = [
            actor.actor_id for actor in sorted(party, key=lambda item: item.dex_mod, reverse=True)
        ]
        enemy_order = [
            actor.actor_id for actor in sorted(enemies, key=lambda item: item.dex_mod, reverse=True)
        ]
        return (
            party_order + enemy_order if party_score >= enemy_score else enemy_order + party_order
        )

    rolls = []
    for actor in actors.values():
        roll = rng.randint(1, 20) + actor.initiative_mod
        tiebreak = rng.randint(1, 20) + actor.dex_mod
        rolls.append((roll, tiebreak, actor.actor_id))
    rolls.sort(reverse=True)
    return [actor_id for _, _, actor_id in rolls]


def _sync_initiative_order(
    initiative_order: list[str], actors: dict[str, ActorRuntimeState]
) -> list[str]:
    existing = [actor_id for actor_id in initiative_order if actor_id in actors]
    known = set(existing)
    missing = [actor for actor in actors.values() if actor.actor_id not in known]
    missing.sort(
        key=lambda actor: (actor.initiative_mod, actor.dex_mod, actor.actor_id), reverse=True
    )
    return existing + [actor.actor_id for actor in missing]


def _has_resources(actor: ActorRuntimeState, cost: dict[str, int]) -> bool:
    for key, amount in cost.items():
        if actor.resources.get(key, 0) < amount:
            return False
    return True


def _spend_resources(actor: ActorRuntimeState, cost: dict[str, int]) -> dict[str, int]:
    spent: dict[str, int] = {}
    for key, amount in cost.items():
        if amount <= 0:
            continue
        current = actor.resources.get(key, 0)
        actual = min(amount, max(current, 0))
        actor.resources[key] = current - actual
        spent[key] = actual
    return spent


def _spend_action_resource_cost(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    resources_spent: dict[str, dict[str, int]],
) -> bool:
    if not _can_pay_resource_cost(actor, action):
        return False
    spent = _spend_resources(actor, action.resource_cost)
    for key, amount in spent.items():
        resources_spent[actor.actor_id][key] = resources_spent[actor.actor_id].get(key, 0) + amount
    return True


def _default_target(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
) -> list[TargetRef]:
    candidates = [
        target
        for target in actors.values()
        if target.team != actor.team and target.hp > 0 and not target.dead
    ]
    if not candidates:
        return []
    target = min(candidates, key=lambda value: (value.hp, value.max_hp))
    return [TargetRef(target.actor_id)]


def _has_action_tag(action: ActionDefinition, tag: str) -> bool:
    target = tag.lower()
    return any(str(candidate).lower() == target for candidate in action.tags)


def _is_probably_ranged_attack(action: ActionDefinition) -> bool:
    if _has_action_tag(action, "ranged") or _has_action_tag(action, "ranged_attack"):
        return True
    name = action.name.lower()
    return any(keyword in name for keyword in _RANGED_ATTACK_KEYWORDS)


def _action_range_ft(action: ActionDefinition) -> float | None:
    if action.target_mode == "self":
        return None
    if action.range_ft is not None:
        return float(action.range_ft)
    if action.action_type in {"grapple", "shove"}:
        return 5.0
    if action.action_type == "attack":
        if _has_action_tag(action, "spell"):
            return 60.0
        if _is_probably_ranged_attack(action):
            return 60.0
        return 5.0
    if action.action_type == "utility":
        return 30.0
    if _has_action_tag(action, "spell"):
        return 60.0
    return 60.0


def _requires_range_resolution(action: ActionDefinition) -> bool:
    if action.target_mode == "self":
        return False
    if action.action_type == "utility" and action.name in {"dodge", "dash", "disengage", "ready"}:
        return False
    return _action_range_ft(action) is not None


def _path_distance(path: list[tuple[float, float, float]]) -> float:
    if len(path) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(path)):
        total += distance_chebyshev(path[idx - 1], path[idx])
    return total


def _path_prefix_for_distance(
    path: list[tuple[float, float, float]],
    distance_ft: float,
) -> list[tuple[float, float, float]]:
    if not path:
        return []
    if len(path) == 1 or distance_ft <= 0:
        return [path[0]]

    traveled: list[tuple[float, float, float]] = [path[0]]
    remaining = distance_ft
    current = path[0]
    for waypoint in path[1:]:
        segment = distance_chebyshev(current, waypoint)
        if segment <= 0:
            current = waypoint
            continue
        if segment <= remaining:
            traveled.append(waypoint)
            remaining -= segment
            current = waypoint
            if remaining <= 0:
                break
            continue
        ratio = remaining / segment
        traveled.append(
            (
                current[0] + (waypoint[0] - current[0]) * ratio,
                current[1] + (waypoint[1] - current[1]) * ratio,
                current[2] + (waypoint[2] - current[2]) * ratio,
            )
        )
        break
    return traveled


def _expand_path_points(
    path: list[tuple[float, float, float]],
    *,
    step_ft: float = 5.0,
) -> list[tuple[float, float, float]]:
    if len(path) < 2:
        return path
    expanded: list[tuple[float, float, float]] = [path[0]]
    for idx in range(1, len(path)):
        start = path[idx - 1]
        end = path[idx]
        segment = distance_chebyshev(start, end)
        if segment <= 0:
            continue
        steps = max(1, int(segment / step_ft))
        if (steps * step_ft) < segment:
            steps += 1
        for step in range(1, steps + 1):
            ratio = step / steps
            expanded.append(
                (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                    start[2] + (end[2] - start[2]) * ratio,
                )
            )
    return expanded


def _advance_along_path(
    path: list[tuple[float, float, float]], distance_ft: float
) -> tuple[float, float, float]:
    if not path:
        return (0.0, 0.0, 0.0)
    if len(path) == 1 or distance_ft <= 0:
        return path[0]
    remaining = distance_ft
    current = path[0]
    for waypoint in path[1:]:
        segment = distance_chebyshev(current, waypoint)
        if segment <= 0:
            current = waypoint
            continue
        if segment <= remaining:
            remaining -= segment
            current = waypoint
            continue
        ratio = remaining / segment
        return (
            current[0] + (waypoint[0] - current[0]) * ratio,
            current[1] + (waypoint[1] - current[1]) * ratio,
            current[2] + (waypoint[2] - current[2]) * ratio,
        )
    return current


def _prepare_voluntary_movement(actor: ActorRuntimeState) -> tuple[float, bool]:
    if actor.movement_remaining <= 0:
        return 0.0, False
    if actor.conditions.intersection({"grappled", "restrained"}):
        return 0.0, False
    if "prone" not in actor.conditions:
        return actor.movement_remaining, False

    stand_cost = float(actor.speed_ft) / 2.0
    if actor.movement_remaining >= stand_cost:
        actor.movement_remaining -= stand_cost
        _remove_condition(actor, "prone")
        return actor.movement_remaining, False

    # RAW crawl when prone: each moved foot costs 2 feet.
    return actor.movement_remaining / 2.0, True


def _find_opportunity_attack_action(actor: ActorRuntimeState) -> ActionDefinition | None:
    best: ActionDefinition | None = None
    for action in actor.actions:
        if action.action_type != "attack":
            continue
        if action.action_cost in {"legendary", "lair"}:
            continue
        if not _can_pay_resource_cost(actor, action):
            continue
        if _action_range_ft(action) is None or _action_range_ft(action) > 5.0:
            continue
        if best is None:
            best = action
            continue
        current_to_hit = action.to_hit if action.to_hit is not None else -999
        best_to_hit = best.to_hit if best.to_hit is not None else -999
        if current_to_hit > best_to_hit:
            best = action
    if best is None:
        return None
    return replace(best, attack_count=1, action_cost="reaction")


def _run_opportunity_attacks_for_movement(
    *,
    rng: random.Random,
    mover: ActorRuntimeState,
    start_pos: tuple[float, float, float],
    end_pos: tuple[float, float, float],
    movement_path: list[tuple[float, float, float]] | None,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> None:
    if mover.dead or mover.hp <= 0:
        return
    if "disengaging" in mover.conditions:
        return
    if start_pos == end_pos:
        return

    path_points = _expand_path_points(movement_path or [start_pos, end_pos])
    if len(path_points) < 2:
        return

    for enemy in actors.values():
        if enemy.team == mover.team or enemy.dead or enemy.hp <= 0:
            continue
        if not enemy.reaction_available:
            continue
        trigger_point: tuple[float, float, float] | None = None
        previous = path_points[0]
        was_in_reach = distance_chebyshev(enemy.position, previous) <= 5.0
        for point in path_points[1:]:
            is_in_reach = distance_chebyshev(enemy.position, point) <= 5.0
            if was_in_reach and not is_in_reach:
                trigger_point = previous
                break
            was_in_reach = is_in_reach
            previous = point
        if trigger_point is None:
            continue
        reaction_attack = _find_opportunity_attack_action(enemy)
        if reaction_attack is None:
            continue
        if not _spend_action_resource_cost(enemy, reaction_attack, resources_spent):
            continue
        enemy.reaction_available = False
        original_position = mover.position
        mover.position = trigger_point
        _execute_action(
            rng=rng,
            actor=enemy,
            action=reaction_attack,
            targets=[mover],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            obstacles=obstacles,
            light_level=light_level,
        )
        mover.position = end_pos if mover.hp > 0 and not mover.dead else original_position
        if mover.dead or mover.hp <= 0:
            break


def _move_actor_for_action_range(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> bool:
    if not targets:
        return False
    action_range = _action_range_ft(action)
    if action_range is None:
        return True

    primary = targets[0]
    current_distance = distance_chebyshev(actor.position, primary.position)
    if current_distance <= action_range:
        return True

    # Reactions do not include movement unless explicitly modeled by the reaction action itself.
    if action.action_cost == "reaction":
        return False

    available_distance, crawling = _prepare_voluntary_movement(actor)
    if available_distance <= 0:
        return False

    target_ids = {target.actor_id for target in targets}
    occupied_positions = [
        other.position
        for other in actors.values()
        if other.actor_id != actor.actor_id
        and other.team == actor.team
        and other.actor_id not in target_ids
        and not other.dead
        and other.hp > 0
    ]
    path = find_path(
        actor.position,
        primary.position,
        obstacles,
        occupied_positions=occupied_positions,
    )
    path_distance = _path_distance(path)
    if path_distance <= action_range:
        return True

    required_move = max(0.0, path_distance - action_range)
    move_distance = min(available_distance, required_move)
    if move_distance <= 0:
        return distance_chebyshev(actor.position, primary.position) <= action_range

    start_pos = actor.position
    movement_path = _path_prefix_for_distance(path, move_distance)
    end_pos = movement_path[-1] if movement_path else _advance_along_path(path, move_distance)
    moved = distance_chebyshev(start_pos, end_pos)
    if moved <= 0:
        return distance_chebyshev(actor.position, primary.position) <= action_range

    actor.position = end_pos
    movement_spent = moved * (2.0 if crawling else 1.0)
    actor.movement_remaining = max(0.0, actor.movement_remaining - movement_spent)

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=actor,
        start_pos=start_pos,
        end_pos=end_pos,
        movement_path=movement_path,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        obstacles=obstacles,
        light_level=light_level,
    )

    if actor.dead or actor.hp <= 0:
        return False
    return distance_chebyshev(actor.position, primary.position) <= action_range


def _filter_targets_in_range(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
) -> list[ActorRuntimeState]:
    action_range = _action_range_ft(action)
    if action_range is None:
        return targets
    if not targets:
        return []
    if action.aoe_type:
        primary = targets[0]
        if distance_chebyshev(actor.position, primary.position) > action_range:
            return []
        if action.aoe_size_ft:
            radius = float(action.aoe_size_ft)
            return [
                target
                for target in targets
                if distance_chebyshev(primary.position, target.position) <= radius
            ]
        return targets
    return [
        target
        for target in targets
        if distance_chebyshev(actor.position, target.position) <= action_range
    ]


def _action_can_target_downed_allies(action: ActionDefinition) -> bool:
    if action.action_type in {"utility", "buff"}:
        return True
    for effect in action.effects:
        if not isinstance(effect, dict):
            continue
        if effect.get("target") != "target":
            continue
        if effect.get("effect_type") in {"heal", "temp_hp", "remove_condition", "resource_change"}:
            return True
    return False


def _target_pool(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    *,
    mode: str,
    include_self: bool,
    include_downed_allies: bool,
) -> list[ActorRuntimeState]:
    def enemy_candidates() -> list[ActorRuntimeState]:
        return [
            value
            for value in actors.values()
            if value.team != actor.team and value.hp > 0 and not value.dead
        ]

    def ally_candidates() -> list[ActorRuntimeState]:
        return [
            value
            for value in actors.values()
            if value.team == actor.team
            and not value.dead
            and (value.hp > 0 or include_downed_allies)
        ]

    if mode == "self":
        return [actor] if not actor.dead else []
    if mode in {"single_enemy", "all_enemies", "n_enemies", "random_enemy"}:
        pool = enemy_candidates()
    elif mode in {"single_ally", "all_allies", "n_allies", "random_ally"}:
        pool = ally_candidates()
    else:
        pool = [
            value
            for value in actors.values()
            if not value.dead and (value.hp > 0 or include_downed_allies)
        ]
    if not include_self and mode != "self":
        pool = [value for value in pool if value.actor_id != actor.actor_id]
    return pool


def _target_sort_key(
    source: ActorRuntimeState,
    target: ActorRuntimeState,
    *,
    mode: str,
) -> tuple[float, int, int, str]:
    if target.team == source.team:
        ratio = target.hp / target.max_hp if target.max_hp > 0 else 1.0
        deficit = target.max_hp - target.hp
        return (ratio, -deficit, target.hp, target.actor_id)
    return (0.0, target.hp, target.max_hp, target.actor_id)


def _distance_2d(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _in_area_template(
    *,
    actor: ActorRuntimeState,
    primary: ActorRuntimeState,
    candidate: ActorRuntimeState,
    aoe_type: str,
    aoe_size_ft: float,
) -> bool:
    template = aoe_type.strip().lower()
    if template in {"sphere", "cylinder"}:
        return _distance_2d(primary.position, candidate.position) <= aoe_size_ft

    if template == "cube":
        half = aoe_size_ft / 2.0
        dx = abs(candidate.position[0] - primary.position[0])
        dy = abs(candidate.position[1] - primary.position[1])
        dz = abs(candidate.position[2] - primary.position[2])
        return dx <= half and dy <= half and dz <= half

    axis = (
        primary.position[0] - actor.position[0],
        primary.position[1] - actor.position[1],
    )
    axis_len = math.hypot(axis[0], axis[1])
    if axis_len <= 0:
        return _distance_2d(primary.position, candidate.position) <= aoe_size_ft
    unit = (axis[0] / axis_len, axis[1] / axis_len)
    rel = (
        candidate.position[0] - actor.position[0],
        candidate.position[1] - actor.position[1],
    )
    projection = rel[0] * unit[0] + rel[1] * unit[1]

    if template == "line":
        if projection < 0 or projection > aoe_size_ft:
            return False
        perp_sq = max(0.0, (rel[0] * rel[0] + rel[1] * rel[1]) - (projection * projection))
        return math.sqrt(perp_sq) <= 5.0

    if template == "cone":
        distance = math.hypot(rel[0], rel[1])
        if distance > aoe_size_ft:
            return False
        if distance == 0:
            return True
        cos_theta = projection / distance
        return cos_theta >= math.cos(math.radians(30))

    return _distance_2d(primary.position, candidate.position) <= aoe_size_ft


def _resolve_template_targets(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    mode: str,
    primaries: list[ActorRuntimeState],
    candidates: list[ActorRuntimeState],
) -> list[ActorRuntimeState]:
    aoe_type = str(action.aoe_type or "").lower().strip()
    if not aoe_type or not action.aoe_size_ft or not primaries:
        return primaries
    size = float(action.aoe_size_ft)
    victims: set[str] = set()
    for primary in primaries:
        for candidate in candidates:
            if _in_area_template(
                actor=actor,
                primary=primary,
                candidate=candidate,
                aoe_type=aoe_type,
                aoe_size_ft=size,
            ):
                victims.add(candidate.actor_id)
    if not action.include_self:
        victims.discard(actor.actor_id)
    return [
        target
        for target in sorted(
            candidates, key=lambda value: _target_sort_key(actor, value, mode=mode)
        )
        if target.actor_id in victims
    ]


def _resolve_targets_for_action(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    actors: dict[str, ActorRuntimeState],
    requested: list[TargetRef],
) -> list[ActorRuntimeState]:
    mode = action.target_mode
    include_self = action.include_self or mode == "self"
    include_downed_allies = _action_can_target_downed_allies(action)
    candidates = _target_pool(
        actor,
        actors,
        mode=mode,
        include_self=include_self,
        include_downed_allies=include_downed_allies,
    )
    if not candidates:
        return []

    required_conditions: set[str] = set()
    excluded_conditions: set[str] = set()
    required_target_traits: set[str] = set()
    excluded_target_traits: set[str] = set()
    for tag in getattr(action, "tags", []) or []:
        text = str(tag)
        if text.startswith("requires_condition:"):
            required_conditions.add(text.split(":", 1)[1].strip().lower())
        elif text.startswith("excludes_condition:"):
            excluded_conditions.add(text.split(":", 1)[1].strip().lower())
        elif text.startswith("requires_target_trait:"):
            required_target_traits.add(text.split(":", 1)[1].strip().lower())
        elif text.startswith("excludes_target_trait:"):
            excluded_target_traits.add(text.split(":", 1)[1].strip().lower())

    if required_conditions:
        candidates = [
            target
            for target in candidates
            if all(cond in target.conditions for cond in required_conditions)
        ]
    if excluded_conditions:
        candidates = [
            target
            for target in candidates
            if not any(cond in target.conditions for cond in excluded_conditions)
        ]
    if required_target_traits:
        candidates = [
            target
            for target in candidates
            if all(_has_trait_marker(target, marker) for marker in required_target_traits)
        ]
    if excluded_target_traits:
        candidates = [
            target
            for target in candidates
            if not any(_has_trait_marker(target, marker) for marker in excluded_target_traits)
        ]
    if not candidates:
        return []
    by_id = {target.actor_id: target for target in candidates}
    ordered_candidates = sorted(
        candidates, key=lambda value: _target_sort_key(actor, value, mode=mode)
    )
    selected: list[ActorRuntimeState]

    if mode in {"all_enemies", "all_allies", "all_creatures"}:
        max_targets = action.max_targets or len(ordered_candidates)
        selected = ordered_candidates[:max_targets]
    elif mode in {"random_enemy", "random_ally"}:
        valid_requested = [ref.actor_id for ref in requested if ref.actor_id in by_id]
        if valid_requested:
            selected = [by_id[valid_requested[0]]]
        else:
            selected = [rng.choice(candidates)]
    elif mode == "self":
        selected = [actor]
    else:
        max_targets = 1
        if mode in {"n_enemies", "n_allies"}:
            max_targets = action.max_targets or 1
        selected = []
        seen: set[str] = set()
        for ref in requested:
            target = by_id.get(ref.actor_id)
            if target is None or target.actor_id in seen:
                continue
            selected.append(target)
            seen.add(target.actor_id)
            if len(selected) >= max_targets:
                break
        if len(selected) < max_targets:
            for target in ordered_candidates:
                if target.actor_id in seen:
                    continue
                selected.append(target)
                seen.add(target.actor_id)
                if len(selected) >= max_targets:
                    break

    # Preserve legacy radius behavior when size is present without a template.
    if action.aoe_size_ft and not action.aoe_type and selected:
        radius = float(action.aoe_size_ft)
        aoe_victims: set[str] = set()
        for primary in selected:
            for cand in actors.values():
                if cand.dead:
                    continue
                if cand.hp <= 0 and not include_downed_allies:
                    continue
                if distance_chebyshev(primary.position, cand.position) <= radius:
                    aoe_victims.add(cand.actor_id)
        if not action.include_self and actor.actor_id in aoe_victims:
            aoe_victims.remove(actor.actor_id)
        return sorted(
            [actors[aid] for aid in aoe_victims],
            key=lambda value: _target_sort_key(actor, value, mode=mode),
        )
    return _resolve_template_targets(
        actor=actor,
        action=action,
        mode=mode,
        primaries=selected,
        candidates=ordered_candidates,
    )


def _resolve_action_selection(
    actor: ActorRuntimeState,
    intent_name: str | None,
) -> ActionDefinition:
    if intent_name:
        for action in actor.actions:
            if action.name == intent_name:
                return action
    for action in actor.actions:
        if action.name == "basic":
            return action
    return actor.actions[0]


def _disadvantaged(actor: ActorRuntimeState) -> bool:
    return bool(actor.conditions.intersection(_DISADVANTAGE_CONDITIONS))


def _can_act(actor: ActorRuntimeState) -> bool:
    return (
        actor.hp > 0
        and not actor.dead
        and not actor.conditions.intersection(_CONTROL_BLOCKING_CONDITIONS)
    )


def _remove_condition(actor: ActorRuntimeState, condition: str) -> None:
    key = condition.lower()
    actor.conditions.discard(key)
    actor.condition_durations.pop(key, None)
    if key == "readying":
        actor.readied_action_name = None
        actor.readied_trigger = None
    for implied in _IMPLIED_CONDITION_MAP.get(key, set()):
        actor.conditions.discard(implied)
        actor.condition_durations.pop(implied, None)


def _break_concentration(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    if (
        not actor.concentrating
        and not actor.concentrated_targets
        and not actor.concentrated_spell
        and not actor.concentrated_spell_level
        and not actor.concentration_conditions
    ):
        return
    actor.concentrating = False
    for target_id in list(actor.concentrated_targets):
        if target_id in actors:
            if "summoned" in actors[target_id].conditions:
                del actors[target_id]
                continue
            for condition in actor.concentration_conditions:
                _remove_condition(actors[target_id], condition)
            if actor.concentrated_spell:
                _remove_condition(actors[target_id], actor.concentrated_spell)
    actor.concentrated_targets.clear()
    actor.concentration_conditions.clear()

    if actor.concentrated_spell or actor.concentrated_spell_level:
        active_hazards[:] = [h for h in active_hazards if h.get("source_id") != actor.actor_id]

    actor.concentrated_spell = None
    actor.concentrated_spell_level = None


def _concentration_forced_end(actor: ActorRuntimeState) -> bool:
    if not actor.concentrating:
        return False
    if actor.dead or actor.hp <= 0:
        return True
    return bool(actor.conditions.intersection(_CONCENTRATION_FORCED_END_CONDITIONS))


def _force_end_concentration_if_needed(
    actor: ActorRuntimeState,
    *,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> bool:
    if not _concentration_forced_end(actor):
        return False
    _break_concentration(actor, actors, active_hazards)
    return True


def _apply_condition(
    actor: ActorRuntimeState,
    condition: str,
    *,
    duration_rounds: int | None = None,
    save_dc: int | None = None,
    save_ability: str | None = None,
) -> None:
    key = condition.lower()
    if key in actor.condition_immunities or "all" in actor.condition_immunities:
        return
    actor.conditions.add(key)
    if duration_rounds is not None and duration_rounds > 0:
        existing = actor.condition_durations.get(key)
        existing_rounds = existing.remaining_rounds if existing else 0
        actor.condition_durations[key] = ConditionTracker(
            remaining_rounds=max(existing_rounds or 0, duration_rounds),
            save_dc=save_dc,
            save_ability=save_ability.lower() if save_ability else None,
        )
    elif save_dc is not None and save_ability:
        # Condition with repeating save but no fixed duration
        actor.condition_durations[key] = ConditionTracker(
            remaining_rounds=None,
            save_dc=save_dc,
            save_ability=save_ability.lower(),
        )
    for implied in _IMPLIED_CONDITION_MAP.get(key, set()):
        actor.conditions.add(implied)
        if duration_rounds is not None and duration_rounds > 0:
            existing = actor.condition_durations.get(implied)
            existing_rounds = existing.remaining_rounds if existing else 0
            actor.condition_durations[implied] = ConditionTracker(
                remaining_rounds=max(existing_rounds or 0, duration_rounds),
            )


def _tick_conditions_for_actor(rng: random.Random, actor: ActorRuntimeState) -> None:
    """Tick condition durations at the start of an actor's turn.

    Conditions with a repeating save allow the actor to roll each turn.
    """
    if "raging" in actor.conditions and not actor.rage_sustained_since_last_turn:
        _remove_condition(actor, "raging")
    actor.rage_sustained_since_last_turn = False

    for condition, tracker in list(actor.condition_durations.items()):
        # Attempt repeating save if available
        if tracker.save_dc is not None and tracker.save_ability:
            save_key = tracker.save_ability
            save_mod = int(actor.save_mods.get(save_key, 0))
            save_roll = rng.randint(1, 20) + save_mod
            if save_roll >= tracker.save_dc:
                _remove_condition(actor, condition)
                continue
        # Decrement duration
        if tracker.remaining_rounds is not None:
            remaining = tracker.remaining_rounds - 1
            if remaining <= 0:
                _remove_condition(actor, condition)
            else:
                actor.condition_durations[condition] = ConditionTracker(
                    remaining_rounds=remaining,
                    save_dc=tracker.save_dc,
                    save_ability=tracker.save_ability,
                )


def _apply_healing(target: ActorRuntimeState, amount: int) -> None:
    if amount <= 0 or target.dead:
        return
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    if before <= 0 and target.hp > 0:
        target.death_successes = 0
        target.death_failures = 0
        target.stable = False
        target.was_downed = False
        _remove_condition(target, "unconscious")
        _remove_condition(target, "incapacitated")


def _effect_matches_event(effect: dict[str, Any], event: str) -> bool:
    apply_on = str(effect.get("apply_on", "always"))
    return apply_on == "always" or apply_on == event


def _consume_attack_flags(actor: ActorRuntimeState) -> tuple[bool, bool]:
    advantage = actor.next_attack_advantage
    disadvantage = _disadvantaged(actor) or actor.next_attack_disadvantage
    if actor.next_attack_advantage or actor.next_attack_disadvantage:
        actor.next_attack_advantage = False
        actor.next_attack_disadvantage = False
    return advantage, disadvantage


def _resolve_effect_target(
    effect: dict[str, Any],
    *,
    actor: ActorRuntimeState,
    target: ActorRuntimeState,
) -> ActorRuntimeState:
    return actor if effect.get("target") == "source" else target


def _apply_effect(
    *,
    action: ActionDefinition | None = None,
    effect: dict[str, Any],
    rng: random.Random,
    actor: ActorRuntimeState,
    target: ActorRuntimeState,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
    round_number: int | None = None,
    turn_token: str | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
) -> None:
    recipient = _resolve_effect_target(effect, actor=actor, target=target)
    effect_type = str(effect.get("effect_type"))

    if effect_type == "damage":
        is_magical = False
        if action and getattr(action, "tags", None):
            is_magical = "spell" in action.tags or "magical" in action.tags
        damage_type = str(effect.get("damage_type", "bludgeoning"))
        raw_damage = _roll_damage_with_channel_divinity_hooks(
            rng=rng,
            actor=actor,
            expr=str(effect.get("damage", "0")),
            damage_type=damage_type,
            resources_spent=resources_spent,
            crit=False,
        )
        applied = apply_damage(
            recipient, raw_damage, damage_type, is_magical=is_magical, source=actor
        )
        if applied > 0:
            if not _force_end_concentration_if_needed(
                recipient, actors=actors, active_hazards=active_hazards
            ) and not run_concentration_check(rng, recipient, applied, source=actor):
                _break_concentration(recipient, actors, active_hazards)
        damage_dealt[actor.actor_id] += applied
        damage_taken[recipient.actor_id] += applied
        threat_scores[actor.actor_id] += applied
        return

    if effect_type == "heal":
        amount = roll_damage(rng, str(effect.get("amount", "0")), crit=False)
        _apply_healing(recipient, amount)
        return

    if effect_type == "temp_hp":
        amount = roll_damage(rng, str(effect.get("amount", "0")), crit=False)
        if amount > 0:
            recipient.temp_hp = max(recipient.temp_hp, amount)
        return

    if effect_type == "apply_condition":
        save_dc = effect.get("save_dc")
        save_ability = effect.get("save_ability")
        if save_dc is not None and save_ability:
            save_key = str(save_ability).lower()
            save_mod = int(recipient.save_mods.get(save_key, 0))
            save_total = rng.randint(1, 20) + save_mod
            if (
                action
                and getattr(action, "tags", None)
                and "spell" in action.tags
                and _has_trait(recipient, "gnomish cunning")
                and save_key in {"int", "wis", "cha"}
            ):
                save_total = max(save_total, rng.randint(1, 20) + save_mod)
            if str(effect.get("condition", "")).lower() == "charmed" and _has_trait(
                recipient, "fey ancestry"
            ):
                save_total = max(save_total, rng.randint(1, 20) + save_mod)
            condition_saved = save_total >= int(save_dc)
            if not condition_saved and recipient.resources.get("legendary_resistance", 0) > 0:
                recipient.resources["legendary_resistance"] -= 1
                resources_spent[recipient.actor_id]["legendary_resistance"] = (
                    resources_spent[recipient.actor_id].get("legendary_resistance", 0) + 1
                )
                condition_saved = True
            if condition_saved:
                return
        _apply_condition(
            recipient,
            str(effect.get("condition", "")),
            duration_rounds=effect.get("duration_rounds"),
            save_dc=int(save_dc) if save_dc is not None else None,
            save_ability=str(save_ability) if save_ability else None,
        )
        _force_end_concentration_if_needed(recipient, actors=actors, active_hazards=active_hazards)
        return

    if effect_type == "remove_condition":
        _remove_condition(recipient, str(effect.get("condition", "")))
        return

    if effect_type == "hazard":
        duration = int(effect.get("duration", 10))
        hazard_type = str(effect.get("hazard_type", "generic"))
        hazard_position = _to_position3(effect.get("position")) or recipient.position
        hazard_radius = float(effect.get("radius", effect.get("radius_ft", 15)))
        active_hazards.append(
            {
                "type": hazard_type,
                "source_id": actor.actor_id,
                "target_id": recipient.actor_id,
                "hazard_type": hazard_type,
                "position": hazard_position,
                "radius": hazard_radius,
                "duration": duration,
            }
        )
        return

    if effect_type in {"summon", "conjure"}:
        summon_id = str(effect.get("actor_id", "")).strip() or (
            f"{actor.actor_id}_summon_{len([key for key in actors if key.startswith(actor.actor_id)])}"
        )
        if summon_id in actors:
            return
        summon_name = str(effect.get("name", summon_id))
        summon_hp = int(effect.get("max_hp", effect.get("hp", 10)))
        summon_ac = int(effect.get("ac", 10))
        summon_to_hit = effect.get("to_hit")
        summon_damage = effect.get("damage")
        summon_damage_type = str(effect.get("damage_type", "force"))
        summon_actions: list[ActionDefinition] = []
        if summon_to_hit is not None and summon_damage:
            summon_actions.append(
                ActionDefinition(
                    name=f"{summon_name.lower().replace(' ', '_')}_attack",
                    action_type="attack",
                    to_hit=int(summon_to_hit),
                    damage=str(summon_damage),
                    damage_type=summon_damage_type,
                    tags=["summon"],
                )
            )

        summoned_actor = ActorRuntimeState(
            actor_id=summon_id,
            team=actor.team,
            name=summon_name,
            max_hp=summon_hp,
            hp=summon_hp,
            temp_hp=0,
            ac=summon_ac,
            initiative_mod=actor.initiative_mod,
            str_mod=0,
            dex_mod=0,
            con_mod=0,
            int_mod=0,
            wis_mod=0,
            cha_mod=0,
            save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
            actions=summon_actions,
            speed_ft=int(effect.get("speed_ft", actor.speed_ft)),
            position=_to_position3(effect.get("position")) or actor.position,
        )
        summoned_actor.conditions.add("summoned")
        if effect_type == "conjure":
            summoned_actor.conditions.add("conjured")
        summoned_actor.traits["summoned"] = {
            "source_id": actor.actor_id,
            "concentration_linked": bool(action and action.concentration),
        }
        actors[summon_id] = summoned_actor
        damage_dealt.setdefault(summon_id, 0)
        damage_taken.setdefault(summon_id, 0)
        threat_scores.setdefault(summon_id, 0)
        resources_spent.setdefault(summon_id, {})
        if action and action.concentration:
            actor.concentrated_targets.add(summon_id)
        return

    if effect_type == "resource_change":
        resource = str(effect.get("resource", ""))
        delta = int(effect.get("amount", 0))
        minimum = int(effect.get("min_value", 0))
        before = int(recipient.resources.get(resource, 0))
        after = max(minimum, before + delta)
        recipient.resources[resource] = after
        if delta < 0:
            resources_spent[recipient.actor_id][resource] = resources_spent[recipient.actor_id].get(
                resource, 0
            ) + (before - after)
        return

    if effect_type == "next_attack_advantage":
        recipient.next_attack_advantage = True
        recipient.next_attack_disadvantage = False
        return

    if effect_type == "next_attack_disadvantage":
        recipient.next_attack_disadvantage = True
        recipient.next_attack_advantage = False
        return

    if effect_type == "forced_movement":
        # v2: Minimal positional forced-movement support. This is intentionally simple:
        # it moves the recipient along the straight line away from/toward the source.
        from .spatial import distance_euclidean, move_towards

        distance_ft = float(effect.get("distance_ft", 0))
        direction = str(effect.get("direction", "away_from_source"))
        if distance_ft <= 0:
            return

        src = actor.position
        cur = recipient.position
        if direction == "toward_source":
            old_position = recipient.position
            recipient.position = move_towards(cur, src, distance_ft)
            recipient.movement_remaining = max(0.0, recipient.movement_remaining - distance_ft)
            if (
                round_number is not None
                and turn_token is not None
                and old_position != recipient.position
                and action is not None
            ):
                _dispatch_combat_event(
                    rng=rng,
                    event="on_move",
                    trigger_actor=actor,
                    trigger_target=recipient,
                    trigger_action=action,
                    actors=actors,
                    round_number=round_number,
                    turn_token=turn_token,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                    rule_trace=rule_trace,
                )
            return

        if direction == "away_from_source":
            # Project a point further away from the source and move toward it.
            dist = distance_euclidean(src, cur)
            if dist <= 0:
                # Arbitrary axis push if co-located.
                old_position = recipient.position
                recipient.position = (cur[0] + distance_ft, cur[1], cur[2])
                recipient.movement_remaining = max(0.0, recipient.movement_remaining - distance_ft)
                if (
                    round_number is not None
                    and turn_token is not None
                    and old_position != recipient.position
                    and action is not None
                ):
                    _dispatch_combat_event(
                        rng=rng,
                        event="on_move",
                        trigger_actor=actor,
                        trigger_target=recipient,
                        trigger_action=action,
                        actors=actors,
                        round_number=round_number,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=rule_trace,
                    )
                return
            unit = ((cur[0] - src[0]) / dist, (cur[1] - src[1]) / dist, (cur[2] - src[2]) / dist)
            dest = (
                cur[0] + unit[0] * distance_ft,
                cur[1] + unit[1] * distance_ft,
                cur[2] + unit[2] * distance_ft,
            )
            old_position = recipient.position
            recipient.position = dest
            recipient.movement_remaining = max(0.0, recipient.movement_remaining - distance_ft)
            if (
                round_number is not None
                and turn_token is not None
                and old_position != recipient.position
                and action is not None
            ):
                _dispatch_combat_event(
                    rng=rng,
                    event="on_move",
                    trigger_actor=actor,
                    trigger_target=recipient,
                    trigger_action=action,
                    actors=actors,
                    round_number=round_number,
                    turn_token=turn_token,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                    rule_trace=rule_trace,
                )
            return

        return

    # note is schema-valid but non-mechanical in v1/v2.
    return


def _apply_action_effects(
    *,
    action: ActionDefinition,
    event: str,
    rng: random.Random,
    actor: ActorRuntimeState,
    target: ActorRuntimeState,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
    round_number: int | None = None,
    turn_token: str | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
) -> None:
    for effect in action.effects + action.mechanics:
        if not isinstance(effect, dict):
            continue
        if _effect_matches_event(effect, event):
            recipient = _resolve_effect_target(effect, actor=actor, target=target)
            if action.concentration and effect.get("effect_type") in ("apply_condition", "hazard"):
                actor.concentrated_targets.add(recipient.actor_id)
            _apply_effect(
                action=action,
                effect=effect,
                rng=rng,
                actor=actor,
                target=target,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                actors=actors,
                active_hazards=active_hazards,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )


def _parse_recharge_threshold(spec: str) -> int | None:
    value = spec.strip()
    if "-" in value:
        _, high = value.split("-", 1)
        return int(high)
    if value.isdigit():
        return int(value)
    return None


def _roll_recharge_for_actor(rng: random.Random, actor: ActorRuntimeState) -> None:
    if not actor.recharge_ready:
        return
    by_name = {action.name: action for action in actor.actions}
    for action_name, is_ready in list(actor.recharge_ready.items()):
        if is_ready:
            continue
        action = by_name.get(action_name)
        if not action or not action.recharge:
            actor.recharge_ready[action_name] = True
            continue
        threshold = _parse_recharge_threshold(action.recharge)
        if threshold is None:
            actor.recharge_ready[action_name] = True
            continue
        if rng.randint(1, 6) >= threshold:
            actor.recharge_ready[action_name] = True


def _action_component_tags(action: ActionDefinition) -> set[str]:
    return {
        str(tag).strip().lower()
        for tag in action.tags
        if str(tag).strip().lower().startswith("component:")
    }


def _can_cast_spell_with_components(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    if "spell" not in action.tags:
        return True
    components = _action_component_tags(action)
    if not components:
        return True

    if "component:verbal" in components and actor.conditions.intersection(
        {"silenced", "gagged", "mute"}
    ):
        return False

    free_hands = int(actor.resources.get("free_hands", 1))
    has_free_hand = free_hands > 0
    has_focus = bool(actor.resources.get("spellcasting_focus", 0)) or _has_trait(
        actor, "spellcasting focus"
    )

    needs_material = "component:material" in components
    needs_somatic = "component:somatic" in components

    if needs_material and not (has_focus or has_free_hand):
        return False

    if needs_somatic and not has_free_hand and not _has_trait(actor, "war caster"):
        # A hand holding an M component/focus can satisfy S+M together.
        if not (needs_material and has_focus):
            return False

    return True


def _can_pay_resource_cost(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    return _has_resources(actor, action.resource_cost)


def _can_take_reaction(actor: ActorRuntimeState) -> bool:
    if not actor.reaction_available:
        return False
    if actor.dead or actor.hp <= 0:
        return False
    if actor.conditions.intersection(_CONTROL_BLOCKING_CONDITIONS):
        return False
    if "open_hand_no_reactions" in actor.conditions:
        return False
    return True


def _action_available(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    if action.name == "lay_on_hands" and actor.resources.get("lay_on_hands_pool", 0) <= 0:
        return False
    if action.max_uses is not None and actor.per_action_uses.get(action.name, 0) >= action.max_uses:
        return False
    if action.recharge and not actor.recharge_ready.get(action.name, True):
        return False
    if not _can_pay_resource_cost(actor, action):
        return False
    if not _can_cast_spell_with_components(actor, action):
        return False
    if action.action_cost == "bonus" and not actor.bonus_available:
        return False
    if action.action_cost == "reaction" and not _can_take_reaction(actor):
        return False
    if action.action_cost == "legendary" and actor.legendary_actions_remaining < _legendary_cost(
        action
    ):
        return False
    if action.action_cost == "lair" and actor.lair_action_used_this_round:
        return False
    return True


def _legendary_cost(action: ActionDefinition) -> int:
    cost = 1
    for tag in getattr(action, "tags", []) or []:
        text = str(tag)
        if text.startswith("legendary_cost:"):
            _, raw = text.split(":", 1)
            try:
                cost = max(cost, int(raw))
            except ValueError:
                continue
    return cost


def _mark_action_cost_used(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    if action.action_cost == "bonus":
        actor.bonus_available = False
    elif action.action_cost == "reaction":
        actor.reaction_available = False
    elif action.action_cost == "legendary":
        actor.legendary_actions_remaining = max(
            0, actor.legendary_actions_remaining - _legendary_cost(action)
        )
    elif action.action_cost == "lair":
        actor.lair_action_used_this_round = True


def _event_trigger_priority(action: ActionDefinition) -> int:
    for tag in action.tags:
        value = str(tag)
        if not value.startswith("trigger_priority:"):
            continue
        _, raw = value.split(":", 1)
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


def _event_trigger_int_tag(action: ActionDefinition, prefix: str) -> int | None:
    for tag in action.tags:
        value = str(tag)
        if not value.startswith(prefix):
            continue
        _, raw = value.split(":", 1)
        try:
            parsed = int(raw)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _event_trigger_duration_rounds(action: ActionDefinition) -> int | None:
    if action.trigger_duration_rounds is not None and action.trigger_duration_rounds > 0:
        return action.trigger_duration_rounds
    return _event_trigger_int_tag(action, "trigger_duration_rounds:")


def _event_trigger_limit_per_turn(action: ActionDefinition) -> int | None:
    if action.trigger_limit_per_turn is not None and action.trigger_limit_per_turn > 0:
        return action.trigger_limit_per_turn
    return _event_trigger_int_tag(action, "trigger_limit_per_turn:")


def _event_trigger_once_per_round(action: ActionDefinition) -> bool:
    return action.trigger_once_per_round or action.action_cost == "reaction"


def _event_trigger_start_key(action: ActionDefinition) -> str:
    event_name = action.event_trigger or "always"
    return f"event_trigger_start:{event_name}:{action.name}"


def _event_trigger_turn_key(
    action: ActionDefinition,
    *,
    round_number: int,
    turn_token: str | None,
) -> str:
    token = turn_token or f"{round_number}:global"
    event_name = action.event_trigger or "always"
    return f"event_turn:{token}:{event_name}:{action.name}"


def _event_trigger_is_expired(
    actor: ActorRuntimeState, action: ActionDefinition, *, round_number: int
) -> bool:
    duration = _event_trigger_duration_rounds(action)
    if duration is None:
        return False
    start_key = _event_trigger_start_key(action)
    started_round = actor.per_action_uses.get(start_key)
    if started_round is None:
        actor.per_action_uses[start_key] = round_number
        return False
    return int(started_round) + duration - 1 < round_number


def _resolve_event_targets(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    actors: dict[str, ActorRuntimeState],
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
) -> list[ActorRuntimeState]:
    requested: list[TargetRef] = _default_target(actor, actors)
    preferred = trigger_target if trigger_target is not None else trigger_actor
    if (
        preferred is not None
        and preferred.actor_id in actors
        and preferred.team != actor.team
        and preferred.hp > 0
        and not preferred.dead
    ):
        requested = [TargetRef(preferred.actor_id)]
    return _resolve_targets_for_action(
        rng=rng,
        actor=actor,
        action=action,
        actors=actors,
        requested=requested,
    )


def _run_trait_event_handlers(
    *,
    rng: random.Random,
    event: str,
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
    actors: dict[str, ActorRuntimeState],
    round_number: int,
    turn_token: str,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    rule_trace: list[dict[str, Any]],
    obstacles: list[AABB],
    light_level: str,
) -> None:
    if trigger_actor is None or trigger_action is None:
        return
    lock_key = f"event_reaction_round:{round_number}"

    if (
        event == "after_action"
        and trigger_action.action_type == "attack"
        and trigger_target is not None
    ):
        reactors = sorted(actors.values(), key=lambda value: value.actor_id)
        for reactor in reactors:
            if (
                reactor.team != trigger_target.team
                or reactor.actor_id == trigger_target.actor_id
                or reactor.dead
                or reactor.hp <= 0
                or not reactor.reaction_available
                or not _has_trait(reactor, "sentinel")
                or _has_trait(trigger_target, "sentinel")
            ):
                continue
            if reactor.per_action_uses.get(lock_key, 0) > 0:
                rule_trace.append(
                    {
                        "event": event,
                        "round": round_number,
                        "turn": turn_token,
                        "handler": "trait:sentinel_reaction",
                        "actor_id": reactor.actor_id,
                        "result": "skipped",
                        "reason": "reaction_lock",
                    }
                )
                continue
            attack_action = _fallback_action(reactor)
            if attack_action is None or attack_action.action_type != "attack":
                continue
            reactor.reaction_available = False
            reactor.per_action_uses[lock_key] = 1
            trigger_actor.movement_remaining = 0.0
            _execute_action(
                rng=rng,
                actor=reactor,
                action=attack_action,
                targets=[trigger_actor],
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )
            rule_trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "handler": "trait:sentinel_reaction",
                    "actor_id": reactor.actor_id,
                    "trigger_actor_id": trigger_actor.actor_id,
                    "result": "executed",
                }
            )

    if event == "after_action" and "spell" in trigger_action.tags:
        reactors = sorted(actors.values(), key=lambda value: value.actor_id)
        for reactor in reactors:
            if (
                reactor.team == trigger_actor.team
                or reactor.dead
                or reactor.hp <= 0
                or not reactor.reaction_available
                or not _has_trait(reactor, "mage slayer")
            ):
                continue
            if reactor.per_action_uses.get(lock_key, 0) > 0:
                rule_trace.append(
                    {
                        "event": event,
                        "round": round_number,
                        "turn": turn_token,
                        "handler": "trait:mage_slayer_reaction",
                        "actor_id": reactor.actor_id,
                        "result": "skipped",
                        "reason": "reaction_lock",
                    }
                )
                continue
            attack_action = _fallback_action(reactor)
            if attack_action is None or attack_action.action_type != "attack":
                continue
            reactor.reaction_available = False
            reactor.per_action_uses[lock_key] = 1
            _execute_action(
                rng=rng,
                actor=reactor,
                action=attack_action,
                targets=[trigger_actor],
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )
            rule_trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "handler": "trait:mage_slayer_reaction",
                    "actor_id": reactor.actor_id,
                    "trigger_actor_id": trigger_actor.actor_id,
                    "result": "executed",
                }
            )


def _dispatch_combat_event(
    *,
    rng: random.Random,
    event: str,
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
    actors: dict[str, ActorRuntimeState],
    round_number: int,
    turn_token: str,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    rule_trace: list[dict[str, Any]] | None = None,
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> list[dict[str, Any]]:
    if obstacles is None:
        obstacles = []
    trace = rule_trace if rule_trace is not None else []
    candidates: list[tuple[int, str, str, ActorRuntimeState, ActionDefinition]] = []
    for actor in actors.values():
        if actor.dead or actor.hp <= 0:
            continue
        for action in actor.actions:
            if action.event_trigger != event:
                continue
            if not _action_available(actor, action):
                continue
            candidates.append(
                (_event_trigger_priority(action), actor.actor_id, action.name, actor, action)
            )

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for _priority, actor_id, action_name, actor, action in candidates:
        if _event_trigger_is_expired(actor, action, round_number=round_number):
            trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "actor_id": actor_id,
                    "action": action_name,
                    "result": "skipped",
                    "reason": "expired",
                }
            )
            continue

        per_turn_limit = _event_trigger_limit_per_turn(action)
        per_turn_key = _event_trigger_turn_key(
            action,
            round_number=round_number,
            turn_token=turn_token,
        )
        if (
            per_turn_limit is not None
            and actor.per_action_uses.get(per_turn_key, 0) >= per_turn_limit
        ):
            trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "actor_id": actor_id,
                    "action": action_name,
                    "result": "skipped",
                    "reason": "per_turn_limit",
                }
            )
            continue

        lock_key = f"event_reaction_round:{round_number}"
        if (
            action.action_cost == "reaction"
            and _event_trigger_once_per_round(action)
            and actor.per_action_uses.get(lock_key, 0) > 0
        ):
            trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "actor_id": actor_id,
                    "action": action_name,
                    "result": "skipped",
                    "reason": "reaction_lock",
                }
            )
            continue

        targets = _resolve_event_targets(
            rng=rng,
            actor=actor,
            action=action,
            actors=actors,
            trigger_actor=trigger_actor,
            trigger_target=trigger_target,
        )
        if not targets:
            trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "actor_id": actor_id,
                    "action": action_name,
                    "result": "skipped",
                    "reason": "no_targets",
                }
            )
            continue

        spent = _spend_resources(actor, action.resource_cost)
        for key, amount in spent.items():
            resources_spent[actor.actor_id][key] = (
                resources_spent[actor.actor_id].get(key, 0) + amount
            )
        actor.per_action_uses[action.name] = actor.per_action_uses.get(action.name, 0) + 1
        actor.per_action_uses[per_turn_key] = actor.per_action_uses.get(per_turn_key, 0) + 1
        _mark_action_cost_used(actor, action)
        if action.action_cost == "reaction" and _event_trigger_once_per_round(action):
            actor.per_action_uses[lock_key] = actor.per_action_uses.get(lock_key, 0) + 1

        _execute_action(
            rng=rng,
            actor=actor,
            action=action,
            targets=targets,
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            obstacles=obstacles,
            light_level=light_level,
            round_number=round_number,
            turn_token=turn_token,
            rule_trace=trace,
        )
        trace.append(
            {
                "event": event,
                "round": round_number,
                "turn": turn_token,
                "actor_id": actor_id,
                "action": action_name,
                "result": "executed",
            }
        )

    _run_trait_event_handlers(
        rng=rng,
        event=event,
        trigger_actor=trigger_actor,
        trigger_target=trigger_target,
        trigger_action=trigger_action,
        actors=actors,
        round_number=round_number,
        turn_token=turn_token,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        rule_trace=trace,
        obstacles=obstacles,
        light_level=light_level,
    )
    return trace


def _run_event_triggered_actions(
    *,
    rng: random.Random,
    event: str,
    trigger_actor: ActorRuntimeState | None,
    actors: dict[str, ActorRuntimeState],
    round_number: int,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    rule_trace: list[dict[str, Any]] | None = None,
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> list[dict[str, Any]]:
    turn_token = (
        f"{round_number}:{trigger_actor.actor_id if trigger_actor is not None else 'global'}"
    )
    return _dispatch_combat_event(
        rng=rng,
        event=event,
        trigger_actor=trigger_actor,
        trigger_target=None,
        trigger_action=None,
        actors=actors,
        round_number=round_number,
        turn_token=turn_token,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        rule_trace=rule_trace,
        obstacles=obstacles,
        light_level=light_level,
    )
def _spell_level_from_action(action: ActionDefinition) -> int:
    slot_levels = []
    for key in action.resource_cost.keys():
        if not key.startswith("spell_slot_"):
            continue
        try:
            slot_levels.append(int(key.split("_")[-1]))
        except ValueError:
            continue
    return max(slot_levels) if slot_levels else 0


def _available_spell_slots(actor: ActorRuntimeState, *, minimum: int = 1) -> list[tuple[str, int]]:
    available: list[tuple[str, int]] = []
    for key, value in actor.resources.items():
        if not key.startswith("spell_slot_") or int(value) <= 0:
            continue
        try:
            level = int(key.split("_")[-1])
        except ValueError:
            continue
        if level >= minimum:
            available.append((key, level))
    available.sort(key=lambda item: item[1])
    return available


def _lowest_available_spell_slot(
    actor: ActorRuntimeState, *, minimum: int = 1
) -> tuple[str, int] | None:
    slots = _available_spell_slots(actor, minimum=minimum)
    return slots[0] if slots else None


def _select_counterspell_slot(
    actor: ActorRuntimeState, *, incoming_spell_level: int
) -> tuple[str, int] | None:
    available = _available_spell_slots(actor, minimum=3)
    if not available:
        return None
    guaranteed = [slot for slot in available if slot[1] >= max(3, incoming_spell_level)]
    if guaranteed:
        return guaranteed[0]
    return available[0]


def _fallback_action(
    actor: ActorRuntimeState, *, allow_special: bool = False
) -> ActionDefinition | None:
    disallowed = set() if allow_special else {"legendary", "lair", "reaction"}
    for action in actor.actions:
        if action.action_cost in disallowed:
            continue
        if action.name == "basic" and _action_available(actor, action):
            return action
    for action in actor.actions:
        if action.action_cost in disallowed:
            continue
        if _action_available(actor, action):
            return action
    return None


def _select_readied_action(actor: ActorRuntimeState) -> ActionDefinition | None:
    preferred_names = {"basic"}
    for action in actor.actions:
        if action.name in preferred_names and action.name != "ready":
            if action.action_cost in {"action", "none"} and _action_available(actor, action):
                return action
    for action in actor.actions:
        if action.name in {"ready", "dodge", "dash", "disengage"}:
            continue
        if action.action_cost in {"legendary", "lair", "reaction"}:
            continue
        if _action_available(actor, action):
            return action
    return None


def _normalize_event_trigger(trigger: str | None) -> str | None:
    if trigger is None:
        return None
    text = str(trigger).strip().lower()
    return text or None


def _trigger_readied_actions(
    *,
    rng: random.Random,
    trigger_actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> None:
    for actor in actors.values():
        if actor.team == trigger_actor.team:
            continue
        if actor.dead or actor.hp <= 0:
            continue
        if not actor.reaction_available:
            continue

        if "readying" in actor.conditions:
            readied_trigger = _normalize_event_trigger(actor.readied_trigger)
            if readied_trigger in {None, "enemy_turn_start", "on_enemy_turn_start"}:
                readied = _resolve_action_selection(actor, actor.readied_action_name)
                if readied.name != "ready":
                    reaction_action = replace(readied, action_cost="reaction")
                    if _action_available(actor, reaction_action):
                        targets = _resolve_targets_for_action(
                            rng=rng,
                            actor=actor,
                            action=reaction_action,
                            actors=actors,
                            requested=[TargetRef(trigger_actor.actor_id)],
                        )
                        targets = [
                            target
                            for target in targets
                            if target.actor_id == trigger_actor.actor_id
                        ]
                        targets = _filter_targets_in_range(actor, reaction_action, targets)
                        if targets and _spend_action_resource_cost(
                            actor, reaction_action, resources_spent
                        ):
                            actor.reaction_available = False
                            _execute_action(
                                rng=rng,
                                actor=actor,
                                action=reaction_action,
                                targets=targets,
                                actors=actors,
                                damage_dealt=damage_dealt,
                                damage_taken=damage_taken,
                                threat_scores=threat_scores,
                                resources_spent=resources_spent,
                                active_hazards=active_hazards,
                                obstacles=obstacles,
                                light_level=light_level,
                            )
                            _remove_condition(actor, "readying")
            if trigger_actor.dead or trigger_actor.hp <= 0:
                break

        if not actor.reaction_available:
            continue

        for reaction_action in actor.actions:
            if reaction_action.action_cost != "reaction":
                continue
            if reaction_action.name in {"shield", "counterspell"}:
                continue
            trigger = _normalize_event_trigger(reaction_action.event_trigger)
            if trigger not in {"enemy_turn_start", "on_enemy_turn_start"}:
                continue
            if not _action_available(actor, reaction_action):
                continue

            targets = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=reaction_action,
                actors=actors,
                requested=[TargetRef(trigger_actor.actor_id)],
            )
            targets = [target for target in targets if target.actor_id == trigger_actor.actor_id]
            targets = _filter_targets_in_range(actor, reaction_action, targets)
            if not targets:
                continue
            if not _spend_action_resource_cost(actor, reaction_action, resources_spent):
                continue

            actor.reaction_available = False
            _execute_action(
                rng=rng,
                actor=actor,
                action=reaction_action,
                targets=targets,
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
            )
            break

        if trigger_actor.dead or trigger_actor.hp <= 0:
            break
def _bardic_inspiration_die_sides(actor: ActorRuntimeState) -> int:
    if _has_trait(actor, "bardic inspiration (d12)"):
        return 12
    if _has_trait(actor, "bardic inspiration (d10)"):
        return 10
    if _has_trait(actor, "bardic inspiration (d8)"):
        return 8
    return 6


def _consume_bardic_inspiration_die(
    actor: ActorRuntimeState,
    resources_spent: dict[str, dict[str, int]],
) -> int:
    key = "bardic_inspiration_die"
    die_sides = int(actor.resources.get(key, 0))
    if die_sides <= 0:
        return 0
    actor.resources[key] = 0
    resources_spent[actor.actor_id][key] = resources_spent[actor.actor_id].get(key, 0) + 1
    return die_sides


def _try_spend_bardic_inspiration_on_attack_roll(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    roll: AttackRollResult,
    target_ac: int,
    resources_spent: dict[str, dict[str, int]],
) -> AttackRollResult:
    if roll.hit or roll.natural_roll == 20:
        return roll
    die_sides = int(actor.resources.get("bardic_inspiration_die", 0))
    if die_sides <= 0:
        return roll
    if roll.total + die_sides < target_ac:
        return roll

    consumed = _consume_bardic_inspiration_die(actor, resources_spent)
    if consumed <= 0:
        return roll
    bonus = rng.randint(1, consumed)
    total = roll.total + bonus
    hit = roll.crit or (roll.natural_roll != 1 and total >= target_ac)
    return AttackRollResult(hit=hit, crit=roll.crit, natural_roll=roll.natural_roll, total=total)


def _try_spend_bardic_inspiration_on_save(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    save_roll: int,
    save_mod: int,
    dc: int,
    resources_spent: dict[str, dict[str, int]],
) -> int:
    if save_roll + save_mod >= dc:
        return save_roll
    die_sides = int(actor.resources.get("bardic_inspiration_die", 0))
    if die_sides <= 0:
        return save_roll
    if save_roll + save_mod + die_sides < dc:
        return save_roll

    consumed = _consume_bardic_inspiration_die(actor, resources_spent)
    if consumed <= 0:
        return save_roll
    return save_roll + rng.randint(1, consumed)


def _find_cutting_words_reactor(
    *,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
) -> ActorRuntimeState | None:
    from .spatial import distance_chebyshev

    if "all" in attacker.condition_immunities or "charmed" in attacker.condition_immunities:
        return None

    candidates: list[tuple[int, ActorRuntimeState]] = []
    for ally in actors.values():
        if ally.team != target.team:
            continue
        if ally.dead or ally.hp <= 0:
            continue
        if not ally.reaction_available:
            continue
        if not _has_trait(ally, "cutting words"):
            continue
        if ally.resources.get("bardic_inspiration", 0) <= 0:
            continue
        if distance_chebyshev(ally.position, attacker.position) > 60:
            continue
        candidates.append((_bardic_inspiration_die_sides(ally), ally))

    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def _spend_cutting_words_reaction(
    *,
    rng: random.Random,
    reactor: ActorRuntimeState,
    resources_spent: dict[str, dict[str, int]],
) -> int:
    die_sides = _bardic_inspiration_die_sides(reactor)
    if die_sides <= 0:
        return 0
    reactor.resources["bardic_inspiration"] = max(
        0, reactor.resources.get("bardic_inspiration", 0) - 1
    )
    reactor.reaction_available = False
    resources_spent[reactor.actor_id]["bardic_inspiration"] = (
        resources_spent[reactor.actor_id].get("bardic_inspiration", 0) + 1
    )
    return rng.randint(1, die_sides)


def _try_cutting_words_on_attack_roll(
    *,
    rng: random.Random,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    roll: AttackRollResult,
    target_ac: int,
    actors: dict[str, ActorRuntimeState],
    resources_spent: dict[str, dict[str, int]],
) -> AttackRollResult:
    if not roll.hit or roll.natural_roll == 20:
        return roll
    reactor = _find_cutting_words_reactor(attacker=attacker, target=target, actors=actors)
    if reactor is None:
        return roll
    max_reduction = _bardic_inspiration_die_sides(reactor)
    if roll.total - max_reduction >= target_ac:
        return roll
    reduction = _spend_cutting_words_reaction(
        rng=rng, reactor=reactor, resources_spent=resources_spent
    )
    if reduction <= 0:
        return roll
    total = roll.total - reduction
    hit = roll.crit or (roll.natural_roll != 1 and total >= target_ac)
    return AttackRollResult(hit=hit, crit=roll.crit, natural_roll=roll.natural_roll, total=total)


def _try_cutting_words_on_damage_roll(
    *,
    rng: random.Random,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    raw_damage: int,
    actors: dict[str, ActorRuntimeState],
    resources_spent: dict[str, dict[str, int]],
) -> int:
    if raw_damage <= 0:
        return raw_damage
    reactor = _find_cutting_words_reactor(attacker=attacker, target=target, actors=actors)
    if reactor is None:
        return raw_damage
    reduction = _spend_cutting_words_reaction(
        rng=rng, reactor=reactor, resources_spent=resources_spent
    )
    if reduction <= 0:
        return raw_damage
    return max(0, raw_damage - reduction)


def _try_shield_reaction(
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    roll: AttackRollResult,
) -> bool:
    """Always-use Shield reaction: +5 AC to negate a hit. Consumes reaction + spell slot.

    Returns True if the hit was negated.
    """
    if not _can_take_reaction(target):
        return False
    shield_action = None
    for action in target.actions:
        if action.name == "shield" and action.action_cost == "reaction":
            shield_action = action
            break
    if shield_action is None:
        return False
    # Need a 1st-level spell slot (or any available slot)
    slot_key = None
    for key in sorted(target.resources.keys()):
        if key.startswith("spell_slot_") and target.resources.get(key, 0) > 0:
            slot_key = key
            break
    if slot_key is None:
        return False
    # Shield: +5 AC. Only use if it would actually negate the hit.
    if roll.total < (target.ac + 5) and roll.natural_roll != 20:
        target.resources[slot_key] -= 1
        target.reaction_available = False
        return True
    return False


def _find_best_bonus_action(actor: ActorRuntimeState) -> ActionDefinition | None:
    """Find the best available bonus action for a character."""
    # Phase 10: Dynamic Barbarian Rage Activation
    if (
        _has_trait(actor, "rage")
        and actor.resources.get("rage", 0) > 0
        and "raging" not in actor.conditions
        and actor.bonus_available
    ):
        return ActionDefinition(
            name="rage_activation",
            action_type="buff",
            action_cost="bonus",
            target_mode="self",
            resource_cost={"rage": 1},
            effects=[
                {
                    "effect_type": "apply_condition",
                    "condition": "raging",
                    "duration_rounds": 10,
                    "target": "self",
                }
            ],
        )

    best: ActionDefinition | None = None
    for action in actor.actions:
        if action.action_cost != "bonus":
            continue
        if not _action_available(actor, action):
            continue
        if (
            "off_hand" in action.tags
            or "martial_arts" in action.tags
            or "polearm_master" in action.tags
            or "gwm_bonus" in action.tags
        ):
            if not actor.took_attack_action_this_turn:
                continue
            if "gwm_bonus" in action.tags and "gwm_bonus_triggered" not in actor.conditions:
                continue
        if best is None or action.action_type == "attack":
            best = action
    return best


def _spellcasting_ability_mod(actor: ActorRuntimeState) -> int:
    return max(actor.int_mod, actor.wis_mod, actor.cha_mod)


def _resolve_dispel_magic(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    dispel_level = max(3, _spell_level_from_action(action))
    check_mod = _spellcasting_ability_mod(actor)
    for target in targets:
        affecting_sources = [
            source
            for source in actors.values()
            if source.concentrating
            and target.actor_id in source.concentrated_targets
            and source.actor_id != actor.actor_id
        ]
        if not affecting_sources:
            continue
        affecting_sources.sort(
            key=lambda source: (source.concentrated_spell_level or 0, source.actor_id),
            reverse=True,
        )
        source = affecting_sources[0]
        source_level = int(source.concentrated_spell_level or 0)
        if source_level <= dispel_level:
            _break_concentration(source, actors, active_hazards)
            continue
        dc = 10 + source_level
        if (rng.randint(1, 20) + check_mod) >= dc:
            _break_concentration(source, actors, active_hazards)
def _apply_domain_attack_roll_hooks(
    *,
    actor: ActorRuntimeState,
    roll: AttackRollResult,
    target_ac: int,
    actors: dict[str, ActorRuntimeState],
    resources_spent: dict[str, dict[str, int]],
) -> AttackRollResult:
    if roll.hit or roll.natural_roll == 1:
        return roll

    guided_strike_traits = ["guided strike", "channel divinity: guided strike"]
    boosted_total = roll.total + 10
    if boosted_total >= target_ac and _has_any_trait(actor, guided_strike_traits):
        if _spend_channel_divinity(actor, resources_spent):
            return AttackRollResult(
                hit=True,
                crit=roll.crit,
                natural_roll=roll.natural_roll,
                total=boosted_total,
            )

    war_gods_blessing_traits = [
        "war god's blessing",
        "channel divinity: war god's blessing",
        "oketra's blessing",
    ]
    if boosted_total < target_ac:
        return roll

    from .spatial import distance_chebyshev

    for ally in actors.values():
        if ally.team != actor.team or ally.actor_id == actor.actor_id:
            continue
        if not ally.reaction_available:
            continue
        if not _has_any_trait(ally, war_gods_blessing_traits):
            continue
        if distance_chebyshev(ally.position, actor.position) > 30:
            continue
        if not _spend_channel_divinity(ally, resources_spent):
            continue
        ally.reaction_available = False
        return AttackRollResult(
            hit=True,
            crit=roll.crit,
            natural_roll=roll.natural_roll,
            total=boosted_total,
        )

    return roll


def _execute_action(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
    round_number: int | None = None,
    turn_token: str | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
) -> None:
    if not targets:
        return
    if obstacles is None:
        obstacles = []
    _force_end_concentration_if_needed(actor, actors=actors, active_hazards=active_hazards)

    def emit_event(
        event_name: str,
        *,
        trigger_target: ActorRuntimeState | None = None,
    ) -> None:
        if round_number is None or turn_token is None:
            return
        _dispatch_combat_event(
            rng=rng,
            event=event_name,
            trigger_actor=actor,
            trigger_target=trigger_target,
            trigger_action=action,
            actors=actors,
            round_number=round_number,
            turn_token=turn_token,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            rule_trace=rule_trace,
            obstacles=obstacles,
            light_level=light_level,
        )

    if _requires_range_resolution(action):
        in_range = _move_actor_for_action_range(
            rng=rng,
            actor=actor,
            action=action,
            targets=targets,
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            obstacles=obstacles,
            light_level=light_level,
        )
        if not in_range:
            return
        targets = _filter_targets_in_range(actor, action, targets)
        if not targets:
            return

    # Counterspell check
    if "spell" in action.tags:
        if not _can_cast_spell_with_components(actor, action):
            return
        spell_level = _spell_level_from_action(action)
        for enemy in actors.values():
            if (
                enemy.team != actor.team
                and enemy.hp > 0
                and not enemy.dead
                and _can_take_reaction(enemy)
            ):
                cs_action = next(
                    (
                        a
                        for a in enemy.actions
                        if a.name == "counterspell" and a.action_cost == "reaction"
                    ),
                    None,
                )
                if cs_action:
                    if distance_chebyshev(enemy.position, actor.position) <= 60:
                        counter_slot = _select_counterspell_slot(
                            enemy, incoming_spell_level=spell_level
                        )
                        if counter_slot:
                            slot_key, counter_level = counter_slot
                            enemy.resources[slot_key] -= 1
                            enemy.reaction_available = False
                            if counter_level >= spell_level:
                                return  # Spell countered automatically.
                            check_dc = 10 + spell_level
                            check_total = rng.randint(1, 20) + enemy.cha_mod
                            if check_total >= check_dc:
                                return  # Spell countered after ability check.

        if action.concentration:
            _break_concentration(actor, actors, active_hazards)
            actor.concentrating = True
            actor.concentrated_spell = action.name
            actor.concentrated_spell_level = spell_level
            actor.concentration_conditions = {
                str(effect.get("condition", "")).lower()
                for effect in action.effects + action.mechanics
                if isinstance(effect, dict)
                if effect.get("effect_type") == "apply_condition"
                and str(effect.get("condition", "")).strip()
            }
            if _is_smite_setup_action(action):
                actor.concentration_conditions.clear()
                actor.concentrated_targets.clear()

    # Phase 11: Contested Grapple/Shove Checks
    if action.action_type in ("grapple", "shove") and targets:
        from .rules_2014 import run_contested_check

        target = targets[0]
        if "raging" in actor.conditions and target.team != actor.team:
            actor.rage_sustained_since_last_turn = True

        # Determine attacker mod (Athletics -> STR)
        attacker_mod = actor.str_mod
        if "athletics" in actor.proficiencies:
            attacker_mod += _calculate_proficiency_bonus(actor.level)
            if "athletics" in actor.expertise:
                attacker_mod += _calculate_proficiency_bonus(actor.level)

        # Determine defender mods (Athletics or Acrobatics)
        defender_athletics = target.str_mod
        defender_acrobatics = target.dex_mod
        if "athletics" in target.proficiencies:
            defender_athletics += _calculate_proficiency_bonus(target.level)
            if "athletics" in target.expertise:
                defender_athletics += _calculate_proficiency_bonus(target.level)
        if "acrobatics" in target.proficiencies:
            defender_acrobatics += _calculate_proficiency_bonus(target.level)
            if "acrobatics" in target.expertise:
                defender_acrobatics += _calculate_proficiency_bonus(target.level)

        # Run Mathematical Check
        success = run_contested_check(rng, attacker_mod, [defender_athletics, defender_acrobatics])

        if success:
            if action.action_type == "grapple":
                _apply_condition(target, "grappled", duration_rounds=100)
            elif action.action_type == "shove":
                _apply_condition(target, "prone", duration_rounds=100)

        if action.action_cost == "action":
            actor.took_attack_action_this_turn = True
        return

    if action.action_type == "attack":
        if action.action_cost == "action":
            actor.took_attack_action_this_turn = True

        if action.to_hit is None:
            return
        # Build preferred target queue for multiattack redirect.
        preferred_ids = [t.actor_id for t in targets]
        per_target_attack = "volley" in action.tags or "whirlwind_attack" in action.tags
        if per_target_attack:
            attack_iterations = len(preferred_ids)
        else:
            attack_iterations = max(1, action.attack_count)

        current_target: ActorRuntimeState | None = None
        for i in range(attack_iterations):
            # Find a living target: try current, then preferred list, then any enemy
            if per_target_attack:
                current_target = None
                if i < len(preferred_ids):
                    candidate = actors.get(preferred_ids[i])
                    if candidate and not candidate.dead and candidate.hp > 0:
                        current_target = candidate
                if current_target is None:
                    continue
            elif current_target is None or current_target.dead or current_target.hp <= 0:
                current_target = None
                for pid in preferred_ids:
                    candidate = actors.get(pid)
                    if candidate and not candidate.dead and candidate.hp > 0:
                        current_target = candidate
                        break
                if current_target is None:
                    # Fallback to any living enemy sorted by lowest HP
                    fallbacks = sorted(
                        [
                            t
                            for t in actors.values()
                            if t.team != actor.team and not t.dead and t.hp > 0
                        ],
                        key=lambda t: (t.hp, t.max_hp),
                    )
                    if fallbacks:
                        current_target = fallbacks[0]
                if current_target is None:
                    break
            target = current_target
            if "raging" in actor.conditions and target.team != actor.team:
                actor.rage_sustained_since_last_turn = True
            advantage, disadvantage = _consume_attack_flags(actor)
            # Target condition-based advantage/auto-crit
            target_conditions = target.conditions
            if target_conditions.intersection(_ATTACKER_ADVANTAGE_CONDITIONS):
                advantage = True
            if "prone" in target_conditions:
                if distance_chebyshev(actor.position, target.position) <= 5.0:
                    advantage = True
                else:
                    disadvantage = True
            if "dodging" in target_conditions:
                disadvantage = True
            force_crit = bool(target_conditions.intersection(_AUTO_CRIT_CONDITIONS))

            # Phase 12: Illumination & Vision Mechanics
            from .spatial import can_see, check_cover

            # Attacker's vision of the target
            attacker_can_see = can_see(
                observer_pos=actor.position,
                target_pos=target.position,
                observer_traits=actor.traits,
                target_conditions=target.conditions,
                active_hazards=active_hazards,
                light_level=light_level,
            )
            # Target's vision of the attacker
            target_can_see = can_see(
                observer_pos=target.position,
                target_pos=actor.position,
                observer_traits=target.traits,
                target_conditions=actor.conditions,
                active_hazards=active_hazards,
                light_level=light_level,
            )

            # Apply RAW Unseen Attacker / Unseen Target rules
            if not attacker_can_see:
                disadvantage = True
            if not target_can_see:
                advantage = True

            # Sharpshooter / Great Weapon Master AI Toggle (-5 to hit / +10 damage)
            power_attack_active = False
            target_ac = target.ac
            cover_bonus = 0
            to_hit_penalty = 0
            damage_bonus = 0

            if action.to_hit is not None:
                weapon_name = action.name.lower()
                inferred_range = _action_range_ft(action)
                is_ranged = bool(inferred_range is not None and inferred_range > 5.0)
                if not is_ranged:
                    is_ranged = any(
                        w in weapon_name
                        for w in ["bow", "dart", "sling", "javelin", "blowgun", "net"]
                    ) or (action.range_ft is not None and action.range_ft > 5)
                is_heavy = any(
                    w in weapon_name
                    for w in [
                        "greatsword",
                        "greataxe",
                        "maul",
                        "glaive",
                        "halberd",
                        "pike",
                        "heavy crossbow",
                    ]
                )

                # Phase 9: Dynamic 3D Raycasting Cover
                cover_state = check_cover(actor.position, target.position, obstacles)
                if cover_state == "TOTAL":
                    _apply_action_effects(
                        action=action,
                        event="miss",
                        rng=rng,
                        actor=actor,
                        target=target,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        actors=actors,
                        active_hazards=active_hazards,
                        round_number=round_number,
                        turn_token=turn_token,
                        rule_trace=rule_trace,
                    )
                    emit_event("on_miss", trigger_target=target)
                    continue
                if cover_state == "HALF":
                    cover_bonus = max(cover_bonus, 2)
                elif cover_state == "THREE_QUARTERS":
                    cover_bonus = max(cover_bonus, 5)
                cover_bonus = max(
                    cover_bonus,
                    _smite_of_protection_half_cover_bonus(target, actors),
                )
                target_ac += cover_bonus

                if _has_trait(actor, "sharpshooter") and is_ranged:
                    if target_ac <= 16 or advantage:
                        power_attack_active = True
                elif _has_trait(actor, "great weapon master") and is_heavy:
                    if target_ac <= 16 or advantage:
                        power_attack_active = True

            if _has_trait(actor, "reckless attack") and not is_ranged:
                advantage = True
                _apply_condition(actor, "reckless_attacking", duration_rounds=1)

            to_hit_penalty = -5 if power_attack_active else 0
            damage_bonus = 10 if power_attack_active else 0

            # Phase 10: Barbarian Rage STR Bonus
            if "raging" in actor.conditions and not is_ranged:
                rage_bonus = 2 if actor.level < 9 else 3 if actor.level < 16 else 4
                damage_bonus += rage_bonus

            roll = attack_roll(
                rng,
                action.to_hit + to_hit_penalty if action.to_hit is not None else 0,
                target_ac,
                advantage=advantage,
                disadvantage=disadvantage,
            )
            roll = _try_spend_bardic_inspiration_on_attack_roll(
                rng=rng,
                actor=actor,
                roll=roll,
                target_ac=target_ac,
                resources_spent=resources_spent,
            )

            # Lucky: Attacker rerolls miss
            if (
                not roll.hit
                and _has_trait(actor, "lucky")
                and actor.resources.get("luck_points", 0) > 0
            ):
                actor.resources["luck_points"] -= 1
                resources_spent[actor.actor_id]["luck_points"] = (
                    resources_spent[actor.actor_id].get("luck_points", 0) + 1
                )
                lucky_natural = rng.randint(1, 20)
                new_natural = max(roll.natural_roll, lucky_natural)
                crit = new_natural == 20
                to_hit_mod = action.to_hit + to_hit_penalty if action.to_hit is not None else 0
                total = new_natural + to_hit_mod
                hit = crit or (new_natural != 1 and total >= target_ac)
                roll = AttackRollResult(hit=hit, crit=crit, natural_roll=new_natural, total=total)

            # Lucky: Defender forces reroll on hit
            if (
                roll.hit
                and _has_trait(target, "lucky")
                and target.resources.get("luck_points", 0) > 0
            ):
                target.resources["luck_points"] -= 1
                resources_spent[target.actor_id]["luck_points"] = (
                    resources_spent[target.actor_id].get("luck_points", 0) + 1
                )
                lucky_natural = rng.randint(1, 20)
                new_natural = min(roll.natural_roll, lucky_natural)
                crit = new_natural == 20
                to_hit_mod = action.to_hit + to_hit_penalty if action.to_hit is not None else 0
                total = new_natural + to_hit_mod
                hit = crit or (new_natural != 1 and total >= target_ac)
                roll = AttackRollResult(hit=hit, crit=crit, natural_roll=new_natural, total=total)

            roll = _apply_domain_attack_roll_hooks(
                actor=actor,
                roll=roll,
                target_ac=target_ac,
                actors=actors,
                resources_spent=resources_spent,
            )

            if force_crit and roll.hit:
                roll = AttackRollResult(
                    hit=True, crit=True, natural_roll=roll.natural_roll, total=roll.total
                )
            roll = _try_cutting_words_on_attack_roll(
                rng=rng,
                attacker=actor,
                target=target,
                roll=roll,
                target_ac=target_ac,
                actors=actors,
                resources_spent=resources_spent,
            )
            event = "hit" if roll.hit else "miss"
            # Shield reaction: always use if available and would negate hit
            if roll.hit and _try_shield_reaction(actor, target, roll):
                event = "miss"
                roll = AttackRollResult(
                    hit=False, crit=False, natural_roll=roll.natural_roll, total=roll.total
                )
            if roll.hit and action.damage:
                empowered_rerolls = 0
                if (
                    "spell" in action.tags
                    and _has_trait(actor, "empowered spell")
                    and actor.resources.get("sorcery_points", 0) >= 1
                ):
                    actor.resources["sorcery_points"] -= 1
                    resources_spent[actor.actor_id]["sorcery_points"] = (
                        resources_spent[actor.actor_id].get("sorcery_points", 0) + 1
                    )
                    empowered_rerolls = max(1, actor.cha_mod)
                damage_expr = action.damage
                sneak_damage_expr: str | None = None

                # Sneak Attack Logic
                if (
                    _has_trait(actor, "sneak attack")
                    and getattr(actor, "sneak_attack_used_this_turn", False) is False
                    and not getattr(actor, "is_heavy", False)
                ):
                    # Finesse or ranged
                    if (
                        is_ranged
                        or getattr(action, "is_finesse", False)
                        or "finesse" in action.tags
                        or "finesse" in action.name.lower()
                        or any(
                            w in weapon_name
                            for w in ["dagger", "shortsword", "rapier", "scimitar", "dart", "whip"]
                        )
                    ):
                        has_sneak = False
                        if advantage and not disadvantage:
                            has_sneak = True
                        elif not disadvantage:
                            # ally within 5ft
                            for cand in actors.values():
                                if (
                                    cand.team == actor.team
                                    and cand.actor_id != actor.actor_id
                                    and cand.hp > 0
                                    and not cand.dead
                                ):
                                    if distance_chebyshev(cand.position, target.position) <= 5:
                                        has_sneak = True
                                        break
                        if has_sneak:
                            actor.sneak_attack_used_this_turn = True
                            sa_dice = (actor.level + 1) // 2
                            sneak_damage_expr = f"{sa_dice}d6"

                if power_attack_active and damage_expr:
                    damage_expr += f"{damage_bonus:+d}"
                raw_damage = _roll_damage_with_channel_divinity_hooks(
                    rng=rng,
                    actor=actor,
                    expr=damage_expr,
                    damage_type=action.damage_type,
                    resources_spent=resources_spent,
                    crit=roll.crit,
                    empowered_rerolls=empowered_rerolls,
                )
                if roll.crit and _has_trait(actor, "brutal critical") and not is_ranged:
                    brutal_extra = 0
                    if actor.level >= 17:
                        brutal_extra = 3
                    elif actor.level >= 13:
                        brutal_extra = 2
                    elif actor.level >= 9:
                        brutal_extra = 1
                    brutal_expr = _critical_bonus_dice_expr(action.damage, brutal_extra)
                    if brutal_expr:
                        raw_damage += roll_damage(
                            rng,
                            brutal_expr,
                            crit=False,
                            source=actor,
                            damage_type=action.damage_type,
                        )
                if sneak_damage_expr:
                    raw_damage += roll_damage(
                        rng,
                        sneak_damage_expr,
                        crit=roll.crit,
                        source=actor,
                        damage_type=action.damage_type,
                    )

                if _has_trait(actor, "improved divine smite") and not is_ranged:
                    raw_damage += roll_damage(
                        rng,
                        "1d8",
                        crit=roll.crit,
                        source=actor,
                        damage_type="radiant",
                    )

                # Divine Smite Logic
                if _has_trait(actor, "divine smite") and not is_ranged and target.hp > 0:
                    slot_level = 0
                    sp_key = None
                    for key in sorted(
                        [k for k in actor.resources.keys() if k.startswith("spell_slot_")],
                        reverse=True,
                    ):
                        if actor.resources[key] > 0:
                            sp_key = key
                            slot_level = int(key.split("_")[-1])
                            break
                    if sp_key:
                        actor.resources[sp_key] -= 1
                        resources_spent[actor.actor_id][sp_key] = (
                            resources_spent[actor.actor_id].get(sp_key, 0) + 1
                        )
                    elif actor.resources.get("paladins_smite_free", 0) > 0:
                        actor.resources["paladins_smite_free"] -= 1
                        resources_spent[actor.actor_id]["paladins_smite_free"] = (
                            resources_spent[actor.actor_id].get("paladins_smite_free", 0) + 1
                        )
                        slot_level = 1
                    if sp_key or slot_level > 0:
                        smite_dice = min(5, 1 + slot_level)
                        raw_smite = roll_damage(
                            rng,
                            f"{smite_dice}d8",
                            crit=roll.crit,
                            source=actor,
                            damage_type="radiant",
                        )
                        raw_damage += raw_smite
                was_active_before_damage = target.hp > 0 and not target.dead
                raw_damage = _try_cutting_words_on_damage_roll(
                    rng=rng,
                    attacker=actor,
                    target=target,
                    raw_damage=raw_damage,
                    actors=actors,
                    resources_spent=resources_spent,
                )
                was_active_before_damage = target.hp > 0 and not target.dead
                applied = apply_damage(
                    target,
                    raw_damage,
                    action.damage_type,
                    is_critical=roll.crit,
                    is_magical="spell" in action.tags or "magical" in action.tags,
                    source=actor,
                )
                if applied > 0:
                    if not _force_end_concentration_if_needed(
                        target, actors=actors, active_hazards=active_hazards
                    ) and not run_concentration_check(rng, target, applied, source=actor):
                        _break_concentration(target, actors, active_hazards)
                damage_dealt[actor.actor_id] += applied
                damage_taken[target.actor_id] += applied
                threat_scores[actor.actor_id] += applied
                if was_active_before_damage and target.hp <= 0:
                    emit_event("on_down", trigger_target=target)

                if _has_trait(target, "multiattack defense"):
                    target.conditions.add(_multiattack_defense_marker(actor.actor_id))

                # GWM Momentum Trigger (Action Economy Buff)
                if (
                    _has_trait(actor, "great weapon master")
                    and (roll.crit or target.hp <= 0)
                    and not is_ranged
                ):
                    actor.conditions.add("gwm_bonus_triggered")
            if roll.hit:
                _try_stunning_strike(
                    rng=rng,
                    actor=actor,
                    target=target,
                    is_ranged=is_ranged,
                    resources_spent=resources_spent,
                )
                _try_open_hand_technique(
                    rng=rng,
                    actor=actor,
                    action=action,
                    target=target,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    actors=actors,
                    active_hazards=active_hazards,
                )
            _apply_action_effects(
                action=action,
                event=event,
                rng=rng,
                actor=actor,
                target=target,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                actors=actors,
                active_hazards=active_hazards,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )
            emit_event(f"on_{event}", trigger_target=target)
        return

    if action.action_type == "save":
        if action.save_dc is None or not action.save_ability:
            return
        save_key = action.save_ability.lower()

        # Roll AoE damage once and apply per-target save outcomes.
        raw_damage = 0
        if action.damage:
            empowered_rerolls = 0
            if (
                "spell" in action.tags
                and _has_trait(actor, "empowered spell")
                and actor.resources.get("sorcery_points", 0) >= 1
            ):
                actor.resources["sorcery_points"] -= 1
                resources_spent[actor.actor_id]["sorcery_points"] = (
                    resources_spent[actor.actor_id].get("sorcery_points", 0) + 1
                )
                empowered_rerolls = max(1, actor.cha_mod)
            raw_damage = _roll_damage_with_channel_divinity_hooks(
                rng=rng,
                actor=actor,
                expr=action.damage,
                damage_type=action.damage_type,
                resources_spent=resources_spent,
                crit=False,
                empowered_rerolls=empowered_rerolls,
            )
        if raw_damage > 0:
            primary_enemy_target = next(
                (
                    candidate
                    for candidate in targets
                    if candidate.team != actor.team and candidate.hp > 0 and not candidate.dead
                ),
                None,
            )
            if primary_enemy_target is not None:
                raw_damage = _try_cutting_words_on_damage_roll(
                    rng=rng,
                    attacker=actor,
                    target=primary_enemy_target,
                    raw_damage=raw_damage,
                    actors=actors,
                    resources_spent=resources_spent,
                )

        careful_allies = set()
        if (
            "spell" in action.tags
            and _has_trait(actor, "careful spell")
            and actor.resources.get("sorcery_points", 0) >= 1
        ):
            allies = [t for t in targets if t.team == actor.team and t.hp > 0 and not t.dead]
            if allies:
                actor.resources["sorcery_points"] -= 1
                resources_spent[actor.actor_id]["sorcery_points"] = (
                    resources_spent[actor.actor_id].get("sorcery_points", 0) + 1
                )
                num_careful = max(1, actor.cha_mod)
                careful_allies = set([a.actor_id for a in allies[:num_careful]])

        for target in targets:
            if target.dead or target.hp <= 0:
                continue
            save_mod = int(target.save_mods.get(save_key, 0))
            if save_key == "dex":
                save_mod += _smite_of_protection_half_cover_bonus(target, actors)
            save_roll = rng.randint(1, 20)
            if (
                save_key == "dex"
                and _has_trait(target, "danger sense")
                and not target.conditions.intersection({"blinded", "deafened", "incapacitated"})
            ):
                save_roll = max(save_roll, rng.randint(1, 20))
            if (
                "spell" in action.tags
                and _has_trait(target, "gnomish cunning")
                and save_key in {"int", "wis", "cha"}
            ):
                save_roll = max(save_roll, rng.randint(1, 20))
            if save_key == "dex" and "dodging" in target.conditions:
                save_roll = max(save_roll, rng.randint(1, 20))
            if "spell" in action.tags and _has_trait(target, "mage slayer"):
                save_roll = max(save_roll, rng.randint(1, 20))
            success = (save_roll + save_mod) >= action.save_dc
            if not success:
                save_roll = _try_spend_bardic_inspiration_on_save(
                    rng=rng,
                    actor=target,
                    save_roll=save_roll,
                    save_mod=save_mod,
                    dc=action.save_dc,
                    resources_spent=resources_spent,
                )
                success = (save_roll + save_mod) >= action.save_dc

            # Lucky: Reroll failed save
            if (
                not success
                and _has_trait(target, "lucky")
                and target.resources.get("luck_points", 0) > 0
            ):
                target.resources["luck_points"] -= 1
                resources_spent[target.actor_id]["luck_points"] = (
                    resources_spent[target.actor_id].get("luck_points", 0) + 1
                )
                lucky_roll = rng.randint(1, 20)
                save_roll = max(save_roll, lucky_roll)
                success = (save_roll + save_mod) >= action.save_dc

            if target.actor_id in careful_allies:
                success = True
            if not success and target.resources.get("legendary_resistance", 0) > 0:
                target.resources["legendary_resistance"] -= 1
                resources_spent[target.actor_id]["legendary_resistance"] = (
                    resources_spent[target.actor_id].get("legendary_resistance", 0) + 1
                )
                success = True

            final_damage = raw_damage
            if success:
                final_damage = raw_damage // 2 if action.half_on_save else 0
            elif (
                action.save_ability == "dex"
                and _has_trait(target, "evasion")
                and action.half_on_save
            ):
                final_damage = raw_damage // 2

            if success and action.save_ability == "dex":
                if _has_trait(target, "evasion"):
                    final_damage = 0
                elif (
                    _has_trait(target, "shield master")
                    and action.half_on_save
                    and _can_take_reaction(target)
                ):
                    final_damage = 0
                    target.reaction_available = False

            was_active_before_damage = target.hp > 0 and not target.dead
            applied = apply_damage(
                target,
                final_damage,
                action.damage_type,
                is_magical="spell" in action.tags or "magical" in action.tags,
                source=actor,
            )
            if applied > 0:
                if not _force_end_concentration_if_needed(
                    target, actors=actors, active_hazards=active_hazards
                ) and not run_concentration_check(rng, target, applied, source=actor):
                    _break_concentration(target, actors, active_hazards)
                damage_dealt[actor.actor_id] += applied
                damage_taken[target.actor_id] += applied
                threat_scores[actor.actor_id] += applied
                if was_active_before_damage and target.hp <= 0:
                    emit_event("on_down", trigger_target=target)

            _apply_action_effects(
                action=action,
                event="save_success" if success else "save_fail",
                rng=rng,
                actor=actor,
                target=target,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                actors=actors,
                active_hazards=active_hazards,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )
            emit_event("on_save", trigger_target=target)
        return

    if action.action_type in {"utility", "buff"}:
        if "dispel" in action.tags or action.name.startswith("dispel_magic"):
            _resolve_dispel_magic(
                rng=rng,
                actor=actor,
                action=action,
                targets=targets,
                actors=actors,
                active_hazards=active_hazards,
            )
            return
        if action.name == "dodge":
            _apply_condition(actor, "dodging", duration_rounds=1)
            return
        if action.name == "disengage":
            _apply_condition(actor, "disengaging", duration_rounds=1)
            return
        if action.name == "dash":
            actor.movement_remaining += actor.speed_ft
            return
        if action.name == "ready":
            _apply_condition(actor, "readying", duration_rounds=1)
            readied_action = _select_readied_action(actor)
            actor.readied_action_name = readied_action.name if readied_action else None
            actor.readied_trigger = action.event_trigger or "enemy_turn_start"
            return
        if action.name == "bardic_inspiration":
            die_sides = _bardic_inspiration_die_sides(actor)
            for target in targets:
                if target.actor_id == actor.actor_id:
                    continue
                target.resources["bardic_inspiration_die"] = die_sides
            return

        for target in targets:
            _apply_action_effects(
                action=action,
                event="always",
                rng=rng,
                actor=actor,
                target=target,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                actors=actors,
                active_hazards=active_hazards,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )


def _build_round_metadata(
    *,
    actors: dict[str, ActorRuntimeState],
    threat_scores: dict[str, int],
    burst_round_threshold: int,
    active_hazards: list[dict[str, Any]] | None = None,
    light_level: str = "bright",
) -> dict[str, Any]:
    return {
        "threat_scores": dict(threat_scores),
        "burst_round_threshold": burst_round_threshold,
        "active_hazards": list(active_hazards or []),
        "light_level": str(light_level),
        "available_actions": {
            actor_id: [action.name for action in actor.actions if _action_available(actor, action)]
            for actor_id, actor in actors.items()
        },
        "action_catalog": {
            actor_id: [
                {
                    "name": action.name,
                    "action_type": action.action_type,
                    "to_hit": action.to_hit,
                    "damage": action.damage,
                    "damage_type": action.damage_type,
                    "attack_count": action.attack_count,
                    "save_dc": action.save_dc,
                    "save_ability": action.save_ability,
                    "half_on_save": action.half_on_save,
                    "resource_cost": dict(action.resource_cost),
                    "max_uses": action.max_uses,
                    "used_count": actor.per_action_uses.get(action.name, 0),
                    "action_cost": action.action_cost,
                    "event_trigger": action.event_trigger,
                    "trigger_duration_rounds": action.trigger_duration_rounds,
                    "trigger_limit_per_turn": action.trigger_limit_per_turn,
                    "trigger_once_per_round": action.trigger_once_per_round,
                    "recharge_ready": actor.recharge_ready.get(action.name, True),
                    "target_mode": action.target_mode,
                    "range_ft": action.range_ft,
                    "aoe_type": action.aoe_type,
                    "aoe_size_ft": action.aoe_size_ft,
                    "max_targets": action.max_targets,
                    "include_self": action.include_self,
                    "effects": list(action.effects),
                    "mechanics": list(action.mechanics),
                    "tags": list(action.tags),
                }
                for action in actor.actions
            ]
            for actor_id, actor in actors.items()
        },
    }


def _run_lair_actions(
    *,
    rng: random.Random,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> None:
    for actor in actors.values():
        if actor.dead or actor.hp <= 0:
            continue
        if actor.lair_action_used_this_round:
            continue
        lair_actions = [action for action in actor.actions if action.action_cost == "lair"]
        if not lair_actions:
            continue
        action: ActionDefinition | None = None
        targets: list[ActorRuntimeState] = []
        for candidate in lair_actions:
            if not _action_available(actor, candidate):
                continue
            resolved = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=candidate,
                actors=actors,
                requested=[],
            )
            if resolved:
                action = candidate
                targets = resolved
                break
        if action is None or not targets:
            continue
        spent = _spend_resources(actor, action.resource_cost)
        for key, amount in spent.items():
            resources_spent[actor.actor_id][key] = (
                resources_spent[actor.actor_id].get(key, 0) + amount
            )
        actor.per_action_uses[action.name] = actor.per_action_uses.get(action.name, 0) + 1
        if action.recharge:
            actor.recharge_ready[action.name] = False
        _mark_action_cost_used(actor, action)
        _execute_action(
            rng=rng,
            actor=actor,
            action=action,
            targets=targets,
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            obstacles=obstacles,
            light_level=light_level,
        )


def _run_legendary_actions(
    *,
    rng: random.Random,
    trigger_actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> None:
    for actor in actors.values():
        if actor.actor_id == trigger_actor.actor_id:
            continue
        if actor.dead or actor.hp <= 0:
            continue
        legendary = [action for action in actor.actions if action.action_cost == "legendary"]
        if not legendary:
            continue
        action: ActionDefinition | None = None
        targets: list[ActorRuntimeState] = []
        for candidate in legendary:
            if not _action_available(actor, candidate):
                continue
            resolved = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=candidate,
                actors=actors,
                requested=[],
            )
            if resolved:
                action = candidate
                targets = resolved
                break
        if action is None or not targets:
            continue
        spent = _spend_resources(actor, action.resource_cost)
        for key, amount in spent.items():
            resources_spent[actor.actor_id][key] = (
                resources_spent[actor.actor_id].get(key, 0) + amount
            )
        actor.per_action_uses[action.name] = actor.per_action_uses.get(action.name, 0) + 1
        if action.recharge:
            actor.recharge_ready[action.name] = False
        _mark_action_cost_used(actor, action)
        _execute_action(
            rng=rng,
            actor=actor,
            action=action,
            targets=targets,
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            obstacles=obstacles,
            light_level=light_level,
        )


def _flatten_trial(trial: TrialResult) -> dict[str, Any]:
    return {
        "trial_index": trial.trial_index,
        "rounds": trial.rounds,
        "winner": trial.winner,
        "damage_taken": json.dumps(trial.damage_taken, sort_keys=True),
        "damage_dealt": json.dumps(trial.damage_dealt, sort_keys=True),
        "resources_spent": json.dumps(trial.resources_spent, sort_keys=True),
        "downed_counts": json.dumps(trial.downed_counts, sort_keys=True),
        "death_counts": json.dumps(trial.death_counts, sort_keys=True),
        "remaining_hp": json.dumps(trial.remaining_hp, sort_keys=True),
    }


def run_simulation(
    scenario: LoadedScenario,
    character_db: dict[str, dict[str, Any]],
    traits_db: dict[str, dict[str, Any]],
    strategy_registry: dict[str, Any],
    *,
    trials: int,
    seed: int,
    run_id: str,
) -> SimulationArtifacts:
    if trials <= 0:
        raise ValueError("trials must be >= 1")

    rng = random.Random(seed)
    trial_results: list[TrialResult] = []

    assumption_overrides = scenario.config.assumption_overrides
    party_default_strategy = assumption_overrides.get("party_strategy", "optimal_expected_damage")
    enemy_default_strategy = assumption_overrides.get("enemy_strategy", "optimal_expected_damage")
    actor_strategy_overrides = assumption_overrides.get("actor_strategy", {})
    tracked_resource_names: dict[str, set[str]] = {}
    battlefield = (
        scenario.config.battlefield if isinstance(scenario.config.battlefield, dict) else {}
    )
    light_level = str(battlefield.get("light_level", "bright")).lower()
    battlefield_obstacles = _build_battlefield_obstacles(battlefield.get("obstacles", []))
    encounter_enemy_lists = [list(scenario.config.enemies)]

    for trial_idx in range(trials):
        actors: dict[str, ActorRuntimeState] = {}
        damage_taken: dict[str, int] = {}
        damage_dealt: dict[str, int] = {}
        resources_spent: dict[str, dict[str, int]] = {}
        threat_scores: dict[str, int] = {}
        downed_counts: dict[str, int] = {}
        death_counts: dict[str, int] = {}
        remaining_hp: dict[str, int] = {}
        active_hazards: list[dict[str, Any]] = []
        trial_rule_trace: list[dict[str, Any]] = []

        for character_id in scenario.config.party:
            if character_id not in character_db:
                raise ValueError(f"Character ID missing from DB: {character_id}")
            actor = _build_actor_from_character(character_db[character_id], traits_db)
            actors[actor.actor_id] = actor
            damage_taken[actor.actor_id] = 0
            damage_dealt[actor.actor_id] = 0
            resources_spent[actor.actor_id] = {}
            threat_scores[actor.actor_id] = 0
            downed_counts[actor.actor_id] = 0
            death_counts[actor.actor_id] = 0

        total_rounds = 0
        overall_winner = "draw"

        for enc_idx, encounter_enemy_ids in enumerate(encounter_enemy_lists):
            for aid in list(actors.keys()):
                if actors[aid].team != "party":
                    downed_counts[aid] = actors[aid].downed_count
                    death_counts[aid] = int(actors[aid].dead)
                    remaining_hp[aid] = actors[aid].hp
                    del actors[aid]

            enemy_counts: dict[str, int] = {}
            for enemy_id in encounter_enemy_ids:
                count = enemy_counts.get(enemy_id, 0) + 1
                enemy_counts[enemy_id] = count
                unique_enemy_id = (
                    f"{enemy_id}_e{enc_idx}_{count}"
                    if (count > 1 or len(encounter_enemy_lists) > 1)
                    else enemy_id
                )

                actor = _build_actor_from_enemy(scenario.enemies[enemy_id], traits_db)
                actor.actor_id = unique_enemy_id
                actor.position = (0.0, 30.0, 0.0)
                actors[actor.actor_id] = actor

                damage_taken[actor.actor_id] = 0
                damage_dealt[actor.actor_id] = 0
                resources_spent[actor.actor_id] = {}
                threat_scores[actor.actor_id] = 0
                downed_counts[actor.actor_id] = 0
                death_counts[actor.actor_id] = 0

            if trial_idx == 0 and enc_idx == 0:
                tracked_resource_names = {
                    actor_id: set(actor.resources.keys()) for actor_id, actor in actors.items()
                }

            initiative_order = _build_initiative_order(rng, actors, scenario.config.initiative_mode)
            rounds = 0
            max_rounds = int(scenario.config.termination_rules.get("max_rounds", 20))

            while rounds < max_rounds:
                rounds += 1
                for actor in actors.values():
                    actor.lair_action_used_this_round = False
                    if any(action.action_cost == "legendary" for action in actor.actions):
                        base_legendary = int(actor.resources.get("legendary_actions", 0))
                        actor.legendary_actions_remaining = (
                            base_legendary if base_legendary > 0 else 3
                        )

                _run_lair_actions(
                    rng=rng,
                    actors=actors,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                    obstacles=battlefield_obstacles,
                    light_level=light_level,
                )

                metadata = _build_round_metadata(
                    actors=actors,
                    threat_scores=threat_scores,
                    burst_round_threshold=int(
                        scenario.config.resource_policy.get("burst_round_threshold", 3)
                    ),
                    active_hazards=active_hazards,
                    light_level=light_level,
                )
                state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                for strategy in strategy_registry.values():
                    strategy.on_round_start(state_view)

                initiative_order = _sync_initiative_order(initiative_order, actors)
                for actor_id in initiative_order:
                    if actor_id not in actors:
                        continue
                    actor = actors[actor_id]
                    actor.movement_remaining = float(actor.speed_ft)
                    actor.took_attack_action_this_turn = False
                    _roll_recharge_for_actor(rng, actor)
                    _tick_conditions_for_actor(rng, actor)
                    _force_end_concentration_if_needed(
                        actor, actors=actors, active_hazards=active_hazards
                    )
                    if "grappled" in actor.conditions:
                        actor.movement_remaining = 0.0
                    actor.bonus_available = True
                    actor.reaction_available = True
                    actor.sneak_attack_used_this_turn = False
                    actor.colossus_slayer_used_this_turn = False
                    actor.horde_breaker_used_this_turn = False

                    if actor.dead:
                        continue

                    if actor.hp <= 0:
                        resolve_death_save(rng, actor)
                        continue

                    if _party_defeated(actors) or _enemies_defeated(actors):
                        break

                    turn_token = f"{rounds}:{actor.actor_id}"
                    _dispatch_combat_event(
                        rng=rng,
                        event="turn_start",
                        trigger_actor=actor,
                        trigger_target=actor,
                        trigger_action=None,
                        actors=actors,
                        round_number=rounds,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=trial_rule_trace,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                    _trigger_readied_actions(
                        rng=rng,
                        trigger_actor=actor,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                    if actor.dead or actor.hp <= 0:
                        continue
                    if _party_defeated(actors) or _enemies_defeated(actors):
                        break
                    if not _can_act(actor):
                        _dispatch_combat_event(
                            rng=rng,
                            event="turn_end",
                            trigger_actor=actor,
                            trigger_target=actor,
                            trigger_action=None,
                            actors=actors,
                            round_number=rounds,
                            turn_token=turn_token,
                            damage_dealt=damage_dealt,
                            damage_taken=damage_taken,
                            threat_scores=threat_scores,
                            resources_spent=resources_spent,
                            active_hazards=active_hazards,
                            rule_trace=trial_rule_trace,
                            obstacles=battlefield_obstacles,
                            light_level=light_level,
                        )
                        continue

                    strategy_name = actor_strategy_overrides.get(actor.actor_id)
                    if strategy_name is None:
                        strategy_name = (
                            party_default_strategy
                            if actor.team == "party"
                            else enemy_default_strategy
                        )
                    strategy = strategy_registry.get(strategy_name)
                    if strategy is None:
                        raise ValueError(
                            f"No strategy registered for actor {actor.actor_id}: {strategy_name}"
                        )

                    metadata = _build_round_metadata(
                        actors=actors,
                        threat_scores=threat_scores,
                        burst_round_threshold=int(
                            scenario.config.resource_policy.get("burst_round_threshold", 3)
                        ),
                        active_hazards=active_hazards,
                        light_level=light_level,
                    )
                    state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                    actor_view = state_view.actors[actor.actor_id]
                    intent = strategy.choose_action(actor_view, state_view)
                    action = _resolve_action_selection(actor, intent.action_name)

                    if not _action_available(actor, action):
                        fallback = _fallback_action(actor)
                        if fallback is None:
                            _dispatch_combat_event(
                                rng=rng,
                                event="turn_end",
                                trigger_actor=actor,
                                trigger_target=actor,
                                trigger_action=None,
                                actors=actors,
                                round_number=rounds,
                                turn_token=turn_token,
                                damage_dealt=damage_dealt,
                                damage_taken=damage_taken,
                                threat_scores=threat_scores,
                                resources_spent=resources_spent,
                                active_hazards=active_hazards,
                                rule_trace=trial_rule_trace,
                                obstacles=battlefield_obstacles,
                                light_level=light_level,
                            )
                            continue
                        action = fallback

                    extra_spend = strategy.decide_resource_spend(
                        actor_view, intent, state_view
                    ).amounts
                    cost = dict(action.resource_cost)
                    for key, amount in extra_spend.items():
                        cost[key] = cost.get(key, 0) + amount

                    if cost and not _has_resources(actor, cost):
                        action = _resolve_action_selection(actor, "basic")
                        cost = dict(action.resource_cost)

                    targets = strategy.choose_targets(actor_view, intent, state_view)
                    resolved_targets = _resolve_targets_for_action(
                        rng=rng,
                        actor=actor,
                        action=action,
                        actors=actors,
                        requested=targets,
                    )
                    if not resolved_targets:
                        _dispatch_combat_event(
                            rng=rng,
                            event="turn_end",
                            trigger_actor=actor,
                            trigger_target=actor,
                            trigger_action=None,
                            actors=actors,
                            round_number=rounds,
                            turn_token=turn_token,
                            damage_dealt=damage_dealt,
                            damage_taken=damage_taken,
                            threat_scores=threat_scores,
                            resources_spent=resources_spent,
                            active_hazards=active_hazards,
                            rule_trace=trial_rule_trace,
                            obstacles=battlefield_obstacles,
                            light_level=light_level,
                        )
                        continue

                    spent = _spend_resources(actor, cost)
                    for key, amount in spent.items():
                        resources_spent[actor.actor_id][key] = (
                            resources_spent[actor.actor_id].get(key, 0) + amount
                        )

                    actor.per_action_uses[action.name] = (
                        actor.per_action_uses.get(action.name, 0) + 1
                    )
                    if action.recharge:
                        actor.recharge_ready[action.name] = False
                    _mark_action_cost_used(actor, action)

                    _execute_action(
                        rng=rng,
                        actor=actor,
                        action=action,
                        targets=resolved_targets,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                        round_number=rounds,
                        turn_token=turn_token,
                        rule_trace=trial_rule_trace,
                    )
                    _dispatch_combat_event(
                        rng=rng,
                        event="after_action",
                        trigger_actor=actor,
                        trigger_target=resolved_targets[0] if resolved_targets else None,
                        trigger_action=action,
                        actors=actors,
                        round_number=rounds,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=trial_rule_trace,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                    # --- Bonus action step ---
                    if actor.bonus_available and _can_act(actor):
                        bonus_action = _find_best_bonus_action(actor)
                        if bonus_action is not None:
                            bonus_targets = _resolve_targets_for_action(
                                rng=rng,
                                actor=actor,
                                action=bonus_action,
                                actors=actors,
                                requested=_default_target(actor, actors),
                            )
                            if bonus_targets:
                                bonus_cost = dict(bonus_action.resource_cost)
                                if not bonus_cost or _has_resources(actor, bonus_cost):
                                    spent = _spend_resources(actor, bonus_cost)
                                    for key, amount in spent.items():
                                        resources_spent[actor.actor_id][key] = (
                                            resources_spent[actor.actor_id].get(key, 0) + amount
                                        )
                                    actor.per_action_uses[bonus_action.name] = (
                                        actor.per_action_uses.get(bonus_action.name, 0) + 1
                                    )
                                    _mark_action_cost_used(actor, bonus_action)
                                    _execute_action(
                                        rng=rng,
                                        actor=actor,
                                        action=bonus_action,
                                        targets=bonus_targets,
                                        actors=actors,
                                        damage_dealt=damage_dealt,
                                        damage_taken=damage_taken,
                                        threat_scores=threat_scores,
                                        resources_spent=resources_spent,
                                        active_hazards=active_hazards,
                                        obstacles=battlefield_obstacles,
                                        light_level=light_level,
                                        round_number=rounds,
                                        turn_token=turn_token,
                                        rule_trace=trial_rule_trace,
                                    )
                                    _dispatch_combat_event(
                                        rng=rng,
                                        event="after_action",
                                        trigger_actor=actor,
                                        trigger_target=bonus_targets[0] if bonus_targets else None,
                                        trigger_action=bonus_action,
                                        actors=actors,
                                        round_number=rounds,
                                        turn_token=turn_token,
                                        damage_dealt=damage_dealt,
                                        damage_taken=damage_taken,
                                        threat_scores=threat_scores,
                                        resources_spent=resources_spent,
                                        active_hazards=active_hazards,
                                        rule_trace=trial_rule_trace,
                                        obstacles=battlefield_obstacles,
                                        light_level=light_level,
                                    )

                    # --- Action Surge step ---
                    if (
                        _has_trait(actor, "action surge")
                        and actor.resources.get("action_surge", 0) > 0
                        and _can_act(actor)
                    ):
                        enemies_alive = [
                            t
                            for t in actors.values()
                            if t.team != actor.team and t.hp > 0 and not t.dead
                        ]
                        if enemies_alive:
                            surge_action = _fallback_action(actor)
                            if surge_action and surge_action.action_cost in ("action", "none"):
                                actor.resources["action_surge"] -= 1
                                resources_spent[actor.actor_id]["action_surge"] = (
                                    resources_spent[actor.actor_id].get("action_surge", 0) + 1
                                )

                                surge_targets = _resolve_targets_for_action(
                                    rng=rng,
                                    actor=actor,
                                    action=surge_action,
                                    actors=actors,
                                    requested=_default_target(actor, actors),
                                )
                                if surge_targets:
                                    surge_cost = dict(surge_action.resource_cost)
                                    if not surge_cost or _has_resources(actor, surge_cost):
                                        spent = _spend_resources(actor, surge_cost)
                                        for key, amount in spent.items():
                                            resources_spent[actor.actor_id][key] = (
                                                resources_spent[actor.actor_id].get(key, 0) + amount
                                            )

                                        actor.per_action_uses[surge_action.name] = (
                                            actor.per_action_uses.get(surge_action.name, 0) + 1
                                        )
                                        if surge_action.recharge:
                                            actor.recharge_ready[surge_action.name] = False
                                        _mark_action_cost_used(actor, surge_action)

                                        _execute_action(
                                            rng=rng,
                                            actor=actor,
                                            action=surge_action,
                                            targets=surge_targets,
                                            actors=actors,
                                            damage_dealt=damage_dealt,
                                            damage_taken=damage_taken,
                                            threat_scores=threat_scores,
                                            resources_spent=resources_spent,
                                            active_hazards=active_hazards,
                                            obstacles=battlefield_obstacles,
                                            light_level=light_level,
                                            round_number=rounds,
                                            turn_token=turn_token,
                                            rule_trace=trial_rule_trace,
                                        )
                                        _dispatch_combat_event(
                                            rng=rng,
                                            event="after_action",
                                            trigger_actor=actor,
                                            trigger_target=(
                                                surge_targets[0] if surge_targets else None
                                            ),
                                            trigger_action=surge_action,
                                            actors=actors,
                                            round_number=rounds,
                                            turn_token=turn_token,
                                            damage_dealt=damage_dealt,
                                            damage_taken=damage_taken,
                                            threat_scores=threat_scores,
                                            resources_spent=resources_spent,
                                            active_hazards=active_hazards,
                                            rule_trace=trial_rule_trace,
                                            obstacles=battlefield_obstacles,
                                            light_level=light_level,
                                        )

                    _run_legendary_actions(
                        rng=rng,
                        trigger_actor=actor,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )
                    _dispatch_combat_event(
                        rng=rng,
                        event="turn_end",
                        trigger_actor=actor,
                        trigger_target=actor,
                        trigger_action=None,
                        actors=actors,
                        round_number=rounds,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=trial_rule_trace,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                if _party_defeated(actors) or _enemies_defeated(actors):
                    break

            total_rounds += rounds

            if _party_defeated(actors):
                overall_winner = "enemy"
                break
            elif not _enemies_defeated(actors):
                party_hp = sum(a.hp for a in actors.values() if a.team == "party" and not a.dead)
                enemy_hp = sum(a.hp for a in actors.values() if a.team != "party" and not a.dead)
                overall_winner = "party" if party_hp >= enemy_hp else "enemy"
                if overall_winner == "enemy":
                    break

        if overall_winner == "draw" and _enemies_defeated(actors):
            overall_winner = "party"

        for aid, actor in actors.items():
            downed_counts[aid] = actor.downed_count
            death_counts[aid] = int(actor.dead)
            remaining_hp[aid] = actor.hp

        trial = TrialResult(
            trial_index=trial_idx,
            rounds=total_rounds,
            winner=overall_winner,
            damage_taken=dict(damage_taken),
            damage_dealt=dict(damage_dealt),
            resources_spent=resources_spent,
            downed_counts=downed_counts,
            death_counts=death_counts,
            remaining_hp=remaining_hp,
        )
        trial_results.append(trial)

    trial_rows = [_flatten_trial(trial) for trial in trial_results]

    party_wins = sum(1 for trial in trial_results if trial.winner == "party")
    enemy_wins = sum(1 for trial in trial_results if trial.winner == "enemy")

    actor_ids = sorted(trial_results[0].damage_taken.keys()) if trial_results else []

    per_actor_damage_taken = {
        actor_id: _metric([trial.damage_taken[actor_id] for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_damage_dealt = {
        actor_id: _metric([trial.damage_dealt[actor_id] for trial in trial_results])
        for actor_id in actor_ids
    }

    resources_all: dict[str, dict[str, list[float]]] = {actor_id: {} for actor_id in actor_ids}
    for trial in trial_results:
        for actor_id in actor_ids:
            for resource_name in tracked_resource_names.get(actor_id, set()):
                resources_all[actor_id].setdefault(resource_name, [])
            for resource_name, amount in trial.resources_spent.get(actor_id, {}).items():
                resources_all[actor_id].setdefault(resource_name, []).append(float(amount))
            for resource_name in resources_all[actor_id]:
                if resource_name not in trial.resources_spent.get(actor_id, {}):
                    resources_all[actor_id][resource_name].append(0.0)

    per_actor_resources_spent: dict[str, dict[str, SummaryMetric]] = {}
    for actor_id, resource_map in resources_all.items():
        per_actor_resources_spent[actor_id] = {
            resource_name: _metric(values) for resource_name, values in resource_map.items()
        }

    per_actor_downed = {
        actor_id: _metric([trial.downed_counts[actor_id] for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_deaths = {
        actor_id: _metric([trial.death_counts[actor_id] for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_remaining_hp = {
        actor_id: _metric([trial.remaining_hp[actor_id] for trial in trial_results])
        for actor_id in actor_ids
    }

    summary = SimulationSummary(
        run_id=run_id,
        scenario_id=scenario.config.scenario_id,
        trials=trials,
        party_win_rate=party_wins / trials,
        enemy_win_rate=enemy_wins / trials,
        rounds=_metric([trial.rounds for trial in trial_results]),
        per_actor_damage_taken=per_actor_damage_taken,
        per_actor_damage_dealt=per_actor_damage_dealt,
        per_actor_resources_spent=per_actor_resources_spent,
        per_actor_downed=per_actor_downed,
        per_actor_deaths=per_actor_deaths,
        per_actor_remaining_hp=per_actor_remaining_hp,
    )

    return SimulationArtifacts(
        trial_results=trial_results,
        trial_rows=trial_rows,
        summary=summary,
    )
