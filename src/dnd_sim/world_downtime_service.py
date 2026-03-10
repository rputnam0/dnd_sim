from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dnd_sim.economy import CraftingProject, CraftingRecipe, apply_crafting_days
from dnd_sim.world_exploration_service import advance_world_clock, create_exploration_state
from dnd_sim.world_contracts import (
    ENCUMBRANCE_ENCUMBERED,
    ENCUMBRANCE_HEAVILY_ENCUMBERED,
    ENCUMBRANCE_OVER_CAPACITY,
    ENCUMBRANCE_UNENCUMBERED,
    DowntimeActionResult,
    DowntimeState,
    EncumbranceStatus,
    MINUTES_PER_DAY,
    _normalize_crafting_project_mapping,
    _required_int,
    _required_non_negative_number,
    _required_text,
)


def create_downtime_state(
    *,
    day: int,
    hour: int,
    minute: int,
    downtime_days_remaining: int,
    wallet_cp: int,
    strength_score: int,
    carried_weight_lb: float = 0.0,
    inventory: Mapping[str, int] | None = None,
    crafting_projects: Mapping[str, CraftingProject | Mapping[str, Any]] | None = None,
    service_effects: Mapping[str, int] | None = None,
    location_id: str | None = None,
    turn_index: int = 0,
) -> DowntimeState:
    exploration_state = create_exploration_state(
        day=day,
        hour=hour,
        minute=minute,
        location_id=location_id,
        turn_index=turn_index,
    )

    normalized_projects = _normalize_crafting_project_mapping(crafting_projects or {})
    return DowntimeState(
        clock=exploration_state.clock,
        turn_index=exploration_state.turn_index,
        downtime_days_remaining=downtime_days_remaining,
        wallet_cp=wallet_cp,
        strength_score=strength_score,
        carried_weight_lb=carried_weight_lb,
        inventory=dict(inventory or {}),
        crafting_projects=normalized_projects,
        service_effects=dict(service_effects or {}),
        location_id=exploration_state.location_id,
    )


def assess_encumbrance(
    *,
    carried_weight_lb: float,
    strength_score: int,
) -> EncumbranceStatus:
    weight = _required_non_negative_number(carried_weight_lb, field_name="carried_weight_lb")
    strength = _required_int(strength_score, field_name="strength_score")
    if strength <= 0:
        raise ValueError("strength_score must be > 0")

    light_threshold = strength * 5.0
    heavy_threshold = strength * 10.0
    max_threshold = strength * 15.0

    if weight <= light_threshold:
        state = ENCUMBRANCE_UNENCUMBERED
        speed_penalty = 0
        travel_allowed = True
    elif weight <= heavy_threshold:
        state = ENCUMBRANCE_ENCUMBERED
        speed_penalty = 10
        travel_allowed = True
    elif weight <= max_threshold:
        state = ENCUMBRANCE_HEAVILY_ENCUMBERED
        speed_penalty = 20
        travel_allowed = True
    else:
        state = ENCUMBRANCE_OVER_CAPACITY
        speed_penalty = 20
        travel_allowed = False

    return EncumbranceStatus(
        carried_weight_lb=weight,
        strength_score=strength,
        light_threshold_lb=light_threshold,
        heavy_threshold_lb=heavy_threshold,
        max_threshold_lb=max_threshold,
        state=state,
        speed_penalty_ft=speed_penalty,
        travel_allowed=travel_allowed,
    )


def run_crafting_downtime(
    state: DowntimeState,
    *,
    recipe: CraftingRecipe,
    days: int,
) -> DowntimeActionResult:
    if not isinstance(state, DowntimeState):
        raise ValueError("state must be DowntimeState")
    if not isinstance(recipe, CraftingRecipe):
        raise ValueError("recipe must be CraftingRecipe")

    downtime_days = _required_int(days, field_name="days")
    if downtime_days <= 0:
        raise ValueError("days must be > 0")
    if downtime_days > state.downtime_days_remaining:
        raise ValueError("downtime_days exceeds available downtime")

    existing_project = state.crafting_projects.get(
        recipe.recipe_id,
        CraftingProject(recipe_id=recipe.recipe_id, accrued_days=0),
    )
    resolution = apply_crafting_days(
        recipe=recipe,
        project=existing_project,
        days=downtime_days,
        available_cp=state.wallet_cp,
    )

    next_inventory = dict(state.inventory)
    for item_id, quantity in resolution.inventory_delta.items():
        next_inventory[item_id] = next_inventory.get(item_id, 0) + quantity

    next_projects = dict(state.crafting_projects)
    next_projects[recipe.recipe_id] = resolution.project

    elapsed_minutes = downtime_days * MINUTES_PER_DAY
    next_clock = advance_world_clock(state.clock, elapsed_minutes=elapsed_minutes)
    next_turn_index = state.turn_index + 1
    next_weight = state.carried_weight_lb + (
        resolution.completed_batches * recipe.output_quantity * recipe.output_weight_lb
    )

    encumbrance = assess_encumbrance(
        carried_weight_lb=next_weight,
        strength_score=state.strength_score,
    )

    next_state = DowntimeState(
        clock=next_clock,
        turn_index=next_turn_index,
        downtime_days_remaining=state.downtime_days_remaining - downtime_days,
        wallet_cp=state.wallet_cp - resolution.cost_paid_cp,
        strength_score=state.strength_score,
        carried_weight_lb=next_weight,
        inventory=next_inventory,
        crafting_projects=next_projects,
        service_effects=state.service_effects,
        location_id=state.location_id,
    )

    return DowntimeActionResult(
        state=next_state,
        action=f"craft:{recipe.recipe_id}",
        downtime_days_spent=downtime_days,
        elapsed_minutes=elapsed_minutes,
        completed_batches=resolution.completed_batches,
        cost_paid_cp=resolution.cost_paid_cp,
        encumbrance=encumbrance,
    )


def run_service_action(
    state: DowntimeState,
    *,
    service_id: str,
    downtime_days: int,
    cost_cp: int,
    effect_id: str | None = None,
    effect_stacks: int = 1,
) -> DowntimeActionResult:
    if not isinstance(state, DowntimeState):
        raise ValueError("state must be DowntimeState")

    normalized_service_id = _required_text(service_id, field_name="service_id")
    days = _required_int(downtime_days, field_name="downtime_days")
    if days <= 0:
        raise ValueError("downtime_days must be > 0")
    if days > state.downtime_days_remaining:
        raise ValueError("downtime_days exceeds available downtime")

    service_cost_cp = _required_int(cost_cp, field_name="cost_cp")
    if service_cost_cp < 0:
        raise ValueError("cost_cp must be >= 0")
    if service_cost_cp > state.wallet_cp:
        raise ValueError("Insufficient currency")

    stacks = _required_int(effect_stacks, field_name="effect_stacks")
    if stacks <= 0:
        raise ValueError("effect_stacks must be > 0")
    normalized_effect_id = _required_text(
        effect_id if effect_id is not None else normalized_service_id,
        field_name="effect_id",
    )

    elapsed_minutes = days * MINUTES_PER_DAY
    next_clock = advance_world_clock(state.clock, elapsed_minutes=elapsed_minutes)
    next_effects = dict(state.service_effects)
    next_effects[normalized_effect_id] = next_effects.get(normalized_effect_id, 0) + stacks

    next_state = DowntimeState(
        clock=next_clock,
        turn_index=state.turn_index + 1,
        downtime_days_remaining=state.downtime_days_remaining - days,
        wallet_cp=state.wallet_cp - service_cost_cp,
        strength_score=state.strength_score,
        carried_weight_lb=state.carried_weight_lb,
        inventory=state.inventory,
        crafting_projects=state.crafting_projects,
        service_effects=next_effects,
        location_id=state.location_id,
    )

    return DowntimeActionResult(
        state=next_state,
        action=f"service:{normalized_service_id}",
        downtime_days_spent=days,
        elapsed_minutes=elapsed_minutes,
        cost_paid_cp=service_cost_cp,
        encumbrance=assess_encumbrance(
            carried_weight_lb=next_state.carried_weight_lb,
            strength_score=next_state.strength_score,
        ),
    )
