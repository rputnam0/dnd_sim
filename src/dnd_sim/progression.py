from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# D&D 5e (2014) cumulative XP thresholds.
XP_LEVEL_THRESHOLDS: dict[int, int] = {
    1: 0,
    2: 300,
    3: 900,
    4: 2700,
    5: 6500,
    6: 14000,
    7: 23000,
    8: 34000,
    9: 48000,
    10: 64000,
    11: 85000,
    12: 100000,
    13: 120000,
    14: 140000,
    15: 165000,
    16: 195000,
    17: 225000,
    18: 265000,
    19: 305000,
    20: 355000,
}

MAX_LEVEL = max(XP_LEVEL_THRESHOLDS)


@dataclass(slots=True, frozen=True)
class XPUpdate:
    starting_xp: int
    ending_xp: int
    starting_level: int
    ending_level: int
    levels_gained: int
    xp_to_next_level: int | None


@dataclass(slots=True)
class CampaignProgression:
    level: int
    xp: int
    downtime_days: int
    gold_gp: int
    max_hp: int
    current_hp: int
    proficiencies: set[str] = field(default_factory=set)
    training_progress_days: dict[str, int] = field(default_factory=dict)
    inventory: dict[str, int] = field(default_factory=dict)


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _clone_state(state: CampaignProgression) -> CampaignProgression:
    return CampaignProgression(
        level=state.level,
        xp=state.xp,
        downtime_days=state.downtime_days,
        gold_gp=state.gold_gp,
        max_hp=state.max_hp,
        current_hp=state.current_hp,
        proficiencies=set(state.proficiencies),
        training_progress_days=dict(state.training_progress_days),
        inventory=dict(state.inventory),
    )


def _assert_enough_downtime_days(state: CampaignProgression, days: int) -> None:
    if days > state.downtime_days:
        raise ValueError("not enough downtime days available")


def _assert_enough_gold(state: CampaignProgression, cost_gp: int) -> None:
    if state.gold_gp < cost_gp:
        raise ValueError("not enough gold available")


def level_for_xp(xp: int) -> int:
    """Return the character level for a cumulative XP total."""
    _require_non_negative("xp", xp)
    level = 1
    for candidate_level, threshold in XP_LEVEL_THRESHOLDS.items():
        if xp >= threshold:
            level = candidate_level
        else:
            break
    return level


def xp_to_next_level(xp: int) -> int | None:
    """Return remaining XP required for the next level, or None at the cap."""
    _require_non_negative("xp", xp)
    level = level_for_xp(xp)
    if level >= MAX_LEVEL:
        return None
    next_threshold = XP_LEVEL_THRESHOLDS[level + 1]
    return max(0, next_threshold - xp)


def award_xp(current_xp: int, gained_xp: int) -> XPUpdate:
    """Apply an XP award and return level progression metadata."""
    _require_non_negative("current_xp", current_xp)
    _require_non_negative("gained_xp", gained_xp)
    starting_level = level_for_xp(current_xp)
    ending_xp = current_xp + gained_xp
    ending_level = level_for_xp(ending_xp)
    return XPUpdate(
        starting_xp=current_xp,
        ending_xp=ending_xp,
        starting_level=starting_level,
        ending_level=ending_level,
        levels_gained=max(0, ending_level - starting_level),
        xp_to_next_level=xp_to_next_level(ending_xp),
    )


def apply_xp_award(
    state: CampaignProgression,
    *,
    gained_xp: int,
) -> tuple[CampaignProgression, XPUpdate]:
    """Apply XP directly to campaign state and synchronize level."""
    xp_update = award_xp(current_xp=state.xp, gained_xp=gained_xp)
    updated = _clone_state(state)
    updated.xp = xp_update.ending_xp
    updated.level = xp_update.ending_level
    return updated, xp_update


def work_for_wages(
    state: CampaignProgression,
    *,
    days: int,
    gp_per_day: int = 2,
) -> CampaignProgression:
    """Spend downtime to earn deterministic wages."""
    _require_positive("days", days)
    _require_non_negative("gp_per_day", gp_per_day)
    _assert_enough_downtime_days(state, days)
    updated = _clone_state(state)
    updated.downtime_days -= days
    updated.gold_gp += days * gp_per_day
    return updated


def recuperate(
    state: CampaignProgression,
    *,
    days: int,
    hp_per_day: int | None = None,
) -> CampaignProgression:
    """Spend downtime to recover hit points."""
    _require_positive("days", days)
    _assert_enough_downtime_days(state, days)
    if hp_per_day is None:
        hp_per_day = max(1, state.level)
    _require_positive("hp_per_day", hp_per_day)

    updated = _clone_state(state)
    updated.downtime_days -= days
    healed = days * hp_per_day
    updated.current_hp = min(updated.max_hp, updated.current_hp + healed)
    return updated


def train_proficiency(
    state: CampaignProgression,
    *,
    proficiency: str,
    days: int,
    gp_per_day: int = 1,
    days_required: int = 10,
) -> CampaignProgression:
    """Spend downtime and gold to train a proficiency deterministically."""
    _require_positive("days", days)
    _require_non_negative("gp_per_day", gp_per_day)
    _require_positive("days_required", days_required)
    _assert_enough_downtime_days(state, days)
    training_cost = days * gp_per_day
    _assert_enough_gold(state, training_cost)

    key = proficiency.strip().lower()
    if not key:
        raise ValueError("proficiency must not be blank")

    updated = _clone_state(state)
    updated.downtime_days -= days
    updated.gold_gp -= training_cost

    progress = updated.training_progress_days.get(key, 0) + days
    if progress >= days_required:
        updated.proficiencies.add(key)
        updated.training_progress_days[key] = 0
    else:
        updated.training_progress_days[key] = progress

    return updated


def craft_item(
    state: CampaignProgression,
    *,
    item_name: str,
    days: int,
    days_per_item: int = 5,
    gp_cost_per_item: int = 0,
) -> CampaignProgression:
    """Craft items using deterministic day and gold conversion rates."""
    _require_positive("days", days)
    _require_positive("days_per_item", days_per_item)
    _require_non_negative("gp_cost_per_item", gp_cost_per_item)
    _assert_enough_downtime_days(state, days)

    key = item_name.strip().lower()
    if not key:
        raise ValueError("item_name must not be blank")

    max_items_by_time = days // days_per_item
    if max_items_by_time <= 0:
        raise ValueError("not enough downtime days to craft one item")

    if gp_cost_per_item == 0:
        crafted_count = max_items_by_time
    else:
        max_items_by_gold = state.gold_gp // gp_cost_per_item
        crafted_count = min(max_items_by_time, max_items_by_gold)

    if crafted_count <= 0:
        raise ValueError("not enough gold to craft any items")

    updated = _clone_state(state)
    spent_days = crafted_count * days_per_item
    spent_gold = crafted_count * gp_cost_per_item
    updated.downtime_days -= spent_days
    updated.gold_gp -= spent_gold
    updated.inventory[key] = updated.inventory.get(key, 0) + crafted_count
    return updated
