"""Built-in strategy modules."""

from dnd_sim.strategies.defaults import (
    AlwaysUseSignatureAbilityStrategy,
    BossHighestThreatTargetStrategy,
    ConserveResourcesThenBurstStrategy,
    FocusFireLowestHPStrategy,
    OptimalExpectedDamageStrategy,
)

__all__ = [
    "AlwaysUseSignatureAbilityStrategy",
    "BossHighestThreatTargetStrategy",
    "ConserveResourcesThenBurstStrategy",
    "FocusFireLowestHPStrategy",
    "OptimalExpectedDamageStrategy",
]
