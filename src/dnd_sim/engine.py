from __future__ import annotations

import json
import math
import random
import re
import statistics
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from dnd_sim.inventory import InventoryState
from dnd_sim.io import EncounterConfig, EnemyConfig, LoadedScenario
from dnd_sim.models import (
    ABILITY_KEYS,
    ActionDefinition,
    ActorRuntimeState,
    ConditionTracker,
    EffectInstance,
    SpellCastRequest,
    SpellComponents,
    SpellDefinition,
    SpellRoll,
    SpellScaling,
    SimulationSummary,
    SummaryMetric,
    TrialResult,
)
from dnd_sim.spatial import (
    AABB,
    distance_chebyshev,
    find_path,
    path_movement_cost,
    path_prefix_for_movement,
)
from dnd_sim.rules_2014 import (
    ActionDeclaredEvent,
    AttackResolvedEvent,
    AttackRollEvent,
    AttackRollResult,
    CombatTimingEngine,
    DamageBundle,
    DamagePacket,
    DamageResolvedEvent,
    DamageRollEvent,
    ListenerSubscription,
    ReactionWindowOpenedEvent,
    apply_damage,
    apply_damage_bundle,
    attack_roll,
    parse_damage_expression,
    resolve_death_save,
    roll_damage,
    roll_damage_packet,
    run_concentration_check,
)
from dnd_sim.strategy_api import (
    ActorView,
    BattleStateView,
    DeclaredAction,
    ReadyDeclaration,
    TargetRef,
    TurnDeclaration,
)

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
_AUTO_CRIT_CONDITIONS = {"paralyzed", "unconscious"}
_AUTO_FAIL_STR_DEX_SAVE_CONDITIONS = {"stunned", "paralyzed", "unconscious"}
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
_WARLOCK_INVOCATION_ALIASES: dict[str, str] = {
    "agonizing blast": "agonizing blast",
    "repelling blast": "repelling blast",
}
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
_RANGED_WEAPON_HINTS = _RANGED_ATTACK_KEYWORDS
_HEAVY_WEAPON_HINTS = (
    "greatsword",
    "greataxe",
    "maul",
    "glaive",
    "halberd",
    "pike",
    "heavy crossbow",
)
_FINESSE_WEAPON_HINTS = ("dagger", "shortsword", "rapier", "scimitar", "dart", "whip")
_RANGED_IN_MELEE_DISADVANTAGE_OVERRIDE_TAGS = {
    "ignore_adjacent_hostile_disadvantage",
    "ignore_ranged_melee_disadvantage",
    "no_ranged_melee_disadvantage",
}
_RANGED_IN_MELEE_DISADVANTAGE_OVERRIDE_TRAITS = {
    "crossbow expert",
    "gunner",
    "close quarters shooter",
}
_ARTIFICER_OPTION_TRAITS = {
    "enhanced defense",
    "enhanced weapon",
    "mind sharpener",
    "radiant weapon",
    "repeating shot",
    "repulsion shield",
    "homunculus servant",
    "steel defender",
}
_SPELL_SLOT_CREATION_COSTS: dict[int, int] = {1: 2, 2: 3, 3: 5, 4: 6, 5: 7}
_TRAVEL_PACE_MILES_PER_DAY: dict[str, float] = {"slow": 18.0, "normal": 24.0, "fast": 30.0}
_TRAVEL_PACE_HAZARD_DC_MODIFIER: dict[str, int] = {"slow": -2, "normal": 0, "fast": 2}
_MULTIATTACK_DEFENSE_PREFIX = "multiattack_defense_from:"
_SPELL_SCHOOL_ORDER = (
    "abjuration",
    "conjuration",
    "divination",
    "enchantment",
    "evocation",
    "illusion",
    "necromancy",
    "transmutation",
)
_SPELL_SCHOOLS = set(_SPELL_SCHOOL_ORDER)
_WIZARD_SCHOOL_TRAIT_TO_SCHOOL = {
    "school of abjuration": "abjuration",
    "school of conjuration": "conjuration",
    "school of divination": "divination",
    "school of enchantment": "enchantment",
    "school of evocation": "evocation",
    "school of illusion": "illusion",
    "school of necromancy": "necromancy",
    "school of transmutation": "transmutation",
}
_KNOWN_MANEUVERS = {
    "commander's strike",
    "disarming attack",
    "distracting strike",
    "evasive footwork",
    "feinting attack",
    "goading attack",
    "lunging attack",
    "maneuvering attack",
    "menacing attack",
    "parry",
    "precision attack",
    "pushing attack",
    "rally",
    "riposte",
    "sweeping attack",
    "trip attack",
}
_DEFAULT_BATTLEMASTER_MANEUVERS = ("trip attack", "menacing attack", "precision attack")
_SUPPORTED_REACTION_POLICY_MODES = {"auto", "none"}


@dataclass(slots=True)
class SimulationArtifacts:
    trial_results: list[TrialResult]
    trial_rows: list[dict[str, Any]]
    summary: SimulationSummary


@dataclass(slots=True)
class AttackConditionModifiers:
    advantage: bool = False
    disadvantage: bool = False
    force_critical: bool = False


class TurnDeclarationValidationError(ValueError):
    def __init__(
        self,
        *,
        actor_id: str,
        code: str,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.actor_id = actor_id
        self.code = code
        self.field = field
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code} [{actor_id}:{field}] {message}")


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


def _is_supported_artificer_option(name: str) -> bool:
    return _normalize_trait_name(name) in _ARTIFICER_OPTION_TRAITS


def _resolve_character_traits(
    character: dict[str, Any], traits_db: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """Resolve character traits/features to canonical DB traits where possible.

    Keeps unresolved traits as empty dict entries so existing name-based hooks still work.
    """
    db_index: dict[str, dict[str, Any]] = {}
    for key, data in (traits_db or {}).items():
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
            if _is_supported_artificer_option(candidate):
                resolved[_normalize_trait_name(candidate)] = {}
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


def _damage_expr_was_crit_expanded(expr: str, *, crit: bool) -> bool:
    if not crit:
        return False
    try:
        n_dice, dice_size, _flat = parse_damage_expression(expr)
    except ValueError:
        return False
    return n_dice > 0 and dice_size > 0


def _append_damage_packet(
    *,
    bundle: DamageBundle,
    amount: int,
    damage_type: str,
    packet_source: str,
    is_magical: bool,
    crit_expanded: bool,
) -> None:
    bundle.add_packet(
        DamagePacket(
            amount=max(0, int(amount)),
            damage_type=str(damage_type).lower(),
            source=str(packet_source),
            is_magical=bool(is_magical),
            crit_expanded=bool(crit_expanded),
        )
    )


def _parse_character_level(class_level: str) -> int:
    """Extract the numeric level from a class_level string like 'Fighter 8' or 'Wizard 5 / Cleric 3'."""
    class_levels = _parse_class_levels(class_level)
    if class_levels:
        return sum(class_levels.values())
    numbers = re.findall(r"\d+", class_level)
    return sum(int(n) for n in numbers) if numbers else 1


def _parse_class_level(class_level_text: str, class_name: str) -> int:
    pattern = re.compile(rf"\b{re.escape(class_name)}\b[^0-9]*(\d+)", re.IGNORECASE)
    return sum(int(match.group(1)) for match in pattern.finditer(class_level_text or ""))


def _parse_class_levels(class_level_text: str) -> dict[str, int]:
    levels: dict[str, int] = {}
    for class_name, raw_level in re.findall(
        r"([A-Za-z][A-Za-z' -]+?)\s*(\d+)", class_level_text or ""
    ):
        key = class_name.strip().lower()
        levels[key] = levels.get(key, 0) + int(raw_level)
    return levels


def _normalize_spell_school(value: Any) -> str | None:
    text = re.sub(r"[^a-z]+", " ", str(value).lower()).strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    if text in _SPELL_SCHOOLS:
        return text
    return None


def _extract_spell_school_from_meta(meta: Any) -> str | None:
    cleaned = re.sub(r"[^a-z]+", " ", str(meta).lower())
    for school in _SPELL_SCHOOL_ORDER:
        if re.search(rf"\b{school}\b", cleaned):
            return school
    return None


def _extract_spell_school(spell: dict[str, Any]) -> str | None:
    explicit = _normalize_spell_school(spell.get("school"))
    if explicit is not None:
        return explicit
    return _extract_spell_school_from_meta(spell.get("meta", ""))


def _append_tag_once(action: ActionDefinition, tag: str) -> None:
    if tag and tag not in action.tags:
        action.tags.append(tag)


def _append_mechanic_once(action: ActionDefinition, mechanic: dict[str, Any]) -> None:
    if mechanic not in action.mechanics:
        action.mechanics.append(mechanic)


def _hook_tag_school_matched_spell(
    *,
    action: ActionDefinition,
    wizard_school: str,
    spell_school: str,
) -> None:
    if wizard_school != spell_school:
        return
    _append_tag_once(action, "wizard_school_hook")
    _append_tag_once(action, f"wizard_school_hook:{wizard_school}")
    _append_mechanic_once(
        action,
        {
            "type": "wizard_school_hook",
            "school": wizard_school,
        },
    )


_WIZARD_SCHOOL_ACTION_HOOKS: dict[str, tuple[Callable[..., None], ...]] = {
    school: (_hook_tag_school_matched_spell,) for school in _SPELL_SCHOOL_ORDER
}


def _school_from_action_tags(action: ActionDefinition) -> str | None:
    for tag in action.tags:
        if not tag.startswith("school:"):
            continue
        school = _normalize_spell_school(tag.split(":", 1)[1])
        if school is not None:
            return school
    return None


def _apply_wizard_school_action_hooks(
    actions: list[ActionDefinition],
    *,
    traits: set[str],
) -> None:
    active_schools = [
        school
        for trait_key, school in _WIZARD_SCHOOL_TRAIT_TO_SCHOOL.items()
        if trait_key in traits
    ]
    if not active_schools:
        return

    for action in actions:
        if "spell" not in action.tags:
            continue
        spell_school = _school_from_action_tags(action)
        if spell_school is None:
            continue
        for wizard_school in active_schools:
            for hook in _WIZARD_SCHOOL_ACTION_HOOKS.get(wizard_school, ()):
                hook(action=action, wizard_school=wizard_school, spell_school=spell_school)


def _ensure_resource_cap(actor: ActorRuntimeState, resource: str, max_value: int) -> None:
    if max_value <= 0:
        return
    existing_max = int(actor.max_resources.get(resource, 0))
    if existing_max < max_value:
        actor.max_resources[resource] = max_value
    cap = int(actor.max_resources[resource])
    if resource not in actor.resources:
        actor.resources[resource] = cap
    else:
        actor.resources[resource] = max(0, min(int(actor.resources[resource]), cap))


def _apply_inferred_wizard_resources(actor: ActorRuntimeState) -> None:
    if not _has_trait(actor, "arcane recovery"):
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    _ensure_resource_cap(actor, "arcane_recovery", 1)


def _iter_spell_slot_levels_desc(actor: ActorRuntimeState) -> list[int]:
    levels: set[int] = set()
    for key in actor.max_resources.keys():
        if not str(key).startswith("spell_slot_"):
            continue
        try:
            level = int(str(key).rsplit("_", 1)[1])
        except ValueError:
            continue
        if level > 0:
            levels.add(level)
    return sorted(levels, reverse=True)


def _recover_spell_slots_with_budget(
    actor: ActorRuntimeState,
    *,
    budget: int,
    max_individual_slot_level: int,
) -> int:
    if budget <= 0:
        return 0
    recovered_levels = 0
    for slot_level in _iter_spell_slot_levels_desc(actor):
        if slot_level > max_individual_slot_level or budget < slot_level:
            continue
        slot_key = f"spell_slot_{slot_level}"
        max_slots = int(actor.max_resources.get(slot_key, 0))
        current_slots = min(int(actor.resources.get(slot_key, 0)), max_slots)
        missing_slots = max(0, max_slots - current_slots)
        recoverable_slots = min(missing_slots, budget // slot_level)
        if recoverable_slots <= 0:
            continue
        actor.resources[slot_key] = current_slots + recoverable_slots
        recovered_levels += recoverable_slots * slot_level
        budget -= recoverable_slots * slot_level
        if budget <= 0:
            break
    return recovered_levels


def _apply_arcane_recovery(actor: ActorRuntimeState) -> None:
    if not _has_trait(actor, "arcane recovery"):
        return
    uses_remaining = int(actor.resources.get("arcane_recovery", 0))
    if uses_remaining <= 0:
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    recovery_budget = max(1, (wizard_level + 1) // 2)
    recovered_levels = _recover_spell_slots_with_budget(
        actor,
        budget=recovery_budget,
        max_individual_slot_level=5,
    )
    if recovered_levels <= 0:
        return
    actor.resources["arcane_recovery"] = uses_remaining - 1


def _fighter_superiority_dice_count(fighter_level: int) -> int:
    if fighter_level >= 15:
        return 6
    if fighter_level >= 7:
        return 5
    if fighter_level >= 3:
        return 4
    return 0


def _fighter_superiority_die_size(
    fighter_level: int,
    *,
    traits: set[str] | None = None,
) -> int:
    trait_keys = traits or set()
    if fighter_level >= 18 or "ultimate combat superiority" in trait_keys:
        return 12
    if fighter_level >= 10 or {
        "improved combat superiority",
        "improved combat superiority (d10)",
    }.intersection(trait_keys):
        return 10
    return 8


def _warlock_level_from_character(character: dict[str, Any]) -> int:
    class_level_text = str(character.get("class_level", ""))
    return _parse_class_level(class_level_text, "warlock")


def _warlock_pact_slot_profile_for_level(warlock_level: int) -> tuple[int, int] | None:
    if warlock_level <= 0:
        return None
    if warlock_level == 1:
        slot_count = 1
    elif warlock_level <= 10:
        slot_count = 2
    elif warlock_level <= 16:
        slot_count = 3
    else:
        slot_count = 4

    if warlock_level <= 2:
        slot_level = 1
    elif warlock_level <= 4:
        slot_level = 2
    elif warlock_level <= 6:
        slot_level = 3
    elif warlock_level <= 8:
        slot_level = 4
    else:
        slot_level = 5
    return slot_level, slot_count


def _extract_pact_slot_profile_from_spell_slots(raw_slots: Any) -> tuple[int, int] | None:
    if not isinstance(raw_slots, dict):
        return None
    positive_slots: list[tuple[int, int]] = []
    for level_raw, count_raw in raw_slots.items():
        try:
            level = int(level_raw)
            count = int(count_raw)
        except (TypeError, ValueError):
            continue
        if level <= 0 or count <= 0:
            continue
        if level > 5:
            continue
        positive_slots.append((level, count))
    if len(positive_slots) == 1:
        return positive_slots[0]
    return None


def _is_pact_magic_character(character: dict[str, Any]) -> bool:
    if _warlock_level_from_character(character) > 0:
        return True
    trait_names = {
        _normalize_trait_name(str(value)) for value in (character.get("traits", []) or [])
    }
    return "pact magic" in trait_names


def _warlock_mystic_arcanum_max_level(warlock_level: int) -> int:
    if warlock_level >= 17:
        return 9
    if warlock_level >= 15:
        return 8
    if warlock_level >= 13:
        return 7
    if warlock_level >= 11:
        return 6
    return 0


def _extract_warlock_invocations(character: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for trait in character.get("traits", []) or []:
        key = _normalize_trait_name(str(trait))
        canonical = _WARLOCK_INVOCATION_ALIASES.get(key)
        if canonical is not None:
            candidates.add(canonical)

    for candidate in _extract_trait_candidates_from_raw_fields(character):
        key = _normalize_trait_name(candidate)
        canonical = _WARLOCK_INVOCATION_ALIASES.get(key)
        if canonical is not None:
            candidates.add(canonical)

    return candidates


# Cantrip damage scaling: at level 5, 11, 17 add an extra die
_CANTRIP_SCALE_TIERS = [(17, 4), (11, 3), (5, 2), (1, 1)]


def _calculate_proficiency_bonus(level: int) -> int:
    """5e proficiency bonus progression by character level."""
    return 2 + max(0, (max(level, 1) - 1) // 4)


def _damage_expr_with_flat_bonus(expr: str, bonus: int) -> str:
    if bonus == 0:
        return expr
    try:
        n_dice, dice_size, flat = parse_damage_expression(expr)
    except ValueError:
        return f"{expr}+{bonus}" if bonus > 0 else f"{expr}{bonus}"

    updated_flat = flat + bonus
    if n_dice == 0 and dice_size == 0:
        return str(updated_flat)

    suffix = ""
    if updated_flat > 0:
        suffix = f"+{updated_flat}"
    elif updated_flat < 0:
        suffix = str(updated_flat)
    return f"{n_dice}d{dice_size}{suffix}"


def _canonical_id(value: Any, *, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or default


def _normalize_weapon_property(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _normalize_weapon_properties(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple, set)):
        candidates = list(raw)
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = _normalize_weapon_property(candidate)
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _normalize_attack_definition(raw_attack: Any, idx: int) -> dict[str, Any]:
    attack = dict(raw_attack) if isinstance(raw_attack, dict) else {}
    default_attack_id = f"attack_profile_{idx}"
    profile_id = _canonical_id(
        attack.get("attack_profile_id", attack.get("attack_id", attack.get("id"))),
        default=default_attack_id,
    )
    attack_name = str(attack.get("name", f"attack_{idx}"))
    default_weapon_id = f"weapon_{_canonical_id(attack_name, default=str(idx))}"
    weapon_id = _canonical_id(
        attack.get("weapon_id", attack.get("equipment_id", attack.get("item_id"))),
        default=default_weapon_id,
    )
    item_id = _canonical_id(attack.get("item_id", weapon_id), default=weapon_id)

    weapon_properties = _normalize_weapon_properties(
        attack.get("weapon_properties", attack.get("properties"))
    )
    for source in (attack.get("tags"), attack.get("traits")):
        for prop in _normalize_weapon_properties(source):
            if prop not in weapon_properties:
                weapon_properties.append(prop)
    if bool(attack.get("magical")) and "magical" not in weapon_properties:
        weapon_properties.append("magical")

    reach_ft = _coerce_optional_int(attack.get("reach_ft"))
    range_ft = _coerce_optional_int(attack.get("range_ft"))
    range_normal_ft = _coerce_optional_int(
        attack.get("range_normal_ft", attack.get("normal_range_ft"))
    )
    range_long_ft = _coerce_optional_int(attack.get("range_long_ft", attack.get("long_range_ft")))
    if range_ft is None:
        if range_normal_ft is not None:
            range_ft = range_normal_ft
        elif reach_ft is not None:
            range_ft = reach_ft

    normalized = dict(attack)
    normalized.update(
        {
            "attack_profile_id": profile_id,
            "weapon_id": weapon_id,
            "item_id": item_id,
            "weapon_properties": weapon_properties,
            "reach_ft": reach_ft,
            "range_ft": range_ft,
            "range_normal_ft": range_normal_ft,
            "range_long_ft": range_long_ft,
        }
    )
    return normalized


def _action_weapon_properties(action: ActionDefinition) -> set[str]:
    return {value for value in _normalize_weapon_properties(action.weapon_properties)}


def _action_has_weapon_property(action: ActionDefinition, property_name: str) -> bool:
    return _normalize_weapon_property(property_name) in _action_weapon_properties(action)


def _action_has_canonical_weapon_data(action: ActionDefinition) -> bool:
    return bool(
        action.weapon_properties
        or action.reach_ft is not None
        or action.range_normal_ft is not None
        or action.range_long_ft is not None
    )


def _mark_action_magical(action: ActionDefinition) -> None:
    if not _action_has_weapon_property(action, "magical"):
        action.weapon_properties.append("magical")
    if "magical" not in action.tags:
        action.tags.append("magical")


def _is_magical_action(action: ActionDefinition) -> bool:
    return (
        "spell" in action.tags
        or "magical" in action.tags
        or _action_has_weapon_property(action, "magical")
    )


def _is_weapon_attack_action(action: ActionDefinition) -> bool:
    return action.action_type == "attack" and "spell" not in set(action.tags or [])


def _is_ranged_weapon_action(action: ActionDefinition) -> bool:
    if not _is_weapon_attack_action(action):
        return False
    has_ranged_property = _action_has_weapon_property(
        action, "ammunition"
    ) or _action_has_weapon_property(action, "ranged")
    has_reach_property = _action_has_weapon_property(action, "reach")
    if has_ranged_property:
        return True
    if _action_has_weapon_property(action, "thrown"):
        if action.range_normal_ft is not None:
            return action.range_normal_ft > 5
        if action.range_ft is not None:
            return action.range_ft > 5
        return True
    if action.range_normal_ft is not None:
        if has_reach_property and not has_ranged_property:
            return False
        return action.range_normal_ft > 5
    if action.range_long_ft is not None:
        if has_reach_property and not has_ranged_property:
            return False
        return action.range_long_ft > 5
    if action.reach_ft is not None:
        return False
    if has_reach_property:
        return False
    if action.range_ft is not None and action.range_ft > 5:
        return True
    name = action.name.lower()
    return any(hint in name for hint in _RANGED_WEAPON_HINTS)


def _ensure_action(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    if any(
        existing.name == action.name and existing.action_cost == action.action_cost
        for existing in actor.actions
    ):
        return
    actor.actions.append(action)


def _construct_command_action() -> ActionDefinition:
    return ActionDefinition(
        name="command_construct_companion",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        effects=[
            {
                "effect_type": "command_construct_companion",
                "target": "source",
            }
        ],
        tags=["bonus", "construct_command"],
    )


def _discover_construct_companion_kinds(actor: ActorRuntimeState) -> set[str]:
    kinds: set[str] = set()
    if _has_trait(actor, "steel defender"):
        kinds.add("steel_defender")
    if _has_trait(actor, "homunculus servant"):
        kinds.add("homunculus_servant")

    for trait_data in actor.traits.values():
        for mechanic in trait_data.get("mechanics", []):
            if not isinstance(mechanic, dict):
                continue
            if str(mechanic.get("type", "")).lower() != "summon":
                continue
            creature = _normalize_trait_name(str(mechanic.get("creature", "")))
            if creature == "steel defender":
                kinds.add("steel_defender")
            elif creature == "homunculus servant":
                kinds.add("homunculus_servant")
    return kinds


def _apply_artificer_infusion_passives(actor: ActorRuntimeState) -> None:
    if _has_trait(actor, "enhanced defense"):
        actor.ac += 2 if actor.level >= 10 else 1

    if _has_trait(actor, "repulsion shield"):
        actor.ac += 1

    if _has_trait(actor, "enhanced weapon"):
        bonus = 2 if actor.level >= 10 else 1
        for action in actor.actions:
            if not _is_weapon_attack_action(action):
                continue
            if action.to_hit is not None:
                action.to_hit += bonus
            if action.damage:
                action.damage = _damage_expr_with_flat_bonus(action.damage, bonus)

    if _has_trait(actor, "radiant weapon"):
        for action in actor.actions:
            if not _is_weapon_attack_action(action):
                continue
            if action.to_hit is not None:
                action.to_hit += 1
            if action.damage:
                action.damage = _damage_expr_with_flat_bonus(action.damage, 1)

    if _has_trait(actor, "repeating shot"):
        for action in actor.actions:
            if not _is_ranged_weapon_action(action):
                continue
            if action.to_hit is not None:
                action.to_hit += 1
            if action.damage:
                action.damage = _damage_expr_with_flat_bonus(action.damage, 1)
            _mark_action_magical(action)

    if _has_trait(actor, "mind sharpener"):
        actor.resources["mind_sharpener_charges"] = int(
            actor.resources.get("mind_sharpener_charges", 4)
        )
        actor.max_resources["mind_sharpener_charges"] = int(
            actor.max_resources.get("mind_sharpener_charges", 4)
        )

    if _discover_construct_companion_kinds(actor):
        _ensure_action(actor, _construct_command_action())


def _build_construct_companion(owner: ActorRuntimeState, kind: str) -> ActorRuntimeState:
    proficiency = _calculate_proficiency_bonus(owner.level)
    if kind == "steel_defender":
        max_hp = max(1, 2 + owner.int_mod + (5 * owner.level))
        attack = ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=owner.int_mod + proficiency,
            damage=f"1d8+{proficiency}",
            damage_type="force",
            target_mode="single_enemy",
            range_ft=5,
            tags=["basic", "construct_companion", "magical"],
        )
        actor_id = f"{owner.actor_id}__steel_defender"
        name = f"{owner.name} Steel Defender"
        speed = 40
        str_mod, dex_mod, con_mod, int_mod, wis_mod, cha_mod = 2, 2, 2, -4, 0, -4
        ac = 15
    else:
        max_hp = max(1, 1 + owner.int_mod + owner.level)
        attack = ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=owner.int_mod + proficiency,
            damage=f"1d4+{proficiency}",
            damage_type="force",
            target_mode="single_enemy",
            range_ft=30,
            tags=["basic", "construct_companion", "magical"],
        )
        actor_id = f"{owner.actor_id}__homunculus_servant"
        name = f"{owner.name} Homunculus"
        speed = 20
        str_mod, dex_mod, con_mod, int_mod, wis_mod, cha_mod = -2, 2, 0, -4, 0, -2
        ac = 13

    save_mods = {
        "str": str_mod,
        "dex": dex_mod + proficiency,
        "con": con_mod + proficiency,
        "int": int_mod,
        "wis": wis_mod,
        "cha": cha_mod,
    }
    traits = {
        "construct companion": {
            "owner_id": owner.actor_id,
            "requires_command": True,
            "kind": kind,
        }
    }
    if kind == "steel_defender":
        traits["steel defender"] = {}
    else:
        traits["homunculus servant"] = {}

    companion = ActorRuntimeState(
        actor_id=actor_id,
        team=owner.team,
        name=name,
        max_hp=max_hp,
        hp=max_hp,
        temp_hp=0,
        ac=ac,
        initiative_mod=owner.initiative_mod,
        str_mod=str_mod,
        dex_mod=dex_mod,
        con_mod=con_mod,
        int_mod=int_mod,
        wis_mod=wis_mod,
        cha_mod=cha_mod,
        save_mods=save_mods,
        actions=[attack] + _get_standard_actions(),
        resources={},
        max_resources={},
        traits=traits,
        level=owner.level,
        speed_ft=speed,
        companion_owner_id=owner.actor_id,
        requires_command=True,
    )
    companion.position = owner.position
    return companion


def _build_construct_companions(owner: ActorRuntimeState) -> list[ActorRuntimeState]:
    companions: list[ActorRuntimeState] = []
    for kind in sorted(_discover_construct_companion_kinds(owner)):
        companions.append(_build_construct_companion(owner, kind))
    return companions


def _owner_is_incapacitated(owner: ActorRuntimeState | None) -> bool:
    return actor_is_incapacitated(owner)


def _reorder_initiative_for_construct_companions(
    order: list[str], actors: dict[str, ActorRuntimeState]
) -> list[str]:
    working = [actor_id for actor_id in order if actor_id in actors]
    companions = [aid for aid in working if actors[aid].companion_owner_id]
    for companion_id in companions:
        companion = actors.get(companion_id)
        if companion is None or not companion.companion_owner_id:
            continue
        owner_id = companion.companion_owner_id
        if owner_id not in working:
            continue
        working = [aid for aid in working if aid != companion_id]
        insert_at = working.index(owner_id) + 1
        working.insert(insert_at, companion_id)
    return working


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
        "is_magical": _is_magical_action(action),
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
) -> DamageBundle:
    pending = actor.pending_smite
    if not pending:
        return DamageBundle()

    pending_name = str(pending.get("name", "pending_smite")).strip().lower()
    bundle = DamageBundle()
    for payload in pending.get("extra_damage", []):
        if (
            not isinstance(payload, (list, tuple))
            or len(payload) != 2
            or not isinstance(payload[0], str)
        ):
            continue
        expr = payload[0]
        dtype = str(payload[1]).lower()
        bundle.add_packet(
            roll_damage_packet(
                rng,
                expr,
                damage_type=dtype,
                packet_source=f"pending_smite:{pending_name}",
                crit=roll_crit,
                source=actor,
                is_magical=bool(pending.get("is_magical", False)),
            )
        )

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
    return bundle


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


def _downcast_damage(scaled_damage: str, per_level_damage: str, removed_levels: int) -> str:
    if removed_levels <= 0:
        return scaled_damage
    scaled_num, scaled_die, scaled_flat = parse_damage_expression(scaled_damage)
    up_num, up_die, up_flat = parse_damage_expression(per_level_damage)
    if scaled_num <= 0 or up_num <= 0 or scaled_die != up_die or up_flat != 0:
        return scaled_damage
    total_num = scaled_num - (up_num * removed_levels)
    if total_num <= 0:
        return scaled_damage
    if scaled_flat:
        sign = "+" if scaled_flat > 0 else "-"
        return f"{total_num}d{scaled_die}{sign}{abs(scaled_flat)}"
    return f"{total_num}d{scaled_die}"


def _apply_upcast_scaling_for_slot(
    action: ActionDefinition,
    *,
    slot_level: int,
) -> ActionDefinition:
    if "spell" not in action.tags:
        return action
    if action.spell is None:
        return action
    base_level = max(0, int(action.spell.level))
    if base_level <= 0:
        return action
    if slot_level <= base_level:
        if not any(str(tag).startswith("upcast_level:") for tag in action.tags):
            return action
        tags = [tag for tag in action.tags if not str(tag).startswith("upcast_level:")]
        tags = list(dict.fromkeys(tags))
        return _clone_action(action, tags=tags)

    upcast_step = str(action.spell.scaling.upcast_dice_per_level or "").strip()
    if not upcast_step and not any(str(tag).startswith("upcast_level:") for tag in action.tags):
        return action

    existing_upcast_level = _upcast_slot_level_from_action(action)
    upcast_damage = action.damage
    if upcast_step and action.damage:
        base_damage = action.damage
        if existing_upcast_level is not None and existing_upcast_level > base_level:
            base_damage = _downcast_damage(
                action.damage,
                upcast_step,
                existing_upcast_level - base_level,
            )
        upcast_damage = _upcast_damage(base_damage, upcast_step, slot_level - base_level)
        if upcast_damage == base_damage:
            slot_effect = dict(action.spell.scaling.upcast_effects).get(slot_level, {})
            slot_effect_damage = slot_effect.get("damage")
            if isinstance(slot_effect_damage, str) and slot_effect_damage.strip():
                upcast_damage = slot_effect_damage

    tags = [tag for tag in action.tags if not str(tag).startswith("upcast_level:")]
    tags.append(f"upcast_level:{slot_level}")
    tags = list(dict.fromkeys(tags))
    upcast_effects = dict(action.spell.scaling.upcast_effects)
    if isinstance(upcast_damage, str) and upcast_damage.strip():
        existing_effect = dict(upcast_effects.get(slot_level, {}))
        existing_effect["damage"] = upcast_damage
        upcast_effects[slot_level] = existing_effect
    scaled_spell = replace(
        action.spell,
        scaling=replace(action.spell.scaling, upcast_effects=upcast_effects),
    )
    return _clone_action(action, damage=upcast_damage, spell=scaled_spell, tags=tags)


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


def _extract_tag_int(tags: list[str], prefix: str) -> int | None:
    for tag in tags:
        value = str(tag)
        if not value.startswith(prefix):
            continue
        raw = value.split(":", 1)[1]
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _spell_level_from_tags(action: ActionDefinition) -> int | None:
    level = _extract_tag_int(list(action.tags), "spell_level:")
    if level is None:
        return None
    return max(0, int(level))


def _is_cantrip_spell_action(action: ActionDefinition) -> bool:
    if "spell" not in action.tags:
        return False
    if any(str(tag) == "cantrip" for tag in action.tags):
        return True
    if action.spell is not None:
        return int(action.spell.level) == 0
    level = _spell_level_from_tags(action)
    if level is not None:
        return level == 0
    return _spell_level_from_action(action) == 0


def _is_action_cantrip_spell(action: ActionDefinition) -> bool:
    return action.action_cost == "action" and _is_cantrip_spell_action(action)


def _build_spell_components_metadata(raw_components: str) -> SpellComponents:
    normalized = str(raw_components or "")
    tags = _component_tags_from_components(normalized)
    detail: str | None = None
    detail_match = re.search(r"\(([^)]*)\)", normalized)
    if detail_match:
        detail = detail_match.group(1).strip() or None
    return SpellComponents(
        verbal="component:verbal" in tags,
        somatic="component:somatic" in tags,
        material="component:material" in tags,
        material_detail=detail,
        raw=normalized,
    )


def _default_casting_time_for_action_cost(action_cost: str) -> str:
    if action_cost == "bonus":
        return "1 bonus action"
    if action_cost == "reaction":
        return "1 reaction"
    return "1 action"


def _build_spell_metadata(
    *,
    spell: dict[str, Any],
    spell_level: int,
    spell_school: str | None,
    action_cost: str,
    target_mode: str,
    to_hit: int | None,
    save_dc: int | None,
    save_ability: str | None,
    half_on_save: bool,
    upcast_dice_per_level: str,
) -> SpellDefinition:
    raw_components = str(spell.get("components") or "")
    casting_time = str(spell.get("casting_time") or "").strip()
    if not casting_time:
        casting_time = _default_casting_time_for_action_cost(action_cost)
    duration = str(spell.get("duration") or "").strip() or None
    scaling = SpellScaling(upcast_dice_per_level=upcast_dice_per_level or None)
    return SpellDefinition(
        name=str(spell.get("name", "unknown_spell")),
        level=max(0, int(spell_level)),
        school=spell_school,
        casting_time=casting_time,
        concentration=bool(spell.get("concentration", False)),
        duration=duration,
        target_mode=target_mode,
        roll=SpellRoll(
            attack_bonus=int(to_hit) if to_hit is not None else None,
            save_dc=int(save_dc) if save_dc is not None else None,
            save_ability=str(save_ability) if save_ability else None,
            half_on_save=bool(half_on_save),
        ),
        scaling=scaling,
        components=_build_spell_components_metadata(raw_components),
    )


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


_REACTION_ID_TAG_PREFIXES = (
    "spell_id:",
    "spell:",
    "action_id:",
    "action:",
    "reaction_id:",
    "reaction:",
)


def _canonical_reaction_spell_id(value: str) -> str:
    key = _spell_lookup_key(value)
    if not key:
        return ""

    tokens = [token for token in key.split() if token]
    while tokens and tokens[-1] == "reaction":
        tokens.pop()

    if len(tokens) == 2 and tokens[1] == "spell" and tokens[0] == "shield":
        tokens = [tokens[0]]

    return "".join(tokens)


def _action_reaction_spell_ids(action: ActionDefinition) -> set[str]:
    ids: set[str] = set()

    def _add(value: str) -> None:
        canonical = _canonical_reaction_spell_id(value)
        if canonical:
            ids.add(canonical)

    _add(action.name)
    if action.spell is not None:
        _add(action.spell.name)

    for raw_tag in action.tags:
        tag = str(raw_tag).strip()
        if not tag:
            continue
        _add(tag)
        lowered = tag.lower()
        for prefix in _REACTION_ID_TAG_PREFIXES:
            if lowered.startswith(prefix):
                _add(tag.split(":", 1)[1])
                break

    return ids


def _action_matches_reaction_spell_id(action: ActionDefinition, *, spell_id: str) -> bool:
    canonical_spell_id = _canonical_reaction_spell_id(spell_id)
    if not canonical_spell_id:
        return False
    return canonical_spell_id in _action_reaction_spell_ids(action)


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


_KNOWN_SPELL_LIST_CLASSES = ("bard", "ranger", "sorcerer", "warlock")
_PREPARED_SPELL_LIST_CLASSES = ("artificer", "cleric", "druid", "paladin", "wizard")


def _character_uses_known_spell_list(character: dict[str, Any]) -> bool:
    class_level_text = str(character.get("class_level", "") or "")
    if not class_level_text:
        return False

    has_known = any(
        _parse_class_level(class_level_text, class_name) > 0
        for class_name in _KNOWN_SPELL_LIST_CLASSES
    )
    has_prepared = any(
        _parse_class_level(class_level_text, class_name) > 0
        for class_name in _PREPARED_SPELL_LIST_CLASSES
    )
    return has_known and not has_prepared


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
    uses_known_spell_list = _character_uses_known_spell_list(character)
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
            and not uses_known_spell_list
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
        if casting_time:
            hydrated["casting_time"] = casting_time
        if duration:
            hydrated["duration"] = duration
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
            school = _extract_spell_school(spell_def)
            if school is not None:
                hydrated["school"] = school
            if "save_ability" in spell_def:
                hydrated["save_ability"] = str(
                    spell_def.get("save_ability") or ""
                ).lower() or hydrated.get("save_ability")
            if "components" in spell_def:
                hydrated["components"] = str(spell_def.get("components") or "")
            if "casting_time" in spell_def:
                hydrated["casting_time"] = str(spell_def.get("casting_time") or "")
            if "duration" in spell_def:
                hydrated["duration"] = str(spell_def.get("duration") or "")
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
            if "no benefit from cover" in description.lower():
                tags = [str(tag) for tag in hydrated.get("tags", [])]
                tags.append("ignore_dex_save_cover")
                hydrated["tags"] = list(dict.fromkeys(tags))

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


def _clone_action(action: ActionDefinition, **overrides: Any) -> ActionDefinition:
    payload: dict[str, Any] = {
        "name": action.name,
        "action_type": action.action_type,
        "attack_profile_id": action.attack_profile_id,
        "weapon_id": action.weapon_id,
        "item_id": action.item_id,
        "weapon_properties": list(action.weapon_properties),
        "to_hit": action.to_hit,
        "damage": action.damage,
        "damage_type": action.damage_type,
        "attack_count": action.attack_count,
        "save_dc": action.save_dc,
        "save_ability": action.save_ability,
        "half_on_save": action.half_on_save,
        "resource_cost": dict(action.resource_cost),
        "recharge": action.recharge,
        "max_uses": action.max_uses,
        "action_cost": action.action_cost,
        "event_trigger": action.event_trigger,
        "target_mode": action.target_mode,
        "reach_ft": action.reach_ft,
        "range_ft": action.range_ft,
        "range_normal_ft": action.range_normal_ft,
        "range_long_ft": action.range_long_ft,
        "aoe_type": action.aoe_type,
        "aoe_size_ft": action.aoe_size_ft,
        "max_targets": action.max_targets,
        "concentration": action.concentration,
        "include_self": action.include_self,
        "effects": [
            dict(effect) if isinstance(effect, dict) else effect for effect in action.effects
        ],
        "mechanics": [
            dict(mechanic) if isinstance(mechanic, dict) else mechanic
            for mechanic in action.mechanics
        ],
        "spell": (
            replace(
                action.spell,
                roll=replace(action.spell.roll),
                scaling=replace(
                    action.spell.scaling,
                    upcast_effects=dict(action.spell.scaling.upcast_effects),
                ),
                components=replace(action.spell.components),
            )
            if action.spell is not None
            else None
        ),
        "tags": list(action.tags),
    }
    payload.update(overrides)
    return ActionDefinition(**payload)


def _add_resource_cost(base_cost: dict[str, int], key: str, amount: int) -> dict[str, int]:
    result = dict(base_cost)
    result[key] = result.get(key, 0) + int(amount)
    return result


def _action_has_duration_payload(action: ActionDefinition) -> bool:
    for entry in action.effects + action.mechanics:
        if not isinstance(entry, dict):
            continue
        for key in ("duration_rounds", "duration"):
            raw_value = entry.get(key)
            if isinstance(raw_value, int) and raw_value > 0:
                return True
    return False


def _double_duration_payload(entries: list[Any]) -> list[Any]:
    doubled: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            doubled.append(entry)
            continue
        updated = dict(entry)
        for key in ("duration_rounds", "duration"):
            raw_value = updated.get(key)
            if isinstance(raw_value, int) and raw_value > 0:
                updated[key] = raw_value * 2
        doubled.append(updated)
    return doubled


def _build_metamagic_spell_actions(
    action: ActionDefinition,
    *,
    spell_level: int,
    traits: set[str],
) -> list[ActionDefinition]:
    if "spell" not in action.tags or not traits:
        return []

    variants: list[ActionDefinition] = []
    has_damage = bool(action.damage)
    has_duration = action.concentration or _action_has_duration_payload(action)
    is_single_target = (
        action.target_mode in {"single_enemy", "single_ally"}
        and action.max_targets in (None, 1)
        and not action.aoe_type
        and not action.include_self
    )
    can_range_extend = (
        action.range_ft is not None and action.range_ft > 0 and action.target_mode != "self"
    )
    is_save_spell = (
        action.action_type == "save" and action.save_dc is not None and bool(action.save_ability)
    )
    is_action_spell = action.action_cost == "action"

    def has_trait(name: str) -> bool:
        return _normalize_trait_name(name) in traits

    def add_variant(
        option: str,
        *,
        sorcery_cost: int,
        target_mode: str | None = None,
        max_targets: int | None = None,
        action_cost: str | None = None,
        range_ft: int | None = None,
        effects: list[dict[str, Any]] | None = None,
        mechanics: list[dict[str, Any]] | None = None,
    ) -> None:
        label = option.capitalize()
        tags = list(action.tags)
        tags.extend(["metamagic", f"metamagic:{option}"])
        variant = _clone_action(
            action,
            name=f"{action.name} [{label}]",
            resource_cost=_add_resource_cost(action.resource_cost, "sorcery_points", sorcery_cost),
            tags=tags,
            target_mode=target_mode if target_mode is not None else action.target_mode,
            max_targets=max_targets if max_targets is not None else action.max_targets,
            action_cost=action_cost if action_cost is not None else action.action_cost,
            range_ft=range_ft if range_ft is not None else action.range_ft,
            effects=effects if effects is not None else action.effects,
            mechanics=mechanics if mechanics is not None else action.mechanics,
        )
        variants.append(variant)

    if has_trait("careful spell") and is_save_spell:
        add_variant("careful", sorcery_cost=1)
    if has_trait("distant spell") and can_range_extend and action.range_ft is not None:
        add_variant("distant", sorcery_cost=1, range_ft=action.range_ft * 2)
    if has_trait("empowered spell") and has_damage:
        add_variant("empowered", sorcery_cost=1)
    if has_trait("extended spell") and has_duration:
        effects = action.effects
        mechanics = action.mechanics
        if _action_has_duration_payload(action):
            effects = _double_duration_payload(action.effects)
            mechanics = _double_duration_payload(action.mechanics)
        add_variant("extended", sorcery_cost=1, effects=effects, mechanics=mechanics)
    if has_trait("heightened spell") and is_save_spell:
        add_variant("heightened", sorcery_cost=3)
    if has_trait("quickened spell") and is_action_spell:
        add_variant("quickened", sorcery_cost=2, action_cost="bonus")
    if has_trait("subtle spell"):
        add_variant("subtle", sorcery_cost=1)
    if has_trait("twinned spell") and is_single_target:
        twin_mode = "n_enemies" if action.target_mode == "single_enemy" else "n_allies"
        add_variant(
            "twinned",
            sorcery_cost=max(1, int(spell_level)),
            target_mode=twin_mode,
            max_targets=2,
        )

    return variants


def _build_font_of_magic_actions(resources: dict[str, Any]) -> list[ActionDefinition]:
    sorcery_points_raw = resources.get("sorcery_points")
    has_sorcery_points = isinstance(sorcery_points_raw, int) or (
        isinstance(sorcery_points_raw, dict) and int(sorcery_points_raw.get("max", 0)) > 0
    )
    if not has_sorcery_points:
        return []

    actions: list[ActionDefinition] = []
    for level, cost in _SPELL_SLOT_CREATION_COSTS.items():
        actions.append(
            ActionDefinition(
                name=f"font_of_magic_create_slot_{level}",
                action_type="utility",
                action_cost="bonus",
                target_mode="self",
                resource_cost={"sorcery_points": cost},
                tags=[
                    "class_feature",
                    "font_of_magic",
                    "conversion:points_to_slot",
                    f"slot_level:{level}",
                ],
            )
        )

    raw_slots = resources.get("spell_slots", {})
    if isinstance(raw_slots, dict):
        slot_levels: list[int] = []
        for key in raw_slots:
            try:
                level = int(key)
            except (TypeError, ValueError):
                continue
            if level > 0:
                slot_levels.append(level)
        for level in sorted(set(slot_levels)):
            actions.append(
                ActionDefinition(
                    name=f"font_of_magic_convert_slot_{level}",
                    action_type="utility",
                    action_cost="bonus",
                    target_mode="self",
                    resource_cost={f"spell_slot_{level}": 1},
                    tags=[
                        "class_feature",
                        "font_of_magic",
                        "conversion:slot_to_points",
                        f"slot_level:{level}",
                    ],
                )
            )

    return actions


def _extract_tag_value(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        text = str(tag)
        if text.startswith(prefix):
            return text.split(":", 1)[1]
    return None


def _slot_level_from_action(action: ActionDefinition) -> int | None:
    raw_level = _extract_tag_value(list(action.tags), "slot_level:")
    if raw_level is None:
        return None
    try:
        level = int(raw_level)
    except ValueError:
        return None
    return level if level > 0 else None


def _has_tag(action: ActionDefinition, tag: str) -> bool:
    return any(str(value) == tag for value in action.tags)


def _build_spell_actions(
    character: dict[str, Any],
    *,
    character_level: int,
    traits: set[str] | None = None,
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
    known_traits = set(traits or set())
    resources = character.get("resources", {})
    raw_spell_slots = resources.get("spell_slots")
    available_slots: dict[str, Any] = {}
    if isinstance(raw_spell_slots, dict):
        available_slots = raw_spell_slots

    has_pact_magic = _is_pact_magic_character(character)
    warlock_level = _warlock_level_from_character(character)
    arcanum_max_level = _warlock_mystic_arcanum_max_level(warlock_level)

    pact_profile = _extract_pact_slot_profile_from_spell_slots(raw_spell_slots)
    has_any_positive_slot = False
    if isinstance(raw_spell_slots, dict):
        for value in raw_spell_slots.values():
            try:
                if int(value) > 0:
                    has_any_positive_slot = True
                    break
            except (TypeError, ValueError):
                continue
    if pact_profile is None and has_pact_magic and not has_any_positive_slot:
        pact_profile = _warlock_pact_slot_profile_for_level(warlock_level)
    pact_slot_key: str | None = None
    if pact_profile is not None:
        pact_slot_level, _pact_slot_count = pact_profile
        pact_slot_key = f"warlock_spell_slot_{pact_slot_level}"

    for spell in spells:
        name = str(spell.get("name", "unknown_spell"))
        spell_level = int(spell.get("level", 0))
        smite_setup = _is_smite_spell_name(name)
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
        tags.append(f"spell_level:{max(0, spell_level)}")
        if spell_level == 0:
            tags.append("cantrip")
        spell_school = _extract_spell_school(spell)
        if spell_school is not None:
            tags.append(f"school:{spell_school}")
        components = str(spell.get("components") or "")
        if components:
            tags.extend(sorted(_component_tags_from_components(components)))
        tags = list(dict.fromkeys(tags))
        smite_setup = _is_smite_spell_name(name)
        if smite_setup:
            action_type = "utility"
            target_mode = "self"
            damage = None
            half_on_save = False
            if "smite_variant" not in tags:
                tags.append("smite_variant")

        resource_cost: dict[str, int] = {}
        max_uses: int | None = None

        if spell_level == 0:
            # Cantrip: no slot cost, scale damage by level
            if damage:
                damage = _scale_cantrip_dice(str(damage), character_level)
        elif has_pact_magic and spell_level >= 6 and arcanum_max_level >= spell_level:
            max_uses = 1
            tags.append("mystic_arcanum")
        elif has_pact_magic and pact_slot_key is not None and spell_level <= 5:
            resource_cost[pact_slot_key] = 1
            tags.append("pact_magic")
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

        upcast_step = str(spell.get("upcast_dice_per_level") or "").strip()
        spell_metadata = _build_spell_metadata(
            spell=spell,
            spell_level=spell_level,
            spell_school=spell_school,
            action_cost=action_cost,
            target_mode=target_mode,
            to_hit=int(to_hit) if to_hit is not None else None,
            save_dc=int(save_dc) if save_dc is not None else None,
            save_ability=str(save_ability) if save_ability else None,
            half_on_save=half_on_save,
            upcast_dice_per_level=upcast_step,
        )

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
            max_uses=max_uses,
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
            spell=spell_metadata,
            tags=tags,
        )
        actions.append(action)
        actions.extend(
            _build_metamagic_spell_actions(action, spell_level=spell_level, traits=known_traits)
        )

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
                upcast_scaling = replace(
                    spell_metadata.scaling,
                    upcast_effects={
                        **dict(spell_metadata.scaling.upcast_effects),
                        slot_level: {"damage": upcast_damage},
                    },
                )
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
                        include_self=smite_setup,
                        effects=list(effects),
                        mechanics=list(mechanics),
                        spell=replace(spell_metadata, scaling=upcast_scaling),
                        tags=list(tags) + [f"upcast_level:{slot_level}"],
                    )
                )

    _apply_wizard_school_action_hooks(actions, traits=known_traits)
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


def _apply_warlock_invocations_to_actions(
    character: dict[str, Any], actions: list[ActionDefinition]
) -> None:
    invocations = _extract_warlock_invocations(character)
    if not invocations:
        return

    for action in actions:
        if _trait_lookup_key(action.name) != "eldritch blast":
            continue
        if "agonizing blast" in invocations and "agonizing_blast" not in action.tags:
            action.tags.append("agonizing_blast")
        if "repelling blast" in invocations:
            has_repelling = any(
                isinstance(effect, dict)
                and effect.get("effect_type") == "forced_movement"
                and effect.get("distance_ft") == 10
                and effect.get("direction") == "away_from_source"
                for effect in action.mechanics
            )
            if not has_repelling:
                action.mechanics.append(
                    {
                        "effect_type": "forced_movement",
                        "target": "target",
                        "distance_ft": 10,
                        "direction": "away_from_source",
                        "apply_on": "hit",
                    }
                )


def _extract_selected_maneuvers(character: dict[str, Any], traits: set[str]) -> list[str]:
    known_by_key = {_trait_lookup_key(name): name for name in _KNOWN_MANEUVERS}
    candidates: set[str] = set(str(value) for value in (character.get("traits", []) or []))
    candidates.update(_extract_trait_candidates_from_raw_fields(character))

    selected: list[str] = []
    seen: set[str] = set()
    for candidate in sorted(candidates):
        maneuver_name = known_by_key.get(_trait_lookup_key(candidate))
        if maneuver_name is None or maneuver_name in seen:
            continue
        selected.append(maneuver_name)
        seen.add(maneuver_name)

    if selected:
        return selected
    if {"combat superiority", "maneuvers", "battle master"}.intersection(traits):
        return list(_DEFAULT_BATTLEMASTER_MANEUVERS)
    return []


def _build_maneuver_attack_action(
    *,
    maneuver_name: str,
    best_attack: dict[str, Any],
    attack_count: int,
    superiority_die_size: int,
    save_dc: int,
) -> ActionDefinition:
    slug = re.sub(r"[^a-z0-9]+", "_", maneuver_name.lower()).strip("_")
    base_to_hit = int(best_attack.get("to_hit", 0))
    to_hit_bonus = 0
    effects: list[dict[str, Any]] = []
    weapon_damage_type = str(best_attack.get("damage_type", "bludgeoning"))

    if maneuver_name == "precision attack":
        to_hit_bonus = max(1, (superiority_die_size + 1) // 2)
    else:
        effects.append(
            {
                "effect_type": "damage",
                "target": "target",
                "apply_on": "hit",
                "damage": f"1d{superiority_die_size}",
                "damage_type": weapon_damage_type,
                "once_per_action": True,
            }
        )
        if maneuver_name == "trip attack":
            effects.append(
                {
                    "effect_type": "apply_condition",
                    "target": "target",
                    "apply_on": "hit",
                    "condition": "prone",
                    "save_dc": save_dc,
                    "save_ability": "str",
                    "once_per_action": True,
                }
            )
        elif maneuver_name == "menacing attack":
            effects.append(
                {
                    "effect_type": "apply_condition",
                    "target": "target",
                    "apply_on": "hit",
                    "condition": "frightened",
                    "save_dc": save_dc,
                    "save_ability": "wis",
                    "once_per_action": True,
                }
            )
        elif maneuver_name == "pushing attack":
            effects.append(
                {
                    "effect_type": "forced_movement",
                    "target": "target",
                    "apply_on": "hit",
                    "direction": "away_from_source",
                    "distance_ft": 15,
                    "save_dc": save_dc,
                    "save_ability": "str",
                    "once_per_action": True,
                }
            )
        elif maneuver_name == "goading attack":
            effects.append(
                {
                    "effect_type": "next_attack_disadvantage",
                    "target": "target",
                    "apply_on": "hit",
                    "once_per_action": True,
                }
            )

    return ActionDefinition(
        name=f"maneuver_{slug}",
        action_type="attack",
        attack_profile_id=str(best_attack.get("attack_profile_id") or ""),
        weapon_id=str(best_attack.get("weapon_id") or ""),
        item_id=str(best_attack.get("item_id") or ""),
        weapon_properties=list(best_attack.get("weapon_properties", [])),
        to_hit=base_to_hit + to_hit_bonus,
        damage=str(best_attack.get("damage", "1")),
        damage_type=weapon_damage_type,
        attack_count=attack_count,
        reach_ft=_coerce_optional_int(best_attack.get("reach_ft")),
        range_ft=_coerce_optional_int(best_attack.get("range_ft")),
        range_normal_ft=_coerce_optional_int(best_attack.get("range_normal_ft")),
        range_long_ft=_coerce_optional_int(best_attack.get("range_long_ft")),
        resource_cost={"superiority_dice": 1},
        effects=effects,
        tags=["attack_option", "maneuver", f"maneuver:{slug}"],
    )


def _build_character_actions(character: dict[str, Any]) -> list[ActionDefinition]:
    attacks = [
        _normalize_attack_definition(attack, idx)
        for idx, attack in enumerate(character.get("attacks", []), start=1)
    ]
    resources = character.get("resources", {})
    traits = {_normalize_trait_name(trait) for trait in character.get("traits", [])}
    class_level_text = str(character.get("class_level", "1"))
    character_level = _parse_character_level(class_level_text)
    fighter_level = _parse_class_level(class_level_text, "fighter")

    def has_trait(name: str) -> bool:
        return _normalize_trait_name(name) in traits

    def resource_pool_max(resource_name: str) -> int:
        value = resources.get(resource_name, 0)
        if isinstance(value, dict):
            raw = value.get("max", 0)
            return int(raw) if isinstance(raw, (int, float)) else 0
        return int(value) if isinstance(value, int) else 0

    def attack_identity_payload(attack: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "attack_profile_id": str(attack.get("attack_profile_id") or ""),
            "weapon_id": str(attack.get("weapon_id") or ""),
            "item_id": str(attack.get("item_id") or ""),
            "weapon_properties": list(attack.get("weapon_properties", [])),
            "reach_ft": _coerce_optional_int(attack.get("reach_ft")),
            "range_ft": _coerce_optional_int(attack.get("range_ft")),
            "range_normal_ft": _coerce_optional_int(attack.get("range_normal_ft")),
            "range_long_ft": _coerce_optional_int(attack.get("range_long_ft")),
        }
        return {
            key: value
            for key, value in payload.items()
            if value not in ("", None, []) or key in {"attack_profile_id", "weapon_id", "item_id"}
        }

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
                **attack_identity_payload(best_attack),
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
                    **attack_identity_payload(attack),
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
                    **attack_identity_payload(best_attack),
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
                    **attack_identity_payload(secondary),
                    to_hit=int(secondary.get("to_hit", best_attack.get("to_hit", 0))),
                    damage=str(secondary.get("damage", best_attack.get("damage", "1"))),
                    damage_type=str(
                        secondary.get("damage_type", best_attack.get("damage_type", "bludgeoning"))
                    ),
                    attack_count=attack_count,
                    tags=["signature"],
                )
            )

        superiority_traits = {"combat superiority", "maneuvers", "battle master", "martial adept"}
        if superiority_traits.intersection(traits):
            selected_maneuvers = _extract_selected_maneuvers(character, traits)
            die_size = _fighter_superiority_die_size(fighter_level, traits=traits)
            ability_scores = character.get("ability_scores", {})
            str_mod = (int(ability_scores.get("str", 10)) - 10) // 2
            dex_mod = (int(ability_scores.get("dex", 10)) - 10) // 2
            save_dc = 8 + _calculate_proficiency_bonus(character_level) + max(str_mod, dex_mod)
            for maneuver_name in selected_maneuvers:
                actions.append(
                    _build_maneuver_attack_action(
                        maneuver_name=maneuver_name,
                        best_attack=best_attack,
                        attack_count=attack_count,
                        superiority_die_size=die_size,
                        save_dc=save_dc,
                    )
                )

        # --- Bonus actions ---
        if has_trait("martial arts"):
            actions.append(
                ActionDefinition(
                    name="martial_arts_bonus",
                    action_type="attack",
                    **attack_identity_payload(best_attack),
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
                        **attack_identity_payload(best_attack),
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
            weapon_name = str(best_attack.get("weapon_id") or best_attack.get("name", "")).lower()
            if any(
                w in weapon_name for w in ["glaive", "halberd", "quarterstaff", "spear", "pike"]
            ):
                flat_mod_match = re.search(r"([+-]\s*\d+)", str(best_attack.get("damage", "")))
                flat_mod = flat_mod_match.group(1).replace(" ", "") if flat_mod_match else ""
                actions.append(
                    ActionDefinition(
                        name="polearm_master_bonus",
                        action_type="attack",
                        **attack_identity_payload(best_attack),
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
                    **attack_identity_payload(off_hand),
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
                    **attack_identity_payload(best_attack),
                    to_hit=int(best_attack.get("to_hit", 0)),
                    damage=str(best_attack.get("damage", "1")),
                    damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                    action_cost="bonus",
                    tags=["bonus", "gwm_bonus"],
                )
            )

        if has_trait("second wind"):
            second_wind_level = max(1, fighter_level or character_level)
            actions.append(
                ActionDefinition(
                    name="second_wind",
                    action_type="utility",
                    action_cost="bonus",
                    target_mode="self",
                    resource_cost={"second_wind": 1},
                    effects=[
                        {
                            "effect_type": "heal",
                            "target": "target",
                            "amount": f"1d10+{second_wind_level}",
                        }
                    ],
                    tags=["bonus", "short_rest", "second_wind"],
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
        spell_actions = _build_spell_actions(
            character,
            character_level=character_level,
            traits=traits,
        )
        _apply_warlock_invocations_to_actions(character, spell_actions)
        actions.extend(spell_actions)
        actions.extend(_build_font_of_magic_actions(resources))
        actions.extend(
            _build_cleric_channel_divinity_actions(
                character=character,
                character_level=character_level,
                traits=traits,
            )
        )

        return actions

    # Fallback: no attacks defined
    spell_actions = _build_spell_actions(character, character_level=character_level, traits=traits)
    font_of_magic_actions = _build_font_of_magic_actions(resources)
    _apply_warlock_invocations_to_actions(character, spell_actions)
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
    if has_trait("second wind"):
        second_wind_level = max(1, fighter_level or character_level)
        base.append(
            ActionDefinition(
                name="second_wind",
                action_type="utility",
                action_cost="bonus",
                target_mode="self",
                resource_cost={"second_wind": 1},
                effects=[
                    {
                        "effect_type": "heal",
                        "target": "target",
                        "amount": f"1d10+{second_wind_level}",
                    }
                ],
                tags=["bonus", "short_rest", "second_wind"],
            )
        )
    return base + spell_actions + font_of_magic_actions + cleric_actions


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
    feature_resource_aliases = {
        "action_surge": "action_surge",
        "second_wind": "second_wind",
        "superiority_dice": "superiority_dice",
    }
    raw = character.get("resources", {})
    has_pact_magic = _is_pact_magic_character(character)
    warlock_level = _warlock_level_from_character(character)
    raw_spell_slots = raw.get("spell_slots")
    pact_slot_profile = _extract_pact_slot_profile_from_spell_slots(raw_spell_slots)
    has_any_positive_slot = False
    if isinstance(raw_spell_slots, dict):
        for value in raw_spell_slots.values():
            try:
                if int(value) > 0:
                    has_any_positive_slot = True
                    break
            except (TypeError, ValueError):
                continue
    if pact_slot_profile is None and has_pact_magic and not has_any_positive_slot:
        pact_slot_profile = _warlock_pact_slot_profile_for_level(warlock_level)

    for key, value in raw.items():
        if isinstance(value, dict):
            max_value = value.get("max")
            if isinstance(max_value, int):
                result[key] = max_value
            elif key == "spell_slots":
                if has_pact_magic and pact_slot_profile is not None:
                    pact_slot_level, pact_slot_count = pact_slot_profile
                    result[f"warlock_spell_slot_{pact_slot_level}"] = pact_slot_count
                else:
                    for level, slots in value.items():
                        result[f"spell_slot_{level}"] = int(slots)
            else:
                for name, amount in value.items():
                    if isinstance(amount, int):
                        mapped = feature_resource_aliases.get(str(name))
                        if key == "feature_uses" and mapped is not None:
                            result[mapped] = amount
                        else:
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


def _ensure_resource_cap(actor: ActorRuntimeState, resource: str, max_value: int) -> None:
    if max_value <= 0:
        return
    existing_max = int(actor.max_resources.get(resource, 0))
    if existing_max < max_value:
        actor.max_resources[resource] = max_value
    cap = int(actor.max_resources[resource])
    if resource not in actor.resources:
        actor.resources[resource] = cap
    else:
        actor.resources[resource] = max(0, min(int(actor.resources[resource]), cap))


def _apply_inferred_fighter_resources(
    actor: ActorRuntimeState,
    *,
    class_level_text: str,
) -> None:
    fighter_level = _parse_class_level(class_level_text, "fighter")

    if _has_trait(actor, "action surge"):
        action_surge_uses = (
            2 if fighter_level >= 17 or _has_trait(actor, "action surge (two uses)") else 1
        )
        _ensure_resource_cap(actor, "action_surge", action_surge_uses)

    if _has_trait(actor, "second wind"):
        _ensure_resource_cap(actor, "second_wind", 1)

    superiority_sources = ("combat superiority", "maneuvers", "battle master", "martial adept")
    if any(_has_trait(actor, trait_name) for trait_name in superiority_sources):
        superiority_dice = _fighter_superiority_dice_count(fighter_level)
        if superiority_dice <= 0 and _has_trait(actor, "martial adept"):
            superiority_dice = 1
        if superiority_dice > 0:
            _ensure_resource_cap(actor, "superiority_dice", superiority_dice)


def _apply_inferred_wizard_resources(actor: ActorRuntimeState) -> None:
    if not _has_trait(actor, "arcane recovery"):
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    _ensure_resource_cap(actor, "arcane_recovery", 1)


def _iter_spell_slot_levels_desc(actor: ActorRuntimeState) -> list[int]:
    levels: set[int] = set()
    for key in actor.max_resources.keys():
        if not str(key).startswith("spell_slot_"):
            continue
        try:
            level = int(str(key).rsplit("_", 1)[1])
        except ValueError:
            continue
        if level > 0:
            levels.add(level)
    return sorted(levels, reverse=True)


def _recover_spell_slots_with_budget(
    actor: ActorRuntimeState,
    *,
    budget: int,
    max_individual_slot_level: int,
) -> int:
    if budget <= 0:
        return 0
    recovered_levels = 0
    for slot_level in _iter_spell_slot_levels_desc(actor):
        if slot_level > max_individual_slot_level or budget < slot_level:
            continue
        slot_key = f"spell_slot_{slot_level}"
        max_slots = int(actor.max_resources.get(slot_key, 0))
        current_slots = min(int(actor.resources.get(slot_key, 0)), max_slots)
        missing_slots = max(0, max_slots - current_slots)
        recoverable_slots = min(missing_slots, budget // slot_level)
        if recoverable_slots <= 0:
            continue
        actor.resources[slot_key] = current_slots + recoverable_slots
        recovered_levels += recoverable_slots * slot_level
        budget -= recoverable_slots * slot_level
        if budget <= 0:
            break
    return recovered_levels


def _apply_arcane_recovery(actor: ActorRuntimeState) -> None:
    if not _has_trait(actor, "arcane recovery"):
        return
    uses_remaining = int(actor.resources.get("arcane_recovery", 0))
    if uses_remaining <= 0:
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    recovery_budget = max(1, (wizard_level + 1) // 2)
    recovered_levels = _recover_spell_slots_with_budget(
        actor,
        budget=recovery_budget,
        max_individual_slot_level=5,
    )
    if recovered_levels <= 0:
        return
    actor.resources["arcane_recovery"] = uses_remaining - 1


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


def _ensure_resource_cap(actor: ActorRuntimeState, resource: str, max_value: int) -> None:
    if max_value <= 0:
        return
    existing_max = int(actor.max_resources.get(resource, 0))
    if existing_max < max_value:
        actor.max_resources[resource] = max_value
    cap = int(actor.max_resources[resource])
    if resource not in actor.resources:
        actor.resources[resource] = cap
    else:
        actor.resources[resource] = max(0, min(int(actor.resources[resource]), cap))


def _apply_inferred_wizard_resources(actor: ActorRuntimeState) -> None:
    if not _has_trait(actor, "arcane recovery"):
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    _ensure_resource_cap(actor, "arcane_recovery", 1)


def _build_actor_from_character(
    character: dict[str, Any], traits_db: dict[str, dict[str, Any]] = None
) -> ActorRuntimeState:
    normalized_traits_db = {
        _normalize_trait_name(key): value for key, value in (traits_db or {}).items()
    }
    class_level_text = str(character.get("class_level", "1"))
    class_levels = _parse_class_levels(class_level_text)
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
        level=_parse_character_level(class_level_text),
        class_levels=class_levels,
        inventory=InventoryState.from_character_payload(character),
    )
    _ensure_channel_divinity_resource(actor)
    _apply_passive_traits(actor)
    _apply_artificer_infusion_passives(actor)
    _apply_inferred_wizard_resources(actor)
    _apply_inferred_fighter_resources(actor, class_level_text=class_level_text)
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
                    attack_profile_id=getattr(action, "attack_profile_id", None),
                    weapon_id=getattr(action, "weapon_id", None),
                    item_id=getattr(action, "item_id", None),
                    weapon_properties=list(getattr(action, "weapon_properties", [])),
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
                    reach_ft=getattr(action, "reach_ft", None),
                    range_ft=getattr(action, "range_ft", None),
                    range_normal_ft=getattr(action, "range_normal_ft", None),
                    range_long_ft=getattr(action, "range_long_ft", None),
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

    short_rest_resources = {
        "action_surge",
        "second_wind",
        "superiority_dice",
        "ki",
        "channel_divinity",
    }
    for res_key in list(actor.resources.keys()):
        if (
            res_key in short_rest_resources
            or "warlock_spell_slot" in res_key
            or _is_channel_divinity_resource_name(res_key)
        ):
            actor.resources[res_key] = actor.max_resources.get(res_key, 0)

    _apply_arcane_recovery(actor)

    for action in actor.actions:
        if action.name in {"action_surge", "second_wind"} or "short_rest" in action.tags:
            actor.per_action_uses.pop(action.name, None)


def long_rest(actor: ActorRuntimeState) -> None:
    actor.hp = actor.max_hp
    actor.temp_hp = 0
    actor.resources = dict(actor.max_resources)
    actor.per_action_uses.clear()
    actor.conditions.clear()
    actor.intrinsic_conditions.clear()
    actor.condition_durations.clear()
    actor.effect_instances.clear()
    actor.effect_instance_seq = 0
    actor.death_failures = 0
    actor.death_successes = 0
    actor.downed_count = 0
    actor.concentrating = False
    actor.concentrated_targets.clear()
    actor.concentration_conditions.clear()
    actor.concentration_effect_instance_ids.clear()
    actor.concentrated_spell = None
    actor.concentrated_spell_level = None
    actor.readied_action_name = None
    actor.readied_trigger = None
    actor.readied_reaction_reserved = False
    actor.readied_spell_slot_level = None
    actor.readied_spell_held = False
    actor.bonus_action_spell_restriction_active = False
    actor.non_action_cantrip_spell_cast_this_turn = False
    actor.gwm_bonus_trigger_available = False
    actor.movement_remaining = float(actor.speed_ft)


def _normalize_travel_pace(value: Any) -> str:
    pace = str(value or "normal").lower().strip()
    if pace not in _TRAVEL_PACE_MILES_PER_DAY:
        return "normal"
    return pace


def _parse_resource_loss(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}

    parsed: dict[str, int] = {}
    for key, value in raw.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            parsed[str(key)] = amount
    return parsed


def _parse_damage_expression(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return str(int(raw))
    text = str(raw).strip()
    if not text:
        return None
    return text


def _spend_exploration_resources(
    actor: ActorRuntimeState,
    resource_loss: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
) -> None:
    if not resource_loss:
        return

    for key, amount in resource_loss.items():
        current = int(actor.resources.get(key, 0))
        spent = min(current, int(amount))
        if spent <= 0:
            continue
        actor.resources[key] = current - spent
        resources_spent[actor.actor_id][key] = resources_spent[actor.actor_id].get(key, 0) + spent


def _apply_exploration_damage(
    rng: random.Random,
    actor: ActorRuntimeState,
    damage_expr: Any,
    damage_type: str,
    damage_taken: dict[str, int],
) -> None:
    expr = _parse_damage_expression(damage_expr)
    if expr is None:
        return
    try:
        rolled = roll_damage(rng, expr)
    except ValueError:
        return
    if rolled <= 0:
        return

    applied = apply_damage(actor, rolled, damage_type or "environmental")
    damage_taken[actor.actor_id] = damage_taken.get(actor.actor_id, 0) + applied


def _determine_exploration_segments(leg_config: dict[str, Any], travel_pace: str) -> int:
    segments = leg_config.get("segments")
    try:
        explicit_segments = int(segments)
    except (TypeError, ValueError):
        explicit_segments = 0
    if explicit_segments > 0:
        return explicit_segments

    distance = leg_config.get("distance_miles", 0)
    try:
        miles = float(distance)
    except (TypeError, ValueError):
        miles = 0.0
    if miles > 0:
        miles_per_day = _TRAVEL_PACE_MILES_PER_DAY.get(
            travel_pace, _TRAVEL_PACE_MILES_PER_DAY["normal"]
        )
        return max(1, int(math.ceil(miles / miles_per_day)))

    has_effects = (
        bool(leg_config.get("hazard_checks"))
        or bool(leg_config.get("resource_attrition"))
        or bool(_parse_damage_expression(leg_config.get("hp_attrition")))
    )
    return 1 if has_effects else 0


def _run_exploration_leg(
    *,
    rng: random.Random,
    actors: dict[str, ActorRuntimeState],
    damage_taken: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    leg_config: dict[str, Any],
) -> None:
    if not isinstance(leg_config, dict):
        return

    travel_pace = _normalize_travel_pace(leg_config.get("travel_pace", "normal"))
    segments = _determine_exploration_segments(leg_config, travel_pace)
    if segments <= 0:
        return

    hazard_dc_modifier = _TRAVEL_PACE_HAZARD_DC_MODIFIER.get(travel_pace, 0)
    attrition_resource_loss = _parse_resource_loss(leg_config.get("resource_attrition", {}))
    hazard_rows = leg_config.get("hazard_checks", [])
    hazard_checks = hazard_rows if isinstance(hazard_rows, list) else []

    for _ in range(segments):
        for actor in actors.values():
            if actor.team != "party" or actor.hp <= 0 or actor.dead:
                continue

            _apply_exploration_damage(
                rng=rng,
                actor=actor,
                damage_expr=leg_config.get("hp_attrition"),
                damage_type="environmental",
                damage_taken=damage_taken,
            )
            _spend_exploration_resources(
                actor=actor,
                resource_loss=attrition_resource_loss,
                resources_spent=resources_spent,
            )

            if actor.hp <= 0 or actor.dead:
                continue

            for hazard in hazard_checks:
                if not isinstance(hazard, dict) or actor.hp <= 0 or actor.dead:
                    continue
                ability = str(hazard.get("ability", "con")).lower()
                if ability not in ABILITY_KEYS:
                    ability = "con"
                save_mod = int(actor.save_mods.get(ability, 0))

                try:
                    dc = int(hazard.get("dc", 10))
                except (TypeError, ValueError):
                    dc = 10
                effective_dc = dc + hazard_dc_modifier
                check_total = rng.randint(1, 20) + save_mod
                if check_total >= effective_dc:
                    continue

                _apply_exploration_damage(
                    rng=rng,
                    actor=actor,
                    damage_expr=hazard.get("damage"),
                    damage_type=str(hazard.get("damage_type", "environmental")),
                    damage_taken=damage_taken,
                )
                _spend_exploration_resources(
                    actor=actor,
                    resource_loss=_parse_resource_loss(hazard.get("resource_loss", {})),
                    resources_spent=resources_spent,
                )


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
                concentrating=actor.concentrating,
            )
            for actor_id, actor in actors.items()
        },
        actor_order=actor_order,
        metadata=metadata,
    )


def _actor_defeated(actor: ActorRuntimeState) -> bool:
    return actor.dead or actor.hp <= 0


def _team_actors(actors: dict[str, ActorRuntimeState], *, team: str) -> list[ActorRuntimeState]:
    if team == "party":
        return [actor for actor in actors.values() if actor.team == "party"]
    return [actor for actor in actors.values() if actor.team != "party"]


def _compare_numeric(lhs: float, op: str, rhs: float) -> bool:
    if op in {"<", "lt"}:
        return lhs < rhs
    if op in {"<=", "le"}:
        return lhs <= rhs
    if op in {">", "gt"}:
        return lhs > rhs
    if op in {">=", "ge"}:
        return lhs >= rhs
    if op in {"==", "eq"}:
        return lhs == rhs
    if op in {"!=", "ne"}:
        return lhs != rhs
    raise ValueError(f"Unsupported predicate operator: {op}")


def _team_metric_value(team_actors: list[ActorRuntimeState], metric: str) -> float:
    key = str(metric).lower()
    if key in {"alive_count", "conscious_count"}:
        return float(sum(1 for actor in team_actors if actor.hp > 0 and not actor.dead))
    if key in {"active_count"}:
        return float(sum(1 for actor in team_actors if not actor.dead))
    if key in {"downed_count"}:
        return float(sum(1 for actor in team_actors if _actor_defeated(actor)))
    if key in {"dead_count"}:
        return float(sum(1 for actor in team_actors if actor.dead))
    if key == "total_hp":
        return float(sum(max(0, int(actor.hp)) for actor in team_actors if not actor.dead))
    if key == "max_hp":
        return float(sum(int(actor.max_hp) for actor in team_actors))
    raise ValueError(f"Unsupported predicate metric: {metric}")


def _evaluate_custom_termination_predicate(
    predicate: dict[str, Any], team_actors: list[ActorRuntimeState]
) -> bool:
    if "all" in predicate:
        clauses = predicate.get("all")
        if not isinstance(clauses, list):
            raise ValueError("Custom predicate 'all' must be a list")
        return all(
            _evaluate_custom_termination_predicate(clause, team_actors)
            for clause in clauses
            if isinstance(clause, dict)
        )
    if "any" in predicate:
        clauses = predicate.get("any")
        if not isinstance(clauses, list):
            raise ValueError("Custom predicate 'any' must be a list")
        return any(
            _evaluate_custom_termination_predicate(clause, team_actors)
            for clause in clauses
            if isinstance(clause, dict)
        )

    metric = predicate.get("metric", "alive_count")
    op = str(predicate.get("op", "<=")).lower()
    value = float(predicate.get("value", 0))
    lhs = _team_metric_value(team_actors, str(metric))
    return _compare_numeric(lhs, op, value)


def _team_defeated(
    actors: dict[str, ActorRuntimeState], *, team: str, rule_spec: Any, default_rule: str
) -> bool:
    team_members = _team_actors(actors, team=team)
    if not team_members:
        return False

    rule = rule_spec if rule_spec is not None else default_rule
    if isinstance(rule, dict):
        return _evaluate_custom_termination_predicate(rule, team_members)
    if not isinstance(rule, str):
        raise ValueError(f"Unsupported termination rule type for team '{team}': {type(rule)}")

    key = rule.strip().lower()
    if key in {"all_unconscious_or_dead", "all_downed", "all_defeated", "none_conscious"}:
        return all(_actor_defeated(actor) for actor in team_members)
    if key in {"all_dead", "none_alive"}:
        return all(actor.dead for actor in team_members)
    if key in {"any_unconscious_or_dead", "any_downed"}:
        return any(_actor_defeated(actor) for actor in team_members)
    if key in {"any_dead"}:
        return any(actor.dead for actor in team_members)
    raise ValueError(f"Unsupported termination rule for team '{team}': {rule}")


def _party_defeated(actors: dict[str, ActorRuntimeState], rule_spec: Any = None) -> bool:
    return _team_defeated(
        actors,
        team="party",
        rule_spec=rule_spec,
        default_rule="all_unconscious_or_dead",
    )


def _enemies_defeated(actors: dict[str, ActorRuntimeState], rule_spec: Any = None) -> bool:
    return _team_defeated(
        actors,
        team="enemy",
        rule_spec=rule_spec,
        default_rule="all_dead",
    )


def _resolve_next_encounter_index(
    *,
    encounter: EncounterConfig,
    encounter_outcome: str,
    encounter_winner: str,
    default_next: int,
    encounter_count: int,
) -> tuple[int | None, str | None]:
    branches = encounter.branches if isinstance(encounter.branches, dict) else {}
    branch_key: str | None = None
    next_idx: int | None = None

    for candidate_key in (encounter_outcome, encounter_winner, "default"):
        if candidate_key in branches:
            branch_key = candidate_key
            next_idx = int(branches[candidate_key])
            break

    if next_idx is None:
        next_idx = default_next

    if next_idx >= encounter_count:
        return None, branch_key
    if next_idx < 0:
        raise ValueError(f"Encounter branch index must be >= 0, got {next_idx}")
    return next_idx, branch_key


def _actor_state_snapshot(actor: ActorRuntimeState) -> dict[str, Any]:
    return {
        "name": actor.name,
        "hp": actor.hp,
        "max_hp": actor.max_hp,
        "temp_hp": actor.temp_hp,
        "dead": actor.dead,
        "downed_count": actor.downed_count,
        "conditions": sorted(actor.conditions),
        "resources": dict(sorted(actor.resources.items())),
    }


def _build_initiative_order_with_scores(
    rng: random.Random, actors: dict[str, ActorRuntimeState], mode: str
) -> tuple[list[str], dict[str, int]]:
    if mode == "grouped":
        party = [actor for actor in actors.values() if actor.team == "party"]
        enemies = [actor for actor in actors.values() if actor.team != "party"]
        party_score = statistics.mean(rng.randint(1, 20) + actor.initiative_mod for actor in party)
        enemy_score = statistics.mean(
            rng.randint(1, 20) + actor.initiative_mod for actor in enemies
        )
        party_score_int = int(party_score)
        enemy_score_int = int(enemy_score)
        party_order = [
            actor.actor_id for actor in sorted(party, key=lambda item: item.dex_mod, reverse=True)
        ]
        enemy_order = [
            actor.actor_id for actor in sorted(enemies, key=lambda item: item.dex_mod, reverse=True)
        ]
        order = (
            party_order + enemy_order if party_score >= enemy_score else enemy_order + party_order
        )
        scores = {
            **{actor.actor_id: party_score_int for actor in party},
            **{actor.actor_id: enemy_score_int for actor in enemies},
        }
        return order, scores

    rolls = []
    scores: dict[str, int] = {}
    for actor in actors.values():
        roll = rng.randint(1, 20) + actor.initiative_mod
        scores[actor.actor_id] = roll
        tiebreak = rng.randint(1, 20) + actor.dex_mod
        rolls.append((roll, tiebreak, actor.actor_id))
    rolls.sort(reverse=True)
    return [actor_id for _, _, actor_id in rolls], scores


def _build_initiative_order(
    rng: random.Random, actors: dict[str, ActorRuntimeState], mode: str
) -> list[str]:
    order, _scores = _build_initiative_order_with_scores(rng, actors, mode)
    return order


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


def _reorder_initiative_for_construct_companions(
    initiative_order: list[str], _actors: dict[str, ActorRuntimeState]
) -> list[str]:
    """Preserve initiative order when no construct-companion rules are active."""
    return initiative_order


def _split_spell_slot_cost(cost: dict[str, int]) -> tuple[dict[str, int], int, list[int]]:
    non_slot_cost: dict[str, int] = {}
    slot_cost_amount = 0
    slot_levels: list[int] = []
    for key, amount in cost.items():
        if int(amount) <= 0:
            continue
        slot_level = _spell_slot_level_from_key(str(key))
        if slot_level is None:
            non_slot_cost[str(key)] = int(amount)
            continue
        slot_cost_amount += int(amount)
        slot_levels.append(slot_level)
    return non_slot_cost, slot_cost_amount, sorted(slot_levels)


def _can_pay_exact_spell_slot(actor: ActorRuntimeState, *, slot_level: int, amount: int) -> bool:
    if slot_level <= 0:
        return False
    if amount <= 0:
        return True
    return int(actor.resources.get(f"spell_slot_{slot_level}", 0)) >= amount


def _can_pay_flexible_spell_slots(
    actor: ActorRuntimeState,
    *,
    minimum_level: int,
    amount: int,
    preferred_level: int | None = None,
) -> bool:
    if amount <= 0:
        return True
    if minimum_level <= 0:
        return True
    effective_floor = minimum_level
    if preferred_level is not None and preferred_level > effective_floor:
        effective_floor = preferred_level
    available = _available_spell_slots(actor, minimum=effective_floor)
    total_available = sum(max(0, int(actor.resources.get(key, 0))) for key, _ in available)
    return total_available >= amount


def _spend_exact_spell_slot(
    actor: ActorRuntimeState, *, slot_level: int, amount: int
) -> dict[str, int]:
    spent: dict[str, int] = {}
    if slot_level <= 0 or amount <= 0:
        return spent
    key = f"spell_slot_{slot_level}"
    current = int(actor.resources.get(key, 0))
    actual = min(amount, max(current, 0))
    actor.resources[key] = current - actual
    if actual > 0:
        spent[key] = actual
    return spent


def _spend_flexible_spell_slots(
    actor: ActorRuntimeState,
    *,
    minimum_level: int,
    amount: int,
    preferred_level: int | None = None,
) -> dict[str, int]:
    spent: dict[str, int] = {}
    if minimum_level <= 0 or amount <= 0:
        return spent

    for _ in range(amount):
        slot_key: str | None = None
        if preferred_level is not None and preferred_level >= minimum_level:
            preferred_key = f"spell_slot_{preferred_level}"
            if int(actor.resources.get(preferred_key, 0)) > 0:
                slot_key = preferred_key

        if slot_key is None:
            floor = minimum_level
            if preferred_level is not None and preferred_level > floor:
                floor = preferred_level
            available = _available_spell_slots(actor, minimum=floor)
            if not available:
                break
            slot_key = available[0][0]

        actor.resources[slot_key] = int(actor.resources.get(slot_key, 0)) - 1
        spent[slot_key] = spent.get(slot_key, 0) + 1

    return spent


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
    *,
    spell_cast_request: SpellCastRequest | None = None,
) -> bool:
    if not _can_pay_resource_cost(actor, action, spell_cast_request=spell_cast_request):
        return False

    if "spell" not in action.tags:
        spent = _spend_resources(actor, action.resource_cost)
    else:
        non_slot_cost, slot_amount, _slot_levels = _split_spell_slot_cost(action.resource_cost)
        spent = _spend_resources(actor, non_slot_cost)
        required_slot_level = _required_spell_slot_level(action)
        preferred_slot = _preferred_spell_slot_level(action)
        explicit_slot = spell_cast_request.slot_level if spell_cast_request is not None else None
        spent_slot_levels: set[int] = set()
        if slot_amount > 0 and required_slot_level > 0:
            if explicit_slot is not None:
                spent_slots = _spend_exact_spell_slot(
                    actor,
                    slot_level=int(explicit_slot),
                    amount=slot_amount,
                )
            else:
                spent_slots = _spend_flexible_spell_slots(
                    actor,
                    minimum_level=required_slot_level,
                    amount=slot_amount,
                    preferred_level=preferred_slot,
                )
            for key, amount in spent_slots.items():
                spent[key] = spent.get(key, 0) + amount
                slot_level = _spell_slot_level_from_key(str(key))
                if slot_level is not None:
                    spent_slot_levels.add(slot_level)
            if (
                spell_cast_request is not None
                and spell_cast_request.slot_level is None
                and len(spent_slot_levels) == 1
            ):
                spell_cast_request.slot_level = next(iter(spent_slot_levels))

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
    has_ranged_property = _action_has_weapon_property(
        action, "ammunition"
    ) or _action_has_weapon_property(action, "ranged")
    has_reach_property = _action_has_weapon_property(action, "reach")
    if action.range_normal_ft is not None and action.range_normal_ft > 5:
        return not has_reach_property
    if action.range_long_ft is not None and action.range_long_ft > 5:
        return not has_reach_property
    if has_ranged_property:
        return True
    if _action_has_weapon_property(action, "thrown"):
        if action.range_normal_ft is not None:
            return action.range_normal_ft > 5
        if action.range_ft is not None:
            return action.range_ft > 5
        return True
    if action.reach_ft is not None or has_reach_property:
        return False
    if _has_action_tag(action, "ranged") or _has_action_tag(action, "ranged_attack"):
        return True
    name = action.name.lower()
    return any(keyword in name for keyword in _RANGED_ATTACK_KEYWORDS)


def _action_range_ft(action: ActionDefinition) -> float | None:
    if action.target_mode == "self":
        return None
    if action.range_ft is not None:
        return float(action.range_ft)
    if action.range_normal_ft is not None:
        return float(action.range_normal_ft)
    if action.reach_ft is not None:
        return float(action.reach_ft)
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


def _is_ranged_attack_action(action: ActionDefinition) -> bool:
    if action.action_type != "attack":
        return False
    if _is_ranged_weapon_action(action):
        return True
    if _has_action_tag(action, "ranged") or _has_action_tag(action, "ranged_attack"):
        return True
    has_reach_property = _action_has_weapon_property(action, "reach")
    if action.reach_ft is not None or has_reach_property:
        return False
    inferred_range = _action_range_ft(action)
    return bool(inferred_range is not None and inferred_range > 5.0)


def _action_max_range_ft(action: ActionDefinition) -> float | None:
    normal_range = _action_range_ft(action)
    if normal_range is None:
        return None
    if not _is_ranged_attack_action(action):
        return normal_range
    if action.range_long_ft is None:
        return normal_range
    return max(normal_range, float(action.range_long_ft))


def _action_has_explicit_range_bounds(action: ActionDefinition) -> bool:
    return any(
        value is not None
        for value in (action.reach_ft, action.range_ft, action.range_normal_ft, action.range_long_ft)
    )


def _attack_range_state(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    target: ActorRuntimeState,
) -> tuple[bool, bool]:
    normal_range = _action_range_ft(action)
    if normal_range is None:
        return True, False
    max_range = _action_max_range_ft(action)
    if max_range is None:
        return True, False

    distance = distance_chebyshev(actor.position, target.position)
    if distance > (max_range + 1e-9):
        return False, False

    long_range_disadvantage = (
        _is_ranged_attack_action(action)
        and action.range_long_ft is not None
        and max_range > (normal_range + 1e-9)
        and distance > (normal_range + 1e-9)
    )
    return True, long_range_disadvantage


def _ranged_attack_ignores_adjacent_hostile_disadvantage(
    actor: ActorRuntimeState,
    action: ActionDefinition,
) -> bool:
    if _has_any_trait(actor, list(_RANGED_IN_MELEE_DISADVANTAGE_OVERRIDE_TRAITS)):
        return True
    return any(
        _has_action_tag(action, tag) for tag in _RANGED_IN_MELEE_DISADVANTAGE_OVERRIDE_TAGS
    )


def _has_hostile_within_melee_range(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
) -> bool:
    for candidate in actors.values():
        if candidate.actor_id == actor.actor_id:
            continue
        if candidate.team == actor.team:
            continue
        if candidate.dead or candidate.hp <= 0:
            continue
        if actor_is_incapacitated(candidate):
            continue
        if distance_chebyshev(actor.position, candidate.position) <= (5.0 + 1e-9):
            return True
    return False


def _requires_range_resolution(action: ActionDefinition) -> bool:
    if action.target_mode == "self":
        return False
    if action.action_type == "utility" and action.name in {"dodge", "dash", "disengage", "ready"}:
        return False
    return _action_range_ft(action) is not None


def _difficult_terrain_positions_from_hazards(
    active_hazards: list[dict[str, Any]],
) -> list[tuple[float, float, float]]:
    difficult_positions: set[tuple[float, float, float]] = set()
    for hazard in active_hazards:
        if not isinstance(hazard, dict):
            continue
        hazard_type = str(hazard.get("type") or hazard.get("hazard_type") or "").strip().lower()
        normalized_type = hazard_type.replace("-", "_").replace(" ", "_")
        if normalized_type != "difficult_terrain":
            continue

        explicit_positions = (
            hazard.get("difficult_positions") or hazard.get("positions") or hazard.get("cells")
        )
        if isinstance(explicit_positions, list):
            for row in explicit_positions:
                pos = _to_position3(row)
                if pos is not None:
                    difficult_positions.add(pos)

        center = _to_position3(hazard.get("position"))
        if center is None:
            continue
        raw_radius = hazard.get("radius", hazard.get("radius_ft", 0))
        try:
            radius_ft = float(raw_radius)
        except (TypeError, ValueError):
            radius_ft = 0.0
        if radius_ft <= 0:
            difficult_positions.add(center)
            continue

        center_cell = (
            int(round(center[0] / 5.0)),
            int(round(center[1] / 5.0)),
            int(round(center[2] / 5.0)),
        )
        radius_cells = int(math.ceil(radius_ft / 5.0))
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                for dz in range(-radius_cells, radius_cells + 1):
                    candidate = (
                        (center_cell[0] + dx) * 5.0,
                        (center_cell[1] + dy) * 5.0,
                        (center_cell[2] + dz) * 5.0,
                    )
                    if distance_chebyshev(center, candidate) <= radius_ft + 1e-9:
                        difficult_positions.add(candidate)

    return sorted(difficult_positions)


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


def _opportunity_attack_reach_ft(action: ActionDefinition) -> float | None:
    if action.action_type != "attack":
        return None
    if _is_ranged_weapon_action(action):
        return None
    if action.reach_ft is not None:
        return max(0.0, float(action.reach_ft))
    if _action_has_weapon_property(action, "reach"):
        if action.range_ft is not None and action.range_ft > 0:
            return float(action.range_ft)
        if action.range_normal_ft is not None and action.range_normal_ft > 0:
            return float(action.range_normal_ft)
        return 10.0
    inferred_range = _action_range_ft(action)
    if inferred_range is None:
        return 5.0
    return min(5.0, max(0.0, float(inferred_range)))


def _opportunity_attack_candidates(
    actor: ActorRuntimeState,
) -> list[tuple[ActionDefinition, float]]:
    candidates: list[tuple[ActionDefinition, float]] = []
    for action in actor.actions:
        if action.action_type != "attack":
            continue
        if action.action_cost in {"legendary", "lair"}:
            continue
        if not _can_pay_resource_cost(actor, action):
            continue
        reach_ft = _opportunity_attack_reach_ft(action)
        if reach_ft is None or reach_ft <= 0:
            continue
        candidates.append((action, reach_ft))
    return candidates


def _find_opportunity_attack_action(
    actor: ActorRuntimeState,
    *,
    required_reach_ft: float = 0.0,
) -> tuple[ActionDefinition, float] | None:
    best: tuple[ActionDefinition, float] | None = None
    for action, reach_ft in _opportunity_attack_candidates(actor):
        if reach_ft + 1e-9 < required_reach_ft:
            continue
        if best is None:
            best = (action, reach_ft)
            continue
        best_action, best_reach = best
        current_to_hit = action.to_hit if action.to_hit is not None else -999
        best_to_hit = best_action.to_hit if best_action.to_hit is not None else -999
        if (current_to_hit, reach_ft) > (best_to_hit, best_reach):
            best = (action, reach_ft)
    if best is None:
        return None
    best_action, best_reach = best
    return replace(best_action, attack_count=1, action_cost="reaction"), best_reach


def _readied_reach_entry_point(
    *,
    responder: ActorRuntimeState,
    path_points: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    if "readying" not in responder.conditions:
        return None
    if not responder.readied_reaction_reserved:
        return None
    if not _readied_trigger_matches(responder.readied_trigger, trigger_event="enemy_enters_reach"):
        return None
    readied = _resolve_named_action(responder, responder.readied_action_name)
    if readied is None or readied.name == "ready":
        return None

    reaction_action = replace(readied, action_cost="reaction")
    if responder.readied_spell_held and "spell" in reaction_action.tags:
        reaction_action = replace(reaction_action, resource_cost={})
    trigger_range = _action_range_ft(reaction_action)
    if trigger_range is None or trigger_range <= 0:
        return None

    previous = path_points[0]
    was_in_range = distance_chebyshev(responder.position, previous) <= trigger_range
    for point in path_points[1:]:
        is_in_range = distance_chebyshev(responder.position, point) <= trigger_range
        if not was_in_range and is_in_range:
            return point
        was_in_range = is_in_range
    return None


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
    round_number: int | None = None,
    turn_token: str | None = None,
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
        readied_reach_entry = _readied_reach_entry_point(
            responder=enemy,
            path_points=path_points,
        )
        if readied_reach_entry is not None:
            original_position = mover.position
            mover.position = readied_reach_entry
            _trigger_readied_actions(
                rng=rng,
                trigger_actor=mover,
                trigger_event="enemy_enters_reach",
                eligible_reactors={enemy.actor_id},
                round_number=round_number,
                turn_token=turn_token,
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

        if not enemy.reaction_available:
            continue
        opportunity_candidates = _opportunity_attack_candidates(enemy)
        if not opportunity_candidates:
            continue
        max_reach = max(reach_ft for _, reach_ft in opportunity_candidates)
        trigger_point: tuple[float, float, float] | None = None
        trigger_distance: float | None = None
        previous = path_points[0]
        was_in_reach = distance_chebyshev(enemy.position, previous) <= max_reach
        for point in path_points[1:]:
            is_in_reach = distance_chebyshev(enemy.position, point) <= max_reach
            if was_in_reach and not is_in_reach:
                trigger_point = previous
                trigger_distance = distance_chebyshev(enemy.position, previous)
                break
            was_in_reach = is_in_reach
            previous = point
        if trigger_point is None:
            continue
        reaction_result = _find_opportunity_attack_action(
            enemy,
            required_reach_ft=float(trigger_distance or 0.0),
        )
        if reaction_result is None:
            continue
        reaction_attack, _ = reaction_result
        spell_cast_request = SpellCastRequest() if "spell" in reaction_attack.tags else None
        if not _spend_action_resource_cost(
            enemy,
            reaction_attack,
            resources_spent,
            spell_cast_request=spell_cast_request,
        ):
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
            round_number=round_number,
            turn_token=turn_token,
            spell_cast_request=spell_cast_request,
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
    round_number: int | None = None,
    turn_token: str | None = None,
) -> bool:
    if not targets:
        return False
    action_range = _action_max_range_ft(action)
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
    difficult_terrain_positions = _difficult_terrain_positions_from_hazards(active_hazards)
    path = find_path(
        actor.position,
        primary.position,
        obstacles,
        occupied_positions=occupied_positions,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    if not path or distance_chebyshev(path[-1], primary.position) > 1e-6:
        return False

    if len(path) < 2:
        return distance_chebyshev(actor.position, primary.position) <= action_range

    approach_path: list[tuple[float, float, float]] = [path[0]]
    for waypoint in path[1:]:
        approach_path.append(waypoint)
        if distance_chebyshev(waypoint, primary.position) <= action_range + 1e-9:
            break

    required_move = path_movement_cost(
        approach_path,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    move_budget = min(available_distance, required_move)
    if move_budget <= 0:
        return distance_chebyshev(actor.position, primary.position) <= action_range

    start_pos = actor.position
    movement_path = path_prefix_for_movement(
        path,
        move_budget,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    if not movement_path:
        movement_path = [start_pos]
    end_pos = movement_path[-1]
    moved = distance_chebyshev(start_pos, end_pos)
    movement_spent = path_movement_cost(
        movement_path,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    if moved <= 0 or movement_spent <= 0:
        return distance_chebyshev(actor.position, primary.position) <= action_range

    actor.position = end_pos
    actor.movement_remaining = max(
        0.0,
        actor.movement_remaining - (movement_spent * (2.0 if crawling else 1.0)),
    )

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
        round_number=round_number,
        turn_token=turn_token,
    )

    if actor.dead or actor.hp <= 0:
        return False
    _process_hazard_movement_triggers(
        rng=rng,
        mover=actor,
        start_pos=start_pos,
        end_pos=actor.position,
        movement_path=movement_path,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    if actor.dead or actor.hp <= 0:
        return False
    return distance_chebyshev(actor.position, primary.position) <= action_range


def _filter_targets_in_range(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
) -> list[ActorRuntimeState]:
    action_range = _action_max_range_ft(action)
    if action_range is None:
        return targets
    if not targets:
        return []
    if action.aoe_type:
        primary = targets[0]
        if distance_chebyshev(actor.position, primary.position) > action_range:
            return []
        if action.aoe_size_ft:
            radius = _coerce_positive_distance(action.aoe_size_ft)
            if radius is None:
                return targets
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


def _coerce_positive_distance(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed


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
    size = _coerce_positive_distance(action.aoe_size_ft)
    if size is None:
        return primaries
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


def _cover_bonus_from_state(cover_state: str) -> int:
    if cover_state == "HALF":
        return 2
    if cover_state == "THREE_QUARTERS":
        return 5
    return 0


def _action_ignores_dex_save_cover(action: ActionDefinition) -> bool:
    return _has_tag(action, "ignore_dex_save_cover")


def _action_requires_line_of_effect(action: ActionDefinition) -> bool:
    if action.target_mode == "self":
        return False
    if _has_tag(action, "ignore_line_of_effect") or _has_tag(action, "ignore_total_cover"):
        return False
    if action.action_type in {"attack", "save", "grapple", "shove"}:
        return True
    for effect in [*action.effects, *action.mechanics]:
        if not isinstance(effect, dict):
            continue
        if str(effect.get("effect_type", "")).lower() in {
            "damage",
            "apply_condition",
            "forced_movement",
        }:
            return True
    return False


def _filter_targets_by_line_of_effect(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    obstacles: list[AABB] | None = None,
) -> list[ActorRuntimeState]:
    if not targets or not obstacles or not _action_requires_line_of_effect(action):
        return targets
    from .spatial import check_cover

    return [
        target
        for target in targets
        if check_cover(actor.position, target.position, obstacles) != "TOTAL"
    ]


def _resolve_targets_for_action(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    actors: dict[str, ActorRuntimeState],
    requested: list[TargetRef],
    obstacles: list[AABB] | None = None,
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
        radius = _coerce_positive_distance(action.aoe_size_ft)
        if radius is None:
            return selected
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
        resolved_targets = sorted(
            [actors[aid] for aid in aoe_victims],
            key=lambda value: _target_sort_key(actor, value, mode=mode),
        )
    else:
        resolved_targets = _resolve_template_targets(
            actor=actor,
            action=action,
            mode=mode,
            primaries=selected,
            candidates=ordered_candidates,
        )
    return _filter_targets_by_line_of_effect(
        actor=actor,
        action=action,
        targets=resolved_targets,
        obstacles=obstacles,
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


def _resolve_named_action(
    actor: ActorRuntimeState, action_name: str | None
) -> ActionDefinition | None:
    if action_name is None:
        return None
    for action in actor.actions:
        if action.name == action_name:
            return action
    return None


def _raise_turn_declaration_error(
    *,
    actor: ActorRuntimeState,
    code: str,
    field: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    raise TurnDeclarationValidationError(
        actor_id=actor.actor_id,
        code=code,
        field=field,
        message=message,
        details=details,
    )


def _declared_action_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
    expected_cost: str,
) -> ActionDefinition:
    action_name = str(declaration.action_name or "").strip()
    if not action_name:
        _raise_turn_declaration_error(
            actor=actor,
            code="missing_action_name",
            field=f"{field_prefix}.action_name",
            message="Declared action is missing action_name.",
        )

    selected = next((entry for entry in actor.actions if entry.name == action_name), None)
    if selected is None:
        _raise_turn_declaration_error(
            actor=actor,
            code="unknown_action",
            field=f"{field_prefix}.action_name",
            message=f"Declared action '{action_name}' does not exist for actor.",
        )

    if expected_cost == "bonus" and selected.action_cost != "bonus":
        _raise_turn_declaration_error(
            actor=actor,
            code="illegal_bonus_action",
            field=f"{field_prefix}.action_name",
            message=f"Action '{selected.name}' is not a bonus action.",
            details={"action_cost": selected.action_cost},
        )
    if expected_cost == "action" and selected.action_cost not in {"action", "none"}:
        _raise_turn_declaration_error(
            actor=actor,
            code="illegal_action",
            field=f"{field_prefix}.action_name",
            message=f"Action '{selected.name}' cannot be used in the main action step.",
            details={"action_cost": selected.action_cost},
        )
    return selected


def _declared_targets_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> list[TargetRef]:
    raw_targets = declaration.targets
    if not isinstance(raw_targets, list):
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_targets",
            field=f"{field_prefix}.targets",
            message="Declared targets must be a list.",
        )

    out: list[TargetRef] = []
    for idx, target in enumerate(raw_targets):
        if not isinstance(target, TargetRef):
            _raise_turn_declaration_error(
                actor=actor,
                code="invalid_target_ref",
                field=f"{field_prefix}.targets[{idx}]",
                message="Declared targets must contain TargetRef entries.",
            )
        out.append(target)
    return out


def _declared_extra_resource_cost_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> dict[str, int]:
    raw = getattr(declaration.resource_spend, "amounts", {})
    if not isinstance(raw, dict):
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_resource_spend",
            field=f"{field_prefix}.resource_spend",
            message="Declared resource_spend must be a mapping of resource -> amount.",
        )
    out: dict[str, int] = {}
    for key, amount in raw.items():
        try:
            parsed = int(amount)
        except (TypeError, ValueError):
            _raise_turn_declaration_error(
                actor=actor,
                code="invalid_resource_amount",
                field=f"{field_prefix}.resource_spend.{key}",
                message="Declared resource spend amount must be an integer.",
            )
        if parsed <= 0:
            continue
        out[str(key)] = parsed
    return out


def _declared_spell_request_or_error(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> SpellCastRequest | None:
    raw_slot_level = declaration.spell_slot_level
    if "spell" not in action.tags:
        if raw_slot_level is not None:
            _raise_turn_declaration_error(
                actor=actor,
                code="illegal_spell_slot_override",
                field=f"{field_prefix}.spell_slot_level",
                message="spell_slot_level can only be declared for spell actions.",
            )
        return None

    request = SpellCastRequest()
    if raw_slot_level is None:
        return request

    try:
        slot_level = int(raw_slot_level)
    except (TypeError, ValueError):
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_spell_slot_level",
            field=f"{field_prefix}.spell_slot_level",
            message="Declared spell_slot_level must be an integer.",
        )
    if slot_level <= 0:
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_spell_slot_level",
            field=f"{field_prefix}.spell_slot_level",
            message="Declared spell_slot_level must be >= 1.",
        )
    request.slot_level = slot_level
    return request


def _declared_movement_path_or_error(
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
) -> list[tuple[float, float, float]]:
    if not isinstance(declaration.movement_path, list):
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_movement_path",
            field="movement_path",
            message="movement_path must be a list of 3D waypoints.",
        )
    if not declaration.movement_path:
        return []

    normalized: list[tuple[float, float, float]] = []
    for idx, waypoint in enumerate(declaration.movement_path):
        if not isinstance(waypoint, (tuple, list)) or len(waypoint) != 3:
            _raise_turn_declaration_error(
                actor=actor,
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint must be a 3-value coordinate.",
            )
        try:
            normalized.append((float(waypoint[0]), float(waypoint[1]), float(waypoint[2])))
        except (TypeError, ValueError):
            _raise_turn_declaration_error(
                actor=actor,
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint value must be numeric.",
            )

    if distance_chebyshev(actor.position, normalized[0]) > 1e-6:
        _raise_turn_declaration_error(
            actor=actor,
            code="movement_path_start_mismatch",
            field="movement_path[0]",
            message="movement_path must start at the actor's current position.",
            details={"current_position": actor.position},
        )
    return normalized


def _apply_declared_movement_or_error(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    movement_path: list[tuple[float, float, float]],
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
) -> None:
    if not movement_path:
        return

    declared_distance = _path_distance(movement_path)
    if declared_distance <= 0:
        return

    available_distance, crawling = _prepare_voluntary_movement(actor)
    if available_distance <= 0:
        _raise_turn_declaration_error(
            actor=actor,
            code="movement_blocked",
            field="movement_path",
            message="Actor cannot move due to current movement restrictions.",
        )
    if declared_distance > (available_distance + 1e-6):
        _raise_turn_declaration_error(
            actor=actor,
            code="movement_exceeds_budget",
            field="movement_path",
            message="Declared movement exceeds remaining movement budget.",
            details={
                "declared_distance": declared_distance,
                "movement_remaining": available_distance,
            },
        )

    start_pos = actor.position
    end_pos = movement_path[-1]
    actor.position = end_pos
    actor.movement_remaining = max(
        0.0, actor.movement_remaining - (declared_distance * (2.0 if crawling else 1.0))
    )

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
        round_number=round_number,
        turn_token=turn_token,
    )
    if actor.dead or actor.hp <= 0:
        return
    _process_hazard_movement_triggers(
        rng=rng,
        mover=actor,
        start_pos=start_pos,
        end_pos=actor.position,
        movement_path=movement_path,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )


def _validate_declared_ready_or_error(
    actor: ActorRuntimeState, declaration: TurnDeclaration
) -> ReadyDeclaration | None:
    ready = declaration.ready
    if ready is None:
        return None
    if not isinstance(ready, ReadyDeclaration):
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_ready_declaration",
            field="ready",
            message="ready must be a ReadyDeclaration object.",
        )

    action_name = declaration.action.action_name if declaration.action is not None else None
    if str(action_name or "").strip().lower() != "ready":
        _raise_turn_declaration_error(
            actor=actor,
            code="ready_metadata_without_ready_action",
            field="ready",
            message="ready metadata is only legal when action.action_name is 'ready'.",
        )

    trigger = str(ready.trigger or "").strip()
    if not trigger:
        _raise_turn_declaration_error(
            actor=actor,
            code="missing_ready_trigger",
            field="ready.trigger",
            message="Ready declaration trigger is required.",
        )
    response_name = str(ready.response_action_name or "").strip()
    if not response_name:
        _raise_turn_declaration_error(
            actor=actor,
            code="missing_ready_response",
            field="ready.response_action_name",
            message="Ready declaration response_action_name is required.",
        )

    response_action = next((a for a in actor.actions if a.name == response_name), None)
    if response_action is None:
        _raise_turn_declaration_error(
            actor=actor,
            code="unknown_ready_response",
            field="ready.response_action_name",
            message=f"Ready response action '{response_name}' does not exist for actor.",
        )
    if response_action.name == "ready" or response_action.action_cost not in {"action", "none"}:
        _raise_turn_declaration_error(
            actor=actor,
            code="illegal_ready_response",
            field="ready.response_action_name",
            message="Ready response must be a non-ready action that uses action or no cost.",
            details={"action_cost": response_action.action_cost},
        )
    return ready


def _apply_declared_reaction_policy_or_error(
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
) -> str:
    policy = declaration.reaction_policy
    mode = "auto"
    if policy is not None:
        mode = str(policy.mode or "auto").strip().lower()
    if mode not in _SUPPORTED_REACTION_POLICY_MODES:
        _raise_turn_declaration_error(
            actor=actor,
            code="invalid_reaction_policy",
            field="reaction_policy.mode",
            message=f"Unsupported reaction policy mode: {mode}",
            details={"supported_modes": sorted(_SUPPORTED_REACTION_POLICY_MODES)},
        )
    if mode == "none":
        actor.reaction_available = False
    return mode


def _execute_declared_action_step_or_error(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    field_prefix: str,
    expected_cost: str,
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
    telemetry: list[dict[str, Any]] | None = None,
    strategy_name: str | None = None,
    ready_declaration: ReadyDeclaration | None = None,
) -> tuple[ActionDefinition, list[ActorRuntimeState]]:
    action = _declared_action_or_error(
        actor,
        declaration,
        field_prefix=field_prefix,
        expected_cost=expected_cost,
    )
    requested_targets = _declared_targets_or_error(actor, declaration, field_prefix=field_prefix)
    spell_cast_request = _declared_spell_request_or_error(
        actor,
        action,
        declaration,
        field_prefix=field_prefix,
    )

    if _mode_requires_explicit_targets(action.target_mode) and not requested_targets:
        _raise_turn_declaration_error(
            actor=actor,
            code="missing_targets",
            field=f"{field_prefix}.targets",
            message=f"Declared action '{action.name}' requires explicit targets.",
        )

    if not _action_available(
        actor,
        action,
        spell_cast_request=spell_cast_request,
        turn_token=turn_token,
    ):
        _raise_turn_declaration_error(
            actor=actor,
            code="unavailable_action",
            field=f"{field_prefix}.action_name",
            message=f"Declared action '{action.name}' is not currently legal.",
        )

    resolved_targets = _resolve_targets_for_action(
        rng=rng,
        actor=actor,
        action=action,
        actors=actors,
        requested=requested_targets,
        obstacles=obstacles,
    )
    if requested_targets:
        requested_ids = {target.actor_id for target in requested_targets}
        resolved_targets = [
            target for target in resolved_targets if target.actor_id in requested_ids
        ]
    resolved_targets = _filter_targets_in_range(actor, action, resolved_targets)
    if not resolved_targets:
        _raise_turn_declaration_error(
            actor=actor,
            code="no_legal_targets",
            field=f"{field_prefix}.targets",
            message=f"Declared action '{action.name}' has no legal in-range targets.",
        )

    extra_cost = _declared_extra_resource_cost_or_error(
        actor, declaration, field_prefix=field_prefix
    )
    non_slot_base_cost, _slot_amount, _slot_levels = _split_spell_slot_cost(action.resource_cost)
    for key, amount in extra_cost.items():
        required = amount + int(non_slot_base_cost.get(key, 0))
        if int(actor.resources.get(key, 0)) < required:
            _raise_turn_declaration_error(
                actor=actor,
                code="insufficient_resources",
                field=f"{field_prefix}.resource_spend.{key}",
                message=f"Declared resource spend exceeds available '{key}'.",
                details={"required": required, "available": int(actor.resources.get(key, 0))},
            )

    if not _spend_action_resource_cost(
        actor,
        action,
        resources_spent,
        spell_cast_request=spell_cast_request,
    ):
        _raise_turn_declaration_error(
            actor=actor,
            code="insufficient_resources",
            field=f"{field_prefix}.action_name",
            message=f"Unable to pay resource cost for declared action '{action.name}'.",
        )
    if extra_cost:
        spent_extra = _spend_resources(actor, extra_cost)
        for key, amount in spent_extra.items():
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
        targets=resolved_targets,
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
        telemetry=telemetry,
        strategy_name=strategy_name,
        spell_cast_request=spell_cast_request,
        allow_auto_movement=False,
        ready_declaration=ready_declaration,
    )
    return action, resolved_targets


def _execute_declared_turn_or_error(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
    strategy_name: str,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    telemetry: list[dict[str, Any]] | None = None,
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
    round_number: int | None = None,
    turn_token: str | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
) -> None:
    movement_path = _declared_movement_path_or_error(actor, declaration)
    _apply_declared_movement_or_error(
        rng=rng,
        actor=actor,
        movement_path=movement_path,
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
    )
    if actor.dead or actor.hp <= 0:
        return

    reaction_mode = _apply_declared_reaction_policy_or_error(actor, declaration)
    ready_declaration = _validate_declared_ready_or_error(actor, declaration)
    if ready_declaration is not None and reaction_mode == "none":
        _raise_turn_declaration_error(
            actor=actor,
            code="conflicting_reaction_policy",
            field="reaction_policy.mode",
            message="reaction_policy.mode='none' conflicts with declaring a ready response.",
        )

    if telemetry is not None:
        telemetry.append(
            {
                "telemetry_type": "decision",
                "decision_mode": "turn_declaration",
                "round": round_number,
                "strategy": strategy_name,
                "actor_id": actor.actor_id,
                "team": actor.team,
                "movement_path": [list(waypoint) for waypoint in movement_path],
                "action_plan": (
                    declaration.action.action_name if declaration.action is not None else None
                ),
                "bonus_action_plan": (
                    declaration.bonus_action.action_name
                    if declaration.bonus_action is not None
                    else None
                ),
                "reaction_policy": reaction_mode,
                "ready_trigger": ready_declaration.trigger if ready_declaration else None,
                "ready_response": (
                    ready_declaration.response_action_name if ready_declaration else None
                ),
                "rationale": (
                    dict(declaration.rationale) if isinstance(declaration.rationale, dict) else {}
                ),
            }
        )

    executed_primary: tuple[ActionDefinition, list[ActorRuntimeState]] | None = None
    if declaration.action is not None:
        executed_primary = _execute_declared_action_step_or_error(
            rng=rng,
            actor=actor,
            declaration=declaration.action,
            field_prefix="action",
            expected_cost="action",
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
            telemetry=telemetry,
            strategy_name=strategy_name,
            ready_declaration=ready_declaration,
        )
        if round_number is not None and turn_token is not None:
            primary_action, primary_targets = executed_primary
            _dispatch_combat_event(
                rng=rng,
                event="after_action",
                trigger_actor=actor,
                trigger_target=primary_targets[0] if primary_targets else None,
                trigger_action=primary_action,
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
    if declaration.bonus_action is not None and actor.hp > 0 and not actor.dead and _can_act(actor):
        bonus_action, bonus_targets = _execute_declared_action_step_or_error(
            rng=rng,
            actor=actor,
            declaration=declaration.bonus_action,
            field_prefix="bonus_action",
            expected_cost="bonus",
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
            telemetry=telemetry,
            strategy_name=strategy_name,
        )
        if round_number is not None and turn_token is not None:
            _dispatch_combat_event(
                rng=rng,
                event="after_action",
                trigger_actor=actor,
                trigger_target=bonus_targets[0] if bonus_targets else None,
                trigger_action=bonus_action,
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

    _ = executed_primary


def _disadvantaged(actor: ActorRuntimeState) -> bool:
    return any(has_condition(actor, condition) for condition in _DISADVANTAGE_CONDITIONS)


def _can_act(actor: ActorRuntimeState) -> bool:
    return actor.hp > 0 and not actor.dead and not actor_is_incapacitated(actor)


def _normalize_condition(condition: str) -> str:
    return str(condition).strip().lower()


def _normalize_duration_boundary(value: Any) -> str:
    key = str(value or "turn_start").strip().lower()
    if key in {"end", "turn_end", "end_of_turn", "at_end"}:
        return "turn_end"
    return "turn_start"


def _normalize_stack_policy(value: Any) -> str:
    key = str(value or "independent").strip().lower()
    if key in {"replace", "overwrite", "exclusive"}:
        return "replace"
    if key in {"refresh", "refresh_by_source", "by_source"}:
        return "refresh"
    return "independent"


def _normalize_internal_tags(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value]
    else:
        return set()
    return {str(item).strip().lower() for item in candidates if str(item).strip()}


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_hazard_trigger(value: Any) -> str | None:
    key = str(value or "").strip().lower().replace("-", "_")
    if key in {"start_turn", "turn_start", "on_start_turn", "start_of_turn"}:
        return "start_turn"
    if key in {"enter", "on_enter", "enter_zone", "creature_enters"}:
        return "enter"
    if key in {"leave", "on_leave", "leave_zone", "exit", "on_exit"}:
        return "leave"
    return None


def _coerce_hazard_effects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if not isinstance(value, list):
        return []
    return [dict(entry) for entry in value if isinstance(entry, dict)]


def _extract_hazard_trigger_effects(effect: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    trigger_effects: dict[str, list[dict[str, Any]]] = {}

    direct_key_map = {
        "start_turn": ("start_turn_effects", "start_turn_effect", "on_start_turn"),
        "enter": ("enter_effects", "enter_effect", "on_enter"),
        "leave": ("leave_effects", "leave_effect", "on_leave"),
    }
    for trigger_name, aliases in direct_key_map.items():
        rows: list[dict[str, Any]] = []
        for alias in aliases:
            rows.extend(_coerce_hazard_effects(effect.get(alias)))
        if rows:
            trigger_effects[trigger_name] = rows

    for container_key in ("trigger_effects", "triggers", "hazard_triggers"):
        payload = effect.get(container_key)
        if isinstance(payload, dict):
            for raw_trigger, raw_effects in payload.items():
                trigger_name = _normalize_hazard_trigger(raw_trigger)
                if trigger_name is None:
                    continue
                trigger_effects.setdefault(trigger_name, []).extend(
                    _coerce_hazard_effects(raw_effects)
                )
            continue
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            trigger_name = _normalize_hazard_trigger(row.get("trigger") or row.get("event"))
            if trigger_name is None:
                continue
            row_effects = _coerce_hazard_effects(row.get("effects", row.get("effect")))
            if row_effects:
                trigger_effects.setdefault(trigger_name, []).extend(row_effects)

    return {trigger_name: rows for trigger_name, rows in trigger_effects.items() if rows}


def _hazard_contains_position(
    hazard: dict[str, Any],
    position: tuple[float, float, float],
) -> bool:
    hazard_position = _to_position3(hazard.get("position")) or (0.0, 0.0, 0.0)
    try:
        radius = float(hazard.get("radius", hazard.get("radius_ft", 0.0)))
    except (TypeError, ValueError):
        radius = 0.0
    return distance_chebyshev(position, hazard_position) <= max(0.0, radius)


def _hazard_trigger_effects(
    hazard: dict[str, Any],
    trigger: str,
) -> list[dict[str, Any]]:
    trigger_name = _normalize_hazard_trigger(trigger)
    if trigger_name is None:
        return []
    payload = hazard.get("trigger_effects")
    if not isinstance(payload, dict):
        return []
    return [dict(row) for row in payload.get(trigger_name, []) if isinstance(row, dict)]


def _resolve_hazard_source_actor(
    hazard: dict[str, Any],
    *,
    actors: dict[str, ActorRuntimeState],
    fallback: ActorRuntimeState,
) -> ActorRuntimeState:
    source_id = str(hazard.get("source_id", "")).strip()
    if source_id and source_id in actors:
        return actors[source_id]
    return fallback


def _apply_hazard_trigger_effects(
    *,
    rng: random.Random,
    hazard: dict[str, Any],
    trigger: str,
    subject: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
) -> None:
    trigger_name = _normalize_hazard_trigger(trigger)
    if trigger_name is None:
        return
    effects = _hazard_trigger_effects(hazard, trigger_name)
    if not effects:
        return

    source_actor = _resolve_hazard_source_actor(hazard, actors=actors, fallback=subject)
    damage_dealt.setdefault(source_actor.actor_id, 0)
    damage_taken.setdefault(subject.actor_id, 0)
    threat_scores.setdefault(source_actor.actor_id, 0)
    resources_spent.setdefault(source_actor.actor_id, {})
    resources_spent.setdefault(subject.actor_id, {})
    for trigger_effect in effects:
        _apply_effect(
            effect=trigger_effect,
            rng=rng,
            actor=source_actor,
            target=subject,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            actors=actors,
            active_hazards=active_hazards,
            trigger_event=f"hazard_{trigger_name}",
            source_bucket="hazard_trigger",
        )
        if subject.dead or subject.hp <= 0:
            return


def _tick_hazards_for_actor_turn(
    *,
    active_hazards: list[dict[str, Any]],
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    boundary: str = "turn_start",
) -> None:
    if not active_hazards:
        return
    tick_boundary = _normalize_duration_boundary(boundary)
    kept: list[dict[str, Any]] = []
    changed = False
    for hazard in active_hazards:
        source_id = str(hazard.get("source_id", "")).strip()
        if source_id and source_id not in actors:
            changed = True
            continue

        duration_remaining = _coerce_positive_int(
            hazard.get("duration_remaining", hazard.get("duration"))
        )
        if duration_remaining is None or not source_id:
            kept.append(hazard)
            continue

        hazard["duration_remaining"] = duration_remaining
        if source_id != actor.actor_id:
            kept.append(hazard)
            continue

        hazard_boundary = _normalize_duration_boundary(hazard.get("duration_boundary"))
        if hazard_boundary != tick_boundary:
            kept.append(hazard)
            continue

        next_duration = duration_remaining - 1
        changed = True
        if next_duration <= 0:
            continue
        hazard["duration_remaining"] = next_duration
        kept.append(hazard)

    if changed:
        active_hazards[:] = kept


def _process_hazard_start_turn_triggers(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
) -> None:
    if actor.dead or actor.hp <= 0:
        return
    for hazard in list(active_hazards):
        if hazard not in active_hazards:
            continue
        if not _hazard_contains_position(hazard, actor.position):
            continue
        _apply_hazard_trigger_effects(
            rng=rng,
            hazard=hazard,
            trigger="start_turn",
            subject=actor,
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
        )
        if actor.dead or actor.hp <= 0:
            return


def _process_hazard_movement_triggers(
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
) -> None:
    if mover.dead or mover.hp <= 0:
        return
    if not movement_path and start_pos == end_pos:
        return
    path_points = _expand_path_points(movement_path or [start_pos, end_pos])
    if len(path_points) < 2:
        return

    for hazard in list(active_hazards):
        if hazard not in active_hazards:
            continue
        enter_effects = _hazard_trigger_effects(hazard, "enter")
        leave_effects = _hazard_trigger_effects(hazard, "leave")
        if not enter_effects and not leave_effects:
            continue

        previous = path_points[0]
        was_inside = _hazard_contains_position(hazard, previous)
        for point in path_points[1:]:
            is_inside = _hazard_contains_position(hazard, point)
            if not was_inside and is_inside and enter_effects:
                _apply_hazard_trigger_effects(
                    rng=rng,
                    hazard=hazard,
                    trigger="enter",
                    subject=mover,
                    actors=actors,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                )
            elif was_inside and not is_inside and leave_effects:
                _apply_hazard_trigger_effects(
                    rng=rng,
                    hazard=hazard,
                    trigger="leave",
                    subject=mover,
                    actors=actors,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                )
            if mover.dead or mover.hp <= 0:
                return
            previous = point
            was_inside = is_inside


def _effect_instance_condition_names(effect: EffectInstance) -> set[str]:
    names = {effect.condition}
    names.update(_IMPLIED_CONDITION_MAP.get(effect.condition, set()))
    return names


def _effect_condition_names(actor: ActorRuntimeState) -> set[str]:
    names: set[str] = set()
    for effect in actor.effect_instances:
        names.update(_effect_instance_condition_names(effect))
    return names


def _rebuild_condition_durations(actor: ActorRuntimeState) -> None:
    trackers: dict[str, ConditionTracker] = {}
    for effect in actor.effect_instances:
        if effect.duration_remaining is None and effect.save_dc is None:
            continue
        for condition in _effect_instance_condition_names(effect):
            previous = trackers.get(condition)
            if previous is None:
                trackers[condition] = ConditionTracker(
                    remaining_rounds=effect.duration_remaining,
                    save_dc=effect.save_dc,
                    save_ability=effect.save_ability,
                )
                continue

            previous_rounds = previous.remaining_rounds
            current_rounds = effect.duration_remaining
            if previous_rounds is None:
                merged_rounds = None
            elif current_rounds is None:
                merged_rounds = None
            else:
                merged_rounds = max(previous_rounds, current_rounds)

            trackers[condition] = ConditionTracker(
                remaining_rounds=merged_rounds,
                save_dc=previous.save_dc if previous.save_dc is not None else effect.save_dc,
                save_ability=(
                    previous.save_ability
                    if previous.save_ability is not None
                    else effect.save_ability
                ),
            )
    actor.condition_durations = trackers


def _sync_condition_state(
    actor: ActorRuntimeState,
    *,
    previous_effect_conditions: set[str] | None = None,
) -> None:
    previous = previous_effect_conditions if previous_effect_conditions is not None else set()
    actor.intrinsic_conditions.update(set(actor.conditions) - previous)
    effect_conditions = _effect_condition_names(actor)
    actor.conditions = set(actor.intrinsic_conditions).union(effect_conditions)
    _rebuild_condition_durations(actor)


def _next_effect_instance_id(actor: ActorRuntimeState) -> str:
    actor.effect_instance_seq += 1
    return f"{actor.actor_id}:effect:{actor.effect_instance_seq}"


def has_condition(actor: ActorRuntimeState, condition: str) -> bool:
    key = _normalize_condition(condition)
    if not key:
        return False
    if key in actor.conditions:
        return True
    for effect in actor.effect_instances:
        if key in _effect_instance_condition_names(effect):
            return True
    return False


def actor_is_incapacitated(actor: ActorRuntimeState | None) -> bool:
    if actor is None:
        return True
    if actor.dead or actor.hp <= 0:
        return True
    return any(has_condition(actor, condition) for condition in _CONTROL_BLOCKING_CONDITIONS)


def _auto_fails_strength_or_dex_save(actor: ActorRuntimeState, ability: str) -> bool:
    save_key = _normalize_condition(ability)
    if save_key not in {"str", "dex"}:
        return False
    return any(has_condition(actor, condition) for condition in _AUTO_FAIL_STR_DEX_SAVE_CONDITIONS)


def query_attack_condition_modifiers(
    *,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    is_melee_attack: bool,
    distance_ft: float,
) -> AttackConditionModifiers:
    _ = attacker
    within_5ft = distance_ft <= 5.0
    modifiers = AttackConditionModifiers()
    if any(has_condition(target, condition) for condition in _ATTACKER_ADVANTAGE_CONDITIONS):
        modifiers.advantage = True
    if has_condition(target, "prone"):
        if within_5ft:
            modifiers.advantage = True
        else:
            modifiers.disadvantage = True
    if has_condition(target, "dodging"):
        modifiers.disadvantage = True
    modifiers.force_critical = within_5ft and any(
        has_condition(target, cond) for cond in _AUTO_CRIT_CONDITIONS
    )
    return modifiers


def _clear_readied_action_state(actor: ActorRuntimeState, *, clear_held_spell: bool) -> None:
    if clear_held_spell and actor.readied_spell_held:
        actor.concentrating = False
        actor.concentrated_spell = None
        actor.concentrated_spell_level = None
        actor.concentrated_targets.clear()
        actor.concentration_conditions.clear()
        actor.concentration_effect_instance_ids.clear()
    actor.readied_action_name = None
    actor.readied_trigger = None
    actor.readied_reaction_reserved = False
    actor.readied_spell_slot_level = None
    actor.readied_spell_held = False


def _remove_effect_instance(
    actor: ActorRuntimeState,
    instance_id: str,
    *,
    source_actor_id: str | None = None,
) -> bool:
    previous_effect_conditions = _effect_condition_names(actor)
    removed = False
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        if effect.instance_id != instance_id:
            kept.append(effect)
            continue
        if source_actor_id is not None and effect.source_actor_id != source_actor_id:
            kept.append(effect)
            continue
        removed = True
    if not removed:
        return False
    actor.effect_instances = kept
    _sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
    if not has_condition(actor, "readying"):
        _clear_readied_action_state(actor, clear_held_spell=True)
    return True


def _remove_condition(
    actor: ActorRuntimeState,
    condition: str,
    *,
    source_actor_id: str | None = None,
    effect_id: str | None = None,
    instance_id: str | None = None,
) -> None:
    key = _normalize_condition(condition)
    if not key:
        return
    previous_effect_conditions = _effect_condition_names(actor)

    removed_effect = False
    normalized_effect_id = _normalize_condition(effect_id) if effect_id is not None else None
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        if effect.condition != key:
            kept.append(effect)
            continue
        if source_actor_id is not None and effect.source_actor_id != source_actor_id:
            kept.append(effect)
            continue
        if normalized_effect_id is not None and effect.effect_id != normalized_effect_id:
            kept.append(effect)
            continue
        if instance_id is not None and effect.instance_id != instance_id:
            kept.append(effect)
            continue
        removed_effect = True
    if removed_effect:
        actor.effect_instances = kept

    should_remove_manual = (
        source_actor_id is None and normalized_effect_id is None and instance_id is None
    )
    if should_remove_manual:
        actor.discard_manual_condition(key)
        for implied in _IMPLIED_CONDITION_MAP.get(key, set()):
            actor.discard_manual_condition(implied)

    if removed_effect or should_remove_manual:
        _sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)

    if key == "readying" and not has_condition(actor, "readying"):
        _clear_readied_action_state(actor, clear_held_spell=True)


def _break_concentration(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    if not _has_active_concentration_state(actor):
        return
    actor.concentrating = False

    linked_ids = set(actor.concentration_effect_instance_ids)
    for target_actor in actors.values():
        for effect in list(target_actor.effect_instances):
            if effect.source_actor_id != actor.actor_id:
                continue
            if effect.instance_id in linked_ids or effect.concentration_linked:
                _remove_effect_instance(
                    target_actor,
                    effect.instance_id,
                    source_actor_id=actor.actor_id,
                )

    summon_ids_to_remove: set[str] = set()
    for target_id in list(actor.concentrated_targets):
        target_actor = actors.get(target_id)
        if target_actor is not None and "summoned" in target_actor.conditions:
            summon_ids_to_remove.add(target_id)
    for summon_id, summon_actor in list(actors.items()):
        if _is_actor_linked_concentration_summon(summon_actor, owner_actor_id=actor.actor_id):
            summon_ids_to_remove.add(summon_id)
    for summon_id in summon_ids_to_remove:
        if summon_id != actor.actor_id:
            actors.pop(summon_id, None)

    active_hazards[:] = [
        hazard
        for hazard in active_hazards
        if not _is_hazard_linked_to_concentration_owner(hazard, owner_actor_id=actor.actor_id)
    ]

    actor.concentrated_targets.clear()
    actor.concentration_conditions.clear()
    actor.concentration_effect_instance_ids.clear()

    actor.concentrated_spell = None
    actor.concentrated_spell_level = None

    if actor.readied_spell_held:
        _remove_condition(actor, "readying")


def _has_active_concentration_state(actor: ActorRuntimeState) -> bool:
    return bool(
        actor.concentrating
        or actor.concentrated_targets
        or actor.concentrated_spell
        or actor.concentrated_spell_level
        or actor.concentration_conditions
        or actor.concentration_effect_instance_ids
    )


def _is_hazard_linked_to_concentration_owner(
    hazard: dict[str, Any],
    *,
    owner_actor_id: str,
) -> bool:
    linked_owner_id = str(hazard.get("concentration_owner_id", "")).strip()
    if linked_owner_id:
        return linked_owner_id == owner_actor_id and bool(hazard.get("concentration_linked", False))
    # Backward-compatible fallback for hazards created before owner linkage metadata.
    return hazard.get("source_id") == owner_actor_id


def _is_actor_linked_concentration_summon(
    actor: ActorRuntimeState,
    *,
    owner_actor_id: str,
) -> bool:
    summon_trait = actor.traits.get("summoned")
    if not isinstance(summon_trait, dict):
        return False
    return (
        str(summon_trait.get("source_id", "")).strip() == owner_actor_id
        and bool(summon_trait.get("concentration_linked", False))
    )


def _concentration_forced_end(actor: ActorRuntimeState) -> bool:
    if not _has_active_concentration_state(actor):
        return False
    if actor.dead or actor.hp <= 0:
        return True
    return any(
        has_condition(actor, condition) for condition in _CONCENTRATION_FORCED_END_CONDITIONS
    )


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
    source_actor_id: str | None = None,
    target_actor_id: str | None = None,
    effect_id: str | None = None,
    duration_timing: str = "turn_start",
    concentration_linked: bool = False,
    stack_policy: str = "independent",
    save_to_end: bool = False,
    internal_tags: set[str] | None = None,
) -> list[str]:
    key = _normalize_condition(condition)
    if not key:
        return []
    if key in actor.condition_immunities or "all" in actor.condition_immunities:
        return []
    previous_effect_conditions = _effect_condition_names(actor)

    normalized_source = str(source_actor_id).strip() if source_actor_id else None
    normalized_target = str(target_actor_id).strip() if target_actor_id else actor.actor_id
    normalized_effect_id = _normalize_condition(effect_id) if effect_id else key
    normalized_boundary = _normalize_duration_boundary(duration_timing)
    normalized_policy = _normalize_stack_policy(stack_policy)
    normalized_tags = set(internal_tags or set())
    normalized_duration = _coerce_positive_int(duration_rounds)
    normalized_save_dc = int(save_dc) if save_dc is not None else None
    normalized_save_ability = _normalize_condition(save_ability) if save_ability else None
    if normalized_save_ability not in ABILITY_KEYS:
        normalized_save_ability = None

    created_ids: list[str] = []

    if normalized_policy == "replace":
        actor.effect_instances = [
            effect for effect in actor.effect_instances if effect.condition != key
        ]
    elif normalized_policy == "refresh":
        for effect in actor.effect_instances:
            if effect.condition != key:
                continue
            if effect.effect_id != normalized_effect_id:
                continue
            if normalized_source and effect.source_actor_id != normalized_source:
                continue
            if normalized_duration is not None:
                current_duration = effect.duration_remaining or 0
                effect.duration_remaining = max(current_duration, normalized_duration)
            effect.duration_boundary = normalized_boundary
            effect.save_dc = normalized_save_dc
            effect.save_ability = normalized_save_ability
            effect.save_to_end = bool(save_to_end)
            effect.concentration_linked = bool(concentration_linked)
            effect.stack_policy = normalized_policy
            effect.internal_tags.update(_normalize_internal_tags(normalized_tags))
            effect.target_actor_id = normalized_target
            _sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
            if (
                key == "unconscious"
                and "prone" not in actor.condition_immunities
                and "all" not in actor.condition_immunities
            ):
                actor.add_manual_condition("prone")
            return [effect.instance_id]

    instance = EffectInstance(
        instance_id=_next_effect_instance_id(actor),
        effect_id=normalized_effect_id,
        condition=key,
        source_actor_id=normalized_source,
        target_actor_id=normalized_target,
        duration_remaining=normalized_duration,
        duration_boundary=normalized_boundary,
        save_dc=normalized_save_dc,
        save_ability=normalized_save_ability,
        save_to_end=bool(save_to_end),
        concentration_linked=bool(concentration_linked),
        stack_policy=normalized_policy,
        internal_tags=_normalize_internal_tags(normalized_tags),
    )
    actor.effect_instances.append(instance)
    created_ids.append(instance.instance_id)
    _sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
    if (
        key == "unconscious"
        and "prone" not in actor.condition_immunities
        and "all" not in actor.condition_immunities
    ):
        actor.add_manual_condition("prone")
    return created_ids


def _tick_conditions_for_actor(
    rng: random.Random,
    actor: ActorRuntimeState,
    *,
    boundary: str = "turn_start",
) -> None:
    """Tick condition durations at the start of an actor's turn.

    Conditions with a repeating save allow the actor to roll each turn.
    """
    tick_boundary = _normalize_duration_boundary(boundary)

    if tick_boundary == "turn_start":
        if has_condition(actor, "raging") and not actor.rage_sustained_since_last_turn:
            _remove_condition(actor, "raging")
        actor.rage_sustained_since_last_turn = False

    if not actor.effect_instances:
        return

    previous_effect_conditions = _effect_condition_names(actor)
    changed = False
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        save_boundary = "turn_end" if effect.save_to_end else "turn_start"
        if effect.save_dc is not None and effect.save_ability and save_boundary == tick_boundary:
            save_key = _normalize_condition(effect.save_ability)
            if _auto_fails_strength_or_dex_save(actor, save_key):
                save_succeeds = False
            else:
                save_mod = int(actor.save_mods.get(save_key, 0))
                save_roll = rng.randint(1, 20) + save_mod
                save_succeeds = save_roll >= effect.save_dc
            if save_succeeds:
                changed = True
                continue

        if effect.duration_remaining is not None and effect.duration_boundary == tick_boundary:
            effect.duration_remaining -= 1
            changed = True
            if effect.duration_remaining <= 0:
                continue

        kept.append(effect)

    if changed:
        actor.effect_instances = kept
        _sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
        if not has_condition(actor, "readying"):
            _clear_readied_action_state(actor, clear_held_spell=True)


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
    telemetry: list[dict[str, Any]] | None = None,
    action_name: str | None = None,
    trigger_event: str = "always",
    source_bucket: str = "effects",
    round_number: int | None = None,
    strategy_name: str | None = None,
    turn_token: str | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
) -> None:
    recipient = _resolve_effect_target(effect, actor=actor, target=target)
    effect_type = str(effect.get("effect_type"))
    telemetry: list[dict[str, Any]] | None = None

    if effect_type == "damage":
        is_magical = False
        if action and getattr(action, "tags", None):
            is_magical = _is_magical_action(action)
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
        if telemetry is not None:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "damage",
                    "damage_type": damage_type,
                    "applied_amount": applied,
                }
            )
        return

    if effect_type == "heal":
        before = recipient.hp
        amount = roll_damage(rng, str(effect.get("amount", "0")), crit=False)
        _apply_healing(recipient, amount)
        if telemetry is not None:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "heal",
                    "applied_amount": max(0, recipient.hp - before),
                }
            )
        return

    if effect_type == "temp_hp":
        amount = roll_damage(rng, str(effect.get("amount", "0")), crit=False)
        before = recipient.temp_hp
        if amount > 0:
            recipient.temp_hp = max(recipient.temp_hp, amount)
        if telemetry is not None:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "temp_hp",
                    "applied_amount": max(0, recipient.temp_hp - before),
                }
            )
        return

    if effect_type == "apply_condition":
        before_conditions = set(recipient.conditions)
        save_dc = effect.get("save_dc")
        save_ability = effect.get("save_ability")
        if save_dc is not None and save_ability:
            save_key = str(save_ability).lower()
            if _auto_fails_strength_or_dex_save(recipient, save_key):
                condition_saved = False
            else:
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
        concentration_linked = bool(
            action and action.concentration and effect.get("concentration_linked", True)
        )
        created_effect_ids = _apply_condition(
            recipient,
            str(effect.get("condition", "")),
            duration_rounds=effect.get("duration_rounds"),
            save_dc=int(save_dc) if save_dc is not None else None,
            save_ability=str(save_ability) if save_ability else None,
            source_actor_id=actor.actor_id,
            target_actor_id=recipient.actor_id,
            effect_id=str(effect.get("effect_id", "")).strip() or None,
            duration_timing=str(
                effect.get("duration_timing", effect.get("duration_boundary", "turn_start"))
            ),
            concentration_linked=concentration_linked,
            stack_policy=str(effect.get("stack_policy", "independent")),
            save_to_end=bool(
                effect.get(
                    "save_to_end",
                    effect.get("save_to_end_policy", False),
                )
            ),
            internal_tags=_normalize_internal_tags(effect.get("internal_tags")),
        )
        if concentration_linked:
            actor.concentrated_targets.add(recipient.actor_id)
            actor.concentration_conditions.add(str(effect.get("condition", "")).lower())
            actor.concentration_effect_instance_ids.update(created_effect_ids)
        _force_end_concentration_if_needed(recipient, actors=actors, active_hazards=active_hazards)
        return

    if effect_type == "remove_condition":
        before_conditions = set(recipient.conditions)
        _remove_condition(recipient, str(effect.get("condition", "")))
        if telemetry is not None and recipient.conditions != before_conditions:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "remove_condition",
                    "condition": str(effect.get("condition", "")).lower(),
                    "applied_amount": 1,
                }
            )
        return

    if effect_type == "hazard":
        duration = _coerce_positive_int(effect.get("duration", effect.get("duration_rounds", 10)))
        if duration is None:
            return
        hazard_type = str(effect.get("hazard_type", "generic"))
        effect_id = str(effect.get("effect_id", "")).strip() or f"hazard:{hazard_type}"
        hazard_position = _to_position3(effect.get("position")) or recipient.position
        hazard_radius = float(effect.get("radius", effect.get("radius_ft", 15)))
        concentration_linked = bool(
            action and action.concentration and effect.get("concentration_linked", True)
        )
        trigger_effects = _extract_hazard_trigger_effects(effect)
        active_hazards.append(
            {
                "type": hazard_type,
                "effect_id": effect_id,
                "source_id": actor.actor_id,
                "target_id": recipient.actor_id,
                "hazard_type": hazard_type,
                "position": hazard_position,
                "radius": hazard_radius,
                "duration": duration,
                "duration_remaining": duration,
                "duration_boundary": _normalize_duration_boundary(
                    effect.get("duration_timing", effect.get("duration_boundary", "turn_start"))
                ),
                "stack_policy": _normalize_stack_policy(effect.get("stack_policy", "independent")),
                "internal_tags": sorted(_normalize_internal_tags(effect.get("internal_tags"))),
                "concentration_linked": concentration_linked,
                "concentration_owner_id": actor.actor_id if concentration_linked else None,
                "trigger_effects": trigger_effects,
            }
        )
        if concentration_linked:
            actor.concentrated_targets.add(recipient.actor_id)
        if telemetry is not None:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "hazard",
                    "hazard_type": hazard_type,
                    "applied_amount": 1,
                }
            )
        return

    if effect_type in {"summon", "conjure"}:
        summon_id = str(effect.get("actor_id", "")).strip() or (
            f"{actor.actor_id}_summon_{len([key for key in actors if key.startswith(actor.actor_id)])}"
        )
        if summon_id in actors:
            return
        concentration_linked = bool(
            action and action.concentration and effect.get("concentration_linked", True)
        )
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
        summoned_actor.add_manual_condition("summoned")
        if effect_type == "conjure":
            summoned_actor.add_manual_condition("conjured")
        summoned_actor.traits["summoned"] = {
            "source_id": actor.actor_id,
            "concentration_linked": concentration_linked,
        }
        actors[summon_id] = summoned_actor
        damage_dealt.setdefault(summon_id, 0)
        damage_taken.setdefault(summon_id, 0)
        threat_scores.setdefault(summon_id, 0)
        resources_spent.setdefault(summon_id, {})
        if concentration_linked:
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
        if telemetry is not None:
            telemetry.append(
                {
                    "telemetry_type": "effect_contribution",
                    "round": round_number,
                    "strategy": strategy_name,
                    "actor_id": actor.actor_id,
                    "target_id": recipient.actor_id,
                    "action_name": action_name or (action.name if action else None),
                    "source_bucket": source_bucket,
                    "trigger_event": trigger_event,
                    "effect_type": "resource_change",
                    "resource": resource,
                    "applied_amount": after - before,
                }
            )
        return

    if effect_type == "command_construct_companion":
        for ally in actors.values():
            if ally.team != actor.team:
                continue
            if getattr(ally, "companion_owner_id", None) != actor.actor_id:
                continue
            if ally.dead or ally.hp <= 0:
                continue
            if hasattr(ally, "commanded_this_round"):
                ally.commanded_this_round = True
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
            if old_position != recipient.position:
                _process_hazard_movement_triggers(
                    rng=rng,
                    mover=recipient,
                    start_pos=old_position,
                    end_pos=recipient.position,
                    movement_path=[old_position, recipient.position],
                    actors=actors,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                )
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
                if old_position != recipient.position:
                    _process_hazard_movement_triggers(
                        rng=rng,
                        mover=recipient,
                        start_pos=old_position,
                        end_pos=recipient.position,
                        movement_path=[old_position, recipient.position],
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                    )
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
            if old_position != recipient.position:
                _process_hazard_movement_triggers(
                    rng=rng,
                    mover=recipient,
                    start_pos=old_position,
                    end_pos=recipient.position,
                    movement_path=[old_position, recipient.position],
                    actors=actors,
                    damage_dealt=damage_dealt,
                    damage_taken=damage_taken,
                    threat_scores=threat_scores,
                    resources_spent=resources_spent,
                    active_hazards=active_hazards,
                )
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
    telemetry: list[dict[str, Any]] | None = None,
    strategy_name: str | None = None,
    once_per_action_used: set[tuple[str, int]] | None = None,
) -> None:
    for source_bucket, effect_list in (
        ("effects", action.effects),
        ("mechanics", action.mechanics),
    ):
        for index, effect in enumerate(effect_list):
            if not isinstance(effect, dict):
                continue
            if not _effect_matches_event(effect, event):
                continue
            if effect.get("once_per_action"):
                marker = (source_bucket, index)
                if once_per_action_used is not None and marker in once_per_action_used:
                    continue
                if once_per_action_used is not None:
                    once_per_action_used.add(marker)
            recipient = _resolve_effect_target(effect, actor=actor, target=target)

            if telemetry is not None:
                telemetry.append(
                    {
                        "telemetry_type": "trigger_provenance",
                        "round": round_number,
                        "strategy": strategy_name,
                        "actor_id": actor.actor_id,
                        "target_id": recipient.actor_id,
                        "action_name": action.name,
                        "source_bucket": source_bucket,
                        "trigger_event": event,
                        "apply_on": str(effect.get("apply_on", "always")),
                        "effect_type": str(effect.get("effect_type", "")),
                    }
                )

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
                telemetry=telemetry,
                action_name=action.name,
                trigger_event=event,
                source_bucket=source_bucket,
                round_number=round_number,
                strategy_name=strategy_name,
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


def _can_pay_resource_cost(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    *,
    spell_cast_request: SpellCastRequest | None = None,
) -> bool:
    if "spell" not in action.tags:
        return _has_resources(actor, action.resource_cost)

    non_slot_cost, slot_amount, _slot_levels = _split_spell_slot_cost(action.resource_cost)
    if not _has_resources(actor, non_slot_cost):
        return False
    if slot_amount <= 0:
        return True

    required_level = _required_spell_slot_level(action)
    if required_level <= 0:
        return True

    explicit_slot = spell_cast_request.slot_level if spell_cast_request is not None else None
    if explicit_slot is not None:
        chosen_level = int(explicit_slot)
        if chosen_level < required_level:
            return False
        return _can_pay_exact_spell_slot(actor, slot_level=chosen_level, amount=slot_amount)

    preferred_level = _preferred_spell_slot_level(action)
    return _can_pay_flexible_spell_slots(
        actor,
        minimum_level=required_level,
        amount=slot_amount,
        preferred_level=preferred_level,
    )


def _can_take_reaction(actor: ActorRuntimeState) -> bool:
    if not actor.reaction_available:
        return False
    if actor.dead or actor.hp <= 0:
        return False
    if actor_is_incapacitated(actor):
        return False
    if has_condition(actor, "open_hand_no_reactions"):
        return False
    return True


def _is_same_turn_for_actor(actor: ActorRuntimeState, turn_token: str | None) -> bool:
    if turn_token is None:
        return True
    text = str(turn_token)
    if ":" in text:
        token_actor_id = text.split(":", 1)[1]
        return token_actor_id == actor.actor_id
    return text == actor.actor_id


def _set_gwm_bonus_trigger(actor: ActorRuntimeState, *, turn_token: str | None = None) -> None:
    if turn_token is not None and not _is_same_turn_for_actor(actor, turn_token):
        return
    actor.gwm_bonus_trigger_available = True


def _clear_gwm_bonus_trigger(actor: ActorRuntimeState) -> None:
    actor.gwm_bonus_trigger_available = False


def _spell_casting_legal_this_turn(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    *,
    turn_token: str | None = None,
) -> bool:
    if "spell" not in action.tags:
        return True
    if not _is_same_turn_for_actor(actor, turn_token):
        return True
    if actor.bonus_action_spell_restriction_active and not _is_action_cantrip_spell(action):
        return False
    if action.action_cost == "bonus" and actor.non_action_cantrip_spell_cast_this_turn:
        return False
    return True


def _action_available(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    *,
    spell_cast_request: SpellCastRequest | None = None,
    turn_token: str | None = None,
) -> bool:
    if action.name == "lay_on_hands" and actor.resources.get("lay_on_hands_pool", 0) <= 0:
        return False
    if action.max_uses is not None and actor.per_action_uses.get(action.name, 0) >= action.max_uses:
        return False
    if action.recharge and not actor.recharge_ready.get(action.name, True):
        return False
    if not _spell_casting_legal_this_turn(actor, action, turn_token=turn_token):
        return False
    if not _can_pay_resource_cost(actor, action, spell_cast_request=spell_cast_request):
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
    if _has_tag(action, "conversion:slot_to_points"):
        slot_level = _slot_level_from_action(action)
        if slot_level is None:
            return False
        current_points = int(actor.resources.get("sorcery_points", 0))
        max_points = actor.max_resources.get("sorcery_points")
        if isinstance(max_points, int) and max_points >= 0:
            if current_points + slot_level > int(max_points):
                return False
    if _has_tag(action, "conversion:points_to_slot"):
        slot_level = _slot_level_from_action(action)
        if slot_level is None or slot_level > 5:
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


def _refresh_legendary_actions_for_turn(actor: ActorRuntimeState) -> None:
    if not any(action.action_cost == "legendary" for action in actor.actions):
        return
    base_legendary = int(actor.resources.get("legendary_actions", 0))
    actor.legendary_actions_remaining = base_legendary if base_legendary > 0 else 3


def _mark_action_cost_used(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    if action.action_cost == "bonus":
        actor.bonus_available = False
        if "gwm_bonus" in action.tags:
            _clear_gwm_bonus_trigger(actor)
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
    obstacles: list[AABB] | None = None,
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
        obstacles=obstacles,
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
            if not _action_available(actor, action, turn_token=turn_token):
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
            obstacles=obstacles,
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

        spell_cast_request = SpellCastRequest() if "spell" in action.tags else None
        if not _spend_action_resource_cost(
            actor,
            action,
            resources_spent,
            spell_cast_request=spell_cast_request,
        ):
            continue
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
            spell_cast_request=spell_cast_request,
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
    if event == "turn_start" and trigger_actor is not None and trigger_actor.actor_id in actors:
        start_actor = actors[trigger_actor.actor_id]
        _clear_gwm_bonus_trigger(start_actor)
    if event == "turn_end" and trigger_actor is not None and trigger_actor.actor_id in actors:
        end_actor = actors[trigger_actor.actor_id]
        _clear_gwm_bonus_trigger(end_actor)
        _tick_conditions_for_actor(rng, end_actor, boundary="turn_end")
        _tick_hazards_for_actor_turn(
            active_hazards=active_hazards,
            actor=end_actor,
            actors=actors,
            boundary="turn_end",
        )
        _force_end_concentration_if_needed(end_actor, actors=actors, active_hazards=active_hazards)
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


def _spell_slot_level_from_key(key: str) -> int | None:
    if not str(key).startswith("spell_slot_"):
        return None
    try:
        level = int(str(key).split("_")[-1])
    except ValueError:
        return None
    return level if level > 0 else None


def _spell_slot_levels_from_cost(cost: dict[str, int]) -> list[int]:
    levels: list[int] = []
    for key, amount in cost.items():
        if int(amount) <= 0:
            continue
        level = _spell_slot_level_from_key(str(key))
        if level is not None:
            levels.append(level)
    return sorted(levels)


def _spell_base_level_from_action(action: ActionDefinition) -> int:
    if action.spell is not None:
        return max(0, int(action.spell.level))
    tagged_level = _spell_level_from_tags(action)
    if tagged_level is not None:
        return max(0, tagged_level)
    slot_levels = _spell_slot_levels_from_cost(action.resource_cost)
    if slot_levels:
        return max(0, min(slot_levels))
    return 0


def _upcast_slot_level_from_action(action: ActionDefinition) -> int | None:
    raw_level = _extract_tag_value(list(action.tags), "upcast_level:")
    if raw_level is None:
        return None
    try:
        level = int(raw_level)
    except ValueError:
        return None
    return level if level > 0 else None


def _required_spell_slot_level(action: ActionDefinition) -> int:
    base_level = _spell_base_level_from_action(action)
    if base_level <= 0:
        return 0
    required_level = base_level
    slot_levels = _spell_slot_levels_from_cost(action.resource_cost)
    if slot_levels:
        required_level = max(required_level, min(slot_levels))
    upcast_level = _upcast_slot_level_from_action(action)
    if upcast_level is not None:
        required_level = max(required_level, upcast_level)
    return required_level


def _preferred_spell_slot_level(action: ActionDefinition) -> int | None:
    upcast_level = _upcast_slot_level_from_action(action)
    if upcast_level is not None:
        return upcast_level
    slot_levels = _spell_slot_levels_from_cost(action.resource_cost)
    return min(slot_levels) if slot_levels else None


def _spell_level_from_action(action: ActionDefinition) -> int:
    if "spell" not in action.tags:
        return 0
    return _required_spell_slot_level(action)


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


def _readied_trigger_matches(readied_trigger: str | None, *, trigger_event: str) -> bool:
    normalized_readied = _normalize_event_trigger(readied_trigger)
    normalized_event = _normalize_event_trigger(trigger_event)
    if normalized_event in {None, "enemy_turn_start", "on_enemy_turn_start"}:
        return normalized_readied in {None, "enemy_turn_start", "on_enemy_turn_start"}
    if normalized_event == "enemy_enters_reach":
        return normalized_readied in {
            "enemy_enters_reach",
            "on_enemy_enters_reach",
            "enters_reach",
            "on_enters_reach",
        }
    return normalized_readied == normalized_event


def _trigger_readied_actions(
    *,
    rng: random.Random,
    trigger_actor: ActorRuntimeState,
    trigger_event: str = "enemy_turn_start",
    eligible_reactors: set[str] | None = None,
    round_number: int | None = None,
    turn_token: str | None = None,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
) -> None:
    normalized_trigger_event = _normalize_event_trigger(trigger_event)
    supports_standard_reactions = normalized_trigger_event in {
        None,
        "enemy_turn_start",
        "on_enemy_turn_start",
    }

    for actor in actors.values():
        if eligible_reactors is not None and actor.actor_id not in eligible_reactors:
            continue
        if actor.team == trigger_actor.team:
            continue
        if actor.dead or actor.hp <= 0:
            continue
        if not actor.reaction_available:
            continue

        if "readying" in actor.conditions and actor.readied_reaction_reserved:
            if _readied_trigger_matches(actor.readied_trigger, trigger_event=trigger_event):
                readied = _resolve_named_action(actor, actor.readied_action_name)
                if readied is None:
                    _remove_condition(actor, "readying")
                elif readied.name != "ready":
                    reaction_action = replace(readied, action_cost="reaction")
                    held_readied_spell = (
                        actor.readied_spell_held and "spell" in reaction_action.tags
                    )
                    spell_cast_request = (
                        SpellCastRequest(slot_level=actor.readied_spell_slot_level)
                        if held_readied_spell
                        else (SpellCastRequest() if "spell" in reaction_action.tags else None)
                    )
                    if held_readied_spell:
                        reaction_action = replace(reaction_action, resource_cost={})
                    if _action_available(
                        actor,
                        reaction_action,
                        spell_cast_request=spell_cast_request,
                        turn_token=turn_token,
                    ):
                        targets = _resolve_targets_for_action(
                            rng=rng,
                            actor=actor,
                            action=reaction_action,
                            actors=actors,
                            requested=[TargetRef(trigger_actor.actor_id)],
                            obstacles=obstacles,
                        )
                        targets = [
                            target
                            for target in targets
                            if target.actor_id == trigger_actor.actor_id
                        ]
                        targets = _filter_targets_in_range(actor, reaction_action, targets)
                        paid_reaction_cost = held_readied_spell
                        if targets and not paid_reaction_cost:
                            paid_reaction_cost = _spend_action_resource_cost(
                                actor,
                                reaction_action,
                                resources_spent,
                                spell_cast_request=spell_cast_request,
                            )
                        if targets and paid_reaction_cost:
                            actor.reaction_available = False
                            if held_readied_spell:
                                actor.readied_spell_held = False
                                _break_concentration(actor, actors, active_hazards)
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
                                round_number=round_number,
                                turn_token=turn_token,
                                spell_cast_request=spell_cast_request,
                            )
                            _remove_condition(actor, "readying")
            if trigger_actor.dead or trigger_actor.hp <= 0:
                break

        if not supports_standard_reactions:
            if trigger_actor.dead or trigger_actor.hp <= 0:
                break
            continue

        if not actor.reaction_available:
            continue

        for reaction_action in actor.actions:
            if reaction_action.action_cost != "reaction":
                continue
            if _action_matches_reaction_spell_id(
                reaction_action,
                spell_id="shield",
            ) or _action_matches_reaction_spell_id(
                reaction_action,
                spell_id="counterspell",
            ):
                continue
            trigger = _normalize_event_trigger(reaction_action.event_trigger)
            if trigger not in {"enemy_turn_start", "on_enemy_turn_start"}:
                continue
            if not _action_available(actor, reaction_action, turn_token=turn_token):
                continue

            targets = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=reaction_action,
                actors=actors,
                requested=[TargetRef(trigger_actor.actor_id)],
                obstacles=obstacles,
            )
            targets = [target for target in targets if target.actor_id == trigger_actor.actor_id]
            targets = _filter_targets_in_range(actor, reaction_action, targets)
            if not targets:
                continue
            spell_cast_request = SpellCastRequest() if "spell" in reaction_action.tags else None
            if not _spend_action_resource_cost(
                actor,
                reaction_action,
                resources_spent,
                spell_cast_request=spell_cast_request,
            ):
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
                round_number=round_number,
                turn_token=turn_token,
                spell_cast_request=spell_cast_request,
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


def _ki_save_dc(actor: ActorRuntimeState) -> int:
    return 8 + _calculate_proficiency_bonus(actor.level) + actor.wis_mod


def _saving_throw_succeeds(
    *,
    rng: random.Random,
    target: ActorRuntimeState,
    ability: str,
    dc: int,
    resources_spent: dict[str, dict[str, int]],
) -> bool:
    save_key = ability.lower()
    if _auto_fails_strength_or_dex_save(target, save_key):
        success = False
    else:
        save_mod = int(target.save_mods.get(save_key, 0))
        save_total = rng.randint(1, 20) + save_mod
        success = save_total >= dc
    if not success and target.resources.get("legendary_resistance", 0) > 0:
        target.resources["legendary_resistance"] -= 1
        resources_spent[target.actor_id]["legendary_resistance"] = (
            resources_spent[target.actor_id].get("legendary_resistance", 0) + 1
        )
        return True
    return success


def _choose_open_hand_rider(action: ActionDefinition, target: ActorRuntimeState) -> str:
    for raw_tag in action.tags:
        tag = str(raw_tag)
        if tag.startswith("open_hand_rider:"):
            choice = tag.split(":", 1)[1].strip().lower()
            if choice in {"prone", "push", "no_reactions"}:
                return choice

    if target.reaction_available and not has_condition(target, "open_hand_no_reactions"):
        return "no_reactions"
    if not has_condition(target, "prone"):
        return "prone"
    return "push"


def _try_stunning_strike(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    target: ActorRuntimeState,
    is_ranged: bool,
    resources_spent: dict[str, dict[str, int]],
) -> None:
    if is_ranged or not _has_trait(actor, "stunning strike"):
        return
    if actor.resources.get("ki", 0) <= 0:
        return
    if actor_is_incapacitated(target):
        return

    actor.resources["ki"] -= 1
    resources_spent[actor.actor_id]["ki"] = resources_spent[actor.actor_id].get("ki", 0) + 1
    dc = _ki_save_dc(actor)
    if _saving_throw_succeeds(
        rng=rng,
        target=target,
        ability="con",
        dc=dc,
        resources_spent=resources_spent,
    ):
        return
    _apply_condition(target, "stunned", duration_rounds=2)


def _try_open_hand_technique(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    target: ActorRuntimeState,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    if not _has_trait(actor, "open hand technique"):
        return
    if "flurry_of_blows" not in action.tags:
        return

    dc = _ki_save_dc(actor)
    rider = _choose_open_hand_rider(action, target)
    if rider == "prone":
        if not _saving_throw_succeeds(
            rng=rng,
            target=target,
            ability="dex",
            dc=dc,
            resources_spent=resources_spent,
        ):
            _apply_condition(target, "prone", duration_rounds=1)
        return

    if rider == "push":
        if _saving_throw_succeeds(
            rng=rng,
            target=target,
            ability="str",
            dc=dc,
            resources_spent=resources_spent,
        ):
            return
        _apply_effect(
            action=action,
            effect={
                "effect_type": "forced_movement",
                "target": "target",
                "distance_ft": 15,
                "direction": "away_from_source",
            },
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
        return

    target.reaction_available = False
    _apply_condition(target, "open_hand_no_reactions", duration_rounds=2)


def _multiattack_defense_marker(attacker_id: str) -> str:
    return f"{_MULTIATTACK_DEFENSE_PREFIX}{attacker_id}"


def _shield_spell_action(shield_action: ActionDefinition) -> ActionDefinition:
    tags = list(shield_action.tags)
    tags.append("spell")
    tags = list(dict.fromkeys(tags))
    return replace(shield_action, tags=tags)


def _try_shield_reaction(
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    roll: AttackRollResult,
    *,
    target_ac: int,
    turn_token: str | None = None,
) -> bool:
    """Always-use Shield reaction: +5 AC to negate a hit. Consumes reaction + spell slot.

    Returns True if the hit was negated.
    """
    if not _can_take_reaction(target):
        return False
    shield_action = None
    for action in target.actions:
        if action.action_cost == "reaction" and _action_matches_reaction_spell_id(
            action, spell_id="shield"
        ):
            shield_action = action
            break
    if shield_action is None:
        return False
    shield_spell_action = _shield_spell_action(shield_action)
    if not _spell_casting_legal_this_turn(
        target,
        shield_spell_action,
        turn_token=turn_token,
    ):
        return False
    # Need a 1st-level spell slot (or any available slot)
    slot_key = None
    for key in sorted(target.resources.keys()):
        if key.startswith("spell_slot_") and target.resources.get(key, 0) > 0:
            slot_key = key
            break
    if slot_key is None:
        return False
    # Shield: +5 AC against the effective AC for this attack (includes cover/other modifiers).
    if roll.total < (target_ac + 5) and roll.natural_roll != 20:
        target.resources[slot_key] -= 1
        target.reaction_available = False
        _record_spell_cast_for_turn(target, shield_spell_action)
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
        if action.name == "second_wind" and actor.hp >= actor.max_hp:
            continue
        if (
            "off_hand" in action.tags
            or "martial_arts" in action.tags
            or "polearm_master" in action.tags
            or "gwm_bonus" in action.tags
        ):
            if not actor.took_attack_action_this_turn:
                continue
            if "gwm_bonus" in action.tags and not actor.gwm_bonus_trigger_available:
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


def _shield_reaction_would_be_legal(
    *,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    roll: AttackRollResult,
    target_ac: int,
    turn_token: str | None = None,
) -> bool:
    if not _can_take_reaction(target):
        return False
    shield_action = next(
        (
            action
            for action in target.actions
            if (
                action.action_cost == "reaction"
                and _action_matches_reaction_spell_id(action, spell_id="shield")
            )
        ),
        None,
    )
    if shield_action is None:
        return False
    if not _spell_casting_legal_this_turn(
        target,
        _shield_spell_action(shield_action),
        turn_token=turn_token,
    ):
        return False
    has_slot = any(
        key.startswith("spell_slot_") and target.resources.get(key, 0) > 0
        for key in sorted(target.resources.keys())
    )
    if not has_slot:
        return False
    return roll.total < (target_ac + 5) and roll.natural_roll != 20


class _AttackRollBardicInspirationRule:
    name = "rule:bardic_inspiration_attack_roll"

    def __call__(self, event: AttackRollEvent) -> None:
        event.roll = _try_spend_bardic_inspiration_on_attack_roll(
            rng=event.rng,
            actor=event.attacker,
            roll=event.roll,
            target_ac=event.target_ac,
            resources_spent=event.resources_spent,
        )


class _AttackRollLuckyAttackerRule:
    name = "rule:lucky_attacker_reroll"

    def __call__(self, event: AttackRollEvent) -> None:
        if event.roll.hit or not _has_trait(event.attacker, "lucky"):
            return
        if event.attacker.resources.get("luck_points", 0) <= 0:
            return
        event.attacker.resources["luck_points"] -= 1
        event.resources_spent[event.attacker.actor_id]["luck_points"] = (
            event.resources_spent[event.attacker.actor_id].get("luck_points", 0) + 1
        )
        lucky_natural = event.rng.randint(1, 20)
        new_natural = max(event.roll.natural_roll, lucky_natural)
        crit = new_natural == 20
        total = new_natural + event.to_hit_modifier
        hit = crit or (new_natural != 1 and total >= event.target_ac)
        event.roll = AttackRollResult(hit=hit, crit=crit, natural_roll=new_natural, total=total)


class _AttackRollLuckyDefenderRule:
    name = "rule:lucky_defender_reroll"

    def __call__(self, event: AttackRollEvent) -> None:
        if not event.roll.hit or not _has_trait(event.target, "lucky"):
            return
        if event.target.resources.get("luck_points", 0) <= 0:
            return
        event.target.resources["luck_points"] -= 1
        event.resources_spent[event.target.actor_id]["luck_points"] = (
            event.resources_spent[event.target.actor_id].get("luck_points", 0) + 1
        )
        lucky_natural = event.rng.randint(1, 20)
        new_natural = min(event.roll.natural_roll, lucky_natural)
        crit = new_natural == 20
        total = new_natural + event.to_hit_modifier
        hit = crit or (new_natural != 1 and total >= event.target_ac)
        event.roll = AttackRollResult(hit=hit, crit=crit, natural_roll=new_natural, total=total)


class _AttackResolvedCuttingWordsRule:
    name = "rule:cutting_words_attack_roll"

    def __call__(self, event: AttackResolvedEvent) -> None:
        event.roll = _try_cutting_words_on_attack_roll(
            rng=event.rng,
            attacker=event.attacker,
            target=event.target,
            roll=event.roll,
            target_ac=event.target_ac,
            actors=event.actors,
            resources_spent=event.resources_spent,
        )


class _AttackResolutionShieldRule:
    name = "rule:shield_reaction"

    def __call__(self, event: AttackResolvedEvent) -> None:
        if not event.roll.hit:
            return
        if not _shield_reaction_would_be_legal(
            attacker=event.attacker,
            target=event.target,
            roll=event.roll,
            target_ac=event.target_ac,
            turn_token=event.turn_token,
        ):
            return
        if event.timing_engine is not None:
            event.timing_engine.emit(
                ReactionWindowOpenedEvent(
                    window="shield",
                    reactor=event.target,
                    attacker=event.attacker,
                    target=event.target,
                    action=event.action,
                    round_number=event.round_number,
                    turn_token=event.turn_token,
                )
            )
        if _try_shield_reaction(
            event.attacker,
            event.target,
            event.roll,
            target_ac=event.target_ac,
            turn_token=event.turn_token,
        ):
            event.roll = AttackRollResult(
                hit=False,
                crit=False,
                natural_roll=event.roll.natural_roll,
                total=event.roll.total,
            )


class _DamageRollCuttingWordsRule:
    name = "rule:cutting_words_damage_roll"

    @staticmethod
    def _sync_bundle_to_raw_damage(event: DamageRollEvent) -> None:
        if event.bundle is None:
            return
        target_total = max(0, int(event.raw_damage))
        if event.bundle.raw_total != target_total:
            event.bundle.rebalance_total(target_total)
        if target_total > 0 and event.bundle.raw_total == 0:
            _append_damage_packet(
                bundle=event.bundle,
                amount=target_total,
                damage_type=event.action.damage_type,
                packet_source="legacy_raw_sync",
                is_magical=_is_magical_action(event.action),
                crit_expanded=False,
            )
        event.raw_damage = event.bundle.raw_total

    def __call__(self, event: DamageRollEvent) -> None:
        self._sync_bundle_to_raw_damage(event)
        reduced_total = _try_cutting_words_on_damage_roll(
            rng=event.rng,
            attacker=event.attacker,
            target=event.target,
            raw_damage=event.raw_damage,
            actors=event.actors,
            resources_spent=event.resources_spent,
        )
        if event.bundle is not None:
            event.bundle.rebalance_total(reduced_total)
            event.raw_damage = event.bundle.raw_total
            return
        event.raw_damage = max(0, int(reduced_total))


class _DamageRollUncannyDodgeRule:
    name = "rule:uncanny_dodge"

    def __call__(self, event: DamageRollEvent) -> None:
        _DamageRollCuttingWordsRule._sync_bundle_to_raw_damage(event)
        if event.raw_damage <= 0:
            return
        if not _has_trait(event.target, "uncanny dodge"):
            return
        if not _can_take_reaction(event.target):
            return
        if not event.target_can_see_attacker:
            return
        if event.timing_engine is not None:
            event.timing_engine.emit(
                ReactionWindowOpenedEvent(
                    window="uncanny_dodge",
                    reactor=event.target,
                    attacker=event.attacker,
                    target=event.target,
                    action=event.action,
                    round_number=event.round_number,
                    turn_token=event.turn_token,
                )
            )
        if event.bundle is not None:
            event.bundle.halve_total()
            event.raw_damage = event.bundle.raw_total
        else:
            event.raw_damage //= 2
        event.target.reaction_available = False


def _register_default_timing_rules(timing_engine: CombatTimingEngine) -> list[ListenerSubscription]:
    return [
        timing_engine.subscribe(
            AttackRollEvent,
            _AttackRollBardicInspirationRule(),
            priority=90,
        ),
        timing_engine.subscribe(AttackRollEvent, _AttackRollLuckyAttackerRule(), priority=80),
        timing_engine.subscribe(AttackRollEvent, _AttackRollLuckyDefenderRule(), priority=70),
        timing_engine.subscribe(
            AttackResolvedEvent, _AttackResolvedCuttingWordsRule(), priority=60
        ),
        timing_engine.subscribe(AttackResolvedEvent, _AttackResolutionShieldRule(), priority=50),
        timing_engine.subscribe(DamageRollEvent, _DamageRollCuttingWordsRule(), priority=40),
        timing_engine.subscribe(DamageRollEvent, _DamageRollUncannyDodgeRule(), priority=30),
    ]


def _create_combat_timing_engine(*, include_default_rules: bool = True) -> CombatTimingEngine:
    timing_engine = CombatTimingEngine()
    if include_default_rules:
        _register_default_timing_rules(timing_engine)
    return timing_engine


_DEFAULT_COMBAT_TIMING_ENGINE: CombatTimingEngine | None = None


def _get_default_combat_timing_engine() -> CombatTimingEngine:
    global _DEFAULT_COMBAT_TIMING_ENGINE
    if _DEFAULT_COMBAT_TIMING_ENGINE is None:
        _DEFAULT_COMBAT_TIMING_ENGINE = _create_combat_timing_engine()
    return _DEFAULT_COMBAT_TIMING_ENGINE


def _mode_requires_explicit_targets(mode: str) -> bool:
    return mode in {
        "single_enemy",
        "single_ally",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    }


def _resolve_spell_cast_request(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    provided: SpellCastRequest | None,
) -> SpellCastRequest:
    if provided is None:
        request = SpellCastRequest()
    else:
        request = SpellCastRequest(
            slot_level=provided.slot_level,
            mode=provided.mode,
            target_actor_ids=list(provided.target_actor_ids),
            origin=provided.origin,
        )

    if request.mode is None:
        request.mode = action.target_mode
    if not request.target_actor_ids and targets:
        request.target_actor_ids = [target.actor_id for target in targets]
    if request.origin is None:
        request.origin = actor.position

    required_slot_level = _required_spell_slot_level(action)
    if required_slot_level > 0 and request.slot_level is None:
        preferred_slot = _preferred_spell_slot_level(action)
        request.slot_level = preferred_slot if preferred_slot is not None else required_slot_level

    if request.mode is None:
        raise ValueError("Spell cast request requires a target mode.")
    if request.mode != action.target_mode:
        raise ValueError("Spell cast request mode must match action target mode.")
    if _mode_requires_explicit_targets(request.mode) and not request.target_actor_ids:
        raise ValueError("Spell cast request requires at least one target.")
    if action.aoe_type and request.origin is None:
        raise ValueError("Spell cast request requires an origin for area spell templates.")
    if required_slot_level > 0:
        if request.slot_level is None:
            raise ValueError("Spell cast request requires a slot for leveled spells.")
        if int(request.slot_level) < required_slot_level:
            raise ValueError("Spell cast request slot level is below the spell level.")

    return request


def _record_spell_cast_for_turn(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    if "spell" not in action.tags:
        return
    if not _is_action_cantrip_spell(action):
        actor.non_action_cantrip_spell_cast_this_turn = True
    if action.action_cost == "bonus":
        actor.bonus_action_spell_restriction_active = True


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
    telemetry: list[dict[str, Any]] | None = None,
    strategy_name: str | None = None,
    timing_engine: CombatTimingEngine | None = None,
    spell_cast_request: SpellCastRequest | None = None,
    allow_auto_movement: bool = True,
    ready_declaration: ReadyDeclaration | None = None,
) -> None:
    if not targets:
        return
    if obstacles is None:
        obstacles = []
    is_spell_action = _has_tag(action, "spell")
    subtle_spell = _has_tag(action, "metamagic:subtle")
    spell_level = _spell_level_from_action(action) if is_spell_action else 0
    resolved_spell_cast_request: SpellCastRequest | None = None
    spell_declared_for_resolution = False
    has_turn_context = round_number is not None and turn_token is not None
    enforce_range_legality = has_turn_context or _action_has_explicit_range_bounds(action)
    active_timing_engine = (
        timing_engine if timing_engine is not None else _get_default_combat_timing_engine()
    )
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
        if allow_auto_movement:
            movement_was_budgeted = actor.movement_remaining > 0
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
                round_number=round_number,
                turn_token=turn_token,
            )
            if not in_range:
                if (
                    not enforce_range_legality
                    and action.action_type == "attack"
                    and not movement_was_budgeted
                    and not actor.conditions.intersection({"grappled", "restrained"})
                ):
                    in_range = True
                else:
                    return
            if has_turn_context:
                targets = _filter_targets_in_range(actor, action, targets)
                if not targets:
                    return
            else:
                # Preserve legacy direct-call monk behavior from feat/class-monk-mechanics
                # while still using range resolution during full round simulation.
                targets = list(targets)
                if not targets:
                    return
        else:
            targets = _filter_targets_in_range(actor, action, list(targets))
            if not targets:
                return

    # Spell declaration and counterspell check
    if is_spell_action:
        if not _spell_casting_legal_this_turn(actor, action, turn_token=turn_token):
            return
        if not _can_cast_spell_with_components(actor, action):
            return

        try:
            resolved_spell_cast_request = _resolve_spell_cast_request(
                actor=actor,
                action=action,
                targets=targets,
                provided=spell_cast_request,
            )
        except ValueError:
            return
        if resolved_spell_cast_request.slot_level is not None:
            spell_level = int(resolved_spell_cast_request.slot_level)
            action = _apply_upcast_scaling_for_slot(action, slot_level=spell_level)

        declaration_event = active_timing_engine.emit(
            ActionDeclaredEvent(
                attacker=actor,
                target=targets[0],
                action=action,
                round_number=round_number,
                turn_token=turn_token,
            )
        )
        if declaration_event.cancelled:
            return
        spell_declared_for_resolution = True

        _record_spell_cast_for_turn(actor, action)

        if not subtle_spell:
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
                            if (
                                a.action_cost == "reaction"
                                and _action_matches_reaction_spell_id(a, spell_id="counterspell")
                            )
                        ),
                        None,
                    )
                    if cs_action:
                        if not _spell_casting_legal_this_turn(
                            enemy,
                            cs_action,
                            turn_token=turn_token,
                        ):
                            continue
                        if distance_chebyshev(enemy.position, actor.position) <= 60:
                            counter_slot = _select_counterspell_slot(
                                enemy, incoming_spell_level=spell_level
                            )
                            if counter_slot:
                                counter_window = active_timing_engine.emit(
                                    ReactionWindowOpenedEvent(
                                        window="counterspell",
                                        reactor=enemy,
                                        attacker=actor,
                                        target=targets[0],
                                        action=action,
                                        round_number=round_number,
                                        turn_token=turn_token,
                                    )
                                )
                                if counter_window.cancelled:
                                    continue
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
            actor.concentration_conditions.clear()
            actor.concentration_effect_instance_ids.clear()
            if _is_smite_setup_action(action):
                actor.concentration_conditions.clear()
                actor.concentrated_targets.clear()
                actor.concentration_effect_instance_ids.clear()

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
        ranged_attack_action = _is_ranged_attack_action(action)

        current_target: ActorRuntimeState | None = None
        once_per_action_used: set[tuple[str, int]] = set()
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
                        if enforce_range_legality:
                            current_target = next(
                                (
                                    candidate
                                    for candidate in fallbacks
                                    if _attack_range_state(actor, action, candidate)[0]
                                ),
                                None,
                            )
                        else:
                            current_target = fallbacks[0]
                if current_target is None:
                    break
            target = current_target
            long_range_disadvantage = False
            if enforce_range_legality:
                in_attack_range, long_range_disadvantage = _attack_range_state(actor, action, target)
                if not in_attack_range:
                    continue
            if not (is_spell_action and spell_declared_for_resolution):
                declaration_event = active_timing_engine.emit(
                    ActionDeclaredEvent(
                        attacker=actor,
                        target=target,
                        action=action,
                        round_number=round_number,
                        turn_token=turn_token,
                    )
                )
                if declaration_event.cancelled:
                    continue
            if "raging" in actor.conditions and target.team != actor.team:
                actor.rage_sustained_since_last_turn = True
            advantage, disadvantage = _consume_attack_flags(actor)
            target_distance_ft = distance_chebyshev(actor.position, target.position)
            weapon_name = action.name.lower()
            inferred_range = _action_range_ft(action)
            has_canonical_weapon_data = _action_has_canonical_weapon_data(action)
            is_ranged = _is_ranged_weapon_action(action)
            if not is_ranged and not has_canonical_weapon_data:
                is_ranged = bool(inferred_range is not None and inferred_range > 5.0)
            attack_condition_modifiers = query_attack_condition_modifiers(
                attacker=actor,
                target=target,
                is_melee_attack=not is_ranged,
                distance_ft=target_distance_ft,
            )
            if attack_condition_modifiers.advantage:
                advantage = True
            if attack_condition_modifiers.disadvantage:
                disadvantage = True
            if long_range_disadvantage:
                disadvantage = True
            if (
                ranged_attack_action
                and not _ranged_attack_ignores_adjacent_hostile_disadvantage(actor, action)
                and _has_hostile_within_melee_range(actor, actors)
            ):
                disadvantage = True
            force_crit = attack_condition_modifiers.force_critical

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
            effective_advantage = advantage and not disadvantage
            effective_disadvantage = disadvantage and not advantage

            # Sharpshooter / Great Weapon Master AI Toggle (-5 to hit / +10 damage)
            power_attack_active = False
            target_ac = target.ac
            if _has_trait(target, "multiattack defense") and (
                _multiattack_defense_marker(actor.actor_id) in target.conditions
            ):
                target_ac += 4
            cover_bonus = 0
            to_hit_penalty = 0
            damage_bonus = 0
            is_heavy = _action_has_weapon_property(action, "heavy")
            if not is_heavy and not has_canonical_weapon_data:
                is_heavy = any(w in weapon_name for w in _HEAVY_WEAPON_HINTS)
            is_finesse = _action_has_weapon_property(action, "finesse")
            if not is_finesse and not has_canonical_weapon_data:
                is_finesse = any(w in weapon_name for w in _FINESSE_WEAPON_HINTS)

            if action.to_hit is not None:
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
                        telemetry=telemetry,
                        strategy_name=strategy_name,
                        once_per_action_used=once_per_action_used,
                    )
                    emit_event("on_miss", trigger_target=target)
                    continue
                cover_bonus = max(cover_bonus, _cover_bonus_from_state(cover_state))
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

            to_hit_mod = action.to_hit + to_hit_penalty if action.to_hit is not None else 0
            roll = attack_roll(
                rng,
                to_hit_mod,
                target_ac,
                advantage=advantage,
                disadvantage=disadvantage,
            )
            roll_event = active_timing_engine.emit(
                AttackRollEvent(
                    rng=rng,
                    attacker=actor,
                    target=target,
                    action=action,
                    roll=roll,
                    target_ac=target_ac,
                    to_hit_modifier=to_hit_mod,
                    actors=actors,
                    resources_spent=resources_spent,
                    round_number=round_number,
                    turn_token=turn_token,
                )
            )
            if roll_event.cancelled:
                continue
            roll = roll_event.roll

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
            resolved_event = active_timing_engine.emit(
                AttackResolvedEvent(
                    rng=rng,
                    attacker=actor,
                    target=target,
                    action=action,
                    roll=roll,
                    target_ac=target_ac,
                    actors=actors,
                    resources_spent=resources_spent,
                    timing_engine=active_timing_engine,
                    round_number=round_number,
                    turn_token=turn_token,
                )
            )
            if resolved_event.cancelled:
                continue
            roll = resolved_event.roll
            event = resolved_event.outcome
            if roll.hit and action.damage:
                empowered_rerolls = 0
                if is_spell_action and _has_tag(action, "metamagic:empowered"):
                    empowered_rerolls = max(1, actor.cha_mod)
                elif (
                    is_spell_action
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

                if damage_expr and "agonizing_blast" in action.tags:
                    cha_bonus = int(actor.cha_mod)
                    if cha_bonus != 0:
                        damage_expr += f"{cha_bonus:+d}"

                # Sneak Attack Logic
                sneak_attack_available = getattr(actor, "sneak_attack_used_this_turn", False) is False
                if turn_token is not None:
                    current_turn_token = str(turn_token)
                    sneak_attack_available = (
                        getattr(actor, "sneak_attack_turn_token", None) != current_turn_token
                    )
                    if sneak_attack_available:
                        actor.sneak_attack_used_this_turn = False
                if (
                    _has_trait(actor, "sneak attack")
                    and sneak_attack_available
                    and not getattr(actor, "is_heavy", False)
                    and "spell" not in action.tags
                ):
                    is_sneak_weapon = (
                        is_ranged
                        or is_finesse
                        or getattr(action, "is_finesse", False)
                        or "finesse" in action.tags
                    )
                    if not is_sneak_weapon and not has_canonical_weapon_data:
                        is_sneak_weapon = any(w in weapon_name for w in _FINESSE_WEAPON_HINTS)
                    if is_sneak_weapon:
                        has_sneak = False
                        if effective_advantage:
                            has_sneak = True
                        elif not effective_disadvantage:
                            # ally within 5ft
                            for cand in actors.values():
                                if (
                                    cand.team == actor.team
                                    and cand.actor_id != actor.actor_id
                                    and cand.hp > 0
                                    and not cand.dead
                                    and not actor_is_incapacitated(cand)
                                ):
                                    if distance_chebyshev(cand.position, target.position) <= 5:
                                        has_sneak = True
                                        break
                        if has_sneak:
                            actor.sneak_attack_used_this_turn = True
                            if turn_token is not None:
                                actor.sneak_attack_turn_token = str(turn_token)
                            sa_dice = (actor.level + 1) // 2
                            sneak_damage_expr = f"{sa_dice}d6"

                if power_attack_active and damage_expr:
                    damage_expr += f"{damage_bonus:+d}"
                attack_is_magical = _is_magical_action(action)
                damage_bundle = DamageBundle()
                base_damage = _roll_damage_with_channel_divinity_hooks(
                    rng=rng,
                    actor=actor,
                    expr=damage_expr,
                    damage_type=action.damage_type,
                    resources_spent=resources_spent,
                    crit=roll.crit,
                    empowered_rerolls=empowered_rerolls,
                )
                _append_damage_packet(
                    bundle=damage_bundle,
                    amount=base_damage,
                    damage_type=action.damage_type,
                    packet_source="attack",
                    is_magical=attack_is_magical,
                    crit_expanded=_damage_expr_was_crit_expanded(damage_expr, crit=roll.crit),
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
                        brutal_roll = roll_damage(
                            rng,
                            brutal_expr,
                            crit=False,
                            source=actor,
                            damage_type=action.damage_type,
                        )
                        _append_damage_packet(
                            bundle=damage_bundle,
                            amount=brutal_roll,
                            damage_type=action.damage_type,
                            packet_source="brutal_critical",
                            is_magical=attack_is_magical,
                            crit_expanded=False,
                        )
                if sneak_damage_expr:
                    sneak_roll = roll_damage(
                        rng,
                        sneak_damage_expr,
                        crit=roll.crit,
                        source=actor,
                        damage_type=action.damage_type,
                    )
                    _append_damage_packet(
                        bundle=damage_bundle,
                        amount=sneak_roll,
                        damage_type=action.damage_type,
                        packet_source="sneak_attack",
                        is_magical=attack_is_magical,
                        crit_expanded=_damage_expr_was_crit_expanded(
                            sneak_damage_expr, crit=roll.crit
                        ),
                    )

                if _has_trait(actor, "improved divine smite") and not is_ranged:
                    damage_bundle.add_packet(
                        roll_damage_packet(
                            rng,
                            "1d8",
                            damage_type="radiant",
                            packet_source="improved_divine_smite",
                            crit=roll.crit,
                            source=actor,
                            is_magical=True,
                        )
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
                        smite_expr = f"{smite_dice}d8"
                        raw_smite = roll_damage(
                            rng,
                            smite_expr,
                            crit=roll.crit,
                            source=actor,
                            damage_type="radiant",
                        )
                        _append_damage_packet(
                            bundle=damage_bundle,
                            amount=raw_smite,
                            damage_type="radiant",
                            packet_source="divine_smite",
                            is_magical=True,
                            crit_expanded=_damage_expr_was_crit_expanded(
                                smite_expr, crit=roll.crit
                            ),
                        )
                        if _has_trait(actor, "smite of protection"):
                            _apply_condition(actor, "smite_of_protection_window", duration_rounds=1)
                if actor.pending_smite and not is_ranged and target.hp > 0:
                    pending_bundle = _apply_pending_smite_on_hit(
                        rng=rng,
                        actor=actor,
                        target=target,
                        roll_crit=roll.crit,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        actors=actors,
                        active_hazards=active_hazards,
                    )
                    for packet in pending_bundle.packets:
                        damage_bundle.add_packet(packet)
                raw_damage = damage_bundle.raw_total
                was_active_before_damage = target.hp > 0 and not target.dead
                damage_roll_event = active_timing_engine.emit(
                    DamageRollEvent(
                        rng=rng,
                        attacker=actor,
                        target=target,
                        action=action,
                        roll=roll,
                        raw_damage=raw_damage,
                        actors=actors,
                        resources_spent=resources_spent,
                        target_can_see_attacker=target_can_see,
                        bundle=damage_bundle,
                        timing_engine=active_timing_engine,
                        round_number=round_number,
                        turn_token=turn_token,
                    )
                )
                if damage_roll_event.cancelled:
                    continue
                damage_bundle = damage_roll_event.bundle or damage_bundle
                raw_damage = max(0, int(damage_roll_event.raw_damage))
                bundle_total = damage_bundle.raw_total
                if raw_damage < bundle_total:
                    damage_bundle.rebalance_total(raw_damage)
                elif raw_damage > bundle_total:
                    if bundle_total > 0:
                        damage_bundle.rebalance_total(raw_damage)
                    else:
                        _append_damage_packet(
                            bundle=damage_bundle,
                            amount=raw_damage - bundle_total,
                            damage_type=action.damage_type,
                            packet_source="event_adjustment",
                            is_magical=attack_is_magical,
                            crit_expanded=False,
                        )
                raw_damage = damage_bundle.raw_total
                resolution = apply_damage_bundle(
                    target,
                    damage_bundle,
                    is_critical=roll.crit,
                    source=actor,
                )
                applied = resolution.applied_total
                active_timing_engine.emit(
                    DamageResolvedEvent(
                        attacker=actor,
                        target=target,
                        action=action,
                        roll=roll,
                        raw_damage=raw_damage,
                        applied_damage=applied,
                        bundle=damage_bundle,
                        resolution=resolution,
                        round_number=round_number,
                        turn_token=turn_token,
                    )
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
                    target.add_manual_condition(_multiattack_defense_marker(actor.actor_id))

                # GWM Momentum Trigger (Action Economy Buff)
                if (
                    _has_trait(actor, "great weapon master")
                    and (roll.crit or target.hp <= 0)
                    and not is_ranged
                ):
                    _set_gwm_bonus_trigger(actor, turn_token=turn_token)
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
                telemetry=telemetry,
                strategy_name=strategy_name,
                once_per_action_used=once_per_action_used,
            )
            emit_event(f"on_{event}", trigger_target=target)
        return

    if action.action_type == "save":
        if action.save_dc is None or not action.save_ability:
            return
        from .spatial import check_cover

        save_key = action.save_ability.lower()
        careful_metamagic = _has_tag(action, "metamagic:careful")
        empowered_metamagic = _has_tag(action, "metamagic:empowered")
        heightened_metamagic = _has_tag(action, "metamagic:heightened")

        # Roll AoE damage once and apply per-target save outcomes.
        raw_damage = 0
        if action.damage:
            empowered_rerolls = 0
            if is_spell_action and empowered_metamagic:
                empowered_rerolls = max(1, actor.cha_mod)
            elif (
                is_spell_action
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
        can_use_careful = careful_metamagic or (
            _has_trait(actor, "careful spell") and actor.resources.get("sorcery_points", 0) >= 1
        )
        if is_spell_action and can_use_careful:
            allies = [t for t in targets if t.team == actor.team and t.hp > 0 and not t.dead]
            if allies:
                if not careful_metamagic:
                    actor.resources["sorcery_points"] -= 1
                    resources_spent[actor.actor_id]["sorcery_points"] = (
                        resources_spent[actor.actor_id].get("sorcery_points", 0) + 1
                    )
                num_careful = max(1, actor.cha_mod)
                careful_allies = set([a.actor_id for a in allies[:num_careful]])

        heightened_target_id: str | None = None
        if is_spell_action and heightened_metamagic:
            for target in targets:
                if target.team != actor.team and target.hp > 0 and not target.dead:
                    heightened_target_id = target.actor_id
                    break

        for target in targets:
            if target.dead or target.hp <= 0:
                continue
            cover_state = check_cover(actor.position, target.position, obstacles)
            if cover_state == "TOTAL" and _action_requires_line_of_effect(action):
                continue
            save_mod = int(target.save_mods.get(save_key, 0))
            if save_key == "dex":
                if not _action_ignores_dex_save_cover(action):
                    save_mod += _cover_bonus_from_state(cover_state)
                save_mod += _smite_of_protection_half_cover_bonus(target, actors)
            auto_fail_save = _auto_fails_strength_or_dex_save(target, save_key)
            if auto_fail_save:
                save_roll = 0
                success = False
            else:
                save_roll = rng.randint(1, 20)
                if (
                    save_key == "dex"
                    and _has_trait(target, "danger sense")
                    and not has_condition(target, "blinded")
                    and not has_condition(target, "deafened")
                    and not has_condition(target, "incapacitated")
                ):
                    save_roll = max(save_roll, rng.randint(1, 20))
                if (
                    "spell" in action.tags
                    and _has_trait(target, "gnomish cunning")
                    and save_key in {"int", "wis", "cha"}
                ):
                    save_roll = max(save_roll, rng.randint(1, 20))
                if save_key == "dex" and has_condition(target, "dodging"):
                    save_roll = max(save_roll, rng.randint(1, 20))
                if is_spell_action and not subtle_spell and _has_trait(target, "mage slayer"):
                    save_roll = max(save_roll, rng.randint(1, 20))
                if target.actor_id == heightened_target_id:
                    save_roll = min(save_roll, rng.randint(1, 20))
                success = (save_roll + save_mod) >= action.save_dc
            if not auto_fail_save and not success:
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
                not auto_fail_save
                and not success
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
                is_magical=_is_magical_action(action),
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
                telemetry=telemetry,
                strategy_name=strategy_name,
            )
            emit_event("on_save", trigger_target=target)
        return

    if action.action_type in {"utility", "buff"}:
        if _is_smite_setup_action(action):
            _arm_pending_smite(actor, action)
            return
        if action.name == "lay_on_hands":
            pool = int(actor.resources.get("lay_on_hands_pool", 0))
            if pool <= 0:
                return
            for target in targets:
                if target.dead:
                    continue
                missing_hp = max(0, target.max_hp - target.hp)
                if missing_hp <= 0:
                    continue
                spent = min(pool, missing_hp)
                if spent <= 0:
                    continue
                _apply_healing(target, spent)
                actor.resources["lay_on_hands_pool"] = max(0, pool - spent)
                resources_spent[actor.actor_id]["lay_on_hands_pool"] = (
                    resources_spent[actor.actor_id].get("lay_on_hands_pool", 0) + spent
                )
                pool = int(actor.resources.get("lay_on_hands_pool", 0))
                if pool <= 0:
                    break
            return
        if _has_tag(action, "conversion:points_to_slot"):
            slot_level = _slot_level_from_action(action)
            if slot_level is not None and slot_level <= 5:
                slot_key = f"spell_slot_{slot_level}"
                actor.resources[slot_key] = actor.resources.get(slot_key, 0) + 1
            return
        if _has_tag(action, "conversion:slot_to_points"):
            slot_level = _slot_level_from_action(action)
            if slot_level is not None:
                current_points = int(actor.resources.get("sorcery_points", 0))
                points_gain = slot_level
                max_points = actor.max_resources.get("sorcery_points")
                if isinstance(max_points, int) and max_points >= 0:
                    points_gain = max(0, min(points_gain, int(max_points) - current_points))
                actor.resources["sorcery_points"] = current_points + points_gain
            return
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
            if ready_declaration is not None:
                readied_action_name = ready_declaration.response_action_name
                readied_trigger = ready_declaration.trigger
            else:
                readied_action = _select_readied_action(actor)
                readied_action_name = readied_action.name if readied_action else None
                readied_trigger = action.event_trigger or "enemy_turn_start"
            readied_response = _resolve_named_action(actor, readied_action_name)
            if readied_response is None or readied_response.name == "ready":
                _clear_readied_action_state(actor, clear_held_spell=True)
                return

            _apply_condition(actor, "readying", duration_rounds=1)
            actor.readied_action_name = readied_action_name
            actor.readied_trigger = readied_trigger
            actor.readied_reaction_reserved = True
            actor.readied_spell_slot_level = None
            actor.readied_spell_held = False

            if "spell" in readied_response.tags:
                held_spell_request = SpellCastRequest()
                if not _spend_action_resource_cost(
                    actor,
                    readied_response,
                    resources_spent,
                    spell_cast_request=held_spell_request,
                ):
                    _remove_condition(actor, "readying")
                    return
                _break_concentration(actor, actors, active_hazards)
                actor.readied_spell_held = True
                actor.readied_spell_slot_level = held_spell_request.slot_level
                actor.concentrating = True
                actor.concentrated_spell = readied_response.name
                held_level = (
                    int(held_spell_request.slot_level)
                    if held_spell_request.slot_level is not None
                    else _spell_level_from_action(readied_response)
                )
                actor.concentrated_spell_level = held_level if held_level > 0 else None
                actor.concentrated_targets.clear()
                actor.concentration_conditions.clear()
                actor.concentration_effect_instance_ids.clear()
            return
        if action.name == "bardic_inspiration":
            die_sides = _bardic_inspiration_die_sides(actor)
            for target in targets:
                if target.actor_id == actor.actor_id:
                    continue
                target.resources["bardic_inspiration_die"] = die_sides
            return

        gained_rage_from_action = "raging" not in actor.conditions
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
                telemetry=telemetry,
                strategy_name=strategy_name,
            )
        if (
            gained_rage_from_action
            and "raging" in actor.conditions
            and actor.took_attack_action_this_turn
        ):
            actor.rage_sustained_since_last_turn = True


def _build_round_metadata(
    *,
    actors: dict[str, ActorRuntimeState],
    threat_scores: dict[str, int],
    burst_round_threshold: int,
    active_hazards: list[dict[str, Any]] | None = None,
    light_level: str = "bright",
    strategy_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = strategy_overrides if isinstance(strategy_overrides, dict) else {}
    raw_policy = overrides.get("strategy_policy", {})
    strategy_policy = dict(raw_policy) if isinstance(raw_policy, dict) else {}
    tactical_branches_raw = overrides.get("tactical_branches", {})
    tactical_branches = (
        dict(tactical_branches_raw) if isinstance(tactical_branches_raw, dict) else {}
    )
    objective_scores_raw = overrides.get("objective_scores", {})
    objective_scores = dict(objective_scores_raw) if isinstance(objective_scores_raw, dict) else {}
    objective_targets_raw = overrides.get("objective_targets", {})
    objective_targets = (
        dict(objective_targets_raw) if isinstance(objective_targets_raw, dict) else {}
    )

    return {
        "threat_scores": dict(threat_scores),
        "burst_round_threshold": burst_round_threshold,
        "active_hazards": list(active_hazards or []),
        "light_level": str(light_level),
        "strategy_policy": strategy_policy,
        "evaluation_mode": str(overrides.get("evaluation_mode", "greedy")),
        "lookahead_discount": float(overrides.get("lookahead_discount", 1.0)),
        "tactical_branches": tactical_branches,
        "objective_scores": objective_scores,
        "objective_targets": objective_targets,
        "available_actions": {
            actor_id: [action.name for action in actor.actions if _action_available(actor, action)]
            for actor_id, actor in actors.items()
        },
        "action_catalog": {
            actor_id: [
                {
                    "name": action.name,
                    "action_type": action.action_type,
                    "attack_profile_id": action.attack_profile_id,
                    "weapon_id": action.weapon_id,
                    "item_id": action.item_id,
                    "weapon_properties": list(action.weapon_properties),
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
                    "reach_ft": action.reach_ft,
                    "range_ft": action.range_ft,
                    "range_normal_ft": action.range_normal_ft,
                    "range_long_ft": action.range_long_ft,
                    "aoe_type": action.aoe_type,
                    "aoe_size_ft": action.aoe_size_ft,
                    "max_targets": action.max_targets,
                    "concentration": action.concentration,
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
    telemetry: list[dict[str, Any]] | None = None,
    round_number: int | None = None,
) -> None:
    lair_turn_token = f"{round_number}:global" if round_number is not None else "global"
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
            if not _action_available(actor, candidate, turn_token=lair_turn_token):
                continue
            resolved = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=candidate,
                actors=actors,
                requested=[],
                obstacles=obstacles,
            )
            if resolved:
                action = candidate
                targets = resolved
                break
        if action is None or not targets:
            continue
        spell_cast_request = SpellCastRequest() if "spell" in action.tags else None
        if not _spend_action_resource_cost(
            actor,
            action,
            resources_spent,
            spell_cast_request=spell_cast_request,
        ):
            continue
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
            telemetry=telemetry,
            round_number=round_number,
            turn_token=lair_turn_token,
            strategy_name="lair_action",
            spell_cast_request=spell_cast_request,
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
    telemetry: list[dict[str, Any]] | None = None,
    round_number: int | None = None,
    turn_token: str | None = None,
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
            if not _action_available(actor, candidate, turn_token=turn_token):
                continue
            resolved = _resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=candidate,
                actors=actors,
                requested=[],
                obstacles=obstacles,
            )
            if resolved:
                action = candidate
                targets = resolved
                break
        if action is None or not targets:
            continue
        spell_cast_request = SpellCastRequest() if "spell" in action.tags else None
        if not _spend_action_resource_cost(
            actor,
            action,
            resources_spent,
            spell_cast_request=spell_cast_request,
        ):
            continue
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
            telemetry=telemetry,
            round_number=round_number,
            turn_token=turn_token,
            strategy_name="legendary_action",
            spell_cast_request=spell_cast_request,
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
        "telemetry": json.dumps(trial.telemetry, sort_keys=True),
        "encounter_outcomes": json.dumps(trial.encounter_outcomes, sort_keys=True),
        "state_snapshots": json.dumps(trial.state_snapshots, sort_keys=True),
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
    exploration = (
        scenario.config.exploration if isinstance(scenario.config.exploration, dict) else {}
    )
    exploration_legs = (
        exploration.get("legs") if isinstance(exploration.get("legs"), list) else None
    )
    light_level = str(battlefield.get("light_level", "bright")).lower()
    battlefield_obstacles = _build_battlefield_obstacles(battlefield.get("obstacles", []))

    encounter_plan = list(scenario.config.encounters)
    if not encounter_plan:
        encounter_plan = [EncounterConfig(enemies=list(scenario.config.enemies))]

    termination_rules = (
        scenario.config.termination_rules
        if isinstance(scenario.config.termination_rules, dict)
        else {}
    )
    party_defeat_rule = termination_rules.get("party_defeat", "all_unconscious_or_dead")
    enemy_defeat_rule = termination_rules.get("enemy_defeat", "all_dead")
    max_rounds = int(termination_rules.get("max_rounds", 20))
    max_encounter_steps = int(
        termination_rules.get("max_encounter_steps", max(1, len(encounter_plan) * 3))
    )
    if max_rounds <= 0:
        raise ValueError("termination_rules.max_rounds must be >= 1")
    if max_encounter_steps <= 0:
        raise ValueError("termination_rules.max_encounter_steps must be >= 1")

    short_rest_healing = int(scenario.config.resource_policy.get("short_rest_healing", 0))

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
        trial_telemetry: list[dict[str, Any]] = []
        encounter_outcomes: list[dict[str, Any]] = []
        state_snapshots: list[dict[str, Any]] = []

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

            for companion in _build_construct_companions(actor):
                if companion.actor_id in actors:
                    continue
                actors[companion.actor_id] = companion
                damage_taken[companion.actor_id] = 0
                damage_dealt[companion.actor_id] = 0
                resources_spent[companion.actor_id] = {}
                threat_scores[companion.actor_id] = 0
                downed_counts[companion.actor_id] = 0
                death_counts[companion.actor_id] = 0

        total_rounds = 0
        overall_winner = "draw"
        encounter_idx: int | None = 0
        encounter_step = 0

        while encounter_idx is not None and encounter_idx < len(encounter_plan):
            if encounter_step >= max_encounter_steps:
                raise ValueError(
                    "Encounter branching exceeded termination_rules.max_encounter_steps"
                )

            step_index = encounter_step
            encounter_step += 1
            encounter = encounter_plan[encounter_idx]
            encounter_enemy_ids = list(encounter.enemies)

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
                    f"{enemy_id}_e{step_index}_{count}"
                    if (count > 1 or len(encounter_plan) > 1)
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

            if trial_idx == 0 and step_index == 0:
                tracked_resource_names = {
                    actor_id: set(actor.resources.keys()) for actor_id, actor in actors.items()
                }

            initiative_order, initiative_scores = _build_initiative_order_with_scores(
                rng, actors, scenario.config.initiative_mode
            )
            initiative_order = _reorder_initiative_for_construct_companions(
                initiative_order, actors
            )
            rounds = 0

            while rounds < max_rounds:
                rounds += 1
                for actor in actors.values():
                    actor.lair_action_used_this_round = False
                    if hasattr(actor, "commanded_this_round"):
                        actor.commanded_this_round = False

                metadata = _build_round_metadata(
                    actors=actors,
                    threat_scores=threat_scores,
                    burst_round_threshold=int(
                        scenario.config.resource_policy.get("burst_round_threshold", 3)
                    ),
                    active_hazards=active_hazards,
                    light_level=light_level,
                    strategy_overrides=assumption_overrides,
                )
                state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                for strategy in strategy_registry.values():
                    strategy.on_round_start(state_view)

                initiative_order = _sync_initiative_order(initiative_order, actors)
                lair_actions_resolved = False

                def _resolve_turn_end(actor: ActorRuntimeState, turn_token: str) -> None:
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
                        telemetry=trial_telemetry,
                        round_number=rounds,
                        turn_token=turn_token,
                    )

                for actor_id in initiative_order:
                    if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                        actors, enemy_defeat_rule
                    ):
                        break

                    if not lair_actions_resolved:
                        actor_initiative = initiative_scores.get(actor_id)
                        if actor_initiative is None:
                            actor_state = actors.get(actor_id)
                            actor_initiative = (
                                actor_state.initiative_mod if actor_state is not None else -999
                            )
                        if actor_initiative < 20:
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
                                telemetry=trial_telemetry,
                                round_number=rounds,
                            )
                            lair_actions_resolved = True
                            if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                                actors, enemy_defeat_rule
                            ):
                                break

                    if actor_id not in actors:
                        continue
                    actor = actors[actor_id]
                    _refresh_legendary_actions_for_turn(actor)
                    actor.movement_remaining = float(actor.speed_ft)
                    actor.took_attack_action_this_turn = False
                    actor.bonus_action_spell_restriction_active = False
                    actor.non_action_cantrip_spell_cast_this_turn = False
                    _roll_recharge_for_actor(rng, actor)
                    _tick_conditions_for_actor(rng, actor)
                    _tick_hazards_for_actor_turn(
                        active_hazards=active_hazards,
                        actor=actor,
                        actors=actors,
                        boundary="turn_start",
                    )
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
                    actor.gwm_bonus_trigger_available = False

                    if actor.dead:
                        continue

                    if actor.hp <= 0:
                        resolve_death_save(rng, actor)
                        _resolve_turn_end(actor, f"{rounds}:{actor.actor_id}")
                        continue

                    _process_hazard_start_turn_triggers(
                        rng=rng,
                        actor=actor,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                    )
                    if actor.dead or actor.hp <= 0:
                        continue

                    if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                        actors, enemy_defeat_rule
                    ):
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
                        round_number=rounds,
                        turn_token=turn_token,
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
                        _resolve_turn_end(actor, turn_token)
                        continue
                    if _party_defeated(actors) or _enemies_defeated(actors):
                        break
                    if not _can_act(actor):
                        _resolve_turn_end(actor, turn_token)
                        continue

                    companion_owner_id = getattr(actor, "companion_owner_id", None)
                    owner = actors.get(companion_owner_id) if companion_owner_id else None
                    should_force_dodge = (
                        bool(getattr(actor, "requires_command", False))
                        and not bool(getattr(actor, "commanded_this_round", False))
                        and not _owner_is_incapacitated(owner)
                    )
                    if should_force_dodge:
                        action = _resolve_action_selection(actor, "dodge")
                        if _action_available(actor, action, turn_token=turn_token):
                            resolved_targets = _resolve_targets_for_action(
                                rng=rng,
                                actor=actor,
                                action=action,
                                actors=actors,
                                requested=[],
                                obstacles=battlefield_obstacles,
                            )
                            if resolved_targets:
                                actor.per_action_uses[action.name] = (
                                    actor.per_action_uses.get(action.name, 0) + 1
                                )
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
                                    telemetry=trial_telemetry,
                                    strategy_name="forced_dodge",
                                )
                        if hasattr(actor, "commanded_this_round"):
                            actor.commanded_this_round = False
                        _resolve_turn_end(actor, turn_token)
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
                        strategy_overrides=assumption_overrides,
                    )
                    state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                    actor_view = state_view.actors[actor.actor_id]
                    declare_turn = getattr(strategy, "declare_turn", None)
                    turn_declaration = (
                        declare_turn(actor_view, state_view) if callable(declare_turn) else None
                    )
                    if turn_declaration is not None:
                        if not isinstance(turn_declaration, TurnDeclaration):
                            _raise_turn_declaration_error(
                                actor=actor,
                                code="invalid_turn_declaration_type",
                                field="turn_declaration",
                                message="declare_turn(...) must return TurnDeclaration or None.",
                                details={"actual_type": type(turn_declaration).__name__},
                            )
                        _execute_declared_turn_or_error(
                            rng=rng,
                            actor=actor,
                            declaration=turn_declaration,
                            strategy_name=strategy_name,
                            actors=actors,
                            damage_dealt=damage_dealt,
                            damage_taken=damage_taken,
                            threat_scores=threat_scores,
                            resources_spent=resources_spent,
                            active_hazards=active_hazards,
                            telemetry=trial_telemetry,
                            obstacles=battlefield_obstacles,
                            light_level=light_level,
                            round_number=rounds,
                            turn_token=turn_token,
                            rule_trace=trial_rule_trace,
                        )
                        _resolve_turn_end(actor, turn_token)
                        continue
                    intent = strategy.choose_action(actor_view, state_view)
                    action = _resolve_action_selection(actor, intent.action_name)
                    fallback_reason: str | None = None

                    if not _action_available(actor, action, turn_token=turn_token):
                        fallback = _fallback_action(actor)
                        if fallback is None:
                            _resolve_turn_end(actor, turn_token)
                            continue
                        action = fallback
                        fallback_reason = "intent_unavailable"

                    extra_spend = strategy.decide_resource_spend(
                        actor_view, intent, state_view
                    ).amounts
                    base_cost = dict(action.resource_cost)
                    extra_cost: dict[str, int] = {}
                    for key, amount in extra_spend.items():
                        if int(amount) <= 0:
                            continue
                        extra_cost[key] = extra_cost.get(key, 0) + int(amount)
                    cost = dict(base_cost)
                    for key, amount in extra_cost.items():
                        cost[key] = cost.get(key, 0) + amount

                    non_slot_base_cost, _slot_amount, _slot_levels = _split_spell_slot_cost(
                        base_cost
                    )
                    can_pay_extra = True
                    for key, amount in extra_cost.items():
                        required = amount + int(non_slot_base_cost.get(key, 0))
                        if int(actor.resources.get(key, 0)) < required:
                            can_pay_extra = False
                            break

                    if not _can_pay_resource_cost(actor, action) or not can_pay_extra:
                        action = _resolve_action_selection(actor, "basic")
                        cost = dict(action.resource_cost)
                        extra_cost = {}
                        fallback_reason = "insufficient_resources"

                    targets = strategy.choose_targets(actor_view, intent, state_view)
                    resolved_targets = _resolve_targets_for_action(
                        rng=rng,
                        actor=actor,
                        action=action,
                        actors=actors,
                        requested=targets,
                        obstacles=battlefield_obstacles,
                    )
                    trial_telemetry.append(
                        {
                            "telemetry_type": "decision",
                            "round": rounds,
                            "strategy": strategy_name,
                            "actor_id": actor.actor_id,
                            "team": actor.team,
                            "intent_action": intent.action_name,
                            "resolved_action": action.name,
                            "fallback_reason": fallback_reason,
                            "requested_targets": [target.actor_id for target in targets],
                            "resolved_targets": [target.actor_id for target in resolved_targets],
                            "rationale": (
                                dict(intent.rationale)
                                if isinstance(getattr(intent, "rationale", {}), dict)
                                else {}
                            ),
                            "extra_resource_request": dict(extra_spend),
                            "resource_cost": dict(cost),
                        }
                    )
                    if not resolved_targets:
                        _resolve_turn_end(actor, turn_token)
                        continue

                    spell_cast_request = SpellCastRequest() if "spell" in action.tags else None
                    if not _spend_action_resource_cost(
                        actor,
                        action,
                        resources_spent,
                        spell_cast_request=spell_cast_request,
                    ):
                        _resolve_turn_end(actor, turn_token)
                        continue
                    if extra_cost:
                        spent_extra = _spend_resources(actor, extra_cost)
                        for key, amount in spent_extra.items():
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
                        telemetry=trial_telemetry,
                        strategy_name=strategy_name,
                        spell_cast_request=spell_cast_request,
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
                                obstacles=battlefield_obstacles,
                            )
                            if bonus_targets:
                                bonus_spell_cast_request = (
                                    SpellCastRequest() if "spell" in bonus_action.tags else None
                                )
                                if _can_pay_resource_cost(
                                    actor, bonus_action
                                ) and _spend_action_resource_cost(
                                    actor,
                                    bonus_action,
                                    resources_spent,
                                    spell_cast_request=bonus_spell_cast_request,
                                ):
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
                                        telemetry=trial_telemetry,
                                        strategy_name=strategy_name,
                                        spell_cast_request=bonus_spell_cast_request,
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
                                    obstacles=battlefield_obstacles,
                                )
                                if surge_targets:
                                    surge_spell_cast_request = (
                                        SpellCastRequest() if "spell" in surge_action.tags else None
                                    )
                                    if _can_pay_resource_cost(
                                        actor, surge_action
                                    ) and _spend_action_resource_cost(
                                        actor,
                                        surge_action,
                                        resources_spent,
                                        spell_cast_request=surge_spell_cast_request,
                                    ):

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
                                            telemetry=trial_telemetry,
                                            strategy_name=strategy_name,
                                            spell_cast_request=surge_spell_cast_request,
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

                    _resolve_turn_end(actor, turn_token)

                if (
                    not lair_actions_resolved
                    and not _party_defeated(actors, party_defeat_rule)
                    and not _enemies_defeated(actors, enemy_defeat_rule)
                ):
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
                        telemetry=trial_telemetry,
                        round_number=rounds,
                    )

                if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                    actors, enemy_defeat_rule
                ):
                    break

            total_rounds += rounds

            party_is_defeated = _party_defeated(actors, party_defeat_rule)
            enemies_are_defeated = _enemies_defeated(actors, enemy_defeat_rule)
            if party_is_defeated:
                encounter_winner = "enemy"
                encounter_outcome = "party_defeat"
            elif enemies_are_defeated:
                encounter_winner = "party"
                encounter_outcome = "enemy_defeat"
            else:
                party_hp = sum(a.hp for a in actors.values() if a.team == "party" and not a.dead)
                enemy_hp = sum(a.hp for a in actors.values() if a.team != "party" and not a.dead)
                encounter_winner = "party" if party_hp >= enemy_hp else "enemy"
                encounter_outcome = encounter_winner

            next_encounter_idx, branch_key = _resolve_next_encounter_index(
                encounter=encounter,
                encounter_outcome=encounter_outcome,
                encounter_winner=encounter_winner,
                default_next=encounter_idx + 1,
                encounter_count=len(encounter_plan),
            )

            continue_campaign = next_encounter_idx is not None
            if party_is_defeated:
                overall_winner = "enemy"
                continue_campaign = False
                next_encounter_idx = None
            elif encounter_winner == "enemy" and branch_key is None:
                overall_winner = "enemy"
                continue_campaign = False
                next_encounter_idx = None

            if continue_campaign and encounter.short_rest_after:
                for actor in actors.values():
                    if actor.team == "party":
                        short_rest(actor, healing=short_rest_healing)

            checkpoint_id = encounter.checkpoint or f"encounter_{step_index}_end"
            party_snapshot = {
                actor_id: _actor_state_snapshot(actor)
                for actor_id, actor in sorted(actors.items())
                if actor.team == "party"
            }
            enemy_snapshot = {
                actor_id: _actor_state_snapshot(actor)
                for actor_id, actor in sorted(actors.items())
                if actor.team != "party"
            }
            state_snapshots.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "encounter_index": encounter_idx,
                    "encounter_step": step_index,
                    "outcome": encounter_outcome,
                    "winner": encounter_winner,
                    "next_encounter_index": next_encounter_idx,
                    "party": party_snapshot,
                    "enemies": enemy_snapshot,
                }
            )
            encounter_outcomes.append(
                {
                    "encounter_index": encounter_idx,
                    "encounter_step": step_index,
                    "outcome": encounter_outcome,
                    "winner": encounter_winner,
                    "branch_key": branch_key,
                    "next_encounter_index": next_encounter_idx,
                }
            )

            if not continue_campaign:
                if overall_winner == "draw":
                    overall_winner = encounter_winner
                break

            encounter_idx = next_encounter_idx

        if overall_winner == "draw":
            if _party_defeated(actors, party_defeat_rule):
                overall_winner = "enemy"
            elif _enemies_defeated(actors, enemy_defeat_rule):
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
            telemetry=trial_telemetry,
            encounter_outcomes=encounter_outcomes,
            state_snapshots=state_snapshots,
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
