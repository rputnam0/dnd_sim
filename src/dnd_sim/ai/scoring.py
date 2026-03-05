from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable

from dnd_sim.spatial import distance_chebyshev
from dnd_sim.strategy_api import ActorView, BattleStateView

_EXPLICIT_TARGET_MODES = {
    "single_enemy",
    "single_ally",
    "n_enemies",
    "n_allies",
    "random_enemy",
    "random_ally",
}

_AUTO_TARGET_MODES = {"all_enemies", "all_allies", "all_creatures"}
_SUPPORTED_TARGET_MODES = _EXPLICIT_TARGET_MODES | _AUTO_TARGET_MODES | {"self"}


@dataclass(frozen=True, slots=True)
class RangeScoringInputs:
    distance_to_primary_ft: float
    action_range_ft: float
    movement_budget_ft: float
    requires_movement: bool
    reachable: bool


@dataclass(frozen=True, slots=True)
class HazardScoringInputs:
    active_hazard_count: int
    hazard_exposure_score: float
    estimated_affected_count: int
    friendly_fire_risk: bool


@dataclass(frozen=True, slots=True)
class ConcentrationScoringInputs:
    actor_concentrating: bool
    action_requires_concentration: bool
    recast_penalty_applies: bool
    actor_hp_ratio: float


@dataclass(frozen=True, slots=True)
class ControlScoringInputs:
    applied_condition_count: int
    forced_movement_count: int
    control_intensity: float


@dataclass(frozen=True, slots=True)
class ObjectiveScoringInputs:
    objective_tags: tuple[str, ...]
    objective_score: float


@dataclass(frozen=True, slots=True)
class ResourceScoringInputs:
    resource_cost: tuple[tuple[str, int], ...]
    total_cost: int
    resource_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateScoringInputs:
    range: RangeScoringInputs
    hazard: HazardScoringInputs
    concentration: ConcentrationScoringInputs
    control: ControlScoringInputs
    objective: ObjectiveScoringInputs
    resource: ResourceScoringInputs


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action_name: str
    action_type: str
    target_mode: str
    target_ids: tuple[str, ...]
    scoring_inputs: CandidateScoringInputs


def _action_catalog_for_actor(actor: ActorView, state: BattleStateView) -> list[dict[str, Any]]:
    raw = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
    return [entry for entry in raw if isinstance(entry, dict)]


def _available_action_names(actor: ActorView, state: BattleStateView) -> set[str] | None:
    raw = state.metadata.get("available_actions", {}).get(actor.actor_id)
    if raw is None:
        return None
    names = {str(action_name).strip() for action_name in raw if str(action_name).strip()}
    return names if names else set()


def _coerce_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _action_range_ft(action: dict[str, Any]) -> float:
    if isinstance(action.get("range_ft"), (int, float)):
        return float(action["range_ft"])
    if isinstance(action.get("range_normal_ft"), (int, float)):
        return float(action["range_normal_ft"])
    if isinstance(action.get("reach_ft"), (int, float)):
        return float(action["reach_ft"])

    action_type = str(action.get("action_type", "")).strip().lower()
    if action_type == "attack":
        return 5.0
    if action_type == "utility":
        return 30.0
    return 60.0


def _can_reach_target(actor: ActorView, action: dict[str, Any], target: ActorView) -> bool:
    if str(action.get("target_mode", "single_enemy")) == "self":
        return True
    action_range = _action_range_ft(action)
    distance = distance_chebyshev(actor.position, target.position)
    return distance <= action_range + float(actor.movement_remaining)


def _can_pay_resource_cost(actor: ActorView, action: dict[str, Any]) -> bool:
    resource_cost = action.get("resource_cost") or {}
    if not isinstance(resource_cost, dict):
        return False
    for key, amount in resource_cost.items():
        if int(actor.resources.get(str(key), 0)) < int(amount):
            return False
    return True


def _is_action_legal(actor: ActorView, action: dict[str, Any]) -> bool:
    target_mode = str(action.get("target_mode", "single_enemy")).strip().lower()
    if target_mode not in _SUPPORTED_TARGET_MODES:
        return False
    action_cost = str(action.get("action_cost", "action")).strip().lower()
    if action_cost in {"reaction", "legendary", "lair"}:
        return False
    max_uses = action.get("max_uses")
    if max_uses is not None and int(action.get("used_count", 0)) >= int(max_uses):
        return False
    if not bool(action.get("recharge_ready", True)):
        return False
    return _can_pay_resource_cost(actor, action)


def _living_pool_for_mode(
    actor: ActorView,
    state: BattleStateView,
    *,
    target_mode: str,
) -> list[ActorView]:
    living = [view for view in state.actors.values() if view.hp > 0]
    enemies = [view for view in living if view.team != actor.team]
    allies = [view for view in living if view.team == actor.team]

    if target_mode in {"single_enemy", "n_enemies", "random_enemy", "all_enemies"}:
        return sorted(enemies, key=lambda entry: entry.actor_id)
    if target_mode in {"single_ally", "n_allies", "random_ally", "all_allies"}:
        return sorted(allies, key=lambda entry: entry.actor_id)
    if target_mode == "all_creatures":
        return sorted(living, key=lambda entry: entry.actor_id)
    return []


def _enumerate_target_sets(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_mode: str,
) -> list[tuple[str, ...]]:
    if target_mode == "self":
        return [(actor.actor_id,)]

    pool = _living_pool_for_mode(actor, state, target_mode=target_mode)
    reachable = [target for target in pool if _can_reach_target(actor, action, target)]
    if not reachable:
        return []

    if target_mode in {"single_enemy", "single_ally", "random_enemy", "random_ally"}:
        return [(target.actor_id,) for target in reachable]

    if target_mode in {"n_enemies", "n_allies"}:
        max_targets = max(1, int(action.get("max_targets") or 1))
        choose_n = min(max_targets, len(reachable))
        return [
            tuple(target.actor_id for target in group)
            for group in combinations(reachable, choose_n)
        ]

    if target_mode in _AUTO_TARGET_MODES:
        return [tuple(target.actor_id for target in reachable)]

    return []


def _objective_tags(action: dict[str, Any]) -> tuple[str, ...]:
    tags = [str(tag).strip() for tag in action.get("tags", []) if str(tag).strip()]
    return tuple(tag for tag in tags if tag.startswith("objective"))


def _objective_score(action: dict[str, Any], state: BattleStateView) -> float:
    objective_scores = state.metadata.get("objective_scores", {})
    if not isinstance(objective_scores, dict):
        return 0.0

    total = float(objective_scores.get(str(action.get("name", "")), 0.0))
    for tag in _objective_tags(action):
        if ":" not in tag:
            continue
        _, objective_id = tag.split(":", 1)
        total += float(objective_scores.get(objective_id, 0.0))
    return total


def _resource_inputs(action: dict[str, Any]) -> ResourceScoringInputs:
    raw_cost = action.get("resource_cost") or {}
    if not isinstance(raw_cost, dict):
        raw_cost = {}

    normalized = {str(key): int(value) for key, value in raw_cost.items() if int(value) > 0}
    ordered_keys = tuple(sorted(normalized.keys()))
    ordered_cost = tuple((key, normalized[key]) for key in ordered_keys)
    total_cost = sum(value for _, value in ordered_cost)
    return ResourceScoringInputs(
        resource_cost=ordered_cost,
        total_cost=total_cost,
        resource_keys=ordered_keys,
    )


def _control_inputs(action: dict[str, Any]) -> ControlScoringInputs:
    applied_condition_count = 0
    forced_movement_count = 0
    for payload in _iter_effect_payloads(action):
        effect_type = str(payload.get("effect_type", "")).strip().lower()
        if effect_type == "apply_condition":
            applied_condition_count += 1
        if effect_type == "forced_movement":
            forced_movement_count += 1
    control_intensity = float(applied_condition_count + forced_movement_count)
    return ControlScoringInputs(
        applied_condition_count=applied_condition_count,
        forced_movement_count=forced_movement_count,
        control_intensity=control_intensity,
    )


def _iter_effect_payloads(action: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("effects", "mechanics"):
        raw = action.get(key, [])
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                yield entry


def _hazard_inputs(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
    target_ids: tuple[str, ...],
) -> HazardScoringInputs:
    active_hazards = state.metadata.get("active_hazards", [])
    active_hazard_count = len(active_hazards) if isinstance(active_hazards, list) else 0

    exposure_map = state.metadata.get("hazard_exposure_by_actor", {})
    if not isinstance(exposure_map, dict):
        exposure_map = {}
    hazard_exposure_score = float(
        sum(float(exposure_map.get(target_id, 0.0)) for target_id in target_ids)
    )

    estimated_affected_count = len(target_ids)
    friendly_fire_risk = any(
        target_id != actor.actor_id
        and target_id in state.actors
        and state.actors[target_id].team == actor.team
        for target_id in target_ids
    )

    aoe_radius = _coerce_positive_float(action.get("aoe_size_ft"))
    aoe_type = str(action.get("aoe_type", "")).strip().lower()
    include_self = bool(action.get("include_self", False))
    if aoe_type and aoe_radius is not None and primary_target is not None:
        estimated_affected_count = 0
        friendly_fire_risk = False
        for candidate in state.actors.values():
            if candidate.hp <= 0:
                continue
            if candidate.actor_id == actor.actor_id and not include_self:
                continue
            if distance_chebyshev(primary_target.position, candidate.position) > aoe_radius:
                continue
            estimated_affected_count += 1
            if candidate.actor_id != actor.actor_id and candidate.team == actor.team:
                friendly_fire_risk = True

    return HazardScoringInputs(
        active_hazard_count=active_hazard_count,
        hazard_exposure_score=hazard_exposure_score,
        estimated_affected_count=estimated_affected_count,
        friendly_fire_risk=friendly_fire_risk,
    )


def _range_inputs(
    actor: ActorView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
) -> RangeScoringInputs:
    action_range_ft = _action_range_ft(action)
    movement_budget_ft = float(actor.movement_remaining)
    if primary_target is None:
        return RangeScoringInputs(
            distance_to_primary_ft=0.0,
            action_range_ft=action_range_ft,
            movement_budget_ft=movement_budget_ft,
            requires_movement=False,
            reachable=True,
        )

    distance_to_primary = float(distance_chebyshev(actor.position, primary_target.position))
    reachable = distance_to_primary <= action_range_ft + movement_budget_ft
    requires_movement = distance_to_primary > action_range_ft
    return RangeScoringInputs(
        distance_to_primary_ft=distance_to_primary,
        action_range_ft=action_range_ft,
        movement_budget_ft=movement_budget_ft,
        requires_movement=requires_movement,
        reachable=reachable,
    )


def _concentration_inputs(
    actor: ActorView, *, action: dict[str, Any]
) -> ConcentrationScoringInputs:
    actor_hp_ratio = float(actor.hp) / float(max(actor.max_hp, 1))
    action_requires_concentration = bool(action.get("concentration", False))
    actor_concentrating = bool(actor.concentrating)
    return ConcentrationScoringInputs(
        actor_concentrating=actor_concentrating,
        action_requires_concentration=action_requires_concentration,
        recast_penalty_applies=actor_concentrating and action_requires_concentration,
        actor_hp_ratio=actor_hp_ratio,
    )


def _build_scoring_inputs(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_ids: tuple[str, ...],
) -> CandidateScoringInputs:
    primary_target = state.actors.get(target_ids[0]) if target_ids else None
    return CandidateScoringInputs(
        range=_range_inputs(actor, action=action, primary_target=primary_target),
        hazard=_hazard_inputs(
            actor,
            state,
            action=action,
            primary_target=primary_target,
            target_ids=target_ids,
        ),
        concentration=_concentration_inputs(actor, action=action),
        control=_control_inputs(action),
        objective=ObjectiveScoringInputs(
            objective_tags=_objective_tags(action),
            objective_score=_objective_score(action, state),
        ),
        resource=_resource_inputs(action),
    )


def enumerate_legal_action_candidates(
    actor: ActorView, state: BattleStateView
) -> list[ActionCandidate]:
    catalog = _action_catalog_for_actor(actor, state)
    available_names = _available_action_names(actor, state)

    candidates: list[ActionCandidate] = []
    for action in catalog:
        action_name = str(action.get("name", "")).strip()
        if not action_name:
            continue
        if available_names is not None and action_name not in available_names:
            continue
        if not _is_action_legal(actor, action):
            continue

        target_mode = str(action.get("target_mode", "single_enemy")).strip().lower()
        for target_ids in _enumerate_target_sets(
            actor,
            state,
            action=action,
            target_mode=target_mode,
        ):
            candidates.append(
                ActionCandidate(
                    action_name=action_name,
                    action_type=str(action.get("action_type", "")).strip().lower(),
                    target_mode=target_mode,
                    target_ids=target_ids,
                    scoring_inputs=_build_scoring_inputs(
                        actor,
                        state,
                        action=action,
                        target_ids=target_ids,
                    ),
                )
            )

    return sorted(candidates, key=lambda row: (row.action_name, row.target_ids))


def _resource_snapshot(resource: ResourceScoringInputs) -> dict[str, Any]:
    return {
        "resource_cost": {key: value for key, value in resource.resource_cost},
        "total_cost": resource.total_cost,
        "resource_keys": list(resource.resource_keys),
    }


def candidate_snapshots(candidates: list[ActionCandidate]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for row in candidates:
        snapshots.append(
            {
                "action_name": row.action_name,
                "action_type": row.action_type,
                "target_mode": row.target_mode,
                "target_ids": list(row.target_ids),
                "range": {
                    "distance_to_primary_ft": row.scoring_inputs.range.distance_to_primary_ft,
                    "action_range_ft": row.scoring_inputs.range.action_range_ft,
                    "movement_budget_ft": row.scoring_inputs.range.movement_budget_ft,
                    "requires_movement": row.scoring_inputs.range.requires_movement,
                    "reachable": row.scoring_inputs.range.reachable,
                },
                "hazard": {
                    "active_hazard_count": row.scoring_inputs.hazard.active_hazard_count,
                    "hazard_exposure_score": row.scoring_inputs.hazard.hazard_exposure_score,
                    "estimated_affected_count": row.scoring_inputs.hazard.estimated_affected_count,
                    "friendly_fire_risk": row.scoring_inputs.hazard.friendly_fire_risk,
                },
                "concentration": {
                    "actor_concentrating": row.scoring_inputs.concentration.actor_concentrating,
                    "action_requires_concentration": row.scoring_inputs.concentration.action_requires_concentration,
                    "recast_penalty_applies": row.scoring_inputs.concentration.recast_penalty_applies,
                    "actor_hp_ratio": row.scoring_inputs.concentration.actor_hp_ratio,
                },
                "control": {
                    "applied_condition_count": row.scoring_inputs.control.applied_condition_count,
                    "forced_movement_count": row.scoring_inputs.control.forced_movement_count,
                    "control_intensity": row.scoring_inputs.control.control_intensity,
                },
                "objective": {
                    "objective_tags": list(row.scoring_inputs.objective.objective_tags),
                    "objective_score": row.scoring_inputs.objective.objective_score,
                },
                "resource": _resource_snapshot(row.scoring_inputs.resource),
            }
        )
    return snapshots
