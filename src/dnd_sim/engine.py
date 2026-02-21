from __future__ import annotations

import json
import random
import re
import statistics
from dataclasses import dataclass
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
_DISADVANTAGE_CONDITIONS = {"poisoned", "frightened", "restrained", "blinded", "prone"}
_ATTACKER_ADVANTAGE_CONDITIONS = {
    "blinded",
    "paralyzed",
    "stunned",
    "unconscious",
    "prone",
    "restrained",
}
_AUTO_CRIT_CONDITIONS = {"paralyzed", "stunned", "unconscious"}
_IMPLIED_CONDITION_MAP: dict[str, set[str]] = {
    "stunned": {"incapacitated"},
    "unconscious": {"incapacitated"},
    "paralyzed": {"incapacitated"},
}
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")


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


def _has_trait(actor: ActorRuntimeState, trait_name: str) -> bool:
    needle = _normalize_trait_name(trait_name)
    return any(_normalize_trait_name(key) == needle for key in actor.traits.keys())


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
                    "trigger": "always",
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
            max_targets=max_targets,
            concentration=bool(spell.get("concentration", False)),
            effects=effects,
            mechanics=mechanics,
            tags=tags,
        )
        actions.append(action)

    return actions


def _build_character_actions(character: dict[str, Any]) -> list[ActionDefinition]:
    attacks = character.get("attacks", [])
    resources = character.get("resources", {})
    traits = {_normalize_trait_name(trait) for trait in character.get("traits", [])}

    def has_trait(name: str) -> bool:
        return _normalize_trait_name(name) in traits

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
        if has_trait("martial arts") and "ki" in resources:
            actions.append(
                ActionDefinition(
                    name="martial_arts_bonus",
                    action_type="attack",
                    to_hit=int(best_attack.get("to_hit", 0)),
                    damage=str(best_attack.get("damage", "1")),
                    damage_type=str(best_attack.get("damage_type", "bludgeoning")),
                    attack_count=1,
                    resource_cost={"ki": 1},
                    action_cost="bonus",
                    tags=["bonus", "martial_arts"],
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
        # --- Spell actions ---
        character_level = _parse_character_level(character.get("class_level", "1"))
        actions.extend(_build_spell_actions(character, character_level=character_level))

        return actions

    # Fallback: no attacks defined
    character_level = _parse_character_level(character.get("class_level", "1"))
    spell_actions = _build_spell_actions(character, character_level=character_level)
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
    return base + spell_actions


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
    return result


def _apply_passive_traits(actor: ActorRuntimeState) -> None:
    for trait_data in actor.traits.values():
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


def _build_actor_from_character(
    character: dict[str, Any], traits_db: dict[str, dict[str, Any]] = None
) -> ActorRuntimeState:
    traits_db = traits_db or {}
    ability_scores = character.get("ability_scores", {})
    dex_mod = (int(ability_scores.get("dex", 10)) - 10) // 2
    con_mod = (int(ability_scores.get("con", 10)) - 10) // 2
    initiative_mod = character.get("initiative_mod", None)
    if initiative_mod is None:
        initiative_mod = dex_mod
    ability_mods = {k: (int(ability_scores.get(k, 10)) - 10) // 2 for k in ABILITY_KEYS}
    explicit_saves = {k: int(v) for k, v in character.get("save_mods", {}).items()}
    save_mods = {k: explicit_saves.get(k, ability_mods.get(k, 0)) for k in ABILITY_KEYS}
    actor = ActorRuntimeState(
        actor_id=character["character_id"],
        team="party",
        name=character["name"],
        max_hp=int(character.get("max_hp", 1)),
        hp=int(character.get("max_hp", 1)),
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
        traits={
            _normalize_trait_name(trait): traits_db.get(
                _normalize_trait_name(trait), traits_db.get(str(trait).lower(), {})
            )
            for trait in character.get("traits", [])
        },
        level=_parse_character_level(character.get("class_level", "1")),
    )
    _apply_passive_traits(actor)
    return actor


def _build_actor_from_enemy(
    enemy: EnemyConfig, traits_db: dict[str, dict[str, Any]] = None
) -> ActorRuntimeState:
    traits_db = traits_db or {}
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
        if explicit is not None:
            return int(explicit)
        return int(enemy.stat_block.save_mods.get(key, 0))

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
            _normalize_trait_name(trait): traits_db.get(
                _normalize_trait_name(trait), traits_db.get(str(trait).lower(), {})
            )
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
        if res_key in short_rest_resources or "warlock_spell_slot" in res_key:
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
    actor.concentrated_spell = None
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


def _action_can_target_downed_allies(action: ActionDefinition) -> bool:
    if action.action_type == "utility":
        return True
    for effect in action.effects:
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
    by_id = {target.actor_id: target for target in candidates}

    if mode in {"all_enemies", "all_allies", "all_creatures"}:
        return sorted(
            candidates,
            key=lambda value: _target_sort_key(actor, value, mode=mode),
        )

    if mode in {"random_enemy", "random_ally"}:
        valid_requested = [ref.actor_id for ref in requested if ref.actor_id in by_id]
        if valid_requested:
            return [by_id[valid_requested[0]]]
        return [rng.choice(candidates)]

    if mode == "self":
        return [actor]

    max_targets = 1
    if mode in {"n_enemies", "n_allies"}:
        max_targets = action.max_targets or 1

    selected: list[ActorRuntimeState] = []
    seen: set[str] = set()
    for ref in requested:
        target = by_id.get(ref.actor_id)
        if target is None or target.actor_id in seen:
            continue
        selected.append(target)
        seen.add(target.actor_id)
        if len(selected) >= max_targets:
            return selected

    for target in sorted(candidates, key=lambda value: _target_sort_key(actor, value, mode=mode)):
        if target.actor_id in seen:
            continue
        selected.append(target)
        seen.add(target.actor_id)
        if len(selected) >= max_targets:
            break

    if action.aoe_type and action.aoe_size_ft:
        radius = float(action.aoe_size_ft)
        aoe_victims = set()
        for primary in selected:
            for cand in actors.values():
                if cand.hp > 0 or include_downed_allies:
                    if distance_chebyshev(primary.position, cand.position) <= radius:
                        aoe_victims.add(cand.actor_id)
        if not action.include_self and actor.actor_id in aoe_victims:
            aoe_victims.remove(actor.actor_id)
        return [actors[aid] for aid in aoe_victims]

    return selected


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
    for implied in _IMPLIED_CONDITION_MAP.get(key, set()):
        actor.conditions.discard(implied)
        actor.condition_durations.pop(implied, None)


def _break_concentration(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    if not actor.concentrating:
        return
    actor.concentrating = False
    for target_id in list(actor.concentrated_targets):
        if target_id in actors and actor.concentrated_spell:
            _remove_condition(actors[target_id], actor.concentrated_spell)
    actor.concentrated_targets.clear()

    if actor.concentrated_spell:
        active_hazards[:] = [h for h in active_hazards if h.get("source_id") != actor.actor_id]

    actor.concentrated_spell = None


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
) -> None:
    recipient = _resolve_effect_target(effect, actor=actor, target=target)
    effect_type = str(effect.get("effect_type"))

    if effect_type == "damage":
        is_magical = False
        if action and getattr(action, "tags", None):
            is_magical = "spell" in action.tags or "magical" in action.tags
        damage_type = str(effect.get("damage_type", "bludgeoning"))
        raw_damage = roll_damage(
            rng, str(effect.get("damage", "0")), crit=False, source=actor, damage_type=damage_type
        )
        applied = apply_damage(
            recipient, raw_damage, damage_type, is_magical=is_magical, source=actor
        )
        if not run_concentration_check(rng, recipient, applied, source=actor):
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
            save_total = rng.randint(1, 20) + int(recipient.save_mods.get(save_key, 0))
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
        return

    if effect_type == "remove_condition":
        _remove_condition(recipient, str(effect.get("condition", "")))
        return

    if effect_type == "hazard":
        duration = int(effect.get("duration", 10))
        hazard_type = str(effect.get("hazard_type", "generic"))
        active_hazards.append(
            {
                "type": hazard_type,
                "source_id": actor.actor_id,
                "target_id": recipient.actor_id,
                "hazard_type": hazard_type,
                "duration": duration,
            }
        )
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

    # forced_movement and note are schema-valid but non-positional in v1.
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
) -> None:
    for effect in action.effects + action.mechanics:
        if _effect_matches_event(effect, event):
            recipient = _resolve_effect_target(effect, actor=actor, target=target)
            if action.concentration and effect.get("effect_type") in ("condition", "hazard"):
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


def _can_pay_resource_cost(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    return _has_resources(actor, action.resource_cost)


def _action_available(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    if action.max_uses is not None and actor.per_action_uses.get(action.name, 0) >= action.max_uses:
        return False
    if action.recharge and not actor.recharge_ready.get(action.name, True):
        return False
    if not _can_pay_resource_cost(actor, action):
        return False
    if action.action_cost == "bonus" and not actor.bonus_available:
        return False
    if action.action_cost == "reaction" and not actor.reaction_available:
        return False
    if action.action_cost == "legendary" and actor.legendary_actions_remaining <= 0:
        return False
    if action.action_cost == "lair" and actor.lair_action_used_this_round:
        return False
    return True


def _mark_action_cost_used(actor: ActorRuntimeState, action: ActionDefinition) -> None:
    if action.action_cost == "bonus":
        actor.bonus_available = False
    elif action.action_cost == "reaction":
        actor.reaction_available = False
    elif action.action_cost == "legendary":
        actor.legendary_actions_remaining = max(0, actor.legendary_actions_remaining - 1)
    elif action.action_cost == "lair":
        actor.lair_action_used_this_round = True


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


def _try_shield_reaction(
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
    roll: AttackRollResult,
) -> bool:
    """Always-use Shield reaction: +5 AC to negate a hit. Consumes reaction + spell slot.

    Returns True if the hit was negated.
    """
    if not target.reaction_available:
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
) -> None:
    if not targets:
        return

    # Counterspell check
    if "spell" in action.tags:
        for enemy in actors.values():
            if (
                enemy.team != actor.team
                and enemy.hp > 0
                and not enemy.dead
                and enemy.reaction_available
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
                    from .spatial import distance_chebyshev

                    if distance_chebyshev(enemy.position, actor.position) <= 60:
                        slot_key = None
                        for key in sorted(enemy.resources.keys()):
                            if key.startswith("spell_slot_") and enemy.resources.get(key, 0) > 0:
                                if int(key.split("_")[-1]) >= 3:
                                    slot_key = key
                                    break
                        if slot_key:
                            enemy.resources[slot_key] -= 1
                            enemy.reaction_available = False
                            return  # Spell countered!

        if action.concentration:
            _break_concentration(actor, actors, active_hazards)
            actor.concentrating = True
            actor.concentrated_spell = action.name

        # Mage Slayer reaction attack
        for enemy in list(actors.values()):
            if (
                enemy.team != actor.team
                and enemy.hp > 0
                and not enemy.dead
                and enemy.reaction_available
                and _has_trait(enemy, "mage slayer")
            ):
                enemy_attack = _fallback_action(enemy)
                if enemy_attack and enemy_attack.action_type == "attack":
                    enemy.reaction_available = False
                    _execute_action(
                        rng=rng,
                        actor=enemy,
                        action=enemy_attack,
                        targets=[actor],
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                    )

    # Phase 11: Contested Grapple/Shove Checks
    if action.action_type in ("grapple", "shove") and targets:
        from .rules_2014 import run_contested_check

        target = targets[0]

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
        # Sentinel reaction attack
        for ally in list(actors.values()):
            if (
                targets
                and ally.team == targets[0].team
                and ally.actor_id != targets[0].actor_id
                and ally.hp > 0
                and not ally.dead
                and ally.reaction_available
                and _has_trait(ally, "sentinel")
                and not _has_trait(targets[0], "sentinel")
            ):
                ally_attack = _fallback_action(ally)
                if ally_attack and ally_attack.action_type == "attack":
                    ally.reaction_available = False
                    actor.movement_remaining = 0.0  # Sentinel movement lock abstract equivalent
                    _execute_action(
                        rng=rng,
                        actor=ally,
                        action=ally_attack,
                        targets=[actor],
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                    )
        if action.action_cost == "action":
            actor.took_attack_action_this_turn = True

        if action.to_hit is None:
            return
        # Build preferred target queue for multiattack redirect
        preferred_ids = [t.actor_id for t in targets]
        current_target: ActorRuntimeState | None = None
        for _ in range(max(1, action.attack_count)):
            # Find a living target: try current, then preferred list, then any enemy
            if current_target is None or current_target.dead or current_target.hp <= 0:
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
            advantage, disadvantage = _consume_attack_flags(actor)
            # Target condition-based advantage/auto-crit
            target_conditions = target.conditions
            if target_conditions.intersection(_ATTACKER_ADVANTAGE_CONDITIONS):
                advantage = True
            if "dodging" in target_conditions:
                disadvantage = True
            force_crit = bool(target_conditions.intersection(_AUTO_CRIT_CONDITIONS))

            # Phase 12: Illumination & Vision Mechanics
            from .spatial import can_see

            # Attacker's vision of the target
            attacker_can_see = can_see(
                observer_pos=actor.position,
                target_pos=target.position,
                observer_traits=actor.traits,
                target_conditions=target.conditions,
                active_hazards=active_hazards,
            )
            # Target's vision of the attacker
            target_can_see = can_see(
                observer_pos=target.position,
                target_pos=actor.position,
                observer_traits=target.traits,
                target_conditions=actor.conditions,
                active_hazards=active_hazards,
            )

            # Apply RAW Unseen Attacker / Unseen Target rules
            if not attacker_can_see:
                disadvantage = True
            if not target_can_see:
                advantage = True

            # Sharpshooter / Great Weapon Master AI Toggle (-5 to hit / +10 damage)
            power_attack_active = False
            target_ac = target.ac
            to_hit_penalty = 0
            damage_bonus = 0

            if action.to_hit is not None:
                weapon_name = action.name.lower()
                is_ranged = any(
                    w in weapon_name for w in ["bow", "dart", "sling", "javelin", "blowgun", "net"]
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
                if is_ranged:
                    from .spatial import check_cover

                    # We pass an empty list if obstacles are not wired into the state view yet
                    obstacles = []
                    cover_state = check_cover(actor.position, target.position, obstacles)
                    if cover_state == "HALF":
                        target_ac += 2
                    elif cover_state == "THREE_QUARTERS":
                        target_ac += 5

                if _has_trait(actor, "sharpshooter") and is_ranged:
                    if target_ac <= 16 or advantage:
                        power_attack_active = True
                elif _has_trait(actor, "great weapon master") and is_heavy:
                    if target_ac <= 16 or advantage:
                        power_attack_active = True

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

            if force_crit and roll.hit:
                roll = AttackRollResult(
                    hit=True, crit=True, natural_roll=roll.natural_roll, total=roll.total
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
                                    from .spatial import distance_chebyshev

                                    if distance_chebyshev(cand.position, target.position) <= 5:
                                        has_sneak = True
                                        break
                        if has_sneak:
                            actor.sneak_attack_used_this_turn = True
                            sa_dice = (actor.level + 1) // 2
                            damage_expr += f"+{sa_dice}d6"

                if power_attack_active and damage_expr:
                    damage_expr += f"{damage_bonus:+d}"
                raw_damage = roll_damage(
                    rng,
                    damage_expr,
                    crit=roll.crit,
                    empowered_rerolls=empowered_rerolls,
                    source=actor,
                    damage_type=action.damage_type,
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
                        smite_dice = min(5, 1 + slot_level)
                        raw_smite = roll_damage(
                            rng,
                            f"{smite_dice}d8",
                            crit=roll.crit,
                            source=actor,
                            damage_type="radiant",
                        )
                        raw_damage += raw_smite
                applied = apply_damage(
                    target,
                    raw_damage,
                    action.damage_type,
                    is_critical=roll.crit,
                    is_magical="spell" in action.tags or "magical" in action.tags,
                    source=actor,
                )
                if not run_concentration_check(rng, target, applied, source=actor):
                    _break_concentration(target, actors, active_hazards)
                damage_dealt[actor.actor_id] += applied
                damage_taken[target.actor_id] += applied
                threat_scores[actor.actor_id] += applied

                # GWM Momentum Trigger (Action Economy Buff)
                if (
                    _has_trait(actor, "great weapon master")
                    and (roll.crit or target.hp <= 0)
                    and not is_ranged
                ):
                    actor.conditions.add("gwm_bonus_triggered")
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
            )
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
            raw_damage = roll_damage(
                rng,
                action.damage,
                crit=False,
                empowered_rerolls=empowered_rerolls,
                source=actor,
                damage_type=action.damage_type,
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
            save_roll = rng.randint(1, 20)
            if save_key == "dex" and "dodging" in target.conditions:
                save_roll = max(save_roll, rng.randint(1, 20))
            if "spell" in action.tags and _has_trait(target, "mage slayer"):
                save_roll = max(save_roll, rng.randint(1, 20))
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
                    and target.reaction_available
                ):
                    final_damage = 0
                    target.reaction_available = False

            applied = apply_damage(
                target,
                final_damage,
                action.damage_type,
                is_magical="spell" in action.tags or "magical" in action.tags,
                source=actor,
            )
            if applied > 0:
                if not run_concentration_check(rng, target, applied, source=actor):
                    _break_concentration(target, actors, active_hazards)
                damage_dealt[actor.actor_id] += applied
                damage_taken[target.actor_id] += applied
                threat_scores[actor.actor_id] += applied

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
            )
        return

    if action.action_type == "utility":
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
            )


def _build_round_metadata(
    *,
    actors: dict[str, ActorRuntimeState],
    threat_scores: dict[str, int],
    burst_round_threshold: int,
    active_hazards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "threat_scores": dict(threat_scores),
        "burst_round_threshold": burst_round_threshold,
        "active_hazards": list(active_hazards or []),
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
) -> None:
    for actor in actors.values():
        if actor.dead or actor.hp <= 0:
            continue
        if actor.lair_action_used_this_round:
            continue
        lair_actions = [action for action in actor.actions if action.action_cost == "lair"]
        if not lair_actions:
            continue
        action = next(
            (candidate for candidate in lair_actions if _action_available(actor, candidate)), None
        )
        if action is None:
            continue
        targets = _resolve_targets_for_action(
            rng=rng,
            actor=actor,
            action=action,
            actors=actors,
            requested=[],
        )
        if not targets:
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
) -> None:
    for actor in actors.values():
        if actor.actor_id == trigger_actor.actor_id:
            continue
        if actor.dead or actor.hp <= 0:
            continue
        legendary = [action for action in actor.actions if action.action_cost == "legendary"]
        if not legendary:
            continue
        action = next(
            (candidate for candidate in legendary if _action_available(actor, candidate)), None
        )
        if action is None:
            continue
        targets = _resolve_targets_for_action(
            rng=rng,
            actor=actor,
            action=action,
            actors=actors,
            requested=[],
        )
        if not targets:
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

        for character_id in scenario.config.party:
            if character_id not in character_db:
                raise ValueError(f"Character ID missing from DB: {character_id}")
            actor = _build_actor_from_character(character_db[character_id], traits_db)
            if not hasattr(actor, "position"):
                actor.position = (0.0, 0.0, 0.0)
            actors[actor.actor_id] = actor
            damage_taken[actor.actor_id] = 0
            damage_dealt[actor.actor_id] = 0
            resources_spent[actor.actor_id] = {}
            threat_scores[actor.actor_id] = 0
            downed_counts[actor.actor_id] = 0
            death_counts[actor.actor_id] = 0

        total_rounds = 0
        overall_winner = "draw"

        for enc_idx, encounter in enumerate(scenario.config.encounters):
            for aid in list(actors.keys()):
                if actors[aid].team != "party":
                    downed_counts[aid] = actors[aid].downed_count
                    death_counts[aid] = int(actors[aid].dead)
                    remaining_hp[aid] = actors[aid].hp
                    del actors[aid]

            enemy_counts: dict[str, int] = {}
            for enemy_id in encounter.enemies:
                count = enemy_counts.get(enemy_id, 0) + 1
                enemy_counts[enemy_id] = count
                unique_enemy_id = (
                    f"{enemy_id}_e{enc_idx}_{count}"
                    if (count > 1 or len(scenario.config.encounters) > 1)
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
                )

                metadata = _build_round_metadata(
                    actors=actors,
                    threat_scores=threat_scores,
                    burst_round_threshold=int(
                        scenario.config.resource_policy.get("burst_round_threshold", 3)
                    ),
                    active_hazards=active_hazards,
                )
                state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                for strategy in strategy_registry.values():
                    strategy.on_round_start(state_view)

                for actor_id in initiative_order:
                    actor = actors[actor_id]
                    actor.movement_remaining = float(actor.speed_ft)
                    actor.took_attack_action_this_turn = False
                    _roll_recharge_for_actor(rng, actor)
                    _tick_conditions_for_actor(rng, actor)
                    actor.bonus_available = True
                    actor.reaction_available = True
                    actor.sneak_attack_used_this_turn = False

                    if actor.dead:
                        continue

                    if actor.hp <= 0:
                        resolve_death_save(rng, actor)
                        continue

                    if _party_defeated(actors) or _enemies_defeated(actors):
                        break

                    if not _can_act(actor):
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
                    )
                    state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                    actor_view = state_view.actors[actor.actor_id]
                    intent = strategy.choose_action(actor_view, state_view)
                    action = _resolve_action_selection(actor, intent.action_name)

                    if not _action_available(actor, action):
                        fallback = _fallback_action(actor)
                        if fallback is None:
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
                    )

                if _party_defeated(actors) or _enemies_defeated(actors):
                    break

            total_rounds += rounds

            if _party_defeated(actors):
                overall_winner = "enemy"
                break
            elif _enemies_defeated(actors):
                if encounter.short_rest_after and enc_idx < len(scenario.config.encounters) - 1:
                    for actor in actors.values():
                        if actor.team == "party":
                            short_rest(actor)
            else:
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
