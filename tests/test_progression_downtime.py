from __future__ import annotations

import pytest

from dnd_sim.progression import (
    CampaignProgression,
    XPUpdate,
    apply_xp_award,
    award_xp,
    craft_item,
    level_for_xp,
    recuperate,
    train_proficiency,
    work_for_wages,
    xp_to_next_level,
)


def test_level_for_xp_uses_2014_threshold_boundaries() -> None:
    assert level_for_xp(0) == 1
    assert level_for_xp(299) == 1
    assert level_for_xp(300) == 2
    assert level_for_xp(6499) == 4
    assert level_for_xp(6500) == 5
    assert level_for_xp(355000) == 20


def test_award_xp_returns_level_up_metadata() -> None:
    update = award_xp(current_xp=250, gained_xp=6250)
    assert isinstance(update, XPUpdate)
    assert update.starting_level == 1
    assert update.ending_level == 5
    assert update.levels_gained == 4
    assert update.ending_xp == 6500
    assert update.xp_to_next_level == 7500


def test_xp_to_next_level_returns_none_at_cap() -> None:
    assert xp_to_next_level(355000) is None
    assert xp_to_next_level(999999) is None


def test_apply_xp_award_updates_campaign_state_level_and_xp() -> None:
    start = CampaignProgression(
        level=1, xp=250, downtime_days=5, gold_gp=10, max_hp=12, current_hp=12
    )
    updated, xp_update = apply_xp_award(start, gained_xp=700)

    assert updated.xp == 950
    assert updated.level == 3
    assert xp_update.starting_level == 1
    assert xp_update.ending_level == 3
    assert start.level == 1
    assert start.xp == 250


def test_work_for_wages_consumes_days_and_increases_gold() -> None:
    start = CampaignProgression(
        level=3, xp=900, downtime_days=5, gold_gp=10, max_hp=24, current_hp=11
    )
    result = work_for_wages(start, days=3, gp_per_day=2)
    assert result.downtime_days == 2
    assert result.gold_gp == 16
    assert result.current_hp == 11


def test_recuperate_heals_and_caps_at_max_hp() -> None:
    start = CampaignProgression(
        level=4, xp=3000, downtime_days=4, gold_gp=0, max_hp=31, current_hp=20
    )
    result = recuperate(start, days=3)
    assert result.current_hp == 31
    assert result.downtime_days == 1


def test_train_proficiency_accumulates_progress_between_calls() -> None:
    start = CampaignProgression(
        level=5, xp=6500, downtime_days=15, gold_gp=25, max_hp=40, current_hp=40
    )
    mid = train_proficiency(start, proficiency="thieves_tools", days=6)
    done = train_proficiency(mid, proficiency="thieves_tools", days=4)

    assert "thieves_tools" not in mid.proficiencies
    assert mid.training_progress_days["thieves_tools"] == 6
    assert "thieves_tools" in done.proficiencies
    assert done.training_progress_days["thieves_tools"] == 0
    assert done.gold_gp == 15
    assert done.downtime_days == 5


def test_craft_item_uses_days_and_gold_per_item_batch() -> None:
    start = CampaignProgression(
        level=5, xp=6500, downtime_days=11, gold_gp=28, max_hp=40, current_hp=40
    )
    result = craft_item(
        start, item_name="healing_potion", days=10, days_per_item=5, gp_cost_per_item=12
    )

    assert result.inventory["healing_potion"] == 2
    assert result.gold_gp == 4
    assert result.downtime_days == 1


def test_downtime_activities_validate_resource_constraints() -> None:
    start = CampaignProgression(
        level=2, xp=300, downtime_days=1, gold_gp=0, max_hp=14, current_hp=10
    )

    with pytest.raises(ValueError, match="downtime days"):
        work_for_wages(start, days=2, gp_per_day=2)

    with pytest.raises(ValueError, match="gold"):
        train_proficiency(start, proficiency="arcana", days=1, gp_per_day=1)
