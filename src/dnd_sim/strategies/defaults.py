from __future__ import annotations

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

    all_effects = action.get("effects", []) + action.get("mechanics", [])

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

    if aoe_type and aoe_size:
        radius = float(aoe_size)
        score = 0.0
        for cand in state.actors.values():
            if cand.hp > 0 and distance_chebyshev(target.position, cand.position) <= radius:
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


def _can_pay(actor, action: dict) -> bool:
    for key, amount in (action.get("resource_cost") or {}).items():
        if actor.resources.get(key, 0) < int(amount):
            return False
    return True


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
            return ActionIntent(action_name=None)

        def _can_reach(actor, action: dict, target) -> bool:
            if action.get("action_type") == "attack":
                action_range = float(action.get("range_ft") or 5.0)
            elif action.get("action_type") == "utility":
                action_range = float(action.get("range_ft") or 30.0)
            else:
                action_range = float(action.get("range_ft") or 60.0)
            return distance_chebyshev(actor.position, target.position) <= (
                action_range + actor.movement_remaining
            )

        best_name = None
        best_score = -1.0
        best_cost = 10**9

        for action in catalog:
            if action.get("action_cost") in {"legendary", "lair", "reaction"}:
                continue
            max_uses = action.get("max_uses")
            used = int(action.get("used_count", 0))
            if max_uses is not None and used >= int(max_uses):
                continue
            if not bool(action.get("recharge_ready", True)):
                continue
            if not _can_pay(actor, action):
                continue

            score = 0.0
            reachable = [t for t in enemies if _can_reach(actor, action, t)]
            if reachable:
                score = max(
                    _evaluate_action_score(action, target, actor, state) for target in reachable
                )

            cost = sum(int(v) for v in (action.get("resource_cost") or {}).values())
            if score > best_score or (score == best_score and cost < best_cost):
                best_score = score
                best_name = action.get("name")
                best_cost = cost

        return ActionIntent(action_name=best_name)

    def choose_targets(self, actor, intent, state):
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action = next((entry for entry in catalog if entry.get("name") == intent.action_name), None)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        allies = [view for view in state.actors.values() if view.team == actor.team and view.hp > 0]

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
            if action and action.get("action_type") == "attack":
                action_range = float(action.get("range_ft") or 5.0)
            elif action and action.get("action_type") == "utility":
                action_range = float(action.get("range_ft") or 30.0)
            else:
                action_range = float(action.get("range_ft") or 60.0)
            return distance_chebyshev(actor.position, target.position) <= (
                action_range + actor.movement_remaining
            )

        if action and action.get("target_mode") == "n_enemies":
            count = int(action.get("max_targets") or 1)
            reachable = [e for e in enemies if _can_reach(e)]
            pool = reachable if reachable else enemies
            ranked = sorted(pool, key=lambda entry: (entry.hp, entry.max_hp))
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

        if action.get("action_type") == "save" and not action.get("aoe_type"):
            save_ability = str(action.get("save_ability") or "").lower()
            target = min(pool, key=lambda entry: int(entry.save_mods.get(save_ability, 0)))
            return [TargetRef(actor_id=target.actor_id)]

        target = max(
            pool,
            key=lambda entry: _evaluate_action_score(action, entry, actor, state),
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
