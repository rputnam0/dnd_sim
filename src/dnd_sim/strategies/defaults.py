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
    effects = action.get("effects") or []

    def effect_damage_weight(
        effect: dict[str, Any], *, hit: float, crit: float, fail: float
    ) -> float:
        if effect.get("effect_type") != "damage":
            return 0.0
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

    if action["action_type"] == "attack":
        to_hit = int(action.get("to_hit") or 0)
        normal_hit, crit_hit = _attack_hit_prob(to_hit, target.ac)
        base = _average_damage(action.get("damage"), crit=False)
        crit = _average_damage(action.get("damage"), crit=True)
        action_hits = max(1, int(action.get("attack_count") or 1))
        rider = sum(
            effect_damage_weight(
                effect, hit=normal_hit, crit=crit_hit, fail=1.0 - normal_hit - crit_hit
            )
            * _average_damage(effect.get("damage"), crit=False)
            for effect in effects
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
            effect_damage_weight(effect, hit=0.0, crit=0.0, fail=fail_prob)
            * _average_damage(effect.get("damage"), crit=False)
            for effect in effects
            if effect.get("target", "target") == "target"
        )
        return fail_prob * base + success_prob * success_damage + rider
    if action["action_type"] == "utility":
        return sum(
            _average_damage(effect.get("damage"), crit=False)
            for effect in effects
            if effect.get("effect_type") == "damage"
            and effect.get("target", "target") == "target"
            and effect.get("apply_on", "always") == "always"
        )
    return 0.0


def _evaluate_action_score(action: dict, target, actor, state) -> float:
    from dnd_sim.spatial import can_see

    multiplier = 1.0
    if not can_see(
        observer_pos=actor.position,
        target_pos=target.position,
        observer_traits=actor.traits,
        target_conditions=target.conditions,
        active_hazards=state.metadata.get("active_hazards", []),
        light_level=str(state.metadata.get("light_level", "bright")),
    ):
        multiplier = 0.5

    aoe_type = action.get("aoe_type")
    aoe_size = action.get("aoe_size_ft")
    if aoe_type and aoe_size:
        radius = float(aoe_size)
        score = 0.0
        for candidate in state.actors.values():
            if candidate.hp <= 0:
                continue
            if distance_chebyshev(target.position, candidate.position) > radius:
                continue
            if candidate.actor_id == actor.actor_id and not action.get("include_self", False):
                continue
            save_mod = (
                int(candidate.save_mods.get(action.get("save_ability", ""), 0))
                if action.get("action_type") == "save"
                else 0
            )
            expected = _expected_damage_against(action, candidate, save_mod=save_mod)
            if candidate.team != actor.team:
                score += expected
            else:
                score -= expected * 1.5
        return score * multiplier

    save_mod = (
        int(target.save_mods.get(action.get("save_ability", ""), 0))
        if action.get("action_type") == "save"
        else 0
    )
    return (
        _expected_damage_against(action, target, save_mod=save_mod)
        * multiplier
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

            score = max(_evaluate_action_score(action, target, actor, state) for target in enemies)

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
        if action and action.get("target_mode") == "n_enemies":
            count = int(action.get("max_targets") or 1)
            ranked = sorted(enemies, key=lambda entry: (entry.hp, entry.max_hp))
            return [TargetRef(actor_id=entry.actor_id) for entry in ranked[:count]]
        if action and action.get("target_mode") == "n_allies":
            count = int(action.get("max_targets") or 1)
            ranked = sorted(allies, key=lambda entry: (entry.hp / max(entry.max_hp, 1), entry.hp))
            return [TargetRef(actor_id=entry.actor_id) for entry in ranked[:count]]

        if not enemies:
            return []
        if not action:
            target = min(enemies, key=lambda entry: (entry.hp, entry.max_hp))
            return [TargetRef(actor_id=target.actor_id)]

        if action.get("action_type") == "save":
            save_ability = str(action.get("save_ability") or "").lower()
            target = min(enemies, key=lambda entry: int(entry.save_mods.get(save_ability, 0)))
            return [TargetRef(actor_id=target.actor_id)]

        target = max(
            enemies,
            key=lambda entry: _expected_damage_against(action, entry),
        )
        return [TargetRef(actor_id=target.actor_id)]
