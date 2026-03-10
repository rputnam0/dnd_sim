from __future__ import annotations

from dnd_sim.strategies.defaults import _declare_turn_for_action
from dnd_sim.strategy_api import BaseStrategy, TargetRef, TurnDeclaration


class LeyHeartPhase1Strategy(BaseStrategy):
    """Focuses pylons in fixed order to mirror the table procedure flow."""

    target_order = ("past_pylon", "present_pylon", "future_pylon")

    def declare_turn(self, actor, state):
        action_name = self._select_action_name(actor, state)
        targets = self._select_targets(actor, action_name, state)
        return _declare_turn_for_action(
            actor,
            state,
            action_name=action_name,
            preferred_targets=targets,
            rationale={"strategy": "ley_heart_phase_1"},
        )

    def _select_action_name(self, actor, state) -> str | None:
        available = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
        has_ki = actor.resources.get("ki", 0) > 0
        if has_ki and state.round_number >= 2 and "signature" in available:
            return "signature"
        if "basic" in available:
            return "basic"
        return str(available[0]) if available else None

    def _select_targets(self, actor, action_name: str, state) -> list[TargetRef]:
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action = next((entry for entry in catalog if entry.get("name") == action_name), None)
        enemies = {
            view.actor_id: view
            for view in state.actors.values()
            if view.team != actor.team and view.hp > 0
        }

        if action and action.get("target_mode") == "self":
            return [TargetRef(actor_id=actor.actor_id)]
        if action and action.get("target_mode") == "all_enemies":
            return [TargetRef(actor_id=entry.actor_id) for entry in enemies.values()]

        for enemy_id in self.target_order:
            if enemy_id in enemies:
                return [TargetRef(actor_id=enemy_id)]

        if enemies:
            fallback = min(enemies.values(), key=lambda entry: (entry.hp, entry.max_hp))
            return [TargetRef(actor_id=fallback.actor_id)]
        return []
