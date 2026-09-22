"""Strict engine-local provenance for post-roll timing hooks."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RollHookTrace:
    """One timing-hook change, including any die it generated."""

    kind: Literal[
        "lucky_attacker",
        "lucky_defender",
        "bardic_inspiration",
        "cutting_words",
        "shield",
        "guided_strike",
        "war_gods_blessing",
    ]
    stage: Literal["replacement", "total", "threshold", "raw"]
    amount: int
    die_sides: int | None = None
    die_value: int | None = None
    selected: bool | None = None

    def __post_init__(self) -> None:
        has_die = self.die_sides is not None or self.die_value is not None
        if has_die:
            if self.die_sides is None or self.die_value is None:
                raise ValueError("hook die sides and value must be present together")
            if self.die_sides < 2 or not 1 <= self.die_value <= self.die_sides:
                raise ValueError("hook die must be a valid generated face")
        if self.stage == "replacement":
            if self.die_sides != 20 or self.selected is None:
                raise ValueError("replacement hooks require a selected d20 face")
        elif self.selected is not None:
            raise ValueError("only replacement hooks may select a face")


__all__ = ["RollHookTrace"]
