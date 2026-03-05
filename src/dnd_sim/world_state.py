from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_FLAG_STATUSES = {"inactive", "active", "resolved", "archived"}
_QUEST_STATUSES = {"not_started", "active", "completed", "failed", "archived"}

_FLAG_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"inactive", "active"},
    "inactive": {"active", "archived"},
    "active": {"inactive", "resolved", "archived"},
    "resolved": {"active", "archived"},
    "archived": set(),
}

_QUEST_TRANSITIONS: dict[str, set[str]] = {
    "not_started": {"active", "archived"},
    "active": {"completed", "failed", "archived"},
    "completed": {"archived"},
    "failed": {"archived"},
    "archived": set(),
}


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _normalize_flag_status(value: Any, *, field_name: str = "flag_status") -> str:
    status = _required_text(value, field_name=field_name).lower()
    if status not in _FLAG_STATUSES:
        allowed = ", ".join(sorted(_FLAG_STATUSES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return status


def _normalize_quest_status(value: Any, *, field_name: str = "quest_status") -> str:
    status = _required_text(value, field_name=field_name).lower()
    if status not in _QUEST_STATUSES:
        allowed = ", ".join(sorted(_QUEST_STATUSES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return status


@dataclass(frozen=True, slots=True)
class QuestState:
    quest_id: str
    status: str = "not_started"
    stage_id: str | None = None
    objective_flags: dict[str, bool] | None = None

    def __post_init__(self) -> None:
        quest_id = _required_text(self.quest_id, field_name="quest_id")
        status = _normalize_quest_status(self.status, field_name="status")

        stage_id: str | None = None
        if self.stage_id is not None:
            stage_id = _required_text(self.stage_id, field_name="stage_id")

        normalized_objectives: dict[str, bool] = {}
        raw_objectives = self.objective_flags or {}
        for objective_id, completed in sorted(dict(raw_objectives).items()):
            normalized_id = _required_text(objective_id, field_name="objective_id")
            if not isinstance(completed, bool):
                raise ValueError("objective_flags values must be bool")
            normalized_objectives[normalized_id] = completed

        object.__setattr__(self, "quest_id", quest_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "stage_id", stage_id)
        object.__setattr__(self, "objective_flags", normalized_objectives)


@dataclass(frozen=True, slots=True)
class FactionState:
    faction_id: str
    reputation: int = 0

    def __post_init__(self) -> None:
        faction_id = _required_text(self.faction_id, field_name="faction_id")
        reputation = _required_int(self.reputation, field_name="reputation")
        if reputation < -100 or reputation > 100:
            raise ValueError("reputation must be in range -100..100")
        object.__setattr__(self, "faction_id", faction_id)
        object.__setattr__(self, "reputation", reputation)

    @property
    def standing(self) -> str:
        if self.reputation <= -75:
            return "hostile"
        if self.reputation <= -25:
            return "unfriendly"
        if self.reputation <= 24:
            return "neutral"
        if self.reputation <= 74:
            return "friendly"
        return "allied"


@dataclass(frozen=True, slots=True)
class WorldState:
    turn_index: int
    world_flags: dict[str, str]
    quests: dict[str, QuestState]
    factions: dict[str, FactionState]

    def __post_init__(self) -> None:
        turn_index = _required_int(self.turn_index, field_name="turn_index")
        if turn_index < 0:
            raise ValueError("turn_index must be >= 0")

        normalized_flags: dict[str, str] = {}
        for flag_id, status in sorted(dict(self.world_flags).items()):
            normalized_id = _required_text(flag_id, field_name="flag_id")
            normalized_flags[normalized_id] = _normalize_flag_status(status)

        normalized_quests: dict[str, QuestState] = {}
        for quest_id, quest_state in sorted(dict(self.quests).items()):
            normalized_id = _required_text(quest_id, field_name="quest_id")
            if not isinstance(quest_state, QuestState):
                raise ValueError("quests must contain QuestState values")
            if quest_state.quest_id != normalized_id:
                quest_state = QuestState(
                    quest_id=normalized_id,
                    status=quest_state.status,
                    stage_id=quest_state.stage_id,
                    objective_flags=quest_state.objective_flags,
                )
            normalized_quests[normalized_id] = quest_state

        normalized_factions: dict[str, FactionState] = {}
        for faction_id, faction_state in sorted(dict(self.factions).items()):
            normalized_id = _required_text(faction_id, field_name="faction_id")
            if not isinstance(faction_state, FactionState):
                raise ValueError("factions must contain FactionState values")
            if faction_state.faction_id != normalized_id:
                faction_state = FactionState(
                    faction_id=normalized_id,
                    reputation=faction_state.reputation,
                )
            normalized_factions[normalized_id] = faction_state

        object.__setattr__(self, "turn_index", turn_index)
        object.__setattr__(self, "world_flags", normalized_flags)
        object.__setattr__(self, "quests", normalized_quests)
        object.__setattr__(self, "factions", normalized_factions)


def create_world_state(
    *,
    turn_index: int = 0,
    world_flags: dict[str, str] | None = None,
    quests: dict[str, QuestState] | None = None,
    factions: dict[str, FactionState] | None = None,
) -> WorldState:
    return WorldState(
        turn_index=turn_index,
        world_flags=dict(world_flags or {}),
        quests=dict(quests or {}),
        factions=dict(factions or {}),
    )


def transition_world_flag(
    state: WorldState,
    *,
    flag_id: str,
    to_status: str,
) -> WorldState:
    normalized_flag_id = _required_text(flag_id, field_name="flag_id")
    normalized_status = _normalize_flag_status(to_status, field_name="to_status")
    current_status = state.world_flags.get(normalized_flag_id)
    allowed_next = _FLAG_TRANSITIONS.get(current_status, set())
    if normalized_status not in allowed_next:
        raise ValueError(
            f"Illegal flag transition for {normalized_flag_id}: {current_status!r} -> {normalized_status!r}"
        )

    next_flags = dict(state.world_flags)
    next_flags[normalized_flag_id] = normalized_status
    return WorldState(
        turn_index=state.turn_index + 1,
        world_flags=next_flags,
        quests=state.quests,
        factions=state.factions,
    )


def set_world_flag_status(
    state: WorldState,
    *,
    flag_id: str,
    to_status: str,
    strict_transition: bool = False,
) -> WorldState:
    normalized_flag_id = _required_text(flag_id, field_name="flag_id")
    normalized_status = _normalize_flag_status(to_status, field_name="to_status")
    current_status = state.world_flags.get(normalized_flag_id)
    if current_status == normalized_status:
        return state

    allowed_next = _FLAG_TRANSITIONS.get(current_status, set())
    if normalized_status in allowed_next:
        return transition_world_flag(
            state,
            flag_id=normalized_flag_id,
            to_status=normalized_status,
        )

    if strict_transition:
        raise ValueError(
            f"Illegal flag transition for {normalized_flag_id}: {current_status!r} -> {normalized_status!r}"
        )

    # Scripted hooks may need to directly set a state (for example, unresolved -> resolved).
    next_flags = dict(state.world_flags)
    next_flags[normalized_flag_id] = normalized_status
    return WorldState(
        turn_index=state.turn_index + 1,
        world_flags=next_flags,
        quests=state.quests,
        factions=state.factions,
    )


def transition_quest_state(
    state: WorldState,
    *,
    quest_id: str,
    to_status: str,
    stage_id: str | None = None,
    objective_updates: dict[str, bool] | None = None,
) -> WorldState:
    normalized_quest_id = _required_text(quest_id, field_name="quest_id")
    normalized_status = _normalize_quest_status(to_status, field_name="to_status")
    existing = state.quests.get(normalized_quest_id, QuestState(quest_id=normalized_quest_id))

    allowed_next = _QUEST_TRANSITIONS.get(existing.status, set())
    if normalized_status not in allowed_next and normalized_status != existing.status:
        raise ValueError(
            f"Illegal quest transition for {normalized_quest_id}: {existing.status!r} -> {normalized_status!r}"
        )

    merged_objectives = dict(existing.objective_flags or {})
    for objective_id, completed in sorted(dict(objective_updates or {}).items()):
        normalized_objective_id = _required_text(objective_id, field_name="objective_id")
        if not isinstance(completed, bool):
            raise ValueError("objective_updates values must be bool")
        merged_objectives[normalized_objective_id] = completed

    next_quests = dict(state.quests)
    next_quests[normalized_quest_id] = QuestState(
        quest_id=normalized_quest_id,
        status=normalized_status,
        stage_id=stage_id if stage_id is not None else existing.stage_id,
        objective_flags=merged_objectives,
    )
    return WorldState(
        turn_index=state.turn_index + 1,
        world_flags=state.world_flags,
        quests=next_quests,
        factions=state.factions,
    )


def apply_faction_reputation_delta(
    state: WorldState,
    *,
    faction_id: str,
    delta: int,
) -> WorldState:
    normalized_faction_id = _required_text(faction_id, field_name="faction_id")
    delta_value = _required_int(delta, field_name="delta")
    existing = state.factions.get(
        normalized_faction_id, FactionState(faction_id=normalized_faction_id)
    )
    next_reputation = max(-100, min(100, existing.reputation + delta_value))

    next_factions = dict(state.factions)
    next_factions[normalized_faction_id] = FactionState(
        faction_id=normalized_faction_id,
        reputation=next_reputation,
    )
    return WorldState(
        turn_index=state.turn_index + 1,
        world_flags=state.world_flags,
        quests=state.quests,
        factions=next_factions,
    )
