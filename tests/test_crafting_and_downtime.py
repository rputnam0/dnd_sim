from __future__ import annotations

import pytest

from dnd_sim.economy import CraftingRecipe
from dnd_sim.world_downtime_service import (
    assess_encumbrance,
    create_downtime_state,
    run_crafting_downtime,
    run_service_action,
)


def test_run_crafting_downtime_completes_batches_and_updates_state() -> None:
    state = create_downtime_state(
        day=3,
        hour=9,
        minute=0,
        downtime_days_remaining=8,
        wallet_cp=900,
        strength_score=10,
    )
    recipe = CraftingRecipe(
        recipe_id="potion_of_healing",
        output_item_id="healing_potion",
        output_quantity=1,
        days_required=2,
        material_cost_cp=250,
        output_weight_lb=0.5,
    )

    result = run_crafting_downtime(
        state,
        recipe=recipe,
        days=4,
    )

    assert result.completed_batches == 2
    assert result.cost_paid_cp == 500
    assert result.state.wallet_cp == 400
    assert result.state.downtime_days_remaining == 4
    assert result.state.inventory == {"healing_potion": 2}
    assert result.state.crafting_projects["potion_of_healing"].accrued_days == 0
    assert result.state.clock.day == 7
    assert result.state.clock.hour == 9


def test_run_crafting_downtime_persists_partial_progress() -> None:
    recipe = CraftingRecipe(
        recipe_id="arrow_batch",
        output_item_id="arrow",
        output_quantity=20,
        days_required=3,
        material_cost_cp=100,
    )
    first = run_crafting_downtime(
        create_downtime_state(
            day=1,
            hour=8,
            minute=30,
            downtime_days_remaining=6,
            wallet_cp=500,
            strength_score=10,
        ),
        recipe=recipe,
        days=2,
    )
    second = run_crafting_downtime(first.state, recipe=recipe, days=1)

    assert first.completed_batches == 0
    assert first.state.crafting_projects["arrow_batch"].accrued_days == 2
    assert second.completed_batches == 1
    assert second.state.inventory["arrow"] == 20
    assert second.state.wallet_cp == 400
    assert second.state.crafting_projects["arrow_batch"].accrued_days == 0


def test_assess_encumbrance_uses_variant_thresholds() -> None:
    unencumbered = assess_encumbrance(carried_weight_lb=49.9, strength_score=10)
    encumbered = assess_encumbrance(carried_weight_lb=50.1, strength_score=10)
    heavy = assess_encumbrance(carried_weight_lb=100.1, strength_score=10)
    over = assess_encumbrance(carried_weight_lb=151.0, strength_score=10)

    assert unencumbered.state == "unencumbered"
    assert unencumbered.speed_penalty_ft == 0
    assert encumbered.state == "encumbered"
    assert encumbered.speed_penalty_ft == 10
    assert heavy.state == "heavily_encumbered"
    assert heavy.speed_penalty_ft == 20
    assert over.state == "over_capacity"
    assert over.travel_allowed is False


def test_run_service_action_spends_downtime_and_records_effect() -> None:
    state = create_downtime_state(
        day=10,
        hour=12,
        minute=0,
        downtime_days_remaining=5,
        wallet_cp=650,
        strength_score=12,
    )

    result = run_service_action(
        state,
        service_id="hire_guide",
        downtime_days=2,
        cost_cp=300,
        effect_id="guided_travel_days",
        effect_stacks=2,
    )

    assert result.state.wallet_cp == 350
    assert result.state.downtime_days_remaining == 3
    assert result.state.service_effects["guided_travel_days"] == 2
    assert result.state.clock.day == 12
    assert result.state.clock.hour == 12
    assert result.action == "service:hire_guide"


def test_run_service_action_rejects_illegal_window_or_funds() -> None:
    state = create_downtime_state(
        day=2,
        hour=8,
        minute=0,
        downtime_days_remaining=1,
        wallet_cp=100,
        strength_score=10,
    )

    with pytest.raises(ValueError, match="downtime_days exceeds available downtime"):
        run_service_action(
            state,
            service_id="temple_healing",
            downtime_days=2,
            cost_cp=50,
        )

    with pytest.raises(ValueError, match="Insufficient currency"):
        run_service_action(
            state,
            service_id="temple_healing",
            downtime_days=1,
            cost_cp=200,
        )
