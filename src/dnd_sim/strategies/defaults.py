from __future__ import annotations

import math
from typing import Any

from dnd_sim.ai.scoring import (
    candidate_rejection_reason_for_action,
    candidate_snapshots,
    enumerate_legal_action_candidates,
)
from dnd_sim.rules_2014 import parse_damage_expression
from dnd_sim.spatial import check_cover, distance_chebyshev, has_clear_path, move_towards
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.telemetry import build_ai_action_rationale_trace, build_ai_candidate_scoring_trace

_EXPLICIT_TARGET_MODES = {
    "single_enemy",
    "single_ally",
    "n_enemies",
    "n_allies",
    "random_enemy",
    "random_ally",
}

_AUTO_TARGET_MODES = {"all_enemies", "all_allies", "all_creatures"}
_COVER_SCORE_PENALTIES = {
    "NONE": 0.0,
    "HALF": 0.5,
    "THREE_QUARTERS": 1.0,
    "TOTAL": 2.0,
}


def build_candidate_trace_rows(
    *,
    ranked_candidates: list[dict[str, Any]],
    excluded_candidates: list[dict[str, Any]],
    selected_action: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(ranked_candidates, start=1):
        action_name = str(candidate.get("name", "")).strip()
        if not action_name:
            continue
        is_selected = selected_action is not None and action_name == selected_action
        rows.append(
            {
                "action_name": action_name,
                "candidate_state": ("selected" if is_selected else "rejected"),
                "rejection_reason": (None if is_selected else "not_selected"),
                "rank": index,
                "cost": int(candidate.get("cost", 0)),
                "score_components": {
                    "base_score": float(candidate.get("base_score", 0.0)),
                    "objective_bonus": float(candidate.get("objective_bonus", 0.0)),
                    "lookahead_bonus": float(candidate.get("lookahead_bonus", 0.0)),
                    "total_score": float(candidate.get("total_score", 0.0)),
                },
            }
        )

    for candidate in excluded_candidates:
        action_name = str(candidate.get("name", "")).strip()
        if not action_name:
            continue
        rows.append(
            {
                "action_name": action_name,
                "candidate_state": "excluded",
                "rejection_reason": str(candidate.get("rejection_reason", "not_viable")),
                "rank": None,
                "cost": int(candidate.get("cost", 0)),
                "score_components": {
                    "base_score": 0.0,
                    "objective_bonus": 0.0,
                    "lookahead_bonus": 0.0,
                    "total_score": 0.0,
                },
            }
        )
    return rows


def _available_actions_for_actor(actor, state) -> list[str]:
    raw = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
    return [str(action_name) for action_name in raw if str(action_name)]


def _action_catalog_for_actor(actor, state) -> list[dict[str, Any]]:
    raw = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
    return [entry for entry in raw if isinstance(entry, dict)]


def _catalog_action_by_name(actor, state, action_name: str | None) -> dict[str, Any] | None:
    if not action_name:
        return None
    for action in _action_catalog_for_actor(actor, state):
        if str(action.get("name", "")) == action_name:
            return action
    return None


def _living_enemies(actor, state) -> list[Any]:
    return [view for view in state.actors.values() if view.team != actor.team and view.hp > 0]


def _living_allies(actor, state) -> list[Any]:
    return [view for view in state.actors.values() if view.team == actor.team and view.hp > 0]


def _basic_or_first_available_action(actor, state) -> str | None:
    available = _available_actions_for_actor(actor, state)
    if "basic" in available:
        return "basic"
    return available[0] if available else None


def _obstacles_from_state(state) -> list[Any]:
    obstacles = state.metadata.get("obstacles", [])
    return obstacles if isinstance(obstacles, list) else []


def _action_requires_line_of_effect(action: dict[str, Any]) -> bool:
    if str(action.get("target_mode", "single_enemy")) == "self":
        return False
    tags = {str(tag).strip().lower() for tag in action.get("tags", [])}
    if "ignore_line_of_effect" in tags or "ignore_total_cover" in tags:
        return False
    if "ignores_line_of_effect" in tags:
        return False
    if "requires_line_of_effect" in tags:
        return True
    action_type = str(action.get("action_type", "")).strip().lower()
    if action_type in {"attack", "save", "grapple", "shove"}:
        return True
    if "spell" in tags:
        return True
    for effect in [*action.get("effects", []), *action.get("mechanics", [])]:
        if not isinstance(effect, dict):
            continue
        if str(effect.get("effect_type", "")).strip().lower() in {
            "damage",
            "apply_condition",
            "forced_movement",
        }:
            return True
    return False


def _line_of_effect_is_clear(
    origin: tuple[float, float, float],
    target: Any,
    action: dict[str, Any],
    obstacles: list[Any],
) -> bool:
    if not obstacles or not _action_requires_line_of_effect(action):
        return True
    return check_cover(origin, target.position, obstacles) != "TOTAL"


def _coerce_position(position: tuple[float, float, float]) -> tuple[float, float, float]:
    return (float(position[0]), float(position[1]), float(position[2]))


def _movement_path_to_target(
    actor,
    target,
    action: dict[str, Any],
    *,
    actor_catalog: list[dict[str, Any]],
    obstacles: list[Any],
) -> list[tuple[float, float, float]] | None:
    origin = _coerce_position(actor.position)
    target_position = _coerce_position(target.position)
    action_range = _effective_action_range_ft(action, actor_catalog)
    if action_range is None:
        return []

    current_distance = distance_chebyshev(origin, target_position)
    if current_distance <= action_range:
        if _line_of_effect_is_clear(origin, target, action, obstacles):
            return []
        return None

    movement_remaining = float(actor.movement_remaining)
    if current_distance > action_range + movement_remaining:
        return None

    if obstacles and not has_clear_path(origin, target_position, obstacles):
        return None

    travel_distance = min(movement_remaining, max(0.0, current_distance - action_range))
    destination = move_towards(origin, target_position, travel_distance)
    destination = _coerce_position(destination)

    if obstacles and not has_clear_path(origin, destination, obstacles):
        return None
    if not _line_of_effect_is_clear(destination, target, action, obstacles):
        return None

    if destination == origin:
        return []
    return [origin, destination]


def _effective_action_range_ft(
    action: dict[str, Any],
    actor_catalog: list[dict[str, Any]],
) -> float | None:
    base_range = _action_range_ft(action)
    sequence_ranges: list[float] = []
    for mechanic in action.get("mechanics", []):
        if not isinstance(mechanic, dict):
            continue
        mechanic_type = str(mechanic.get("effect_type", "")).strip().lower()
        if mechanic_type not in {"attack_sequence", "multiattack_sequence"}:
            continue
        raw_sequence = mechanic.get("sequence")
        if raw_sequence is None:
            raw_sequence = mechanic.get("attacks")
        if not isinstance(raw_sequence, list):
            continue
        for row in raw_sequence:
            if isinstance(row, str):
                action_name = row.strip()
            elif isinstance(row, dict):
                action_name = str(row.get("action_name") or row.get("name") or "").strip()
            else:
                action_name = ""
            if not action_name:
                continue
            referenced = next(
                (
                    entry
                    for entry in actor_catalog
                    if str(entry.get("name", "")).strip() == action_name
                ),
                None,
            )
            if referenced is None:
                continue
            referenced_range = _action_range_ft(referenced)
            if referenced_range is not None:
                sequence_ranges.append(float(referenced_range))
    if sequence_ranges:
        return min(sequence_ranges)
    return base_range


def _declare_turn_for_action(
    actor,
    state,
    *,
    action_name: str | None,
    preferred_targets: list[TargetRef] | None = None,
    rationale: dict[str, Any] | None = None,
) -> TurnDeclaration:
    details = dict(rationale or {})
    if action_name is None:
        details.setdefault("reason", "no_available_actions")
        return TurnDeclaration(rationale=details)

    action = _catalog_action_by_name(actor, state, action_name)
    if action is None:
        details.setdefault("reason", "unknown_action")
        details.setdefault("action_name", action_name)
        return TurnDeclaration(rationale=details)

    mode = str(action.get("target_mode", "single_enemy"))
    obstacles = _obstacles_from_state(state)
    actor_catalog = _action_catalog_for_actor(actor, state)
    actors_by_id = state.actors
    requested = list(preferred_targets or [])

    if mode == "self":
        return TurnDeclaration(
            action=DeclaredAction(
                action_name=action_name,
                targets=[TargetRef(actor_id=actor.actor_id)],
                rationale=details,
            ),
            rationale=details,
        )

    if mode in _AUTO_TARGET_MODES:
        if mode == "all_enemies":
            pool = _living_enemies(actor, state)
        elif mode == "all_allies":
            pool = _living_allies(actor, state)
        else:
            pool = [entry for entry in state.actors.values() if entry.hp > 0]
        if not pool:
            details.setdefault("reason", "no_targets")
            details.setdefault("action_name", action_name)
            return TurnDeclaration(rationale=details)

        movement_path: list[tuple[float, float, float]] = []
        legal_anchor_found = False
        for candidate in pool:
            plan = _movement_path_to_target(
                actor,
                candidate,
                action,
                actor_catalog=actor_catalog,
                obstacles=obstacles,
            )
            if plan is None:
                continue
            movement_path = plan
            legal_anchor_found = True
            break
        if not legal_anchor_found:
            details.setdefault("reason", "no_legal_targets")
            details.setdefault("action_name", action_name)
            return TurnDeclaration(rationale=details)
        return TurnDeclaration(
            movement_path=movement_path,
            action=DeclaredAction(action_name=action_name, targets=[], rationale=details),
            rationale=details,
        )

    if not requested and mode in _EXPLICIT_TARGET_MODES:
        details.setdefault("reason", "missing_targets")
        details.setdefault("action_name", action_name)
        return TurnDeclaration(rationale=details)

    if mode not in _EXPLICIT_TARGET_MODES:
        # Unknown modes are treated conservatively to avoid invalid declarations.
        details.setdefault("reason", "unsupported_target_mode")
        details.setdefault("target_mode", mode)
        details.setdefault("action_name", action_name)
        return TurnDeclaration(rationale=details)

    legal_targets: list[TargetRef] = []
    movement_path: list[tuple[float, float, float]] | None = None
    seen: set[str] = set()
    for ref in requested:
        if ref.actor_id in seen:
            continue
        target = actors_by_id.get(ref.actor_id)
        if target is None or target.hp <= 0:
            continue
        candidate_path = _movement_path_to_target(
            actor,
            target,
            action,
            actor_catalog=actor_catalog,
            obstacles=obstacles,
        )
        if candidate_path is None:
            continue
        if movement_path is None:
            movement_path = candidate_path
        legal_targets.append(TargetRef(actor_id=ref.actor_id))
        seen.add(ref.actor_id)
        if mode in {"single_enemy", "single_ally", "random_enemy", "random_ally"}:
            break

    if not legal_targets:
        details.setdefault("reason", "no_legal_targets")
        details.setdefault("action_name", action_name)
        return TurnDeclaration(rationale=details)

    if mode in {"n_enemies", "n_allies"}:
        max_targets = int(action.get("max_targets") or len(legal_targets))
        legal_targets = legal_targets[:max_targets]
    else:
        legal_targets = legal_targets[:1]

    return TurnDeclaration(
        movement_path=movement_path or [],
        action=DeclaredAction(action_name=action_name, targets=legal_targets, rationale=details),
        rationale=details,
    )


def _lowest_hp_enemy_targets(actor, state) -> list[TargetRef]:
    enemies = _living_enemies(actor, state)
    if not enemies:
        return []
    target = min(enemies, key=lambda entry: (entry.hp, entry.max_hp))
    return [TargetRef(actor_id=target.actor_id)]


def _default_targets_for_action(actor, state, action_name: str | None) -> list[TargetRef]:
    action = _catalog_action_by_name(actor, state, action_name)
    enemies = _living_enemies(actor, state)
    allies = _living_allies(actor, state)

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
    return _lowest_hp_enemy_targets(actor, state)


class FocusFireLowestHPStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        action_name = _basic_or_first_available_action(actor, state)
        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=_lowest_hp_enemy_targets(actor, state),
        )


class BossHighestThreatTargetStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        action_name = _basic_or_first_available_action(actor, state)
        if action_name is None:
            return TurnDeclaration(rationale={"reason": "no_available_actions"})

        action = _catalog_action_by_name(actor, state, action_name)
        if action and action.get("target_mode") in {
            "self",
            "all_enemies",
            "all_allies",
            "all_creatures",
            "n_enemies",
            "n_allies",
        }:
            targets = _default_targets_for_action(actor, state, action_name)
        else:
            enemies = _living_enemies(actor, state)
            if not enemies:
                return TurnDeclaration(rationale={"reason": "no_targets"})
            threat_scores = state.metadata.get("threat_scores", {})
            target = max(
                enemies,
                key=lambda entry: (threat_scores.get(entry.actor_id, 0), -entry.hp),
            )
            targets = [TargetRef(actor_id=target.actor_id)]
        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=targets,
        )


class ConserveResourcesThenBurstStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        available = _available_actions_for_actor(actor, state)
        burst_threshold = int(state.metadata.get("burst_round_threshold", 3))
        action_name: str | None
        if state.round_number >= burst_threshold and "signature" in available:
            action_name = "signature"
        elif "basic" in available:
            action_name = "basic"
        else:
            action_name = available[0] if available else None

        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=_default_targets_for_action(actor, state, action_name),
        )


class AlwaysUseSignatureAbilityStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        available = _available_actions_for_actor(actor, state)
        action_name: str | None
        if "signature" in available:
            action_name = "signature"
        elif "basic" in available:
            action_name = "basic"
        else:
            action_name = available[0] if available else None

        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=_default_targets_for_action(actor, state, action_name),
        )


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


def _hazard_radius_ft(hazard: dict[str, Any]) -> float:
    for key in ("radius_ft", "radius", "aoe_size_ft"):
        parsed = _coerce_positive_distance(hazard.get(key))
        if parsed is not None:
            return parsed
    return 10.0


def _hazard_severity(hazard: dict[str, Any]) -> float:
    for key in ("severity", "weight", "risk"):
        parsed = _coerce_positive_distance(hazard.get(key))
        if parsed is not None:
            return parsed
    return 1.0


def _path_samples(path: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if not path:
        return []
    if len(path) == 1:
        return [_coerce_position(path[0])]
    samples: list[tuple[float, float, float]] = []
    for idx in range(len(path) - 1):
        start = _coerce_position(path[idx])
        end = _coerce_position(path[idx + 1])
        midpoint = (
            (start[0] + end[0]) / 2.0,
            (start[1] + end[1]) / 2.0,
            (start[2] + end[2]) / 2.0,
        )
        samples.extend((start, midpoint))
    samples.append(_coerce_position(path[-1]))
    return samples


def _hazard_exposure_penalty(
    actor,
    target,
    *,
    path: list[tuple[float, float, float]] | None,
    state,
) -> float:
    penalty = 0.0
    exposure_by_actor = state.metadata.get("hazard_exposure_by_actor", {})
    if isinstance(exposure_by_actor, dict):
        penalty += float(exposure_by_actor.get(str(actor.actor_id), 0.0))
        penalty += float(exposure_by_actor.get(str(target.actor_id), 0.0))

    active_hazards = state.metadata.get("active_hazards", [])
    if not isinstance(active_hazards, list) or path is None:
        return penalty

    sampled_points = _path_samples(path)
    if not sampled_points:
        return penalty

    for hazard in active_hazards:
        if not isinstance(hazard, dict):
            continue
        raw_position = hazard.get("position")
        if raw_position is None:
            continue
        try:
            center = _coerce_position(raw_position)
        except (TypeError, ValueError, IndexError):
            continue
        radius_ft = _hazard_radius_ft(hazard)
        if any(distance_chebyshev(point, center) <= radius_ft for point in sampled_points):
            penalty += _hazard_severity(hazard)
    return penalty


def _route_penalty(
    actor, target, action: dict[str, Any], *, path: list[tuple[float, float, float]] | None, state
) -> float:
    action_range = _effective_action_range_ft(action, _action_catalog_for_actor(actor, state))
    if action_range is None:
        return 0.0
    distance = distance_chebyshev(actor.position, target.position)
    if distance <= action_range:
        return 0.0
    if path is None:
        return 5.0

    movement_needed = max(0.0, distance - action_range)
    movement_budget = max(1.0, float(actor.movement_remaining))
    return min(2.5, movement_needed / movement_budget)


def _geometry_penalty(
    actor,
    target,
    action: dict[str, Any],
    *,
    path: list[tuple[float, float, float]] | None,
    state,
) -> float:
    if path is None:
        return 5.0 if _action_requires_line_of_effect(action) else 2.0
    obstacles = _obstacles_from_state(state)
    if not obstacles:
        return 0.0

    origin = actor.position if not path else path[-1]
    cover_level = check_cover(origin, target.position, obstacles)
    penalty = _COVER_SCORE_PENALTIES.get(cover_level, _COVER_SCORE_PENALTIES["TOTAL"])
    if _action_requires_line_of_effect(action) and cover_level == "TOTAL":
        penalty += 5.0
    return penalty


def _hazard_geometry_adjustment(action: dict[str, Any], target, actor, state) -> float:
    movement_path = _movement_path_to_target(
        actor,
        target,
        action,
        actor_catalog=_action_catalog_for_actor(actor, state),
        obstacles=_obstacles_from_state(state),
    )
    route_penalty = _route_penalty(actor, target, action, path=movement_path, state=state)
    hazard_penalty = _hazard_exposure_penalty(actor, target, path=movement_path, state=state)
    geometry_penalty = _geometry_penalty(actor, target, action, path=movement_path, state=state)
    return -(route_penalty + hazard_penalty + geometry_penalty)


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
        score *= score_multiplier
        score += _hazard_geometry_adjustment(action, target, actor, state)
        return score

    save_mod = (
        int(target.save_mods.get(action.get("save_ability", ""), 0))
        if action.get("action_type") == "save"
        else 0
    )
    score = (
        _expected_damage_against(action, target, save_mod=save_mod)
        * score_multiplier
        * max(1, _target_count_for_action(actor, state, action))
    )
    score += _hazard_geometry_adjustment(action, target, actor, state)
    return score


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
    return (
        candidate_rejection_reason_for_action(
            action,
            resources=resources,
            used_count=used_count,
        )
        == "unknown"
    )


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

    def declare_turn(self, actor, state):
        action_name, rationale = self._select_action(actor, state)
        targets = self._select_targets(actor, action_name, state) if action_name else []
        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=targets,
            rationale={"action_selection": rationale},
        )

    def _select_action(self, actor, state) -> tuple[str | None, dict[str, Any]]:
        catalog = _action_catalog_for_actor(actor, state)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        evaluation_mode = str(state.metadata.get("evaluation_mode", "greedy")).lower()
        if not catalog or not enemies:
            trace_events = [
                build_ai_candidate_scoring_trace(
                    actor_id=actor.actor_id,
                    team=actor.team,
                    strategy=self.__class__.__name__,
                    round_number=state.round_number,
                    selected_action=None,
                    evaluation_mode=evaluation_mode,
                    candidate_rows=[],
                    source=__name__,
                ),
                build_ai_action_rationale_trace(
                    actor_id=actor.actor_id,
                    team=actor.team,
                    strategy=self.__class__.__name__,
                    round_number=state.round_number,
                    selected_action=None,
                    evaluation_mode=evaluation_mode,
                    enabled_policies=[],
                    selected_candidate=None,
                    source=__name__,
                ),
            ]
            return None, {
                "reason": "no_actions_or_targets",
                "mode": evaluation_mode,
                "trace_events": trace_events,
            }

        policy = _strategy_policy(actor, state)
        concentration_cfg = _policy_section(policy, "concentration_protection")
        concentration_enabled = bool(concentration_cfg.get("enabled", False))
        hp_ratio = actor.hp / max(actor.max_hp, 1)

        enabled_policies = [
            name
            for name in ("threat_management", "concentration_protection", "objective_play")
            if bool(_policy_section(policy, name).get("enabled", False))
        ]

        def _trace_events(
            *,
            selected_action: str | None,
            selected_candidate: dict[str, Any] | None,
            candidate_rows: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            return [
                build_ai_candidate_scoring_trace(
                    actor_id=actor.actor_id,
                    team=actor.team,
                    strategy=self.__class__.__name__,
                    round_number=state.round_number,
                    selected_action=selected_action,
                    evaluation_mode=evaluation_mode,
                    candidate_rows=candidate_rows,
                    source=__name__,
                ),
                build_ai_action_rationale_trace(
                    actor_id=actor.actor_id,
                    team=actor.team,
                    strategy=self.__class__.__name__,
                    round_number=state.round_number,
                    selected_action=selected_action,
                    evaluation_mode=evaluation_mode,
                    enabled_policies=enabled_policies,
                    selected_candidate=selected_candidate,
                    source=__name__,
                ),
            ]

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
                selected = {
                    "name": "dodge",
                    "base_score": 0.0,
                    "objective_bonus": 0.0,
                    "lookahead_bonus": 0.0,
                    "total_score": 0.0,
                    "cost": sum(int(v) for v in (dodge.get("resource_cost") or {}).values()),
                }
                candidate_rows = build_candidate_trace_rows(
                    ranked_candidates=[selected],
                    excluded_candidates=[],
                    selected_action="dodge",
                )
                return "dodge", {
                    "mode": "policy_guardrail",
                    "guardrail": "concentration_protection",
                    "hp_ratio": hp_ratio,
                    "trace_events": _trace_events(
                        selected_action="dodge",
                        selected_candidate=selected,
                        candidate_rows=candidate_rows,
                    ),
                }

        lookahead_enabled = evaluation_mode == "lookahead"
        lookahead_discount = float(state.metadata.get("lookahead_discount", 1.0))
        tactical_branches = state.metadata.get("tactical_branches", {})
        branch_map = tactical_branches if isinstance(tactical_branches, dict) else {}
        normalized_candidates = enumerate_legal_action_candidates(actor, state)
        if not normalized_candidates:
            return None, {"reason": "no_viable_actions"}
        normalized_snapshots = candidate_snapshots(normalized_candidates)
        legal_action_names = {row.action_name for row in normalized_candidates}
        available_action_names = set(_available_actions_for_actor(actor, state))
        legal_enemy_target_ids_by_action: dict[str, set[str]] = {}
        normalized_inputs_by_action: dict[str, list[dict[str, Any]]] = {}
        for index, row in enumerate(normalized_candidates):
            normalized_inputs_by_action.setdefault(row.action_name, []).append(
                normalized_snapshots[index]
            )
            targets = legal_enemy_target_ids_by_action.setdefault(row.action_name, set())
            for target_id in row.target_ids:
                target_view = state.actors.get(target_id)
                if target_view is None or target_view.hp <= 0 or target_view.team == actor.team:
                    continue
                targets.add(target_id)

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
        excluded_candidates: list[dict[str, Any]] = []
        for action in catalog:
            action_name = str(action.get("name", ""))
            if available_action_names and action_name not in available_action_names:
                continue
            used = int(action.get("used_count", 0))
            if action_name not in legal_action_names:
                rejection_reason = candidate_rejection_reason_for_action(
                    action,
                    resources=actor.resources,
                    used_count=used,
                )
                excluded_candidates.append(
                    {
                        "name": action_name,
                        "cost": sum(int(v) for v in (action.get("resource_cost") or {}).values()),
                        "rejection_reason": (
                            rejection_reason if rejection_reason != "unknown" else "not_viable"
                        ),
                    }
                )
                continue

            reachable_ids = legal_enemy_target_ids_by_action.get(action_name, set())
            reachable = [target for target in enemies if target.actor_id in reachable_ids]
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
                    "normalized_candidates": normalized_inputs_by_action.get(action_name, [])[:3],
                }
            )

        if not candidates:
            candidate_rows = build_candidate_trace_rows(
                ranked_candidates=[],
                excluded_candidates=excluded_candidates,
                selected_action=None,
            )
            return None, {
                "reason": "no_viable_actions",
                "mode": evaluation_mode,
                "enabled_policies": enabled_policies,
                "trace_events": _trace_events(
                    selected_action=None,
                    selected_candidate=None,
                    candidate_rows=candidate_rows,
                ),
            }

        ranked = sorted(candidates, key=lambda row: (-row["total_score"], row["cost"], row["name"]))
        best = ranked[0]
        candidate_rows = build_candidate_trace_rows(
            ranked_candidates=ranked,
            excluded_candidates=excluded_candidates,
            selected_action=best["name"],
        )

        return best["name"], {
            "mode": evaluation_mode,
            "selected": best,
            "top_candidates": ranked[:3],
            "candidate_count": len(normalized_candidates),
            "enabled_policies": enabled_policies,
            "trace_events": _trace_events(
                selected_action=str(best["name"]),
                selected_candidate=best,
                candidate_rows=candidate_rows,
            ),
        }

    def _select_targets(self, actor, action_name: str, state) -> list[TargetRef]:
        catalog = _action_catalog_for_actor(actor, state)
        action = next((entry for entry in catalog if entry.get("name") == action_name), None)
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
    def _select_targets(self, actor, action_name: str, state) -> list[TargetRef]:
        catalog = _action_catalog_for_actor(actor, state)
        action = next((entry for entry in catalog if entry.get("name") == action_name), None)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]

        if not enemies or not action or action.get("target_mode") not in {"single_enemy"}:
            return super()._select_targets(actor, action_name, state)

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
    def _select_action(self, actor, state) -> tuple[str | None, dict[str, Any]]:
        catalog = _action_catalog_for_actor(actor, state)
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
                chosen_name = str(best_heal.get("name", "")).strip() or None
                return chosen_name, {
                    "mode": "healer_priority",
                    "target_pool": ("critical_allies" if critical_allies else "low_allies"),
                    "selected_heal_action": chosen_name,
                }

        return super()._select_action(actor, state)

    def _select_targets(self, actor, action_name: str, state) -> list[TargetRef]:
        catalog = _action_catalog_for_actor(actor, state)
        action = next((entry for entry in catalog if entry.get("name") == action_name), None)

        if action and any(e.get("effect_type") == "heal" for e in action.get("effects", [])):
            allies = [view for view in state.actors.values() if view.team == actor.team]
            critical_allies = [a for a in allies if a.hp <= 0 and not "dead" in a.conditions]
            low_allies = [a for a in allies if a.hp > 0 and a.hp < a.max_hp * 0.25]

            target_pool = critical_allies or low_allies or allies

            # Heal the one with lowest hp percentage
            target = min(target_pool, key=lambda a: (a.hp / max(a.max_hp, 1), a.hp))
            return [TargetRef(actor_id=target.actor_id)]

        return super()._select_targets(actor, action_name, state)


class SkirmisherStrategy(OptimalExpectedDamageStrategy):
    def _select_action(self, actor, state) -> tuple[str | None, dict[str, Any]]:
        action_name, rationale = super()._select_action(actor, state)

        # If no good action and movement remaining, or if we want to disengage/dodge
        catalog = _action_catalog_for_actor(actor, state)
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]

        # Check if an enemy is adjacent (melee range)
        melee_enemies = [
            e for e in enemies if distance_chebyshev(actor.position, e.position) <= 5.0
        ]

        if melee_enemies and action_name:
            action = next((entry for entry in catalog if entry.get("name") == action_name), None)
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
                    disengage_name = str(disengage.get("name", "")).strip() or None
                    return disengage_name, {
                        "mode": "skirmisher_defensive_swap",
                        "replaced_action": action_name,
                        "base_rationale": rationale,
                    }

        return action_name, rationale
