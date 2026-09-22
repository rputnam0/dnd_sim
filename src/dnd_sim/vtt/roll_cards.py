"""Audience-safe VTT projection of finalized engine roll journal facts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from dnd_sim.roll_journal import (
    AuthoritativeRollRecord,
    D20Adjustment,
    D20RollFact,
    DamageRollFact,
    DamageAdjustment,
    DieFace,
    HealingRollFact,
    ModifierDieFace,
    SavingThrowFact,
)

from .participants import TableParticipant

ROLL_CARD_SCHEMA_VERSION = "vtt.roll_card.v1"
ROLL_CARD_FACE_SCHEMA_VERSION = "vtt.roll_card_face.v1"
ROLL_CARD_ADJUSTMENT_SCHEMA_VERSION = "vtt.roll_card_adjustment.v1"
ROLL_CARD_D20_FACT_SCHEMA_VERSION = "vtt.roll_card_d20_fact.v1"
ROLL_CARD_SAVE_FACT_SCHEMA_VERSION = "vtt.roll_card_save_fact.v1"
ROLL_CARD_DAMAGE_FACT_SCHEMA_VERSION = "vtt.roll_card_damage_fact.v1"
ROLL_CARD_HEALING_FACT_SCHEMA_VERSION = "vtt.roll_card_healing_fact.v1"


class _StrictCardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RollCardFace(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_FACE_SCHEMA_VERSION] = ROLL_CARD_FACE_SCHEMA_VERSION
    generation_index: Annotated[int, Field(strict=True, ge=1)]
    sides: Annotated[int, Field(strict=True, ge=2)]
    value: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["kept", "discarded", "rerolled", "replaced"]
    replacement_generation_index: Annotated[int, Field(strict=True, ge=1)] | None


class RollCardAdjustment(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_ADJUSTMENT_SCHEMA_VERSION] = (
        ROLL_CARD_ADJUSTMENT_SCHEMA_VERSION
    )
    stage: Literal["total", "threshold", "raw", "applied"]
    kind: Literal[
        "bardic_inspiration",
        "cutting_words",
        "shield",
        "guided_strike",
        "war_gods_blessing",
        "floor",
        "bonus",
        "reduction",
        "resistance",
        "vulnerability",
        "immunity",
        "absorption",
        "other",
    ]
    amount: int
    generated_face: RollCardFace | None


class RollCardD20Fact(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_D20_FACT_SCHEMA_VERSION] = ROLL_CARD_D20_FACT_SCHEMA_VERSION
    kind: Literal["d20"] = "d20"
    expression: str
    mode: Literal["normal", "advantage", "disadvantage", "resolved"]
    faces: tuple[RollCardFace, ...]
    kept_generation_index: Annotated[int, Field(strict=True, ge=1)]
    flat_modifier: int
    total: int
    threshold: int | None
    outcome: Literal["hit", "miss", "success", "failure", "none"]
    critical: bool
    adjustments: tuple[RollCardAdjustment, ...]


class RollCardSaveFact(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_SAVE_FACT_SCHEMA_VERSION] = ROLL_CARD_SAVE_FACT_SCHEMA_VERSION
    kind: Literal["saving_throw"] = "saving_throw"
    ability: Literal[
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ]
    expression: str
    mode: Literal["normal", "advantage", "disadvantage"]
    faces: tuple[RollCardFace, ...]
    kept_generation_index: Annotated[int, Field(strict=True, ge=1)]
    flat_modifier: int
    total: int
    dc: Annotated[int, Field(strict=True, ge=0)]
    succeeded: bool


class RollCardDamageFact(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_DAMAGE_FACT_SCHEMA_VERSION] = (
        ROLL_CARD_DAMAGE_FACT_SCHEMA_VERSION
    )
    kind: Literal["damage"] = "damage"
    expression: str
    damage_type: str | None
    faces: tuple[RollCardFace, ...]
    flat_modifier: int
    rolled_total: int
    raw_damage: Annotated[int, Field(strict=True, ge=0)]
    applied_damage: Annotated[int, Field(strict=True, ge=0)]
    critical: bool
    adjustments: tuple[RollCardAdjustment, ...]


class RollCardHealingFact(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_HEALING_FACT_SCHEMA_VERSION] = (
        ROLL_CARD_HEALING_FACT_SCHEMA_VERSION
    )
    kind: Literal["healing"] = "healing"
    expression: str
    faces: tuple[RollCardFace, ...]
    flat_modifier: int
    rolled_healing: Annotated[int, Field(strict=True, ge=0)]
    effective_healing: Annotated[int, Field(strict=True, ge=0)]
    overheal: Annotated[int, Field(strict=True, ge=0)]


RollCardFact: TypeAlias = Annotated[
    RollCardD20Fact | RollCardSaveFact | RollCardDamageFact | RollCardHealingFact,
    Field(discriminator="kind"),
]


class VttRollCard(_StrictCardModel):
    schema_version: Literal[ROLL_CARD_SCHEMA_VERSION] = ROLL_CARD_SCHEMA_VERSION
    card_id: str
    roll_sequence: Annotated[int, Field(strict=True, ge=1)]
    source_actor_id: str | None
    target_actor_id: str | None
    action_id: str | None
    purpose: str
    fact: RollCardFact


def _face(face: DieFace) -> RollCardFace:
    return RollCardFace(
        generation_index=face.generation_index,
        sides=face.sides,
        value=face.value,
        status=face.status,
        replacement_generation_index=face.replacement_generation_index,
    )


def _modifier_face(face: ModifierDieFace | None) -> RollCardFace | None:
    if face is None:
        return None
    return RollCardFace(
        generation_index=face.generation_index,
        sides=face.sides,
        value=face.value,
        status="kept",
        replacement_generation_index=None,
    )


def _adjustment(item: D20Adjustment | DamageAdjustment) -> RollCardAdjustment:
    return RollCardAdjustment(
        stage=item.stage,
        kind=item.kind,
        amount=item.amount,
        generated_face=_modifier_face(item.generated_face),
    )


def _viewer_allows(record: AuthoritativeRollRecord, participant: TableParticipant | None) -> bool:
    if participant is None or participant.role == "gm":
        return True
    intent = record.audience
    if intent.visibility == "public":
        return True
    if intent.visibility == "gm_only":
        return False
    return bool(set(intent.actor_ids).intersection(participant.owned_actor_ids))


def _project_fact(record: AuthoritativeRollRecord) -> RollCardFact | None:
    fact = record.fact
    if isinstance(fact, D20RollFact):
        return RollCardD20Fact(
            expression=fact.roll.expression,
            mode=fact.roll.mode,
            faces=tuple(_face(face) for face in fact.roll.faces),
            kept_generation_index=fact.roll.kept_generation_index,
            flat_modifier=fact.roll.flat_modifier,
            total=fact.total,
            threshold=fact.threshold,
            outcome=fact.outcome,
            critical=fact.critical,
            adjustments=tuple(_adjustment(item) for item in fact.adjustments),
        )
    if isinstance(fact, SavingThrowFact):
        return RollCardSaveFact(
            ability=fact.ability,
            expression=fact.roll.expression,
            mode=fact.roll.mode,
            faces=tuple(_face(face) for face in fact.roll.faces),
            kept_generation_index=fact.roll.kept_generation_index,
            flat_modifier=fact.roll.flat_modifier,
            total=fact.roll.total,
            dc=fact.dc,
            succeeded=fact.succeeded,
        )
    if isinstance(fact, DamageRollFact):
        if fact.applied_damage is None:
            return None
        return RollCardDamageFact(
            expression=fact.expression,
            damage_type=fact.damage_type,
            faces=tuple(_face(face) for face in fact.faces),
            flat_modifier=fact.flat_modifier,
            rolled_total=fact.rolled_total,
            raw_damage=fact.raw_damage,
            applied_damage=fact.applied_damage,
            critical=fact.critical,
            adjustments=tuple(_adjustment(item) for item in fact.adjustments),
        )
    if isinstance(fact, HealingRollFact):
        return RollCardHealingFact(
            expression=fact.expression,
            faces=tuple(_face(face) for face in fact.faces),
            flat_modifier=fact.flat_modifier,
            rolled_healing=fact.rolled_healing,
            effective_healing=fact.effective_healing,
            overheal=fact.overheal,
        )
    return None


def project_roll_card(
    record: AuthoritativeRollRecord,
    *,
    participant: TableParticipant | None,
    hidden_actor_values: frozenset[str] = frozenset(),
) -> VttRollCard | None:
    """Project one final record, omitting unauthorized facts and hidden identities."""

    if not isinstance(record, AuthoritativeRollRecord):
        raise TypeError("record must be an AuthoritativeRollRecord")
    if participant is not None and not isinstance(participant, TableParticipant):
        raise TypeError("participant must be a TableParticipant")
    if not _viewer_allows(record, participant):
        return None
    fact = _project_fact(record)
    if fact is None:
        return None
    source_hidden = record.source_actor_id in hidden_actor_values
    target_hidden = record.target_actor_id in hidden_actor_values
    return VttRollCard(
        card_id=record.record_id,
        roll_sequence=record.sequence,
        source_actor_id=None if source_hidden else record.source_actor_id,
        target_actor_id=None if target_hidden else record.target_actor_id,
        action_id=None if source_hidden else record.action_id,
        purpose=record.purpose,
        fact=fact,
    )


__all__ = [
    "ROLL_CARD_SCHEMA_VERSION",
    "RollCardAdjustment",
    "RollCardD20Fact",
    "RollCardDamageFact",
    "RollCardFace",
    "RollCardFact",
    "RollCardHealingFact",
    "RollCardSaveFact",
    "VttRollCard",
    "project_roll_card",
]
