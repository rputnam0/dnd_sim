"""Focused authoritative roll adapters used by combat action resolution."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from typing import Any, Iterator, Literal, Sequence

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.roll_journal import (
    BoundRollJournalRecorder,
    D20Adjustment,
    D20Resolution,
    D20RollFact,
    DamageAdjustment,
    DamageRollFact,
    DieFace,
    EngineRollJournalRecorder,
    HealingRollFact,
    ModifierDieFace,
    RollAudienceIntent,
    RollRecordContext,
    SavingThrowFact,
)
from dnd_sim.roll_hook_provenance import RollHookTrace

logger = logging.getLogger(__name__)

_ACTIVE_RECORDER: ContextVar[EngineRollJournalRecorder | None] = ContextVar(
    "active_combat_roll_journal_recorder",
    default=None,
)


@contextmanager
def combat_roll_journal_scope(
    recorder: EngineRollJournalRecorder | None,
) -> Iterator[None]:
    """Bind an opt-in authoritative recorder to one synchronous resolution."""

    if recorder is not None and not isinstance(recorder, EngineRollJournalRecorder):
        raise TypeError("recorder must be an EngineRollJournalRecorder")
    token = _ACTIVE_RECORDER.set(recorder)
    try:
        yield
    finally:
        _ACTIVE_RECORDER.reset(token)


def bound_roll_recorder(
    *,
    source: ActorRuntimeState,
    target: ActorRuntimeState | None,
    action: ActionDefinition,
    purpose: str,
) -> BoundRollJournalRecorder | None:
    recorder = _ACTIVE_RECORDER.get()
    if recorder is None:
        return None
    return recorder.bind(
        RollRecordContext(
            source_actor_id=source.actor_id,
            target_actor_id=target.actor_id if target is not None else None,
            action_id=f"action:{action.name}",
            purpose=purpose,
            audience=RollAudienceIntent(visibility="public", actor_ids=()),
        )
    )


def capture_roll_recorder(
    bound: BoundRollJournalRecorder | None,
) -> BoundRollJournalRecorder | None:
    if bound is None:
        return None
    return EngineRollJournalRecorder.empty("capture").bind(bound.context)


def captured_damage_fact(
    recorder: BoundRollJournalRecorder | None,
) -> DamageRollFact | None:
    if recorder is None or not recorder.journal.records:
        return None
    fact = recorder.journal.records[-1].fact
    return fact if isinstance(fact, DamageRollFact) else None


def damage_packet_identity(packets: Sequence[Any], index: int) -> tuple[str, int]:
    """Identify a packet by stable source plus its occurrence within the bundle."""

    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(packets):
        raise IndexError("damage packet index is out of bounds")
    source = str(packets[index].source)
    occurrence = sum(1 for packet in packets[:index] if str(packet.source) == source)
    return source, occurrence


def first_generated_raw_modifier_face(
    hook_trace: Sequence[RollHookTrace],
) -> ModifierDieFace | None:
    """Return the one generated die responsible for a raw-stage timing change."""

    traced = [
        item
        for item in hook_trace
        if item.stage == "raw" and item.die_sides is not None and item.die_value is not None
    ]
    if len(traced) > 1:
        raise ValueError("raw damage finalization supports one generated timing die")
    if not traced:
        return None
    return ModifierDieFace(
        generation_index=1,
        sides=int(traced[0].die_sides),
        value=int(traced[0].die_value),
    )


def finalized_attack_fact(
    captured: D20RollFact,
    *,
    natural_roll: int,
    total: int,
    hit: bool,
    critical: bool,
    target_ac: int,
    hook_trace: Sequence[RollHookTrace] = (),
) -> D20RollFact:
    """Promote a base d20 fact using explicit post-hook provenance only."""

    trace = tuple(hook_trace)
    if any(not isinstance(item, RollHookTrace) for item in trace):
        raise TypeError("hook_trace must contain RollHookTrace values")
    captured_roll = captured.roll
    final_faces = list(captured_roll.faces)
    final_candidates = list(captured_roll.candidate_generation_indices)
    final_kept_index = captured_roll.kept_generation_index
    used_replacement_hook = False
    for item in trace:
        if item.stage != "replacement":
            continue
        used_replacement_hook = True
        replacement_index = len(final_faces) + 1
        if item.selected:
            current = final_faces[final_kept_index - 1]
            final_faces[final_kept_index - 1] = current.model_copy(
                update={
                    "status": "replaced",
                    "replacement_generation_index": replacement_index,
                }
            )
            final_candidates.remove(final_kept_index)
            status = "kept"
            final_kept_index = replacement_index
        else:
            status = "discarded"
        final_candidates.append(replacement_index)
        final_faces.append(
            DieFace(
                generation_index=replacement_index,
                sides=20,
                value=int(item.die_value),
                status=status,
                replacement_generation_index=None,
            )
        )

    modifier_generation_index = 0
    adjustments: list[D20Adjustment] = []
    for item in trace:
        if item.stage not in {"total", "threshold"}:
            continue
        generated_face = None
        if item.die_value is not None and item.die_sides is not None:
            modifier_generation_index += 1
            generated_face = ModifierDieFace(
                generation_index=modifier_generation_index,
                sides=item.die_sides,
                value=item.die_value,
            )
        adjustments.append(
            D20Adjustment(
                stage=item.stage,
                kind=item.kind,
                amount=item.amount,
                generated_face=generated_face,
            )
        )

    kept = final_faces[final_kept_index - 1]
    if kept.value != natural_roll:
        raise ValueError("hook trace does not identify the authoritative final natural roll")
    base_total = natural_roll + captured_roll.flat_modifier
    traced_total = base_total + sum(item.amount for item in adjustments if item.stage == "total")
    if traced_total != total:
        raise ValueError("hook trace does not account for the authoritative final total")
    final_threshold = target_ac + sum(
        item.amount for item in adjustments if item.stage == "threshold"
    )
    return D20RollFact(
        kind="d20",
        roll=D20Resolution(
            expression=captured_roll.expression,
            mode="resolved" if used_replacement_hook else captured_roll.mode,
            faces=tuple(final_faces),
            candidate_generation_indices=tuple(final_candidates),
            kept_generation_index=final_kept_index,
            flat_modifier=captured_roll.flat_modifier,
            total=base_total,
        ),
        threshold=final_threshold,
        outcome="hit" if hit else "miss",
        critical=critical,
        adjustments=tuple(adjustments),
    )


def finalized_damage_fact(
    captured: DamageRollFact,
    *,
    raw_damage: int | None = None,
    applied_damage: int,
    raw_generated_face: ModifierDieFace | None = None,
    adjustment_kind: (
        Literal[
            "floor",
            "bonus",
            "reduction",
            "resistance",
            "vulnerability",
            "immunity",
            "absorption",
            "other",
        ]
        | None
    ) = None,
) -> DamageRollFact:
    finalized_raw = captured.raw_damage if raw_damage is None else raw_damage
    raw_adjustments: tuple[DamageAdjustment, ...] = ()
    raw_adjustment_amount = finalized_raw - captured.raw_damage
    if raw_adjustment_amount:
        raw_adjustments = (
            DamageAdjustment(
                stage="raw",
                kind="reduction" if raw_adjustment_amount < 0 else "bonus",
                amount=raw_adjustment_amount,
                source_id=None,
                generated_face=raw_generated_face,
            ),
        )
    elif raw_generated_face is not None:
        raise ValueError("a generated raw modifier die requires a raw damage change")
    adjustment_amount = applied_damage - finalized_raw
    applied_adjustments: tuple[DamageAdjustment, ...] = ()
    if adjustment_amount:
        kind = adjustment_kind
        if kind is None:
            if applied_damage == 0:
                kind = "immunity"
            elif applied_damage == captured.raw_damage // 2:
                kind = "resistance"
            elif applied_damage == captured.raw_damage * 2:
                kind = "vulnerability"
            elif adjustment_amount < 0:
                kind = "reduction"
            else:
                kind = "bonus"
        applied_adjustments = (
            DamageAdjustment(
                stage="applied",
                kind=kind,
                amount=adjustment_amount,
                source_id=None,
            ),
        )
    return DamageRollFact.model_validate(
        {
            **captured.model_dump(mode="python"),
            "applied_damage": applied_damage,
            "raw_damage": finalized_raw,
            "adjustments": [
                *captured.adjustments,
                *raw_adjustments,
                *applied_adjustments,
            ],
        }
    )


def record_saving_throw(
    recorder: BoundRollJournalRecorder | None,
    *,
    ability: str,
    mode: Literal["normal", "advantage", "disadvantage"],
    generated_values: Sequence[int],
    natural_roll: int,
    modifier: int,
    dc: int,
    succeeded: bool,
) -> None:
    if recorder is None or not generated_values:
        return
    kept_generation_index = next(
        index for index, value in enumerate(generated_values, start=1) if value == natural_roll
    )
    expression = {
        "normal": "1d20",
        "advantage": f"{len(generated_values)}d20kh1",
        "disadvantage": f"{len(generated_values)}d20kl1",
    }[mode]
    ability_name = {
        "str": "strength",
        "dex": "dexterity",
        "con": "constitution",
        "int": "intelligence",
        "wis": "wisdom",
        "cha": "charisma",
    }.get(ability, ability)
    recorder.record_fact(
        SavingThrowFact.model_validate(
            {
                "kind": "saving_throw",
                "ability": ability_name,
                "roll": {
                    "expression": f"{expression}{modifier:+d}",
                    "mode": mode,
                    "faces": [
                        {
                            "generation_index": index,
                            "sides": 20,
                            "value": value,
                            "status": ("kept" if index == kept_generation_index else "discarded"),
                            "replacement_generation_index": None,
                        }
                        for index, value in enumerate(generated_values, start=1)
                    ],
                    "candidate_generation_indices": list(range(1, len(generated_values) + 1)),
                    "kept_generation_index": kept_generation_index,
                    "flat_modifier": modifier,
                    "total": natural_roll + modifier,
                },
                "dc": dc,
                "succeeded": succeeded,
            }
        )
    )


def finalized_healing_fact(
    *,
    captured: DamageRollFact | None,
    expression: str,
    rolled_healing: int,
    effective_healing: int,
) -> HealingRollFact | None:
    if captured is not None:
        if captured.raw_damage != captured.rolled_total or captured.raw_damage != rolled_healing:
            return None
        faces = captured.faces
        flat_modifier = captured.flat_modifier
        expression = captured.expression
    else:
        faces = ()
        flat_modifier = rolled_healing
    return HealingRollFact(
        kind="healing",
        expression=expression,
        faces=faces,
        flat_modifier=flat_modifier,
        rolled_healing=rolled_healing,
        effective_healing=effective_healing,
        overheal=rolled_healing - effective_healing,
    )


__all__ = [
    "bound_roll_recorder",
    "capture_roll_recorder",
    "captured_damage_fact",
    "combat_roll_journal_scope",
    "damage_packet_identity",
    "first_generated_raw_modifier_face",
    "finalized_attack_fact",
    "finalized_damage_fact",
    "finalized_healing_fact",
    "record_saving_throw",
]
