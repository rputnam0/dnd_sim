from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

INTERACTABLE_KINDS = {"trap", "lock", "container", "secret", "searchable"}

logger = logging.getLogger(__name__)


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


def _normalize_text_tuple(values: Any, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple, set)):
        raise ValueError(f"{field_name} must be a sequence")
    normalized = sorted({_required_text(value, field_name=field_name) for value in values})
    return tuple(normalized)


def _normalize_positive_or_none(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    normalized = _required_int(value, field_name=field_name)
    if normalized < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return normalized


@dataclass(frozen=True, slots=True)
class AwarenessState:
    actor_id: str
    hidden: bool = False
    detected_by: tuple[str, ...] = ()
    surprised: bool = False
    stealth_total: int | None = None

    def __post_init__(self) -> None:
        actor_id = _required_text(self.actor_id, field_name="actor_id")
        if not isinstance(self.hidden, bool):
            raise ValueError("hidden must be a bool")
        if not isinstance(self.surprised, bool):
            raise ValueError("surprised must be a bool")
        stealth_total = _normalize_positive_or_none(self.stealth_total, field_name="stealth_total")
        detected_by = tuple(
            entry
            for entry in _normalize_text_tuple(self.detected_by, field_name="detected_by")
            if entry != actor_id
        )
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "detected_by", detected_by)
        object.__setattr__(self, "stealth_total", stealth_total)


@dataclass(frozen=True, slots=True)
class InteractableState:
    object_id: str
    kind: str
    location_id: str | None = None
    hidden: bool = False
    discovered: bool = False
    open: bool = False
    locked: bool = False
    trap_armed: bool = False
    disarmed: bool = False
    triggered: bool = False
    discovery_dc: int | None = None
    unlock_dc: int | None = None
    disarm_dc: int | None = None
    trigger_on_fail: bool = False
    key_item_id: str | None = None
    contents: tuple[str, ...] = ()
    loot_transferred: bool = False

    def __post_init__(self) -> None:
        object_id = _required_text(self.object_id, field_name="object_id")
        kind = _required_text(self.kind, field_name="kind").lower()
        if kind not in INTERACTABLE_KINDS:
            raise ValueError("kind must be one of: " + ", ".join(sorted(INTERACTABLE_KINDS)))
        if self.location_id is not None:
            _required_text(self.location_id, field_name="location_id")
        if not isinstance(self.hidden, bool):
            raise ValueError("hidden must be a bool")
        if not isinstance(self.discovered, bool):
            raise ValueError("discovered must be a bool")
        if not isinstance(self.open, bool):
            raise ValueError("open must be a bool")
        if not isinstance(self.locked, bool):
            raise ValueError("locked must be a bool")
        if not isinstance(self.trap_armed, bool):
            raise ValueError("trap_armed must be a bool")
        if not isinstance(self.disarmed, bool):
            raise ValueError("disarmed must be a bool")
        if not isinstance(self.triggered, bool):
            raise ValueError("triggered must be a bool")
        if not isinstance(self.trigger_on_fail, bool):
            raise ValueError("trigger_on_fail must be a bool")
        if self.key_item_id is not None:
            _required_text(self.key_item_id, field_name="key_item_id")
        discovery_dc = _normalize_positive_or_none(self.discovery_dc, field_name="discovery_dc")
        unlock_dc = _normalize_positive_or_none(self.unlock_dc, field_name="unlock_dc")
        disarm_dc = _normalize_positive_or_none(self.disarm_dc, field_name="disarm_dc")
        contents = _normalize_text_tuple(self.contents, field_name="contents")
        if self.open and self.locked:
            raise ValueError("open interactables cannot be locked")

        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "discovery_dc", discovery_dc)
        object.__setattr__(self, "unlock_dc", unlock_dc)
        object.__setattr__(self, "disarm_dc", disarm_dc)
        object.__setattr__(self, "contents", contents)
        if kind != "trap" and self.disarmed:
            raise ValueError("only trap interactables can be disarmed")
        if kind == "trap" and self.disarmed and self.trap_armed:
            object.__setattr__(self, "trap_armed", False)


@dataclass(frozen=True, slots=True)
class InteractionEvent:
    event_type: str
    actor_id: str
    outcome: str
    object_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_type", _required_text(self.event_type, field_name="event_type")
        )
        object.__setattr__(self, "actor_id", _required_text(self.actor_id, field_name="actor_id"))
        object.__setattr__(self, "outcome", _required_text(self.outcome, field_name="outcome"))
        if self.object_id is not None:
            object.__setattr__(
                self, "object_id", _required_text(self.object_id, field_name="object_id")
            )
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", dict(sorted(dict(self.details).items())))


@dataclass(frozen=True, slots=True)
class ExplorationInteractionState:
    awareness: dict[str, AwarenessState] = field(default_factory=dict)
    interactables: dict[str, InteractableState] = field(default_factory=dict)
    event_log: tuple[InteractionEvent, ...] = ()

    def __post_init__(self) -> None:
        normalized_awareness: dict[str, AwarenessState] = {}
        for actor_id, awareness in sorted(dict(self.awareness).items()):
            normalized_actor_id = _required_text(actor_id, field_name="actor_id")
            if not isinstance(awareness, AwarenessState):
                raise ValueError("awareness must contain AwarenessState values")
            if awareness.actor_id != normalized_actor_id:
                awareness = AwarenessState(
                    actor_id=normalized_actor_id,
                    hidden=awareness.hidden,
                    detected_by=awareness.detected_by,
                    surprised=awareness.surprised,
                    stealth_total=awareness.stealth_total,
                )
            normalized_awareness[normalized_actor_id] = awareness

        normalized_interactables: dict[str, InteractableState] = {}
        for object_id, interactable in sorted(dict(self.interactables).items()):
            normalized_object_id = _required_text(object_id, field_name="object_id")
            if not isinstance(interactable, InteractableState):
                raise ValueError("interactables must contain InteractableState values")
            if interactable.object_id != normalized_object_id:
                interactable = InteractableState(
                    object_id=normalized_object_id,
                    kind=interactable.kind,
                    location_id=interactable.location_id,
                    hidden=interactable.hidden,
                    discovered=interactable.discovered,
                    open=interactable.open,
                    locked=interactable.locked,
                    trap_armed=interactable.trap_armed,
                    disarmed=interactable.disarmed,
                    triggered=interactable.triggered,
                    discovery_dc=interactable.discovery_dc,
                    unlock_dc=interactable.unlock_dc,
                    disarm_dc=interactable.disarm_dc,
                    trigger_on_fail=interactable.trigger_on_fail,
                    key_item_id=interactable.key_item_id,
                    contents=interactable.contents,
                    loot_transferred=interactable.loot_transferred,
                )
            normalized_interactables[normalized_object_id] = interactable

        normalized_events = tuple(
            event if isinstance(event, InteractionEvent) else InteractionEvent(**dict(event))
            for event in self.event_log
        )
        object.__setattr__(self, "awareness", normalized_awareness)
        object.__setattr__(self, "interactables", normalized_interactables)
        object.__setattr__(self, "event_log", normalized_events)


@dataclass(frozen=True, slots=True)
class ContestedStealthResult:
    state: ExplorationInteractionState
    hidden: bool
    detected_by: tuple[str, ...]
    undetected_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActiveSearchResult:
    state: ExplorationInteractionState
    revealed_actor_ids: tuple[str, ...]
    discovered_object_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurpriseResolutionResult:
    state: ExplorationInteractionState
    surprised_actor_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnlockResult:
    state: ExplorationInteractionState
    success: bool
    trap_triggered: bool


@dataclass(frozen=True, slots=True)
class TrapDisarmResult:
    state: ExplorationInteractionState
    success: bool
    trap_triggered: bool


@dataclass(frozen=True, slots=True)
class OpenCloseResult:
    state: ExplorationInteractionState
    success: bool


@dataclass(frozen=True, slots=True)
class LootTransferResult:
    state: ExplorationInteractionState
    success: bool
    loot_item_ids: tuple[str, ...]


def _append_event(
    state: ExplorationInteractionState,
    *,
    event_type: str,
    actor_id: str,
    outcome: str,
    object_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ExplorationInteractionState:
    event = InteractionEvent(
        event_type=event_type,
        actor_id=actor_id,
        object_id=object_id,
        outcome=outcome,
        details=dict(details or {}),
    )
    return ExplorationInteractionState(
        awareness=state.awareness,
        interactables=state.interactables,
        event_log=tuple(state.event_log) + (event,),
    )


def _json_compatible(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_compatible(entry) for entry in value]
    if isinstance(value, list):
        return [_json_compatible(entry) for entry in value]
    if isinstance(value, set):
        return [_json_compatible(entry) for entry in sorted(value)]
    if isinstance(value, dict):
        return {
            str(key): _json_compatible(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _replace_awareness(
    state: ExplorationInteractionState, awareness: dict[str, AwarenessState]
) -> ExplorationInteractionState:
    return ExplorationInteractionState(
        awareness=awareness,
        interactables=state.interactables,
        event_log=state.event_log,
    )


def _replace_interactables(
    state: ExplorationInteractionState, interactables: dict[str, InteractableState]
) -> ExplorationInteractionState:
    return ExplorationInteractionState(
        awareness=state.awareness,
        interactables=interactables,
        event_log=state.event_log,
    )


def resolve_contested_stealth(
    state: ExplorationInteractionState,
    *,
    actor_id: str,
    stealth_total: int,
    observer_passive_perception: Mapping[str, int],
) -> ContestedStealthResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    stealth_score = _required_int(stealth_total, field_name="stealth_total")
    if stealth_score < 0:
        raise ValueError("stealth_total must be >= 0")
    if not isinstance(observer_passive_perception, Mapping):
        raise ValueError("observer_passive_perception must be a mapping")

    normalized_passives: dict[str, int] = {}
    for observer_id, passive in sorted(dict(observer_passive_perception).items()):
        normalized_observer_id = _required_text(observer_id, field_name="observer_id")
        passive_value = _required_int(passive, field_name="passive_perception")
        if passive_value < 0:
            raise ValueError("passive_perception must be >= 0")
        normalized_passives[normalized_observer_id] = passive_value

    detected_by = sorted(
        observer_id
        for observer_id, passive in normalized_passives.items()
        if passive >= stealth_score
    )
    undetected_by = sorted(
        observer_id for observer_id in normalized_passives if observer_id not in set(detected_by)
    )
    hidden = True if not normalized_passives else bool(undetected_by)

    awareness = dict(state.awareness)
    current = awareness.get(normalized_actor_id, AwarenessState(actor_id=normalized_actor_id))
    awareness[normalized_actor_id] = AwarenessState(
        actor_id=normalized_actor_id,
        hidden=hidden,
        detected_by=tuple(detected_by),
        surprised=current.surprised,
        stealth_total=stealth_score,
    )
    next_state = _replace_awareness(state, awareness)
    next_state = _append_event(
        next_state,
        event_type="stealth_check",
        actor_id=normalized_actor_id,
        outcome="hidden" if hidden else "detected",
        details={
            "stealth_total": stealth_score,
            "detected_by": tuple(detected_by),
            "undetected_by": tuple(undetected_by),
        },
    )
    return ContestedStealthResult(
        state=next_state,
        hidden=hidden,
        detected_by=tuple(detected_by),
        undetected_by=tuple(undetected_by),
    )


def resolve_active_search(
    state: ExplorationInteractionState,
    *,
    seeker_id: str,
    search_total: int,
    target_actor_ids: tuple[str, ...] | list[str] = (),
    target_object_ids: tuple[str, ...] | list[str] = (),
) -> ActiveSearchResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_seeker_id = _required_text(seeker_id, field_name="seeker_id")
    search_score = _required_int(search_total, field_name="search_total")
    if search_score < 0:
        raise ValueError("search_total must be >= 0")

    actor_targets = _normalize_text_tuple(target_actor_ids, field_name="target_actor_ids")
    object_targets = _normalize_text_tuple(target_object_ids, field_name="target_object_ids")

    awareness = dict(state.awareness)
    revealed_actor_ids: list[str] = []
    for actor_id in actor_targets:
        actor_state = awareness.get(actor_id)
        if actor_state is None:
            continue
        dc = actor_state.stealth_total if actor_state.stealth_total is not None else 10
        if search_score < dc:
            continue
        detected = sorted(set(actor_state.detected_by) | {normalized_seeker_id})
        awareness[actor_id] = AwarenessState(
            actor_id=actor_state.actor_id,
            hidden=False,
            detected_by=tuple(detected),
            surprised=actor_state.surprised,
            stealth_total=actor_state.stealth_total,
        )
        revealed_actor_ids.append(actor_id)

    interactables = dict(state.interactables)
    discovered_object_ids: list[str] = []
    for object_id in object_targets:
        interactable = interactables.get(object_id)
        if interactable is None:
            continue
        dc = interactable.discovery_dc if interactable.discovery_dc is not None else 0
        if search_score < dc:
            continue
        if interactable.discovered and not interactable.hidden:
            continue
        interactables[object_id] = InteractableState(
            object_id=interactable.object_id,
            kind=interactable.kind,
            location_id=interactable.location_id,
            hidden=False,
            discovered=True,
            open=interactable.open,
            locked=interactable.locked,
            trap_armed=interactable.trap_armed,
            disarmed=interactable.disarmed,
            triggered=interactable.triggered,
            discovery_dc=interactable.discovery_dc,
            unlock_dc=interactable.unlock_dc,
            disarm_dc=interactable.disarm_dc,
            trigger_on_fail=interactable.trigger_on_fail,
            key_item_id=interactable.key_item_id,
            contents=interactable.contents,
            loot_transferred=interactable.loot_transferred,
        )
        discovered_object_ids.append(object_id)

    next_state = ExplorationInteractionState(
        awareness=awareness,
        interactables=interactables,
        event_log=state.event_log,
    )
    next_state = _append_event(
        next_state,
        event_type="search",
        actor_id=normalized_seeker_id,
        outcome="resolved",
        details={
            "search_total": search_score,
            "revealed_actor_ids": tuple(sorted(revealed_actor_ids)),
            "discovered_object_ids": tuple(sorted(discovered_object_ids)),
        },
    )
    return ActiveSearchResult(
        state=next_state,
        revealed_actor_ids=tuple(sorted(revealed_actor_ids)),
        discovered_object_ids=tuple(sorted(discovered_object_ids)),
    )


def resolve_encounter_surprise(
    state: ExplorationInteractionState,
    *,
    teams: Mapping[str, str],
) -> SurpriseResolutionResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    if not isinstance(teams, Mapping):
        raise ValueError("teams must be a mapping")

    normalized_teams: dict[str, str] = {}
    for actor_id, team in sorted(dict(teams).items()):
        normalized_teams[_required_text(actor_id, field_name="actor_id")] = _required_text(
            team, field_name="team"
        )

    awareness = dict(state.awareness)
    surprised_actor_ids: list[str] = []
    for actor_id, team in sorted(normalized_teams.items()):
        enemies = [
            enemy_id for enemy_id, enemy_team in normalized_teams.items() if enemy_team != team
        ]
        actor_awareness = awareness.get(actor_id, AwarenessState(actor_id=actor_id))
        aware_of_any_enemy = False
        for enemy_id in enemies:
            enemy_state = awareness.get(enemy_id, AwarenessState(actor_id=enemy_id))
            if not enemy_state.hidden:
                aware_of_any_enemy = True
                break
            if actor_id in enemy_state.detected_by:
                aware_of_any_enemy = True
                break

        surprised = bool(enemies) and not aware_of_any_enemy
        if surprised:
            surprised_actor_ids.append(actor_id)
        awareness[actor_id] = AwarenessState(
            actor_id=actor_id,
            hidden=actor_awareness.hidden,
            detected_by=actor_awareness.detected_by,
            surprised=surprised,
            stealth_total=actor_awareness.stealth_total,
        )

    next_state = _replace_awareness(state, awareness)
    next_state = _append_event(
        next_state,
        event_type="surprise_resolution",
        actor_id="encounter",
        outcome="resolved",
        details={"surprised_actor_ids": tuple(sorted(surprised_actor_ids))},
    )
    return SurpriseResolutionResult(
        state=next_state,
        surprised_actor_ids=tuple(sorted(surprised_actor_ids)),
    )


def resolve_unlock(
    state: ExplorationInteractionState,
    *,
    actor_id: str,
    object_id: str,
    check_total: int,
    key_item_ids: tuple[str, ...] | list[str] = (),
) -> UnlockResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    normalized_object_id = _required_text(object_id, field_name="object_id")
    normalized_check = _required_int(check_total, field_name="check_total")
    if normalized_check < 0:
        raise ValueError("check_total must be >= 0")
    key_ids = set(_normalize_text_tuple(key_item_ids, field_name="key_item_ids"))

    interactables = dict(state.interactables)
    interactable = interactables.get(normalized_object_id)
    if interactable is None:
        return UnlockResult(state=state, success=False, trap_triggered=False)
    if interactable.kind not in {"lock", "container"}:
        return UnlockResult(state=state, success=False, trap_triggered=False)
    if not interactable.discovered:
        return UnlockResult(state=state, success=False, trap_triggered=False)
    if not interactable.locked:
        return UnlockResult(state=state, success=True, trap_triggered=False)

    unlocked = False
    if interactable.key_item_id and interactable.key_item_id in key_ids:
        unlocked = True
    elif interactable.unlock_dc is not None and normalized_check >= interactable.unlock_dc:
        unlocked = True

    trap_triggered = bool(not unlocked and interactable.trigger_on_fail and interactable.trap_armed)

    interactables[normalized_object_id] = InteractableState(
        object_id=interactable.object_id,
        kind=interactable.kind,
        location_id=interactable.location_id,
        hidden=interactable.hidden,
        discovered=interactable.discovered,
        open=interactable.open,
        locked=(not unlocked),
        trap_armed=interactable.trap_armed,
        disarmed=interactable.disarmed,
        triggered=interactable.triggered or trap_triggered,
        discovery_dc=interactable.discovery_dc,
        unlock_dc=interactable.unlock_dc,
        disarm_dc=interactable.disarm_dc,
        trigger_on_fail=interactable.trigger_on_fail,
        key_item_id=interactable.key_item_id,
        contents=interactable.contents,
        loot_transferred=interactable.loot_transferred,
    )

    next_state = _replace_interactables(state, interactables)
    next_state = _append_event(
        next_state,
        event_type="unlock",
        actor_id=normalized_actor_id,
        object_id=normalized_object_id,
        outcome="success" if unlocked else "failure",
        details={"trap_triggered": trap_triggered},
    )
    return UnlockResult(state=next_state, success=unlocked, trap_triggered=trap_triggered)


def resolve_trap_disarm(
    state: ExplorationInteractionState,
    *,
    actor_id: str,
    object_id: str,
    check_total: int,
) -> TrapDisarmResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    normalized_object_id = _required_text(object_id, field_name="object_id")
    normalized_check = _required_int(check_total, field_name="check_total")
    if normalized_check < 0:
        raise ValueError("check_total must be >= 0")

    interactables = dict(state.interactables)
    interactable = interactables.get(normalized_object_id)
    if interactable is None:
        return TrapDisarmResult(state=state, success=False, trap_triggered=False)
    if interactable.kind != "trap":
        return TrapDisarmResult(state=state, success=False, trap_triggered=False)
    if not interactable.discovered:
        return TrapDisarmResult(state=state, success=False, trap_triggered=False)
    if interactable.disarmed:
        return TrapDisarmResult(state=state, success=True, trap_triggered=False)

    dc = interactable.disarm_dc if interactable.disarm_dc is not None else 10
    success = normalized_check >= dc
    trap_triggered = bool(not success and interactable.trigger_on_fail and interactable.trap_armed)
    next_trap_armed = False if success else interactable.trap_armed
    interactables[normalized_object_id] = InteractableState(
        object_id=interactable.object_id,
        kind=interactable.kind,
        location_id=interactable.location_id,
        hidden=interactable.hidden,
        discovered=interactable.discovered,
        open=interactable.open,
        locked=interactable.locked,
        trap_armed=next_trap_armed,
        disarmed=success or interactable.disarmed,
        triggered=interactable.triggered or trap_triggered,
        discovery_dc=interactable.discovery_dc,
        unlock_dc=interactable.unlock_dc,
        disarm_dc=interactable.disarm_dc,
        trigger_on_fail=interactable.trigger_on_fail,
        key_item_id=interactable.key_item_id,
        contents=interactable.contents,
        loot_transferred=interactable.loot_transferred,
    )
    next_state = _replace_interactables(state, interactables)
    next_state = _append_event(
        next_state,
        event_type="disarm",
        actor_id=normalized_actor_id,
        object_id=normalized_object_id,
        outcome="success" if success else "failure",
        details={"trap_triggered": trap_triggered},
    )
    return TrapDisarmResult(
        state=next_state,
        success=success,
        trap_triggered=trap_triggered,
    )


def resolve_open_close(
    state: ExplorationInteractionState,
    *,
    actor_id: str,
    object_id: str,
    open: bool,
) -> OpenCloseResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    normalized_object_id = _required_text(object_id, field_name="object_id")
    if not isinstance(open, bool):
        raise ValueError("open must be a bool")

    interactables = dict(state.interactables)
    interactable = interactables.get(normalized_object_id)
    if interactable is None:
        return OpenCloseResult(state=state, success=False)
    if open and interactable.locked:
        return OpenCloseResult(state=state, success=False)

    interactables[normalized_object_id] = InteractableState(
        object_id=interactable.object_id,
        kind=interactable.kind,
        location_id=interactable.location_id,
        hidden=interactable.hidden,
        discovered=interactable.discovered,
        open=open,
        locked=interactable.locked,
        trap_armed=interactable.trap_armed,
        disarmed=interactable.disarmed,
        triggered=interactable.triggered,
        discovery_dc=interactable.discovery_dc,
        unlock_dc=interactable.unlock_dc,
        disarm_dc=interactable.disarm_dc,
        trigger_on_fail=interactable.trigger_on_fail,
        key_item_id=interactable.key_item_id,
        contents=interactable.contents,
        loot_transferred=interactable.loot_transferred,
    )
    next_state = _replace_interactables(state, interactables)
    next_state = _append_event(
        next_state,
        event_type="open_close",
        actor_id=normalized_actor_id,
        object_id=normalized_object_id,
        outcome="open" if open else "closed",
    )
    return OpenCloseResult(state=next_state, success=True)


def resolve_transfer_loot(
    state: ExplorationInteractionState,
    *,
    actor_id: str,
    object_id: str,
) -> LootTransferResult:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    normalized_object_id = _required_text(object_id, field_name="object_id")

    interactables = dict(state.interactables)
    interactable = interactables.get(normalized_object_id)
    if interactable is None:
        return LootTransferResult(state=state, success=False, loot_item_ids=())
    if interactable.kind != "container":
        return LootTransferResult(state=state, success=False, loot_item_ids=())
    if interactable.locked or not interactable.open:
        return LootTransferResult(state=state, success=False, loot_item_ids=())

    loot_item_ids: tuple[str, ...]
    if interactable.loot_transferred:
        loot_item_ids = ()
    else:
        loot_item_ids = tuple(sorted(interactable.contents))

    interactables[normalized_object_id] = InteractableState(
        object_id=interactable.object_id,
        kind=interactable.kind,
        location_id=interactable.location_id,
        hidden=interactable.hidden,
        discovered=interactable.discovered,
        open=interactable.open,
        locked=interactable.locked,
        trap_armed=interactable.trap_armed,
        disarmed=interactable.disarmed,
        triggered=interactable.triggered,
        discovery_dc=interactable.discovery_dc,
        unlock_dc=interactable.unlock_dc,
        disarm_dc=interactable.disarm_dc,
        trigger_on_fail=interactable.trigger_on_fail,
        key_item_id=interactable.key_item_id,
        contents=interactable.contents,
        loot_transferred=True,
    )
    next_state = _replace_interactables(state, interactables)
    next_state = _append_event(
        next_state,
        event_type="loot_transfer",
        actor_id=normalized_actor_id,
        object_id=normalized_object_id,
        outcome="success",
        details={"loot_item_ids": loot_item_ids},
    )
    return LootTransferResult(
        state=next_state,
        success=True,
        loot_item_ids=loot_item_ids,
    )


def serialize_interaction_state(state: ExplorationInteractionState) -> dict[str, Any]:
    if not isinstance(state, ExplorationInteractionState):
        raise ValueError("state must be an ExplorationInteractionState")
    return {
        "awareness": [
            {
                "actor_id": awareness.actor_id,
                "hidden": awareness.hidden,
                "detected_by": list(awareness.detected_by),
                "surprised": awareness.surprised,
                "stealth_total": awareness.stealth_total,
            }
            for _, awareness in sorted(state.awareness.items())
        ],
        "interactables": [
            {
                "object_id": interactable.object_id,
                "kind": interactable.kind,
                "location_id": interactable.location_id,
                "hidden": interactable.hidden,
                "discovered": interactable.discovered,
                "open": interactable.open,
                "locked": interactable.locked,
                "trap_armed": interactable.trap_armed,
                "disarmed": interactable.disarmed,
                "triggered": interactable.triggered,
                "discovery_dc": interactable.discovery_dc,
                "unlock_dc": interactable.unlock_dc,
                "disarm_dc": interactable.disarm_dc,
                "trigger_on_fail": interactable.trigger_on_fail,
                "key_item_id": interactable.key_item_id,
                "contents": list(interactable.contents),
                "loot_transferred": interactable.loot_transferred,
            }
            for _, interactable in sorted(state.interactables.items())
        ],
        "events": [
            {
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "object_id": event.object_id,
                "outcome": event.outcome,
                "details": _json_compatible(dict(event.details)),
            }
            for event in state.event_log
        ],
    }


def deserialize_interaction_state(payload: Mapping[str, Any] | None) -> ExplorationInteractionState:
    if payload is None:
        return ExplorationInteractionState()
    if not isinstance(payload, Mapping):
        raise ValueError("interaction payload must be a mapping")

    awareness: dict[str, AwarenessState] = {}
    for row in payload.get("awareness", []):
        if not isinstance(row, Mapping):
            raise ValueError("awareness rows must be mappings")
        actor_id = _required_text(row.get("actor_id"), field_name="actor_id")
        awareness[actor_id] = AwarenessState(
            actor_id=actor_id,
            hidden=bool(row.get("hidden", False)),
            detected_by=tuple(row.get("detected_by", ())),
            surprised=bool(row.get("surprised", False)),
            stealth_total=row.get("stealth_total"),
        )

    interactables: dict[str, InteractableState] = {}
    for row in payload.get("interactables", []):
        if not isinstance(row, Mapping):
            raise ValueError("interactable rows must be mappings")
        object_id = _required_text(row.get("object_id"), field_name="object_id")
        interactables[object_id] = InteractableState(
            object_id=object_id,
            kind=row.get("kind", ""),
            location_id=row.get("location_id"),
            hidden=bool(row.get("hidden", False)),
            discovered=bool(row.get("discovered", False)),
            open=bool(row.get("open", False)),
            locked=bool(row.get("locked", False)),
            trap_armed=bool(row.get("trap_armed", False)),
            disarmed=bool(row.get("disarmed", False)),
            triggered=bool(row.get("triggered", False)),
            discovery_dc=row.get("discovery_dc"),
            unlock_dc=row.get("unlock_dc"),
            disarm_dc=row.get("disarm_dc"),
            trigger_on_fail=bool(row.get("trigger_on_fail", False)),
            key_item_id=row.get("key_item_id"),
            contents=tuple(row.get("contents", ())),
            loot_transferred=bool(row.get("loot_transferred", False)),
        )

    events: list[InteractionEvent] = []
    for row in payload.get("events", []):
        if not isinstance(row, Mapping):
            raise ValueError("event rows must be mappings")
        events.append(
            InteractionEvent(
                event_type=row.get("event_type", ""),
                actor_id=row.get("actor_id", ""),
                object_id=row.get("object_id"),
                outcome=row.get("outcome", ""),
                details=dict(row.get("details", {})),
            )
        )

    return ExplorationInteractionState(
        awareness=awareness,
        interactables=interactables,
        event_log=tuple(events),
    )


__all__ = [
    "ActiveSearchResult",
    "AwarenessState",
    "ContestedStealthResult",
    "ExplorationInteractionState",
    "InteractableState",
    "LootTransferResult",
    "OpenCloseResult",
    "SurpriseResolutionResult",
    "TrapDisarmResult",
    "UnlockResult",
    "deserialize_interaction_state",
    "resolve_active_search",
    "resolve_contested_stealth",
    "resolve_encounter_surprise",
    "resolve_open_close",
    "resolve_transfer_loot",
    "resolve_trap_disarm",
    "resolve_unlock",
    "serialize_interaction_state",
]
