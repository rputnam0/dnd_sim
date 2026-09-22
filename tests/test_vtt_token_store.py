from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.participants import PARTICIPANT_SCHEMA_VERSION, TableParticipant
from dnd_sim.vtt.board_calibration import AxialHexCell
from dnd_sim.vtt.scene import FeetPosition
from dnd_sim.vtt.token_contracts import (
    TOKEN_COMMAND_SCHEMA_VERSION,
    TOKEN_POSE_SCHEMA_VERSION,
    TOKEN_RECORD_SCHEMA_VERSION,
    TokenCreateCommand,
    TokenDeleteCommand,
    TokenDuplicateCommand,
    TokenPose,
    TokenRecord,
    TokenUpdateCommand,
    project_token_view,
)
from dnd_sim.vtt.token_store import (
    SQLiteTokenStore,
    TokenCommandConflictError,
    TokenIdConflictError,
    TokenLockedError,
    TokenRevisionConflictError,
)


def _participant(
    participant_id: str,
    role: str,
    *,
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def _pose(
    x_ft: float = 12.5,
    y_ft: float = 7.5,
    *,
    rotation_degrees: float = 0.0,
) -> TokenPose:
    return TokenPose(
        schema_version=TOKEN_POSE_SCHEMA_VERSION,
        position_ft=FeetPosition(x_ft=x_ft, y_ft=y_ft, z_ft=0.0),
        width_ft=5.0,
        height_ft=5.0,
        rotation_degrees=rotation_degrees,
        layer=0,
    )


def _token(
    token_id: str,
    *,
    actor_id: str | None = None,
    visibility: str = "public",
    locked: bool = False,
    pose: TokenPose | None = None,
) -> TokenRecord:
    return TokenRecord(
        schema_version=TOKEN_RECORD_SCHEMA_VERSION,
        token_id=token_id,
        scene_id="echo-vault",
        actor_id=actor_id,
        name=token_id.replace("-", " ").title(),
        pose=pose or _pose(),
        visibility=visibility,
        locked=locked,
        nameplate="hover",
        show_hp_bar=actor_id is not None,
        aura_radius_ft=0.0,
        aura_color="#4DD7B3",
        condition_labels=(),
    )


def _create(
    command_id: str,
    token: TokenRecord,
    *,
    expected_revision: int,
) -> TokenCreateCommand:
    return TokenCreateCommand(
        schema_version=TOKEN_COMMAND_SCHEMA_VERSION,
        table_id="table-a",
        command_id=command_id,
        expected_revision=expected_revision,
        token=token,
    )


def test_token_contracts_are_strict_bounded_and_owner_visibility_requires_actor() -> None:
    token = _token("vela-token", actor_id="vela", visibility="owners")

    assert token.pose.position_ft.x_ft == 12.5
    assert token.model_dump(mode="json")["actor_id"] == "vela"

    with pytest.raises(ValidationError):
        TokenRecord.model_validate({**token.model_dump(mode="json"), "unknown": True})
    with pytest.raises(ValidationError):
        TokenRecord.model_validate(
            {**_token("marker").model_dump(mode="json"), "visibility": "owners"}
        )
    with pytest.raises(ValidationError):
        TokenPose.model_validate({**token.pose.model_dump(mode="json"), "rotation_degrees": 360.0})
    with pytest.raises(ValidationError):
        TokenPose.model_validate({**token.pose.model_dump(mode="json"), "width_ft": 0.0})
    with pytest.raises(ValidationError):
        TokenRecord.model_validate(
            {**token.model_dump(mode="json"), "condition_labels": ["prone", "prone"]}
        )


def test_token_pose_has_a_bounded_canonical_optional_hex_footprint() -> None:
    pose = _pose().model_copy(
        update={
            "occupied_hex_cells": (
                AxialHexCell(q=1, r=2),
                AxialHexCell(q=1, r=3),
            )
        }
    )

    encoded = pose.model_dump(mode="json")
    assert encoded["occupied_hex_cells"] == [{"q": 1, "r": 2}, {"q": 1, "r": 3}]
    assert "occupied_hex_cells" not in _pose().model_dump(mode="json")
    assert TokenPose.model_validate(encoded) == pose

    for invalid in (
        [{"q": 1, "r": 3}, {"q": 1, "r": 2}],
        [{"q": 1, "r": 2}, {"q": 1, "r": 2}],
        [{"q": index, "r": 0} for index in range(65)],
    ):
        with pytest.raises(ValidationError):
            TokenPose.model_validate(
                {**_pose().model_dump(mode="json"), "occupied_hex_cells": invalid}
            )


def test_token_store_create_update_duplicate_delete_and_lock_lifecycle() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        store = SQLiteTokenStore(connection)
        created = store.execute(
            _create("create-vela", _token("vela", actor_id="vela"), expected_revision=0)
        )
        locked = _token("screen", locked=True, pose=_pose(22.5, 7.5))
        store.execute(_create("create-screen", locked, expected_revision=1))

        assert created.replayed is False
        assert store.snapshot("table-a", "echo-vault").revision == 2

        with pytest.raises(TokenLockedError):
            store.execute(
                TokenUpdateCommand(
                    table_id="table-a",
                    command_id="move-locked",
                    expected_revision=2,
                    token=locked.model_copy(update={"pose": _pose(27.5, 7.5)}),
                )
            )

        store.execute(
            TokenUpdateCommand(
                table_id="table-a",
                command_id="unlock-screen",
                expected_revision=2,
                token=locked.model_copy(update={"locked": False}),
            )
        )
        store.execute(
            TokenUpdateCommand(
                table_id="table-a",
                command_id="move-screen",
                expected_revision=3,
                token=locked.model_copy(
                    update={"locked": False, "pose": _pose(27.5, 7.5, rotation_degrees=90.0)}
                ),
            )
        )
        duplicated = store.execute(
            TokenDuplicateCommand(
                table_id="table-a",
                command_id="copy-screen",
                expected_revision=4,
                source_token_id="screen",
                new_token_id="screen-copy",
                pose=_pose(32.5, 7.5),
            )
        )
        deleted = store.execute(
            TokenDeleteCommand(
                table_id="table-a",
                command_id="delete-copy",
                expected_revision=5,
                scene_id="echo-vault",
                token_id="screen-copy",
            )
        )

        view = store.snapshot("table-a", "echo-vault")
        assert duplicated.receipt.event.token.pose.position_ft.x_ft == 32.5
        assert deleted.receipt.event.token_id == "screen-copy"
        assert view.revision == 6
        assert [token.token_id for token in view.tokens] == ["screen", "vela"]
        assert view.token("screen").pose.rotation_degrees == 90.0  # type: ignore[union-attr]
    finally:
        connection.close()


def test_token_store_exact_retry_conflict_stale_revision_and_reserved_ids() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        store = SQLiteTokenStore(connection)
        command = _create("create-once", _token("marker"), expected_revision=0)
        first = store.execute(command)
        replayed = store.execute(command)

        assert replayed.replayed is True
        assert replayed.receipt == first.receipt

        with pytest.raises(TokenCommandConflictError):
            store.execute(_create("create-once", _token("different"), expected_revision=0))
        with pytest.raises(TokenRevisionConflictError) as caught:
            store.execute(_create("stale", _token("stale"), expected_revision=0))
        assert caught.value.current_revision == 1

        store.execute(
            TokenDeleteCommand(
                table_id="table-a",
                command_id="delete-marker",
                expected_revision=1,
                scene_id="echo-vault",
                token_id="marker",
            )
        )
        with pytest.raises(TokenIdConflictError):
            store.execute(_create("reuse-marker", _token("marker"), expected_revision=2))
    finally:
        connection.close()


def test_token_store_restart_and_server_projection_omit_hidden_identities(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "tokens.sqlite3"
    connection = sqlite3.connect(database_path)
    store = SQLiteTokenStore(connection)
    store.execute(_create("public", _token("public"), expected_revision=0))
    store.execute(
        _create(
            "owned",
            _token("owned", actor_id="vela", visibility="owners"),
            expected_revision=1,
        )
    )
    store.execute(
        _create(
            "secret",
            _token("secret", actor_id="sentry", visibility="gm_only"),
            expected_revision=2,
        )
    )
    connection.close()

    restored_connection = sqlite3.connect(database_path)
    try:
        restored = SQLiteTokenStore(restored_connection)
        truth = restored.snapshot("table-a", "echo-vault")
        gm = project_token_view(truth, _participant("gm", "gm"))
        owner = project_token_view(
            truth,
            _participant("player", "player", owned_actor_ids=("vela",)),
        )
        other = project_token_view(truth, _participant("other", "player"))
        spectator = project_token_view(truth, _participant("watch", "spectator"))

        assert [token.token_id for token in gm.tokens] == ["owned", "public", "secret"]
        assert [token.token_id for token in owner.tokens] == ["owned", "public"]
        assert [token.token_id for token in other.tokens] == ["public"]
        assert [token.token_id for token in spectator.tokens] == ["public"]
        assert "secret" not in spectator.model_dump_json()
        assert "sentry" not in spectator.model_dump_json()
    finally:
        restored_connection.close()
