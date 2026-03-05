from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from dnd_sim.world_state import (
    QuestState,
    WorldState,
    set_world_flag_status,
    transition_quest_state,
)

_HOOK_TRIGGERS = {"manual", "wave_start", "wave_complete"}
_WAVE_STATUSES = {"locked", "active", "completed"}
_RUN_STATUSES = {"active", "completed"}
_FLAG_STATUSES = {"inactive", "active", "resolved", "archived"}


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _normalize_text_tuple(values: Any, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple")
    normalized = sorted({_required_text(value, field_name=field_name) for value in values})
    return tuple(normalized)


def _required_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


@dataclass(frozen=True, slots=True)
class EncounterObjective:
    objective_id: str
    description: str
    quest_id: str | None = None
    quest_objective_id: str | None = None
    completion_flag: str | None = None

    def __post_init__(self) -> None:
        objective_id = _required_text(self.objective_id, field_name="objective_id")
        description = _required_text(self.description, field_name="description")

        quest_id: str | None = None
        if self.quest_id is not None:
            quest_id = _required_text(self.quest_id, field_name="quest_id")

        quest_objective_id: str | None = None
        if self.quest_objective_id is not None:
            quest_objective_id = _required_text(
                self.quest_objective_id,
                field_name="quest_objective_id",
            )
        elif quest_id is not None:
            quest_objective_id = objective_id

        completion_flag: str | None = None
        if self.completion_flag is not None:
            completion_flag = _required_text(self.completion_flag, field_name="completion_flag")

        object.__setattr__(self, "objective_id", objective_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "quest_id", quest_id)
        object.__setattr__(self, "quest_objective_id", quest_objective_id)
        object.__setattr__(self, "completion_flag", completion_flag)


@dataclass(frozen=True, slots=True)
class EncounterMapHook:
    hook_id: str
    trigger: str
    flag_id: str
    to_status: str = "active"

    def __post_init__(self) -> None:
        hook_id = _required_text(self.hook_id, field_name="hook_id")
        trigger = _required_text(self.trigger, field_name="trigger")
        flag_id = _required_text(self.flag_id, field_name="flag_id")
        to_status = _required_text(self.to_status, field_name="to_status").lower()

        if trigger not in _HOOK_TRIGGERS:
            allowed = ", ".join(sorted(_HOOK_TRIGGERS))
            raise ValueError(f"trigger must be one of: {allowed}")
        if to_status not in _FLAG_STATUSES:
            allowed = ", ".join(sorted(_FLAG_STATUSES))
            raise ValueError(f"to_status must be one of: {allowed}")

        object.__setattr__(self, "hook_id", hook_id)
        object.__setattr__(self, "trigger", trigger)
        object.__setattr__(self, "flag_id", flag_id)
        object.__setattr__(self, "to_status", to_status)


@dataclass(frozen=True, slots=True)
class EncounterWave:
    wave_id: str
    objective_ids: tuple[str, ...]
    spawn_ids: tuple[str, ...] = ()
    on_start_hooks: tuple[str, ...] = ()
    on_complete_hooks: tuple[str, ...] = ()
    next_wave_id: str | None = None

    def __post_init__(self) -> None:
        wave_id = _required_text(self.wave_id, field_name="wave_id")
        objective_ids = _normalize_text_tuple(self.objective_ids, field_name="objective_ids")
        spawn_ids = _normalize_text_tuple(self.spawn_ids, field_name="spawn_ids")
        on_start_hooks = _normalize_text_tuple(self.on_start_hooks, field_name="on_start_hooks")
        on_complete_hooks = _normalize_text_tuple(
            self.on_complete_hooks,
            field_name="on_complete_hooks",
        )

        next_wave_id: str | None = None
        if self.next_wave_id is not None:
            next_wave_id = _required_text(self.next_wave_id, field_name="next_wave_id")

        object.__setattr__(self, "wave_id", wave_id)
        object.__setattr__(self, "objective_ids", objective_ids)
        object.__setattr__(self, "spawn_ids", spawn_ids)
        object.__setattr__(self, "on_start_hooks", on_start_hooks)
        object.__setattr__(self, "on_complete_hooks", on_complete_hooks)
        object.__setattr__(self, "next_wave_id", next_wave_id)


@dataclass(frozen=True, slots=True)
class EncounterScript:
    encounter_id: str
    initial_wave_id: str
    objectives: dict[str, EncounterObjective]
    waves: dict[str, EncounterWave]
    map_hooks: dict[str, EncounterMapHook]

    def __post_init__(self) -> None:
        encounter_id = _required_text(self.encounter_id, field_name="encounter_id")
        initial_wave_id = _required_text(self.initial_wave_id, field_name="initial_wave_id")

        objectives: dict[str, EncounterObjective] = {}
        for objective_id, objective in sorted(dict(self.objectives).items()):
            normalized_id = _required_text(objective_id, field_name="objective_id")
            if not isinstance(objective, EncounterObjective):
                raise ValueError("objectives must contain EncounterObjective values")
            if objective.objective_id != normalized_id:
                objective = EncounterObjective(
                    objective_id=normalized_id,
                    description=objective.description,
                    quest_id=objective.quest_id,
                    quest_objective_id=objective.quest_objective_id,
                    completion_flag=objective.completion_flag,
                )
            objectives[normalized_id] = objective

        hooks: dict[str, EncounterMapHook] = {}
        for hook_id, hook in sorted(dict(self.map_hooks).items()):
            normalized_id = _required_text(hook_id, field_name="hook_id")
            if not isinstance(hook, EncounterMapHook):
                raise ValueError("map_hooks must contain EncounterMapHook values")
            if hook.hook_id != normalized_id:
                hook = EncounterMapHook(
                    hook_id=normalized_id,
                    trigger=hook.trigger,
                    flag_id=hook.flag_id,
                    to_status=hook.to_status,
                )
            hooks[normalized_id] = hook

        waves: dict[str, EncounterWave] = {}
        for wave_id, wave in sorted(dict(self.waves).items()):
            normalized_id = _required_text(wave_id, field_name="wave_id")
            if not isinstance(wave, EncounterWave):
                raise ValueError("waves must contain EncounterWave values")
            if wave.wave_id != normalized_id:
                wave = EncounterWave(
                    wave_id=normalized_id,
                    objective_ids=wave.objective_ids,
                    spawn_ids=wave.spawn_ids,
                    on_start_hooks=wave.on_start_hooks,
                    on_complete_hooks=wave.on_complete_hooks,
                    next_wave_id=wave.next_wave_id,
                )
            waves[normalized_id] = wave

        if initial_wave_id not in waves:
            raise ValueError("initial_wave_id must reference an existing wave")

        objective_ids = set(objectives)
        hook_ids = set(hooks)
        wave_ids = set(waves)
        for wave in waves.values():
            for objective_id in wave.objective_ids:
                if objective_id not in objective_ids:
                    raise ValueError(
                        f"wave '{wave.wave_id}' references unknown objective_id '{objective_id}'"
                    )
            for hook_id in wave.on_start_hooks:
                if hook_id not in hook_ids:
                    raise ValueError(
                        f"wave '{wave.wave_id}' references unknown map hook '{hook_id}'"
                    )
            for hook_id in wave.on_complete_hooks:
                if hook_id not in hook_ids:
                    raise ValueError(
                        f"wave '{wave.wave_id}' references unknown map hook '{hook_id}'"
                    )
            if wave.next_wave_id is not None and wave.next_wave_id not in wave_ids:
                raise ValueError(
                    f"wave '{wave.wave_id}' next_wave_id '{wave.next_wave_id}' does not exist"
                )

        object.__setattr__(self, "encounter_id", encounter_id)
        object.__setattr__(self, "initial_wave_id", initial_wave_id)
        object.__setattr__(self, "objectives", objectives)
        object.__setattr__(self, "waves", waves)
        object.__setattr__(self, "map_hooks", hooks)


@dataclass(frozen=True, slots=True)
class EncounterRunState:
    encounter_id: str
    active_wave_id: str | None
    wave_statuses: dict[str, str]
    objective_statuses: dict[str, bool]
    triggered_hooks: tuple[str, ...] = ()
    status: str = "active"

    def __post_init__(self) -> None:
        encounter_id = _required_text(self.encounter_id, field_name="encounter_id")
        active_wave_id: str | None = None
        if self.active_wave_id is not None:
            active_wave_id = _required_text(self.active_wave_id, field_name="active_wave_id")

        status = _required_text(self.status, field_name="status")
        if status not in _RUN_STATUSES:
            allowed = ", ".join(sorted(_RUN_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")

        wave_statuses: dict[str, str] = {}
        active_count = 0
        for wave_id, wave_status in sorted(dict(self.wave_statuses).items()):
            normalized_wave_id = _required_text(wave_id, field_name="wave_id")
            normalized_status = _required_text(
                wave_status,
                field_name=f"wave_status[{normalized_wave_id}]",
            )
            if normalized_status not in _WAVE_STATUSES:
                allowed = ", ".join(sorted(_WAVE_STATUSES))
                raise ValueError(f"wave status must be one of: {allowed}")
            if normalized_status == "active":
                active_count += 1
            wave_statuses[normalized_wave_id] = normalized_status

        if active_count > 1:
            raise ValueError("only one wave can be active at a time")
        if status == "active" and active_wave_id is None:
            raise ValueError("active encounter run must have an active_wave_id")
        if status == "completed" and active_wave_id is not None:
            raise ValueError("completed encounter run cannot have an active_wave_id")
        if active_wave_id is not None and wave_statuses.get(active_wave_id) != "active":
            raise ValueError("active_wave_id must reference a wave with status 'active'")

        objective_statuses: dict[str, bool] = {}
        for objective_id, completed in sorted(dict(self.objective_statuses).items()):
            normalized_id = _required_text(objective_id, field_name="objective_id")
            if not isinstance(completed, bool):
                raise ValueError("objective_statuses values must be bool")
            objective_statuses[normalized_id] = completed

        triggered_hooks = _normalize_text_tuple(self.triggered_hooks, field_name="triggered_hooks")

        object.__setattr__(self, "encounter_id", encounter_id)
        object.__setattr__(self, "active_wave_id", active_wave_id)
        object.__setattr__(self, "wave_statuses", wave_statuses)
        object.__setattr__(self, "objective_statuses", objective_statuses)
        object.__setattr__(self, "triggered_hooks", triggered_hooks)
        object.__setattr__(self, "status", status)


def _parse_objectives(raw: Any) -> dict[str, EncounterObjective]:
    if raw is None:
        return {}
    objectives: dict[str, EncounterObjective] = {}

    if isinstance(raw, list):
        for item in raw:
            payload = _required_mapping(item, field_name="objective")
            objective = EncounterObjective(
                objective_id=payload.get("objective_id"),
                description=payload.get("description"),
                quest_id=payload.get("quest_id"),
                quest_objective_id=payload.get("quest_objective_id"),
                completion_flag=payload.get("completion_flag"),
            )
            objectives[objective.objective_id] = objective
        return objectives

    if isinstance(raw, Mapping):
        for objective_id, item in sorted(raw.items()):
            payload = _required_mapping(item, field_name="objective")
            objective = EncounterObjective(
                objective_id=payload.get("objective_id", objective_id),
                description=payload.get("description"),
                quest_id=payload.get("quest_id"),
                quest_objective_id=payload.get("quest_objective_id"),
                completion_flag=payload.get("completion_flag"),
            )
            objectives[objective.objective_id] = objective
        return objectives

    raise ValueError("objectives must be a list or mapping")


def _parse_map_hooks(raw: Any) -> dict[str, EncounterMapHook]:
    if raw is None:
        return {}
    hooks: dict[str, EncounterMapHook] = {}

    if isinstance(raw, list):
        for item in raw:
            payload = _required_mapping(item, field_name="map_hook")
            hook = EncounterMapHook(
                hook_id=payload.get("hook_id"),
                trigger=payload.get("trigger", "manual"),
                flag_id=payload.get("flag_id"),
                to_status=payload.get("to_status", "active"),
            )
            hooks[hook.hook_id] = hook
        return hooks

    if isinstance(raw, Mapping):
        for hook_id, item in sorted(raw.items()):
            payload = _required_mapping(item, field_name="map_hook")
            hook = EncounterMapHook(
                hook_id=payload.get("hook_id", hook_id),
                trigger=payload.get("trigger", "manual"),
                flag_id=payload.get("flag_id"),
                to_status=payload.get("to_status", "active"),
            )
            hooks[hook.hook_id] = hook
        return hooks

    raise ValueError("map_hooks must be a list or mapping")


def _parse_waves(raw: Any) -> dict[str, EncounterWave]:
    if raw is None:
        raise ValueError("waves must be provided")
    waves: dict[str, EncounterWave] = {}

    if isinstance(raw, list):
        for item in raw:
            payload = _required_mapping(item, field_name="wave")
            wave = EncounterWave(
                wave_id=payload.get("wave_id"),
                objective_ids=tuple(payload.get("objective_ids", ())),
                spawn_ids=tuple(payload.get("spawn_ids", ())),
                on_start_hooks=tuple(payload.get("on_start_hooks", ())),
                on_complete_hooks=tuple(payload.get("on_complete_hooks", ())),
                next_wave_id=payload.get("next_wave_id"),
            )
            waves[wave.wave_id] = wave
        return waves

    if isinstance(raw, Mapping):
        for wave_id, item in sorted(raw.items()):
            payload = _required_mapping(item, field_name="wave")
            wave = EncounterWave(
                wave_id=payload.get("wave_id", wave_id),
                objective_ids=tuple(payload.get("objective_ids", ())),
                spawn_ids=tuple(payload.get("spawn_ids", ())),
                on_start_hooks=tuple(payload.get("on_start_hooks", ())),
                on_complete_hooks=tuple(payload.get("on_complete_hooks", ())),
                next_wave_id=payload.get("next_wave_id"),
            )
            waves[wave.wave_id] = wave
        return waves

    raise ValueError("waves must be a list or mapping")


def parse_encounter_script(payload: Mapping[str, Any]) -> EncounterScript:
    root = _required_mapping(payload, field_name="payload")
    return EncounterScript(
        encounter_id=root.get("encounter_id"),
        initial_wave_id=root.get("initial_wave_id"),
        objectives=_parse_objectives(root.get("objectives")),
        waves=_parse_waves(root.get("waves")),
        map_hooks=_parse_map_hooks(root.get("map_hooks")),
    )


def _apply_wave_hooks(
    script: EncounterScript,
    run: EncounterRunState,
    state: WorldState,
    *,
    wave_id: str,
    trigger: str,
) -> tuple[EncounterRunState, WorldState]:
    wave = script.waves[wave_id]
    hook_ids = wave.on_start_hooks if trigger == "wave_start" else wave.on_complete_hooks
    next_run = run
    next_state = state
    for hook_id in hook_ids:
        hook = script.map_hooks[hook_id]
        if hook.trigger != trigger:
            continue
        next_run, next_state = trigger_map_hook(
            script,
            next_run,
            next_state,
            hook_id=hook_id,
        )
    return next_run, next_state


def create_encounter_run(
    script: EncounterScript,
    state: WorldState,
) -> tuple[EncounterRunState, WorldState]:
    if not isinstance(script, EncounterScript):
        raise ValueError("script must be an EncounterScript")
    if not isinstance(state, WorldState):
        raise ValueError("state must be a WorldState")

    wave_statuses = {wave_id: "locked" for wave_id in sorted(script.waves)}
    wave_statuses[script.initial_wave_id] = "active"
    objective_statuses = {objective_id: False for objective_id in sorted(script.objectives)}

    run = EncounterRunState(
        encounter_id=script.encounter_id,
        active_wave_id=script.initial_wave_id,
        wave_statuses=wave_statuses,
        objective_statuses=objective_statuses,
        triggered_hooks=(),
        status="active",
    )

    next_state = set_world_flag_status(
        state,
        flag_id=f"encounter.{script.encounter_id}.status",
        to_status="active",
    )
    next_state = set_world_flag_status(
        next_state,
        flag_id=f"encounter.{script.encounter_id}.wave.{script.initial_wave_id}",
        to_status="active",
    )
    run, next_state = _apply_wave_hooks(
        script,
        run,
        next_state,
        wave_id=script.initial_wave_id,
        trigger="wave_start",
    )
    return run, next_state


def trigger_map_hook(
    script: EncounterScript,
    run: EncounterRunState,
    state: WorldState,
    *,
    hook_id: str,
) -> tuple[EncounterRunState, WorldState]:
    normalized_hook_id = _required_text(hook_id, field_name="hook_id")
    if normalized_hook_id not in script.map_hooks:
        raise ValueError(f"Unknown map hook '{normalized_hook_id}'")

    if normalized_hook_id in run.triggered_hooks:
        return run, state

    hook = script.map_hooks[normalized_hook_id]
    next_state = set_world_flag_status(
        state,
        flag_id=hook.flag_id,
        to_status=hook.to_status,
    )
    next_run = EncounterRunState(
        encounter_id=run.encounter_id,
        active_wave_id=run.active_wave_id,
        wave_statuses=run.wave_statuses,
        objective_statuses=run.objective_statuses,
        triggered_hooks=tuple(sorted(set(run.triggered_hooks) | {normalized_hook_id})),
        status=run.status,
    )
    return next_run, next_state


def set_encounter_objective(
    script: EncounterScript,
    run: EncounterRunState,
    state: WorldState,
    *,
    objective_id: str,
    completed: bool = True,
) -> tuple[EncounterRunState, WorldState]:
    normalized_objective_id = _required_text(objective_id, field_name="objective_id")
    if normalized_objective_id not in script.objectives:
        raise ValueError(f"Unknown objective_id '{normalized_objective_id}'")
    if not isinstance(completed, bool):
        raise ValueError("completed must be a bool")

    objective = script.objectives[normalized_objective_id]
    objective_statuses = dict(run.objective_statuses)
    objective_statuses[normalized_objective_id] = completed
    next_state = state

    if objective.quest_id is not None:
        existing = next_state.quests.get(
            objective.quest_id, QuestState(quest_id=objective.quest_id)
        )
        target_status = existing.status
        if completed and target_status == "not_started":
            target_status = "active"
        objective_key = objective.quest_objective_id or normalized_objective_id
        next_state = transition_quest_state(
            next_state,
            quest_id=objective.quest_id,
            to_status=target_status,
            objective_updates={objective_key: completed},
        )

    if completed and objective.completion_flag is not None:
        next_state = set_world_flag_status(
            next_state,
            flag_id=objective.completion_flag,
            to_status="active",
        )

    next_run = EncounterRunState(
        encounter_id=run.encounter_id,
        active_wave_id=run.active_wave_id,
        wave_statuses=run.wave_statuses,
        objective_statuses=objective_statuses,
        triggered_hooks=run.triggered_hooks,
        status=run.status,
    )
    return next_run, next_state


def advance_encounter_wave(
    script: EncounterScript,
    run: EncounterRunState,
    state: WorldState,
) -> tuple[EncounterRunState, WorldState]:
    if run.status != "active":
        raise ValueError("Encounter run is not active")
    if run.active_wave_id is None:
        raise ValueError("active_wave_id must be set when run is active")

    current_wave = script.waves[run.active_wave_id]
    incomplete_objectives = [
        objective_id
        for objective_id in current_wave.objective_ids
        if not run.objective_statuses.get(objective_id, False)
    ]
    if incomplete_objectives:
        missing = ", ".join(incomplete_objectives)
        raise ValueError(f"Cannot advance wave with incomplete objectives: {missing}")

    next_run, next_state = _apply_wave_hooks(
        script,
        run,
        state,
        wave_id=current_wave.wave_id,
        trigger="wave_complete",
    )

    next_state = set_world_flag_status(
        next_state,
        flag_id=f"encounter.{script.encounter_id}.wave.{current_wave.wave_id}",
        to_status="resolved",
    )

    wave_statuses = dict(next_run.wave_statuses)
    wave_statuses[current_wave.wave_id] = "completed"

    if current_wave.next_wave_id is None:
        next_state = set_world_flag_status(
            next_state,
            flag_id=f"encounter.{script.encounter_id}.status",
            to_status="resolved",
        )
        completed_run = EncounterRunState(
            encounter_id=next_run.encounter_id,
            active_wave_id=None,
            wave_statuses=wave_statuses,
            objective_statuses=next_run.objective_statuses,
            triggered_hooks=next_run.triggered_hooks,
            status="completed",
        )
        return completed_run, next_state

    next_wave_id = current_wave.next_wave_id
    wave_statuses[next_wave_id] = "active"
    next_state = set_world_flag_status(
        next_state,
        flag_id=f"encounter.{script.encounter_id}.wave.{next_wave_id}",
        to_status="active",
    )
    promoted_run = EncounterRunState(
        encounter_id=next_run.encounter_id,
        active_wave_id=next_wave_id,
        wave_statuses=wave_statuses,
        objective_statuses=next_run.objective_statuses,
        triggered_hooks=next_run.triggered_hooks,
        status="active",
    )
    promoted_run, next_state = _apply_wave_hooks(
        script,
        promoted_run,
        next_state,
        wave_id=next_wave_id,
        trigger="wave_start",
    )
    return promoted_run, next_state
