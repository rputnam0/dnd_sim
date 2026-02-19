from __future__ import annotations

from dnd_sim.strategy_api import ActionIntent, BaseStrategy, TargetRef


class LeyHeartPhase1Strategy(BaseStrategy):
    """Focuses pylons in fixed order to mirror the table procedure flow."""

    target_order = ("past_pylon", "present_pylon", "future_pylon")

    def choose_action(self, actor, state):
        available = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
        has_ki = actor.resources.get("ki", 0) > 0
        if has_ki and state.round_number >= 2 and "signature" in available:
            return ActionIntent(action_name="signature")
        if "basic" in available:
            return ActionIntent(action_name="basic")
        return ActionIntent(action_name=available[0] if available else None)

    def choose_targets(self, actor, intent, state):
        enemies = {
            view.actor_id: view
            for view in state.actors.values()
            if view.team != actor.team and view.hp > 0
        }
        for enemy_id in self.target_order:
            if enemy_id in enemies:
                return [TargetRef(actor_id=enemy_id)]
        return super().choose_targets(actor, intent, state)
