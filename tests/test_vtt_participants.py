from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
    audience_allows,
    validate_audience_selectors,
)


def _participant(
    participant_id: str,
    *,
    role: str = "player",
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.replace("-", " ").title(),
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def test_roster_round_trips_sorted_strict_participants() -> None:
    roster = TableRoster(
        schema_version=ROSTER_SCHEMA_VERSION,
        table_id="echo-vault-table",
        participants=(
            _participant("gm-1", role="gm"),
            _participant("player-1", owned_actor_ids=("vela_quill",)),
            _participant("spectator-1", role="spectator"),
        ),
    )

    assert TableRoster.model_validate(roster.model_dump(mode="json")) == roster
    assert roster.participant("player-1").owned_actor_ids == ("vela_quill",)
    assert roster.participant("missing") is None

    labeled = TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id="gm-2",
        display_name="GM: Lantern Keeper",
        role="gm",
    )
    assert labeled.display_name == "GM: Lantern Keeper"


@pytest.mark.parametrize(
    "patch",
    [
        {"participant_id": " player-1"},
        {"role": "owner"},
        {"owned_actor_ids": ("vela_quill", "vela_quill")},
        {"owned_actor_ids": ("z_actor", "a_actor")},
        {"extra": True},
    ],
)
def test_participant_contract_rejects_ambiguous_or_noncanonical_values(patch: dict) -> None:
    payload = _participant("player-1", owned_actor_ids=("vela_quill",)).model_dump(mode="json")
    payload.update(patch)

    with pytest.raises(ValidationError):
        TableParticipant.model_validate(payload)


def test_spectators_cannot_own_actors_and_roster_requires_a_gm() -> None:
    with pytest.raises(ValidationError, match="spectator.*own"):
        _participant(
            "spectator-1",
            role="spectator",
            owned_actor_ids=("vela_quill",),
        )

    with pytest.raises(ValidationError, match="at least one GM"):
        TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="echo-vault-table",
            participants=(_participant("player-1"),),
        )


def test_roster_rejects_duplicate_unsorted_participants_and_actor_owners() -> None:
    gm = _participant("gm-1", role="gm")
    player = _participant("player-1", owned_actor_ids=("vela_quill",))

    with pytest.raises(ValidationError, match="sorted"):
        TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="echo-vault-table",
            participants=(player, gm),
        )
    with pytest.raises(ValidationError, match="unique"):
        TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="echo-vault-table",
            participants=(gm, player, player),
        )
    with pytest.raises(ValidationError, match="one player"):
        TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="echo-vault-table",
            participants=(
                gm,
                player,
                _participant("player-2", owned_actor_ids=("vela_quill",)),
            ),
        )


def test_explicit_audience_selectors_filter_without_inspecting_payloads() -> None:
    gm = _participant("gm-1", role="gm")
    vela_player = _participant("player-1", owned_actor_ids=("vela_quill",))
    other_player = _participant("player-2", owned_actor_ids=("other_actor",))
    spectator = _participant("spectator-1", role="spectator")

    assert validate_audience_selectors(("all",)) == ("all",)
    assert audience_allows(("all",), spectator) is True
    assert audience_allows(("role:player",), vela_player) is True
    assert audience_allows(("role:player",), spectator) is False
    assert audience_allows(("participant:player-1",), vela_player) is True
    assert audience_allows(("participant:player-1",), other_player) is False
    assert audience_allows(("actor:vela_quill",), vela_player) is True
    assert audience_allows(("actor:vela_quill",), other_player) is False
    assert audience_allows(("role:gm",), gm) is True
    assert audience_allows(("participant:player-1",), gm) is True
    assert audience_allows(("participant:spectator-1",), spectator) is False
    assert audience_allows(("role:spectator",), spectator) is True


@pytest.mark.parametrize(
    "audience",
    [
        (),
        ("all", "role:gm"),
        ("role:owner",),
        ("participant:",),
        ("actor: vela_quill",),
        ("participant:player-1", "participant:player-1"),
        ("role:gm", "all"),
    ],
)
def test_audience_selectors_reject_ambiguous_or_noncanonical_forms(audience) -> None:
    with pytest.raises(ValueError):
        validate_audience_selectors(audience)
