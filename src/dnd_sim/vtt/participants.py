"""Strict participant, ownership, and audience-policy contracts for VTT tables."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

PARTICIPANT_SCHEMA_VERSION = "vtt.participant.v1"
ROSTER_SCHEMA_VERSION = "vtt.roster.v1"

TableRole = Literal["gm", "player", "spectator"]


class _StrictParticipantModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(
    value: str,
    *,
    field_name: str,
    allow_colon: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if not allow_colon and ":" in value:
        raise ValueError(f"{field_name} must not contain ':'")
    return value


def _canonical_ids(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an ordered list or tuple")
    values = tuple(_canonical_text(item, field_name=f"{field_name} entry") for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} entries must be unique")
    if values != tuple(sorted(values)):
        raise ValueError(f"{field_name} entries must be sorted")
    return values


class TableParticipant(_StrictParticipantModel):
    """One table principal with an explicit role and deterministic actor ownership."""

    schema_version: Literal["vtt.participant.v1"]
    participant_id: str
    display_name: str
    role: TableRole
    owned_actor_ids: tuple[str, ...] = ()

    @field_validator("participant_id", "display_name")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _canonical_text(
            value,
            field_name=info.field_name,
            allow_colon=info.field_name == "display_name",
        )

    @field_validator("owned_actor_ids", mode="before")
    @classmethod
    def validate_owned_actor_ids(cls, value: Any) -> tuple[str, ...]:
        return _canonical_ids(value, field_name="owned_actor_ids")

    @model_validator(mode="after")
    def validate_spectator_ownership(self) -> "TableParticipant":
        if self.role == "spectator" and self.owned_actor_ids:
            raise ValueError("a spectator cannot own actors")
        return self


class TableRoster(_StrictParticipantModel):
    """A canonical participant roster for one VTT table."""

    schema_version: Literal["vtt.roster.v1"]
    table_id: str
    participants: tuple[TableParticipant, ...]

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="table_id")

    @field_validator("participants", mode="before")
    @classmethod
    def normalize_participants(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("participants must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_roster(self) -> "TableRoster":
        participant_ids = tuple(participant.participant_id for participant in self.participants)
        if len(set(participant_ids)) != len(participant_ids):
            raise ValueError("participant IDs must be unique")
        if participant_ids != tuple(sorted(participant_ids)):
            raise ValueError("participants must be sorted by participant_id")
        if not any(participant.role == "gm" for participant in self.participants):
            raise ValueError("a table roster requires at least one GM")

        actor_owners: dict[str, str] = {}
        for participant in self.participants:
            if participant.role != "player":
                continue
            for actor_id in participant.owned_actor_ids:
                existing = actor_owners.get(actor_id)
                if existing is not None:
                    raise ValueError(f"actor '{actor_id}' may belong to only one player")
                actor_owners[actor_id] = participant.participant_id
        return self

    def participant(self, participant_id: str) -> TableParticipant | None:
        """Return a detached immutable principal lookup, if present."""

        if not isinstance(participant_id, str):
            raise TypeError("participant_id must be a string")
        for participant in self.participants:
            if participant.participant_id == participant_id:
                return participant
        return None


def validate_audience_selectors(audience: Sequence[str]) -> tuple[str, ...]:
    """Validate explicit audience selectors without reading an event payload.

    Supported selectors are ``all``, ``role:<role>``,
    ``participant:<participant_id>``, and ``actor:<actor_id>``. ``all`` is
    canonical only when used alone.
    """

    if not isinstance(audience, (list, tuple)):
        raise ValueError("audience must be an ordered list or tuple")
    selectors = tuple(audience)
    if not selectors:
        raise ValueError("audience must contain at least one selector")
    if len(set(selectors)) != len(selectors):
        raise ValueError("audience selectors must be unique")
    if "all" in selectors:
        if selectors != ("all",):
            raise ValueError("the 'all' selector must be used alone")
        return selectors
    if selectors != tuple(sorted(selectors)):
        raise ValueError("audience selectors must be sorted")

    for selector in selectors:
        if not isinstance(selector, str):
            raise ValueError("audience selectors must be strings")
        if selector.startswith("role:"):
            role = selector.removeprefix("role:")
            if role not in {"gm", "player", "spectator"}:
                raise ValueError(f"unsupported audience role '{role}'")
            continue
        if selector.startswith("participant:"):
            _canonical_text(
                selector.removeprefix("participant:"),
                field_name="audience participant ID",
            )
            continue
        if selector.startswith("actor:"):
            _canonical_text(
                selector.removeprefix("actor:"),
                field_name="audience actor ID",
            )
            continue
        raise ValueError(f"unsupported audience selector '{selector}'")
    return selectors


def audience_allows(
    audience: Sequence[str],
    participant: TableParticipant,
) -> bool:
    """Return whether ``participant`` may receive an audience-filtered record.

    GMs are table authorities and can inspect every valid audience. Players may
    match public, player-role, participant-private, or owned-actor selectors.
    Spectators receive only public or spectator-role records.
    """

    if not isinstance(participant, TableParticipant):
        raise TypeError("participant must be a TableParticipant")
    selectors = validate_audience_selectors(audience)
    if participant.role == "gm" or selectors == ("all",):
        return True
    for selector in selectors:
        if selector == f"role:{participant.role}":
            return True
        if participant.role == "player" and selector == f"participant:{participant.participant_id}":
            return True
        if participant.role == "player" and selector.startswith("actor:"):
            actor_id = selector.removeprefix("actor:")
            if actor_id in participant.owned_actor_ids:
                return True
    return False


__all__ = [
    "PARTICIPANT_SCHEMA_VERSION",
    "ROSTER_SCHEMA_VERSION",
    "TableParticipant",
    "TableRole",
    "TableRoster",
    "audience_allows",
    "validate_audience_selectors",
]
