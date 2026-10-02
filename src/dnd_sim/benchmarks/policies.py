"""Deterministic complete-turn policies for the declared level-five loadouts.

These heuristics use visible engine state, never dice previews. They deliberately
exclude unsupported actions instead of treating arbitrary catalog entries as
verified combat options. Resolution and legality remain engine-owned.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from typing import Any

from dnd_sim.rules_2014 import parse_damage_expression
from dnd_sim.spatial import (
    check_cover,
    distance_chebyshev,
    find_path,
    grid_cell_for_position,
    path_prefix_for_movement,
    template_cells,
)
from dnd_sim.strategy_api import (
    ActorView,
    BaseStrategy,
    BattleStateView,
    DeclaredAction,
    ReactionPolicy,
    TargetRef,
    TurnDeclaration,
)

POLICIES = ("conservative", "typical", "aggressive")
logger = logging.getLogger(__name__)
_RESOURCE_PRICE = {"conservative": 6.0, "typical": 3.0, "aggressive": 0.0}


def _average(expression: str | None) -> float:
    if not expression:
        return 0.0
    count, sides, flat = parse_damage_expression(expression)
    return count * (sides + 1) / 2 + flat


def _spell_level(action: dict[str, Any]) -> int:
    return max(
        (
            int(tag.split(":")[1])
            for tag in action.get("tags", [])
            if tag.startswith("spell_level:")
        ),
        default=0,
    )


def _healing(action: dict[str, Any]) -> float:
    return sum(
        _average(effect.get("amount"))
        for effect in action.get("effects", [])
        if effect.get("effect_type") == "heal"
    )


def _affordable(action: dict[str, Any], resources: dict[str, int]) -> bool:
    return bool(action.get("recharge_ready", True)) and all(
        resources.get(key, 0) >= value for key, value in action.get("resource_cost", {}).items()
    )


def _range(action: dict[str, Any]) -> float:
    return float(
        action.get("range_normal_ft") or action.get("range_ft") or action.get("reach_ft") or 5
    )


def _is_ranged(action: dict[str, Any]) -> bool:
    return _range(action) > 5 and action.get("action_type") == "attack"


def _movement_budget(actor: ActorView) -> float:
    stand_cost = actor.speed_ft / 2 if "prone" in actor.conditions else 0
    return max(0, actor.movement_remaining - stand_cost)


def _route(actor: ActorView, target: ActorView, action, state) -> list | None:
    obstacles = state.metadata.get("obstacles", [])
    reach = _range(action)
    if target.actor_id == actor.actor_id:
        return []
    if distance_chebyshev(actor.position, target.position) <= reach:
        return [] if check_cover(actor.position, target.position, obstacles) != "TOTAL" else None
    path = find_path(
        actor.position,
        target.position,
        obstacles=obstacles,
        occupied_positions=[a.position for a in state.actors.values() if a.hp > 0],
    )
    prefix = path_prefix_for_movement(path, _movement_budget(actor))
    for index, point in enumerate(prefix):
        if (
            distance_chebyshev(point, target.position) <= reach
            and check_cover(point, target.position, obstacles) != "TOTAL"
        ):
            return prefix[: index + 1] if index else []
    return None


@dataclass
class _Candidate:
    score: float
    action: dict[str, Any]
    target: ActorView
    movement: list


class TacticalPolicy(BaseStrategy):
    """Plan movement, a primary action, a compatible bonus, and auto reactions."""

    def __init__(self, profile: str = "typical"):
        if profile not in POLICIES:
            raise ValueError(f"Unknown tactical policy: {profile}")
        self.profile = profile

    def _resource_price(self, actor: ActorView, action: dict[str, Any]) -> float:
        # Enemy tactics stay fixed across party-policy comparisons.
        price = _RESOURCE_PRICE[self.profile] if actor.team == "party" else 0.0
        cost = sum(
            value * (int(key.rsplit("_", 1)[1]) if key.startswith("spell_slot_") else 1)
            for key, value in action.get("resource_cost", {}).items()
        )
        return price * cost

    def _score(self, actor, action, target, state) -> float | None:
        healing = _healing(action)
        if healing:
            missing = target.max_hp - target.hp
            if target.team != actor.team or target.dead or missing <= 0:
                return None
            return min(missing, healing) + (30 if target.hp == 0 else 0)
        if target.team == actor.team or target.hp <= 0 or not action.get("damage"):
            return None
        victims = [target]
        if action.get("aoe_type"):
            cells = template_cells(
                template=action["aoe_type"], origin=target.position, size_ft=action["aoe_size_ft"]
            )
            victims = [
                a
                for a in state.actors.values()
                if not a.dead and grid_cell_for_position(a.position) in cells
            ]
            # Include downed allies and the caster: never knowingly damage friends.
            if any(a.team == actor.team for a in victims):
                return None
        score = 0.0
        for victim in victims:
            damage = _average(action.get("damage"))
            if action.get("action_type") == "save":
                modifier = victim.save_mods.get(action.get("save_ability", "dex"), 0)
                failed = min(1.0, max(0.0, (action.get("save_dc", 10) - modifier - 1) / 20))
                damage *= failed + (0.5 * (1 - failed) if action.get("half_on_save") else 0)
            else:
                cover = check_cover(
                    actor.position, victim.position, state.metadata.get("obstacles", [])
                )
                armor = victim.ac + {"HALF": 2, "THREE_QUARTERS": 5}.get(cover, 0)
                chance = min(0.95, max(0.05, (21 + action.get("to_hit", 0) - armor) / 20))
                if _is_ranged(action) and any(
                    a.team != actor.team
                    and a.hp > 0
                    and distance_chebyshev(actor.position, a.position) <= 5
                    for a in state.actors.values()
                ):
                    chance *= chance
                damage *= chance * action.get("attack_count", 1)
                if (
                    "sneak attack" in actor.traits
                    and any(
                        a.team == actor.team
                        and a.actor_id != actor.actor_id
                        and a.hp > 0
                        and distance_chebyshev(a.position, victim.position) <= 5
                        for a in state.actors.values()
                    )
                    and "spell" not in action.get("tags", [])
                ):
                    damage += 10.5 * chance
            score += min(damage, victim.hp) + (3 if damage >= victim.hp else 0)
        return score

    def _candidates(self, actor, state, catalog, *, bonus=False):
        rows = []
        for action in catalog:
            if action.get("action_cost", "action") != ("bonus" if bonus else "action"):
                continue
            if not _affordable(action, actor.resources):
                continue
            if not action.get("damage") and not _healing(action):
                continue
            targets = [actor] if action.get("target_mode") == "self" else state.actors.values()
            for target in targets:
                if target.dead:
                    continue
                if _healing(action):
                    if target.team != actor.team or target.hp >= target.max_hp:
                        continue
                elif target.team == actor.team or target.hp <= 0:
                    continue
                route = _route(actor, target, action, state)
                if route is None or (bonus and route):
                    continue
                projected = replace(actor, position=route[-1]) if route else actor
                score = self._score(projected, action, target, state)
                if score is not None:
                    rows.append(
                        _Candidate(
                            score - self._resource_price(actor, action), action, target, route
                        )
                    )
        return rows

    @staticmethod
    def _declaration(candidate: _Candidate) -> DeclaredAction:
        level = _spell_level(candidate.action)
        return DeclaredAction(
            action_name=candidate.action["name"],
            targets=[TargetRef(candidate.target.actor_id)],
            spell_slot_level=level or None,
        )

    def declare_turn(self, actor: ActorView, state: BattleStateView) -> TurnDeclaration:
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        candidates = self._candidates(actor, state, catalog)
        plans = []
        for primary in candidates:
            resources = dict(actor.resources)
            for key, cost in primary.action.get("resource_cost", {}).items():
                resources[key] -= cost
            projected = replace(
                actor,
                resources=resources,
                movement_remaining=0,
                position=primary.movement[-1] if primary.movement else actor.position,
            )
            bonuses = []
            for bonus in self._candidates(projected, state, catalog, bonus=True):
                if "spell" in bonus.action.get("tags", []) and _spell_level(primary.action) > 0:
                    continue
                if bonus.action["name"] == "off_hand_attack":
                    props = set(primary.action.get("weapon_properties", []))
                    if "light" not in props or _is_ranged(primary.action):
                        continue
                    if primary.action.get("weapon_id") == bonus.action.get("weapon_id"):
                        continue
                    # Sneak Attack is already valued in the primary action score.
                    bonus.score = min(_average(bonus.action.get("damage")), bonus.target.hp) * 0.6
                if _healing(primary.action) and _healing(bonus.action):
                    continue
                if bonus.score > 0:
                    bonuses.append(bonus)
            best_bonus = max(
                bonuses,
                key=lambda row: (row.score, row.action["name"], row.target.actor_id),
                default=None,
            )
            total = primary.score + (best_bonus.score if best_bonus else 0)
            plans.append((total, primary, best_bonus))
        if plans:
            # Stable tie-breaking favors smaller slot costs and ordinary weapon names.
            _, primary, bonus = max(
                plans,
                key=lambda row: (
                    row[0],
                    -_spell_level(row[1].action),
                    row[1].action["name"],
                    row[1].target.actor_id,
                ),
            )
            return TurnDeclaration(
                movement_path=primary.movement,
                action=self._declaration(primary),
                bonus_action=self._declaration(bonus) if bonus else None,
                reaction_policy=ReactionPolicy(mode="auto"),
                rationale={
                    "policy": self.profile if actor.team == "party" else "fixed_aggressive",
                    "plan_score": round(primary.score + (bonus.score if bonus else 0), 4),
                    "bonus_reason": (
                        "compatible_and_affordable" if bonus else "no_useful_legal_bonus"
                    ),
                },
            )
        enemies = [a for a in state.actors.values() if a.team != actor.team and a.hp > 0]
        movement = []
        if enemies:
            target = min(
                enemies, key=lambda a: (distance_chebyshev(actor.position, a.position), a.actor_id)
            )
            route = find_path(
                actor.position,
                target.position,
                obstacles=state.metadata.get("obstacles", []),
                occupied_positions=[a.position for a in state.actors.values() if a.hp > 0],
            )
            movement = path_prefix_for_movement(route, _movement_budget(actor))
            if movement and movement[-1] == target.position:
                movement = movement[:-1]
        return TurnDeclaration(
            movement_path=movement if len(movement) > 1 else [],
            action=(
                DeclaredAction(action_name="dodge", targets=[TargetRef(actor.actor_id)])
                if any(action["name"] == "dodge" for action in catalog)
                else None
            ),
            reaction_policy=ReactionPolicy(mode="auto"),
            rationale={"policy": self.profile, "reason": "advance_until_a_target_is_reachable"},
        )
