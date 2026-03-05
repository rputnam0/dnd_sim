from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

FALL_DAMAGE_DIE_SIDES = 6
MAX_FALL_DAMAGE_DICE = 20
MINUTES_PER_HOUR = 60
DISEASE_SAVE_INTERVAL_MINUTES = 24 * MINUTES_PER_HOUR


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _normalize_conditions(values: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("conditions must contain strings")
        text = raw.strip().lower()
        if text:
            normalized.add(text)
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class DiseaseState:
    disease_id: str
    stage: int = 0
    minutes_until_next_save: int = DISEASE_SAVE_INTERVAL_MINUTES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disease_id",
            _required_text(self.disease_id, field_name="disease_id"),
        )
        if not isinstance(self.stage, int) or isinstance(self.stage, bool) or self.stage < 0:
            raise ValueError("stage must be an integer >= 0")
        if (
            not isinstance(self.minutes_until_next_save, int)
            or isinstance(self.minutes_until_next_save, bool)
            or self.minutes_until_next_save <= 0
        ):
            raise ValueError("minutes_until_next_save must be an integer > 0")


@dataclass(frozen=True, slots=True)
class HazardActorState:
    actor_id: str
    hp: int
    max_hp: int
    con_mod: int = 0
    exhaustion_level: int = 0
    breath_rounds_remaining: int | None = None
    suffocating_rounds: int = 0
    poisoned_minutes_remaining: int = 0
    conditions: tuple[str, ...] = ()
    diseases: dict[str, DiseaseState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _required_text(self.actor_id, field_name="actor_id"))
        for field_name in ("hp", "max_hp", "con_mod", "exhaustion_level", "suffocating_rounds"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be an integer")
        if self.max_hp <= 0:
            raise ValueError("max_hp must be > 0")
        if self.hp < 0 or self.hp > self.max_hp:
            raise ValueError("hp must be between 0 and max_hp")
        if self.exhaustion_level < 0 or self.exhaustion_level > 6:
            raise ValueError("exhaustion_level must be from 0 to 6")
        if self.suffocating_rounds < 0:
            raise ValueError("suffocating_rounds must be >= 0")
        if (
            not isinstance(self.poisoned_minutes_remaining, int)
            or isinstance(self.poisoned_minutes_remaining, bool)
            or self.poisoned_minutes_remaining < 0
        ):
            raise ValueError("poisoned_minutes_remaining must be an integer >= 0")
        if self.breath_rounds_remaining is not None and (
            not isinstance(self.breath_rounds_remaining, int)
            or isinstance(self.breath_rounds_remaining, bool)
            or self.breath_rounds_remaining < 0
        ):
            raise ValueError("breath_rounds_remaining must be None or an integer >= 0")

        object.__setattr__(self, "conditions", _normalize_conditions(self.conditions))

        normalized_diseases: dict[str, DiseaseState] = {}
        for disease_key, disease in sorted(dict(self.diseases).items()):
            if not isinstance(disease, DiseaseState):
                raise ValueError("diseases must contain DiseaseState values")
            normalized_key = _required_text(disease_key, field_name="disease_id")
            if disease.disease_id != normalized_key:
                disease = DiseaseState(
                    disease_id=normalized_key,
                    stage=disease.stage,
                    minutes_until_next_save=disease.minutes_until_next_save,
                )
            normalized_diseases[normalized_key] = disease
        object.__setattr__(self, "diseases", normalized_diseases)


@dataclass(frozen=True, slots=True)
class WorldHazardState:
    minute_index: int
    actors: dict[str, HazardActorState]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.minute_index, int)
            or isinstance(self.minute_index, bool)
            or self.minute_index < 0
        ):
            raise ValueError("minute_index must be an integer >= 0")

        normalized_actors: dict[str, HazardActorState] = {}
        for actor_id, actor in sorted(dict(self.actors).items()):
            normalized_actor_id = _required_text(actor_id, field_name="actor_id")
            if not isinstance(actor, HazardActorState):
                raise ValueError("actors must contain HazardActorState values")
            if actor.actor_id != normalized_actor_id:
                actor = HazardActorState(
                    actor_id=normalized_actor_id,
                    hp=actor.hp,
                    max_hp=actor.max_hp,
                    con_mod=actor.con_mod,
                    exhaustion_level=actor.exhaustion_level,
                    breath_rounds_remaining=actor.breath_rounds_remaining,
                    suffocating_rounds=actor.suffocating_rounds,
                    poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
                    conditions=actor.conditions,
                    diseases=actor.diseases,
                )
            normalized_actors[normalized_actor_id] = actor
        object.__setattr__(self, "actors", normalized_actors)


@dataclass(frozen=True, slots=True)
class HazardResolution:
    state: WorldHazardState
    event_type: str
    actor_id: str
    details: dict[str, Any]


def _coerce_disease_state(disease_id: str, payload: DiseaseState | dict[str, Any]) -> DiseaseState:
    if isinstance(payload, DiseaseState):
        if payload.disease_id == disease_id:
            return payload
        return DiseaseState(
            disease_id=disease_id,
            stage=payload.stage,
            minutes_until_next_save=payload.minutes_until_next_save,
        )
    if not isinstance(payload, dict):
        raise ValueError("disease payload must be a dict or DiseaseState")
    return DiseaseState(
        disease_id=disease_id,
        stage=int(payload.get("stage", 0)),
        minutes_until_next_save=int(
            payload.get("minutes_until_next_save", DISEASE_SAVE_INTERVAL_MINUTES)
        ),
    )


def _coerce_actor_state(
    actor_id: str,
    payload: HazardActorState | dict[str, Any],
) -> HazardActorState:
    if isinstance(payload, HazardActorState):
        if payload.actor_id == actor_id:
            return payload
        return HazardActorState(
            actor_id=actor_id,
            hp=payload.hp,
            max_hp=payload.max_hp,
            con_mod=payload.con_mod,
            exhaustion_level=payload.exhaustion_level,
            breath_rounds_remaining=payload.breath_rounds_remaining,
            suffocating_rounds=payload.suffocating_rounds,
            poisoned_minutes_remaining=payload.poisoned_minutes_remaining,
            conditions=payload.conditions,
            diseases=payload.diseases,
        )
    if not isinstance(payload, dict):
        raise ValueError("actor payload must be a dict or HazardActorState")

    diseases_payload = payload.get("diseases", {})
    if not isinstance(diseases_payload, dict):
        raise ValueError("diseases must be a mapping")
    diseases: dict[str, DiseaseState] = {}
    for disease_id, disease_payload in diseases_payload.items():
        normalized_id = _required_text(disease_id, field_name="disease_id")
        diseases[normalized_id] = _coerce_disease_state(normalized_id, disease_payload)

    return HazardActorState(
        actor_id=actor_id,
        hp=int(payload.get("hp", payload.get("max_hp", 1))),
        max_hp=int(payload.get("max_hp", payload.get("hp", 1))),
        con_mod=int(payload.get("con_mod", 0)),
        exhaustion_level=int(payload.get("exhaustion_level", 0)),
        breath_rounds_remaining=(
            None
            if payload.get("breath_rounds_remaining") is None
            else int(payload["breath_rounds_remaining"])
        ),
        suffocating_rounds=int(payload.get("suffocating_rounds", 0)),
        poisoned_minutes_remaining=int(payload.get("poisoned_minutes_remaining", 0)),
        conditions=tuple(payload.get("conditions", ())),
        diseases=diseases,
    )


def create_world_hazard_state(
    *,
    actors: dict[str, HazardActorState | dict[str, Any]] | None = None,
    minute_index: int = 0,
) -> WorldHazardState:
    normalized_actors: dict[str, HazardActorState] = {}
    for actor_id, actor_payload in sorted((actors or {}).items()):
        normalized_actor_id = _required_text(actor_id, field_name="actor_id")
        normalized_actors[normalized_actor_id] = _coerce_actor_state(
            normalized_actor_id,
            actor_payload,
        )
    return WorldHazardState(minute_index=minute_index, actors=normalized_actors)


def _replace_actor(state: WorldHazardState, actor: HazardActorState) -> WorldHazardState:
    actors = dict(state.actors)
    actors[actor.actor_id] = actor
    return WorldHazardState(minute_index=state.minute_index, actors=actors)


def _advance_minutes(state: WorldHazardState, *, elapsed_minutes: int) -> WorldHazardState:
    return WorldHazardState(
        minute_index=state.minute_index + elapsed_minutes,
        actors=state.actors,
    )


def breath_round_capacity(con_mod: int) -> int:
    normalized = int(con_mod)
    return max(10, (1 + normalized) * 10)


def suffocation_round_tolerance(con_mod: int) -> int:
    return max(1, int(con_mod))


def fall_damage_dice(distance_ft: int) -> int:
    if not isinstance(distance_ft, int) or isinstance(distance_ft, bool) or distance_ft < 0:
        raise ValueError("distance_ft must be an integer >= 0")
    return min(MAX_FALL_DAMAGE_DICE, distance_ft // 10)


def _clamp_d6(value: int) -> int:
    return max(1, min(FALL_DAMAGE_DIE_SIDES, int(value)))


def resolve_falling(
    state: WorldHazardState,
    *,
    actor_id: str,
    distance_ft: int,
    dice_rolls: tuple[int, ...] | list[int] | None = None,
    rng: random.Random | None = None,
) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")

    dice_count = fall_damage_dice(distance_ft)
    rolls: list[int] = []
    if dice_count > 0:
        if dice_rolls is not None:
            if len(dice_rolls) < dice_count:
                raise ValueError("dice_rolls must include one value per damage die")
            rolls = [_clamp_d6(int(value)) for value in list(dice_rolls)[:dice_count]]
        elif rng is not None:
            rolls = [rng.randint(1, FALL_DAMAGE_DIE_SIDES) for _ in range(dice_count)]
        else:
            raise ValueError("rng or dice_rolls is required when fall damage dice are rolled")

    damage = sum(rolls)
    hp_before = actor.hp
    hp_after = max(0, hp_before - damage)
    conditions = set(actor.conditions)
    if hp_after == 0 and hp_before > 0:
        conditions.add("unconscious")

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=hp_after,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=actor.exhaustion_level,
        breath_rounds_remaining=actor.breath_rounds_remaining,
        suffocating_rounds=actor.suffocating_rounds,
        poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
        conditions=tuple(conditions),
        diseases=actor.diseases,
    )
    next_state = _replace_actor(state, next_actor)
    return HazardResolution(
        state=next_state,
        event_type="fall",
        actor_id=normalized_actor_id,
        details={
            "distance_ft": distance_ft,
            "dice_count": dice_count,
            "rolls": tuple(rolls),
            "damage": damage,
            "hp_before": hp_before,
            "hp_after": hp_after,
        },
    )


def start_suffocation(state: WorldHazardState, *, actor_id: str) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=actor.hp,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=actor.exhaustion_level,
        breath_rounds_remaining=breath_round_capacity(actor.con_mod),
        suffocating_rounds=0,
        poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
        conditions=actor.conditions,
        diseases=actor.diseases,
    )
    next_state = _replace_actor(state, next_actor)
    return HazardResolution(
        state=next_state,
        event_type="suffocation_start",
        actor_id=normalized_actor_id,
        details={"breath_rounds": next_actor.breath_rounds_remaining},
    )


def advance_suffocation(
    state: WorldHazardState,
    *,
    actor_id: str,
    rounds: int,
    reason: str = "suffocation",
) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds <= 0:
        raise ValueError("rounds must be an integer > 0")

    breath = (
        breath_round_capacity(actor.con_mod)
        if actor.breath_rounds_remaining is None
        else actor.breath_rounds_remaining
    )
    suffocating_rounds = actor.suffocating_rounds
    hp = actor.hp
    conditions = set(actor.conditions)
    tolerance = suffocation_round_tolerance(actor.con_mod)

    for _ in range(rounds):
        if breath > 0:
            breath -= 1
            continue
        suffocating_rounds += 1
        if suffocating_rounds > tolerance and hp > 0:
            hp = 0
            conditions.add("unconscious")
            break

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=hp,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=actor.exhaustion_level,
        breath_rounds_remaining=breath,
        suffocating_rounds=suffocating_rounds,
        poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
        conditions=tuple(conditions),
        diseases=actor.diseases,
    )
    next_state = _advance_minutes(_replace_actor(state, next_actor), elapsed_minutes=rounds)

    return HazardResolution(
        state=next_state,
        event_type="suffocation_tick",
        actor_id=normalized_actor_id,
        details={
            "reason": _required_text(reason, field_name="reason"),
            "rounds": rounds,
            "breath_rounds_remaining": breath,
            "suffocating_rounds": suffocating_rounds,
            "hp_after": hp,
            "tolerance_rounds": tolerance,
        },
    )


def start_drowning(state: WorldHazardState, *, actor_id: str) -> HazardResolution:
    base = start_suffocation(state, actor_id=actor_id)
    return HazardResolution(
        state=base.state,
        event_type="drowning_start",
        actor_id=base.actor_id,
        details=base.details,
    )


def advance_drowning(
    state: WorldHazardState,
    *,
    actor_id: str,
    rounds: int,
) -> HazardResolution:
    tick = advance_suffocation(
        state,
        actor_id=actor_id,
        rounds=rounds,
        reason="drowning",
    )
    return HazardResolution(
        state=tick.state,
        event_type="drowning_tick",
        actor_id=tick.actor_id,
        details=tick.details,
    )


def resolve_environmental_exposure(
    state: WorldHazardState,
    *,
    actor_id: str,
    hazard_type: str,
    save_succeeded: bool,
    on_failure_damage: int = 0,
    failure_exhaustion: int = 1,
) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")
    normalized_hazard = _required_text(hazard_type, field_name="hazard_type").lower()
    if on_failure_damage < 0:
        raise ValueError("on_failure_damage must be >= 0")
    if failure_exhaustion < 0:
        raise ValueError("failure_exhaustion must be >= 0")

    hp_before = actor.hp
    exhaustion_before = actor.exhaustion_level
    hp_after = hp_before
    exhaustion_after = exhaustion_before
    conditions = set(actor.conditions)

    if not save_succeeded:
        hp_after = max(0, hp_before - int(on_failure_damage))
        exhaustion_after = min(6, exhaustion_before + int(failure_exhaustion))
        if hp_after == 0 and hp_before > 0:
            conditions.add("unconscious")

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=hp_after,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=exhaustion_after,
        breath_rounds_remaining=actor.breath_rounds_remaining,
        suffocating_rounds=actor.suffocating_rounds,
        poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
        conditions=tuple(conditions),
        diseases=actor.diseases,
    )
    next_state = _replace_actor(state, next_actor)

    return HazardResolution(
        state=next_state,
        event_type="environmental_exposure",
        actor_id=normalized_actor_id,
        details={
            "hazard_type": normalized_hazard,
            "save_succeeded": bool(save_succeeded),
            "hp_before": hp_before,
            "hp_after": hp_after,
            "exhaustion_before": exhaustion_before,
            "exhaustion_after": exhaustion_after,
        },
    )


def apply_poison_exposure(
    state: WorldHazardState,
    *,
    actor_id: str,
    duration_minutes: int,
    save_succeeded: bool,
) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")
    if (
        not isinstance(duration_minutes, int)
        or isinstance(duration_minutes, bool)
        or duration_minutes <= 0
    ):
        raise ValueError("duration_minutes must be an integer > 0")

    conditions = set(actor.conditions)
    poisoned_after = actor.poisoned_minutes_remaining
    if not save_succeeded:
        poisoned_after = max(poisoned_after, duration_minutes)
        conditions.add("poisoned")

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=actor.hp,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=actor.exhaustion_level,
        breath_rounds_remaining=actor.breath_rounds_remaining,
        suffocating_rounds=actor.suffocating_rounds,
        poisoned_minutes_remaining=poisoned_after,
        conditions=tuple(conditions),
        diseases=actor.diseases,
    )
    next_state = _replace_actor(state, next_actor)
    return HazardResolution(
        state=next_state,
        event_type="poison_exposure",
        actor_id=normalized_actor_id,
        details={
            "save_succeeded": bool(save_succeeded),
            "poisoned_minutes_before": actor.poisoned_minutes_remaining,
            "poisoned_minutes_after": poisoned_after,
        },
    )


def advance_poison(
    state: WorldHazardState,
    *,
    elapsed_minutes: int,
) -> HazardResolution:
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes <= 0
    ):
        raise ValueError("elapsed_minutes must be an integer > 0")

    updated_actors = dict(state.actors)
    changed_ids: list[str] = []
    for actor_id, actor in sorted(state.actors.items()):
        if actor.poisoned_minutes_remaining <= 0:
            continue
        after_minutes = max(0, actor.poisoned_minutes_remaining - elapsed_minutes)
        conditions = set(actor.conditions)
        if after_minutes == 0:
            conditions.discard("poisoned")
        next_actor = HazardActorState(
            actor_id=actor.actor_id,
            hp=actor.hp,
            max_hp=actor.max_hp,
            con_mod=actor.con_mod,
            exhaustion_level=actor.exhaustion_level,
            breath_rounds_remaining=actor.breath_rounds_remaining,
            suffocating_rounds=actor.suffocating_rounds,
            poisoned_minutes_remaining=after_minutes,
            conditions=tuple(conditions),
            diseases=actor.diseases,
        )
        updated_actors[actor_id] = next_actor
        changed_ids.append(actor_id)

    next_state = _advance_minutes(
        WorldHazardState(minute_index=state.minute_index, actors=updated_actors),
        elapsed_minutes=elapsed_minutes,
    )
    return HazardResolution(
        state=next_state,
        event_type="poison_tick",
        actor_id="*",
        details={"elapsed_minutes": elapsed_minutes, "changed_actor_ids": tuple(changed_ids)},
    )


def apply_disease_exposure(
    state: WorldHazardState,
    *,
    actor_id: str,
    disease_id: str,
    incubation_hours: int,
    save_succeeded: bool,
) -> HazardResolution:
    normalized_actor_id = _required_text(actor_id, field_name="actor_id")
    actor = state.actors.get(normalized_actor_id)
    if actor is None:
        raise ValueError("actor_id was not found in world hazard state")
    normalized_disease_id = _required_text(disease_id, field_name="disease_id")
    if (
        not isinstance(incubation_hours, int)
        or isinstance(incubation_hours, bool)
        or incubation_hours <= 0
    ):
        raise ValueError("incubation_hours must be an integer > 0")
    incubation_minutes = incubation_hours * MINUTES_PER_HOUR

    diseases = dict(actor.diseases)
    if not save_succeeded and normalized_disease_id not in diseases:
        diseases[normalized_disease_id] = DiseaseState(
            disease_id=normalized_disease_id,
            stage=0,
            minutes_until_next_save=incubation_minutes,
        )

    next_actor = HazardActorState(
        actor_id=actor.actor_id,
        hp=actor.hp,
        max_hp=actor.max_hp,
        con_mod=actor.con_mod,
        exhaustion_level=actor.exhaustion_level,
        breath_rounds_remaining=actor.breath_rounds_remaining,
        suffocating_rounds=actor.suffocating_rounds,
        poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
        conditions=actor.conditions,
        diseases=diseases,
    )
    next_state = _replace_actor(state, next_actor)
    return HazardResolution(
        state=next_state,
        event_type="disease_exposure",
        actor_id=normalized_actor_id,
        details={
            "disease_id": normalized_disease_id,
            "save_succeeded": bool(save_succeeded),
            "incubation_hours": incubation_hours,
        },
    )


def advance_disease_progression(
    state: WorldHazardState,
    *,
    elapsed_minutes: int,
    save_outcomes: dict[str, bool] | None = None,
) -> HazardResolution:
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes <= 0
    ):
        raise ValueError("elapsed_minutes must be an integer > 0")

    outcomes = dict(save_outcomes or {})
    updated_actors: dict[str, HazardActorState] = dict(state.actors)
    progressed: list[tuple[str, str, int]] = []

    for actor_id, actor in sorted(state.actors.items()):
        if not actor.diseases:
            continue
        diseases: dict[str, DiseaseState] = {}
        exhaustion_level = actor.exhaustion_level
        for disease_id, disease in sorted(actor.diseases.items()):
            remaining = disease.minutes_until_next_save - elapsed_minutes
            stage = disease.stage
            cleared = False
            while remaining <= 0:
                save_key = f"{actor_id}:{disease_id}"
                if bool(outcomes.get(save_key, False)):
                    cleared = True
                    break
                stage += 1
                exhaustion_level = min(6, exhaustion_level + 1)
                progressed.append((actor_id, disease_id, stage))
                remaining += DISEASE_SAVE_INTERVAL_MINUTES
            if not cleared:
                diseases[disease_id] = DiseaseState(
                    disease_id=disease_id,
                    stage=stage,
                    minutes_until_next_save=remaining,
                )

        updated_actors[actor_id] = HazardActorState(
            actor_id=actor.actor_id,
            hp=actor.hp,
            max_hp=actor.max_hp,
            con_mod=actor.con_mod,
            exhaustion_level=exhaustion_level,
            breath_rounds_remaining=actor.breath_rounds_remaining,
            suffocating_rounds=actor.suffocating_rounds,
            poisoned_minutes_remaining=actor.poisoned_minutes_remaining,
            conditions=actor.conditions,
            diseases=diseases,
        )

    next_state = _advance_minutes(
        WorldHazardState(minute_index=state.minute_index, actors=updated_actors),
        elapsed_minutes=elapsed_minutes,
    )
    return HazardResolution(
        state=next_state,
        event_type="disease_tick",
        actor_id="*",
        details={"elapsed_minutes": elapsed_minutes, "progressed": tuple(progressed)},
    )


def serialize_world_hazard_state(state: WorldHazardState) -> dict[str, Any]:
    actors_payload: list[dict[str, Any]] = []
    for actor_id, actor in sorted(state.actors.items()):
        diseases_payload: list[dict[str, Any]] = []
        for disease_id, disease in sorted(actor.diseases.items()):
            diseases_payload.append(
                {
                    "disease_id": disease_id,
                    "stage": disease.stage,
                    "minutes_until_next_save": disease.minutes_until_next_save,
                }
            )
        actors_payload.append(
            {
                "actor_id": actor_id,
                "hp": actor.hp,
                "max_hp": actor.max_hp,
                "con_mod": actor.con_mod,
                "exhaustion_level": actor.exhaustion_level,
                "breath_rounds_remaining": actor.breath_rounds_remaining,
                "suffocating_rounds": actor.suffocating_rounds,
                "poisoned_minutes_remaining": actor.poisoned_minutes_remaining,
                "conditions": list(actor.conditions),
                "diseases": diseases_payload,
            }
        )
    return {
        "minute_index": state.minute_index,
        "actors": actors_payload,
    }


def deserialize_world_hazard_state(payload: dict[str, Any]) -> WorldHazardState:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a mapping")

    minute_index = int(payload.get("minute_index", 0))
    actors_payload = payload.get("actors", [])
    if not isinstance(actors_payload, list):
        raise ValueError("actors must be a list")

    actors: dict[str, HazardActorState] = {}
    for actor_entry in actors_payload:
        if not isinstance(actor_entry, dict):
            raise ValueError("actor entries must be mappings")
        actor_id = _required_text(actor_entry.get("actor_id"), field_name="actor_id")
        diseases_payload = actor_entry.get("diseases", [])
        diseases: dict[str, DiseaseState] = {}
        if not isinstance(diseases_payload, list):
            raise ValueError("diseases must be a list")
        for disease_entry in diseases_payload:
            if not isinstance(disease_entry, dict):
                raise ValueError("disease entries must be mappings")
            disease_id = _required_text(disease_entry.get("disease_id"), field_name="disease_id")
            diseases[disease_id] = DiseaseState(
                disease_id=disease_id,
                stage=int(disease_entry.get("stage", 0)),
                minutes_until_next_save=int(
                    disease_entry.get("minutes_until_next_save", DISEASE_SAVE_INTERVAL_MINUTES)
                ),
            )
        actors[actor_id] = HazardActorState(
            actor_id=actor_id,
            hp=int(actor_entry.get("hp", actor_entry.get("max_hp", 1))),
            max_hp=int(actor_entry.get("max_hp", actor_entry.get("hp", 1))),
            con_mod=int(actor_entry.get("con_mod", 0)),
            exhaustion_level=int(actor_entry.get("exhaustion_level", 0)),
            breath_rounds_remaining=(
                None
                if actor_entry.get("breath_rounds_remaining") is None
                else int(actor_entry.get("breath_rounds_remaining"))
            ),
            suffocating_rounds=int(actor_entry.get("suffocating_rounds", 0)),
            poisoned_minutes_remaining=int(actor_entry.get("poisoned_minutes_remaining", 0)),
            conditions=tuple(actor_entry.get("conditions", ())),
            diseases=diseases,
        )
    return WorldHazardState(minute_index=minute_index, actors=actors)
