from __future__ import annotations

import pytest

from dnd_sim.vtt.access import TableAccessError, TableAccessPolicy
from dnd_sim.vtt.contracts import VTTCommand
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)


def _participant(
    participant_id: str,
    *,
    role: str,
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id,
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def _roster() -> TableRoster:
    return TableRoster(
        schema_version=ROSTER_SCHEMA_VERSION,
        table_id="echo-vault",
        participants=(
            _participant("gm", role="gm"),
            _participant("player", role="player", owned_actor_ids=("vela_quill",)),
            _participant("spectator", role="spectator"),
        ),
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=_roster(),
        bearer_tokens={
            "gm": "gm-token-1234567890",
            "player": "player-token-1234567890",
            "spectator": "spectator-token-1234567890",
        },
    )


def _command(
    *,
    actor_id: str | None,
    mode: str = "commit",
) -> VTTCommand:
    payload = {"reaction_id": "reaction-1"} if mode == "reaction" else {}
    return VTTCommand(
        command_id="command-1",
        session_id="echo-vault-session",
        actor_id=actor_id,
        expected_revision=0,
        mode=mode,
        kind="dnd.turn.declare.v1",
        payload=payload,
    )


def test_bearer_authentication_returns_the_detached_roster_participant() -> None:
    policy = _policy()

    principal = policy.authenticate("Bearer player-token-1234567890")

    assert principal == _roster().participant("player")
    assert policy.roster == _roster()
    assert "player-token" not in repr(policy)


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic player-token-1234567890",
        "bearer player-token-1234567890",
        "BEARER player-token-1234567890",
        "Bearer",
        "Bearer  player-token-1234567890",
        "Bearer player-token-1234567890 ",
        "Bearer unknown-token-1234567890",
        "Bearer player-token-1234567890 extra",
    ],
)
def test_authentication_rejects_missing_malformed_and_unknown_credentials(
    authorization: str | None,
) -> None:
    with pytest.raises(TableAccessError) as caught:
        _policy().authenticate(authorization)

    assert caught.value.code == "authentication_required"
    assert "token" not in str(caught.value).lower()


@pytest.mark.parametrize(
    "bearer_tokens",
    [
        {"gm": "gm-token-1234567890", "player": "player-token-1234567890"},
        {
            "gm": "shared-token-1234567890",
            "player": "shared-token-1234567890",
            "spectator": "spectator-token-1234567890",
        },
        {
            "gm": "short",
            "player": "player-token-1234567890",
            "spectator": "spectator-token-1234567890",
        },
        {
            "gm": " gm-token-1234567890",
            "player": "player-token-1234567890",
            "spectator": "spectator-token-1234567890",
        },
        {
            "gm": "gm-token-1234567890",
            "player": "player-token-1234567890",
            "spectator": "spectator-token-1234567890",
            "unknown": "unknown-token-1234567890",
        },
    ],
)
def test_access_policy_requires_one_strong_unique_credential_per_participant(
    bearer_tokens: dict[str, str],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        TableAccessPolicy(roster=_roster(), bearer_tokens=bearer_tokens)


def test_gm_may_issue_admin_and_actor_commands() -> None:
    policy = _policy()
    gm = policy.authenticate("Bearer gm-token-1234567890")

    policy.authorize_command(gm, _command(actor_id=None, mode="admin"))
    policy.authorize_command(gm, _command(actor_id="hushglass_sentry"))


def test_player_may_only_issue_non_admin_commands_for_owned_actors() -> None:
    policy = _policy()
    player = policy.authenticate("Bearer player-token-1234567890")

    policy.authorize_command(player, _command(actor_id="vela_quill", mode="preview"))
    policy.authorize_command(player, _command(actor_id="vela_quill", mode="commit"))
    policy.authorize_command(player, _command(actor_id="vela_quill", mode="reaction"))

    for command in (
        _command(actor_id=None),
        _command(actor_id="hushglass_sentry"),
        _command(actor_id="vela_quill", mode="admin"),
    ):
        with pytest.raises(TableAccessError) as caught:
            policy.authorize_command(player, command)
        assert caught.value.code == "command_forbidden"


def test_spectators_cannot_issue_commands() -> None:
    policy = _policy()
    spectator = policy.authenticate("Bearer spectator-token-1234567890")

    with pytest.raises(TableAccessError) as caught:
        policy.authorize_command(spectator, _command(actor_id="vela_quill"))

    assert caught.value.code == "command_forbidden"


def test_principal_must_be_the_canonical_roster_member() -> None:
    policy = _policy()
    forged = _participant("player", role="gm")

    with pytest.raises(TableAccessError) as caught:
        policy.authorize_command(forged, _command(actor_id="hushglass_sentry"))

    assert caught.value.code == "command_forbidden"
