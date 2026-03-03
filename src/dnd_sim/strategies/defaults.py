from __future__ import annotations

import math
from typing import Any

from dnd_sim.rules_2014 import parse_damage_expression
from dnd_sim.spatial import distance_chebyshev
from dnd_sim.strategy_api import ActionIntent, BaseStrategy, TargetRef


class FocusFireLowestHPStrategy(BaseStrategy):
    pass


class BossHighestThreatTargetStrategy(BaseStrategy):
    def choose_targets(self, actor, intent, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return []
        threat_scores = state.metadata.get("threat_scores", {})
        target = max(
            enemies,
            key=lambda entry: (threat_scores.get(entry.actor_id, 0), -entry.hp),
        )
        return [TargetRef(actor_id=target.actor_id)]


class ConserveResourcesThenBurstStrategy(BaseStrategy):
    def choose_action(self, actor, state):
        available = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
        burst_threshold = int(state.metadata.get("burst_round_threshold", 3))
        if state.round_number >= burst_threshold and "signature" in available:
            return ActionIntent(action_name="signature")
        if "basic" in available:
            return ActionIntent(action_name="basic")
        return ActionIntent(action_name=available[0] if available else None)


class AlwaysUseSignatureAbilityStrategy(BaseStrategy):
    def choose_action(self, actor, state):
        available = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
        if "signature" in available:
            return ActionIntent(action_name="signature")
        if "basic" in available:
            return ActionIntent(action_name="basic")
        return ActionIntent(action_name=available[0] if available else None)


def _average_damage(expr: str | None, crit: bool = False) -> float:
    if not expr:
        return 0.0
    n_dice, dice_size, flat = parse_damage_expression(expr)
    if n_dice == 0:
        return float(flat)
    dice = n_dice * (2 if crit else 1)
    return dice * ((dice_size + 1) / 2.0) + flat


def _attack_hit_prob(to_hit: int, target_ac: int) -> tuple[float, float]:
    crit = 0.05
    non_crit_hits = 0
    for roll in range(2, 20):
        if roll + to_hit >= target_ac:
            non_crit_hits += 1
    return non_crit_hits / 20.0, crit


def _expected_damage_against(action: dict, target, *, save_mod: int = 0) -> float:
    def effect_prob(effect: dict[str, Any], *, hit: float, crit: float, fail: float) -> float:
        apply_on = effect.get("apply_on", "always")
        if apply_on == "always":
            return 1.0
        if apply_on == "hit":
            return hit + crit
        if apply_on == "miss":
            return 1.0 - hit - crit
        if apply_on == "save_fail":
            return fail
        if apply_on == "save_success":
            return 1.0 - fail
        return 0.0

    def effect_impact(effect: dict[str, Any]) -> float:
        if effect.get("effect_type") == "damage":
            return _average_damage(effect.get("damage"), crit=False)
        if effect.get("effect_type") == "apply_condition":
            condition = str(effect.get("condition", ""))
            duration = int(effect.get("duration_rounds") or 1)
            if condition in {"paralyzed", "stunned", "unconscious", "petrified", "incapacitated"}:
                return 25.0 * duration
            if condition in {"blinded", "restrained", "frightened", "poisoned", "charmed"}:
                return 10.0 * duration
            if condition in {"prone", "grappled"}:
                return 5.0 * duration
            return 2.0 * duration
        return 0.0

    all_effects: list[dict[str, Any]] = []
    for raw_effect in action.get("effects", []) + action.get("mechanics", []):
        if isinstance(raw_effect, dict):
            all_effects.append(raw_effect)

    if action["action_type"] == "attack":
        to_hit = int(action.get("to_hit") or 0)
        normal_hit, crit_hit = _attack_hit_prob(to_hit, target.ac)
        base = _average_damage(action.get("damage"), crit=False)
        crit = _average_damage(action.get("damage"), crit=True)
        action_hits = max(1, int(action.get("attack_count") or 1))
        rider = sum(
            effect_prob(effect, hit=normal_hit, crit=crit_hit, fail=1.0 - normal_hit - crit_hit)
            * effect_impact(effect)
            for effect in all_effects
            if effect.get("target", "target") == "target"
        )
        return ((normal_hit * base + crit_hit * crit) + rider) * action_hits
    if action["action_type"] == "save":
        dc = action.get("save_dc")
        if dc is None:
            return 0.0
        success_outcomes = max(0, min(20, 21 - (int(dc) - save_mod)))
        success_prob = success_outcomes / 20.0
        fail_prob = 1.0 - success_prob
        base = _average_damage(action.get("damage"), crit=False)
        success_damage = base / 2.0 if action.get("half_on_save", False) else 0.0
        rider = sum(
            effect_prob(effect, hit=0.0, crit=0.0, fail=fail_prob) * effect_impact(effect)
            for effect in all_effects
            if effect.get("target", "target") == "target"
        )
        return fail_prob * base + success_prob * success_damage + rider
    if action["action_type"] == "utility":
        return sum(
            effect_impact(effect)
            for effect in all_effects
            if effect.get("target", "target") == "target"
            and effect.get("apply_on", "always") == "always"
        )
    return 0.0


def _evaluate_action_score(action: dict, target, actor, state) -> float:
    # Phase 12: Vision Penalty
    from ..spatial import can_see

    score_multiplier = 1.0

    can_see_target = can_see(
        observer_pos=actor.position,
        target_pos=target.position,
        observer_traits=actor.traits,
        target_conditions=target.conditions,
        active_hazards=state.metadata.get("active_hazards", []),
        light_level=str(state.metadata.get("light_level", "bright")),
    )
    if not can_see_target:
        score_multiplier = 0.5  # Penalize attacking unseen targets heavily

    aoe_type = action.get("aoe_type")
    aoe_size = action.get("aoe_size_ft")
    aoe_radius = _coerce_positive_distance(aoe_size)

    if aoe_type and aoe_radius is not None:
        score = 0.0
        for cand in state.actors.values():
            if cand.hp > 0 and distance_chebyshev(target.position, cand.position) <= aoe_radius:
                if cand.actor_id == actor.actor_id and not action.get("include_self", False):
                    continue
                save_mod = (
                    int(cand.save_mods.get(action.get("save_ability", ""), 0))
                    if action.get("action_type") == "save"
                    else 0
                )
                expected = _expected_damage_against(action, cand, save_mod=save_mod)
                if cand.team != actor.team:
                    score += expected
                else:
                    score -= expected * 1.5
        return score * score_multiplier

    save_mod = (
        int(target.save_mods.get(action.get("save_ability", ""), 0))
        if action.get("action_type") == "save"
        else 0
    )
    return (
        _expected_damage_against(action, target, save_mod=save_mod)
        * score_multiplier
        * max(1, _target_count_for_action(actor, state, action))
    )


def _coerce_positive_distance(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed


def _can_pay(actor, action: dict) -> bool:
    for key, amount in (action.get("resource_cost") or {}).items():
        if actor.resources.get(key, 0) < int(amount):
            return False
    return True


def _can_pay_with_resources(resources: dict[str, int], action: dict[str, Any]) -> bool:
    for key, amount in (action.get("resource_cost") or {}).items():
        if int(resources.get(key, 0)) < int(amount):
            return False
    return True


def _project_resources(resources: dict[str, int], action: dict[str, Any]) -> dict[str, int]:
    projected = dict(resources)
    for key, amount in (action.get("resource_cost") or {}).items():
        projected[key] = max(0, int(projected.get(key, 0)) - int(amount))
    return projected


def _strategy_policy(actor, state) -> dict[str, Any]:
    raw = state.metadata.get("strategy_policy", {})
    if not isinstance(raw, dict):
        return {}

    merged: dict[str, Any] = {k: v for k, v in raw.items() if k not in {"party", "enemy"}}
    team_policy = raw.get(actor.team)
    if isinstance(team_policy, dict):
        merged.update(team_policy)
    return merged


def _policy_section(policy: dict[str, Any], key: str) -> dict[str, Any]:
    value = policy.get(key, {})
    return value if isinstance(value, dict) else {}


def _action_range_ft(action: dict[str, Any]) -> float:
    if action.get("action_type") == "attack":
        return float(action.get("range_ft") or 5.0)
    if action.get("action_type") == "utility":
        return float(action.get("range_ft") or 30.0)
    return float(action.get("range_ft") or 60.0)


def _can_reach_target(actor, action: dict[str, Any], target) -> bool:
    return distance_chebyshev(actor.position, target.position) <= (
        _action_range_ft(action) + actor.movement_remaining
    )


def _objective_action_bonus(action: dict[str, Any], policy: dict[str, Any], state) -> float:
    objective_cfg = _policy_section(policy, "objective_play")
    if not bool(objective_cfg.get("enabled", False)):
        return 0.0

    tags = [str(tag) for tag in action.get("tags", [])]
    is_objective_action = any(tag.startswith("objective") for tag in tags)
    if not is_objective_action:
        return 0.0

    bonus = float(objective_cfg.get("objective_action_bonus", 0.0))
    objective_scores = state.metadata.get("objective_scores", {})
    if isinstance(objective_scores, dict):
        bonus += float(objective_scores.get(str(action.get("name", "")), 0.0))
        for tag in tags:
            if ":" not in tag:
                continue
            _, objective_id = tag.split(":", 1)
            bonus += float(objective_scores.get(objective_id, 0.0))
    return bonus


def _target_policy_bonus(actor, target, policy: dict[str, Any], state) -> float:
    bonus = 0.0

    threat_cfg = _policy_section(policy, "threat_management")
    if bool(threat_cfg.get("enabled", False)) and target.team != actor.team:
        weight = float(threat_cfg.get("target_weight", 0.0))
        threat_scores = state.metadata.get("threat_scores", {})
        if isinstance(threat_scores, dict):
            bonus += weight * float(threat_scores.get(target.actor_id, 0.0))

    objective_cfg = _policy_section(policy, "objective_play")
    if bool(objective_cfg.get("enabled", False)):
        objective_targets = state.metadata.get("objective_targets", {})
        if isinstance(objective_targets, dict):
            target_weight = float(objective_cfg.get("target_weight", 1.0))
            bonus += target_weight * float(objective_targets.get(target.actor_id, 0.0))

    return bonus


def _action_viable(
    action: dict[str, Any],
    *,
    resources: dict[str, int],
    used_count: int,
) -> bool:
    if action.get("action_cost") in {"legendary", "lair", "reaction"}:
        return False
    max_uses = action.get("max_uses")
    if max_uses is not None and used_count >= int(max_uses):
        return False
    if not bool(action.get("recharge_ready", True)):
        return False
    return _can_pay_with_resources(resources, action)


def _target_count_for_action(actor, state, action: dict) -> int:
    mode = action.get("target_mode", "single_enemy")
    enemies = [view for view in state.actors.values() if view.team != actor.team and view.hp > 0]
    allies = [view for view in state.actors.values() if view.team == actor.team and view.hp > 0]
    if mode == "all_enemies":
        return len(enemies)
    if mode == "all_allies":
        return len(allies)
    if mode == "all_creatures":
        return len([view for view in state.actors.values() if view.hp > 0])
    if mode in {"n_enemies", "n_allies"}:
        max_targets = int(action.get("max_targets") or 1)
        pool = enemies if mode == "n_enemies" else allies
        return min(max_targets, len(pool))
    return 1


class OptimalExpectedDamageStrategy(BaseStrategy):
    """Greedy expected-damage maximizer for 5e-2014 encounter simulations."""

    def choose_action(self, actor, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not catalog or not enemies:
            return ActionIntent(
                action_name=None,
                rationale={"reason": "no_actions_or_targets"},
            )

        policy = _strategy_policy(actor, state)
        concentration_cfg = _policy_section(policy, "concentration_protection")
        concentration_enabled = bool(concentration_cfg.get("enabled", False))
        hp_ratio = actor.hp / max(actor.max_hp, 1)
        if (
            concentration_enabled
            and actor.concentrating
            and hp_ratio <= float(concentration_cfg.get("hp_ratio_threshold", 0.35))
            and bool(concentration_cfg.get("prefer_dodge", True))
        ):
            dodge = next(
                (
                    action
                    for action in catalog
                    if str(action.get("name", "")) == "dodge"
                    and _action_viable(
                        action,
                        resources=actor.resources,
                        used_count=int(action.get("used_count", 0)),
                    )
                ),
                None,
            )
            if dodge is not None:
                return ActionIntent(
                    action_name="dodge",
                    rationale={
                        "mode": "policy_guardrail",
                        "guardrail": "concentration_protection",
                        "hp_ratio": hp_ratio,
                    },
                )

        evaluation_mode = str(state.metadata.get("evaluation_mode", "greedy")).lower()
        lookahead_enabled = evaluation_mode == "lookahead"
        lookahead_discount = float(state.metadata.get("lookahead_discount", 1.0))
        tactical_branches = state.metadata.get("tactical_branches", {})
        branch_map = tactical_branches if isinstance(tactical_branches, dict) else {}

        def _best_follow_up_score(
            resources_after: dict[str, int],
            used_counts_after: dict[str, int],
        ) -> float:
            best = 0.0
            for next_action in catalog:
                next_name = str(next_action.get("name", ""))
                used_count = used_counts_after.get(next_name, int(next_action.get("used_count", 0)))
                if not _action_viable(
                    next_action, resources=resources_after, used_count=used_count
                ):
                    continue

                reachable = [
                    target for target in enemies if _can_reach_target(actor, next_action, target)
                ]
                if not reachable:
                    continue
                best_target_score = max(
                    _evaluate_action_score(next_action, target, actor, state)
                    + _target_policy_bonus(actor, target, policy, state)
                    for target in reachable
                )
                best = max(
                    best,
                    best_target_score + _objective_action_bonus(next_action, policy, state),
                )
            return best

        def _best_branch_score(
            action_name: str,
            resources_after: dict[str, int],
            used_counts_after: dict[str, int],
        ) -> float:
            raw_branches = branch_map.get(action_name, [])
            if not isinstance(raw_branches, list):
                return 0.0

            best = 0.0
            for branch in raw_branches:
                if not isinstance(branch, dict):
                    continue
                next_name = str(branch.get("next_action", "")).strip()
                if not next_name:
                    continue
                next_action = next(
                    (entry for entry in catalog if str(entry.get("name", "")) == next_name),
                    None,
                )
                if next_action is None:
                    continue

                branch_resource_cost = branch.get("resource_cost")
                if isinstance(branch_resource_cost, dict) and not _can_pay_with_resources(
                    resources_after, {"resource_cost": branch_resource_cost}
                ):
                    continue

                used_count = used_counts_after.get(next_name, int(next_action.get("used_count", 0)))
                if not _action_viable(
                    next_action, resources=resources_after, used_count=used_count
                ):
                    continue

                reachable = [
                    target for target in enemies if _can_reach_target(actor, next_action, target)
                ]
                if not reachable:
                    continue
                next_score = max(
                    _evaluate_action_score(next_action, target, actor, state)
                    + _target_policy_bonus(actor, target, policy, state)
                    for target in reachable
                )
                next_score += _objective_action_bonus(next_action, policy, state)
                branch_weight = float(branch.get("weight", 1.0))
                branch_bonus = float(branch.get("score_bonus", 0.0))
                best = max(best, next_score * branch_weight + branch_bonus)
            return best

        candidates: list[dict[str, Any]] = []
        for action in catalog:
            action_name = str(action.get("name", ""))
            used = int(action.get("used_count", 0))
            if not _action_viable(action, resources=actor.resources, used_count=used):
                continue

            reachable = [target for target in enemies if _can_reach_target(actor, action, target)]
            base_score = 0.0
            if reachable:
                base_score = max(
                    _evaluate_action_score(action, target, actor, state)
                    + _target_policy_bonus(actor, target, policy, state)
                    for target in reachable
                )
            objective_bonus = _objective_action_bonus(action, policy, state)
            lookahead_bonus = 0.0
            if lookahead_enabled:
                resources_after = _project_resources(actor.resources, action)
                used_counts_after = {
                    str(entry.get("name", "")): int(entry.get("used_count", 0)) for entry in catalog
                }
                used_counts_after[action_name] = used_counts_after.get(action_name, 0) + 1
                lookahead_bonus = max(
                    _best_follow_up_score(resources_after, used_counts_after),
                    _best_branch_score(action_name, resources_after, used_counts_after),
                )

            total = base_score + objective_bonus + (lookahead_discount * lookahead_bonus)
            if concentration_enabled and actor.concentrating and bool(action.get("concentration")):
                total -= float(concentration_cfg.get("recast_penalty", 5.0))

            candidates.append(
                {
                    "name": action_name,
                    "base_score": base_score,
                    "objective_bonus": objective_bonus,
                    "lookahead_bonus": lookahead_bonus,
                    "total_score": total,
                    "cost": sum(int(v) for v in (action.get("resource_cost") or {}).values()),
                }
            )

        if not candidates:
            return ActionIntent(
                action_name=None,
                rationale={"reason": "no_viable_actions"},
            )

        ranked = sorted(candidates, key=lambda row: (-row["total_score"], row["cost"], row["name"]))
        best = ranked[0]
        enabled_policies = [
            name
            for name in ("threat_management", "concentration_protection", "objective_play")
            if bool(_policy_section(policy, name).get("enabled", False))
        ]

        return ActionIntent(
            action_name=best["name"],
            rationale={
                "mode": evaluation_mode,
                "selected": best,
                "top_candidates": ranked[:3],
                "enabled_policies": enabled_policies,
            },
        )

    def choose_targets(self, actor, intent, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action = next((entry for entry in catalog if entry.get("name") == intent.action_name), None)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        allies = [view for view in state.actors.values() if view.team == actor.team and view.hp > 0]
        policy = _strategy_policy(actor, state)

        if action and action.get("target_mode") == "self":
            return [TargetRef(actor_id=actor.actor_id)]
        if action and action.get("target_mode") == "all_enemies":
            return [TargetRef(actor_id=entry.actor_id) for entry in enemies]
        if action and action.get("target_mode") == "all_allies":
            return [TargetRef(actor_id=entry.actor_id) for entry in allies]
        if action and action.get("target_mode") == "all_creatures":
            everyone = [view for view in state.actors.values() if view.hp > 0]
            return [TargetRef(actor_id=entry.actor_id) for entry in everyone]

        def _can_reach(target) -> bool:
            return _can_reach_target(actor, action or {}, target)

        if action and action.get("target_mode") == "n_enemies":
            count = int(action.get("max_targets") or 1)
            reachable = [e for e in enemies if _can_reach(e)]
            pool = reachable if reachable else enemies
            ranked = sorted(
                pool,
                key=lambda entry: (
                    _evaluate_action_score(action, entry, actor, state)
                    + _target_policy_bonus(actor, entry, policy, state)
                ),
                reverse=True,
            )
            return [TargetRef(actor_id=entry.actor_id) for entry in ranked[:count]]

        if action and action.get("target_mode") == "n_allies":
            count = int(action.get("max_targets") or 1)
            reachable = [a for a in allies if _can_reach(a)]
            pool = reachable if reachable else allies
            ranked = sorted(pool, key=lambda entry: (entry.hp / max(entry.max_hp, 1), entry.hp))
            return [TargetRef(actor_id=entry.actor_id) for entry in ranked[:count]]

        if not enemies:
            return []

        reachable = [e for e in enemies if _can_reach(e)]
        pool = reachable if reachable else enemies

        if not action:
            target = min(pool, key=lambda entry: (entry.hp, entry.max_hp))
            return [TargetRef(actor_id=target.actor_id)]

        target = max(
            pool,
            key=lambda entry: _evaluate_action_score(action, entry, actor, state)
            + _target_policy_bonus(actor, entry, policy, state),
        )
        return [TargetRef(actor_id=target.actor_id)]


class PackTacticsStrategy(OptimalExpectedDamageStrategy):
    def choose_targets(self, actor, intent, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action = next((entry for entry in catalog if entry.get("name") == intent.action_name), None)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]

        if not enemies or not action or action.get("target_mode") not in {"single_enemy"}:
            return super().choose_targets(actor, intent, state)

        def _can_reach(target) -> bool:
            if action.get("action_type") == "attack":
                action_range = float(action.get("range_ft") or 5.0)
            elif action.get("action_type") == "utility":
                action_range = float(action.get("range_ft") or 30.0)
            else:
                action_range = float(action.get("range_ft") or 60.0)
            return distance_chebyshev(actor.position, target.position) <= (
                action_range + actor.movement_remaining
            )

        reachable = [e for e in enemies if _can_reach(e)]
        pool = reachable if reachable else enemies

        def _has_ally_adjacent(target) -> bool:
            for view in state.actors.values():
                if view.team == actor.team and view.actor_id != actor.actor_id and view.hp > 0:
                    if distance_chebyshev(view.position, target.position) <= 5.0:
                        return True
            return False

        # Sort by ally adajcency (Pack Tactics advantage), then expected damage
        target = max(
            pool,
            key=lambda entry: (
                1 if _has_ally_adjacent(entry) else 0,
                _expected_damage_against(action, entry),
            ),
        )
        return [TargetRef(actor_id=target.actor_id)]


class HealerStrategy(OptimalExpectedDamageStrategy):
    def choose_action(self, actor, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        allies = [view for view in state.actors.values() if view.team == actor.team]

        critical_allies = [a for a in allies if a.hp <= 0 and not "dead" in a.conditions]
        low_allies = [a for a in allies if a.hp > 0 and a.hp < a.max_hp * 0.25]

        target_allies = critical_allies or low_allies

        if target_allies:
            heal_actions = [
                action
                for action in catalog
                if action.get("action_type") == "utility"
                and any(e.get("effect_type") == "heal" for e in action.get("effects", []))
                and _can_pay(actor, action)
            ]

            if heal_actions:
                # Pick the best heal action
                best_heal = max(
                    heal_actions,
                    key=lambda a: sum(
                        _average_damage(e.get("amount", "0"), crit=False)
                        for e in a.get("effects", [])
                        if e.get("effect_type") == "heal"
                    ),
                )
                return ActionIntent(action_name=best_heal.get("name"))

        return super().choose_action(actor, state)

    def choose_targets(self, actor, intent, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action = next((entry for entry in catalog if entry.get("name") == intent.action_name), None)

        if action and any(e.get("effect_type") == "heal" for e in action.get("effects", [])):
            allies = [view for view in state.actors.values() if view.team == actor.team]
            critical_allies = [a for a in allies if a.hp <= 0 and not "dead" in a.conditions]
            low_allies = [a for a in allies if a.hp > 0 and a.hp < a.max_hp * 0.25]

            target_pool = critical_allies or low_allies or allies

            # Heal the one with lowest hp percentage
            target = min(target_pool, key=lambda a: (a.hp / max(a.max_hp, 1), a.hp))
            return [TargetRef(actor_id=target.actor_id)]

        return super().choose_targets(actor, intent, state)


class SkirmisherStrategy(OptimalExpectedDamageStrategy):
    def choose_action(self, actor, state):
        intent = super().choose_action(actor, state)

        # If no good action and movement remaining, or if we want to disengage/dodge
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]

        # Check if an enemy is adjacent (melee range)
        melee_enemies = [
            e for e in enemies if distance_chebyshev(actor.position, e.position) <= 5.0
        ]

        if melee_enemies and intent.action_name:
            action = next(
                (entry for entry in catalog if entry.get("name") == intent.action_name), None
            )
            if (
                action
                and action.get("action_type") == "attack"
                and float(action.get("range_ft", 5.0)) > 5.0
            ):
                # If we're using a ranged attack and an enemy is in melee, using Disengage and then moving is better
                # if we had proper movement modeling. Since we don't, we might just Disengage if we have it as a bonus action,
                # or we Dodge to survive.
                disengage = next(
                    (a for a in catalog if a.get("name") == "disengage" and _can_pay(actor, a)),
                    None,
                )
                if disengage and disengage.get("action_cost") == action.get("action_cost"):
                    return ActionIntent(action_name=disengage.get("name"))

        return intent
