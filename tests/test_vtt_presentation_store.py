from __future__ import annotations

import base64
import json
import sqlite3

import pytest

from dnd_sim.vtt.presentation_contracts import (
    CameraShareCommand,
    PlaybackPauseCommand,
    PlaybackPlayCommand,
    PlaybackStopCommand,
    CameraDisableCommand,
    SoundPlaylistDeleteCommand,
    SoundTrackDeleteCommand,
    SoundPlaylistPutCommand,
    SoundPlaylistRecord,
    SoundTrackUploadCommand,
)
from dnd_sim.vtt.presentation_store import (
    PresentationCommandConflictError,
    PresentationRevisionConflictError,
    PresentationReferenceError,
    SQLitePresentationStore,
    PresentationInvalidAudioError,
    PresentationStoreCorruptionError,
    inspect_audio,
)


def _wav_bytes() -> bytes:
    payload = b"\x00\x00\x01\x00"
    body = (
        b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00\x01\x00"
        + (8_000).to_bytes(4, "little")
        + (16_000).to_bytes(4, "little")
        + b"\x02\x00\x10\x00"
        + b"data"
        + len(payload).to_bytes(4, "little")
        + payload
    )
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _upload(expected_revision: int = 0) -> SoundTrackUploadCommand:
    return SoundTrackUploadCommand(
        table_id="table-a",
        command_id="upload-hum",
        expected_revision=expected_revision,
        track_id="vault-hum",
        name="Vault hum",
        content_base64=base64.b64encode(_wav_bytes()).decode("ascii"),
    )


def test_presentation_store_restarts_replays_and_preserves_server_timing(tmp_path) -> None:
    path = tmp_path / "presentation.sqlite3"
    connection = sqlite3.connect(path)
    store = SQLitePresentationStore(connection)
    upload = _upload()
    first = store.execute(upload, epoch_ms=1_000)
    assert first.replayed is False
    assert store.execute(upload, epoch_ms=9_999).replayed is True
    with pytest.raises(PresentationCommandConflictError):
        store.execute(upload.model_copy(update={"name": "Different"}), epoch_ms=1_000)
    record, content = store.content("table-a", "vault-hum")
    assert record.media_type == "audio/wav"
    assert content == _wav_bytes()

    store.execute(
        SoundPlaylistPutCommand(
            table_id="table-a",
            command_id="put-ambience",
            expected_revision=1,
            playlist=SoundPlaylistRecord(
                playlist_id="ambience",
                name="Ambience",
                track_ids=("vault-hum",),
            ),
        ),
        epoch_ms=1_000,
    )
    store.execute(
        PlaybackPlayCommand(
            table_id="table-a",
            command_id="play-hum",
            expected_revision=2,
            track_id="vault-hum",
            playlist_id="ambience",
            position_ms=250,
            loop=True,
            audience=("role:player",),
        ),
        epoch_ms=2_000,
    )
    store.execute(
        PlaybackPauseCommand(
            table_id="table-a",
            command_id="pause-hum",
            expected_revision=3,
        ),
        epoch_ms=2_750,
    )
    store.execute(
        CameraShareCommand(
            table_id="table-a",
            command_id="share-view",
            expected_revision=4,
            scene_id="echo-vault",
            center_x_ft=25.0,
            center_y_ft=20.0,
            zoom=2.0,
        ),
        epoch_ms=2_750,
    )
    snapshot = store.snapshot("table-a")
    assert snapshot.revision == 5
    assert snapshot.playback.status == "paused"
    assert snapshot.playback.position_ms == 1_000
    assert snapshot.camera.enabled is True
    assert snapshot.camera.epoch == 1
    connection.close()

    reopened_connection = sqlite3.connect(path)
    reopened = SQLitePresentationStore(reopened_connection)
    assert reopened.snapshot("table-a") == snapshot
    assert [event.revision for event in reopened.events_after("table-a", 2)] == [3, 4, 5]
    with pytest.raises(PresentationRevisionConflictError):
        reopened.execute(
            CameraShareCommand(
                table_id="table-a",
                command_id="stale-camera",
                expected_revision=1,
                scene_id="echo-vault",
                center_x_ft=0.0,
                center_y_ft=0.0,
                zoom=1.0,
            ),
            epoch_ms=3_000,
        )
    assert reopened.revision("table-a") == 5
    reopened_connection.close()


def test_audio_inspection_requires_a_complete_mp3_frame() -> None:
    header = bytes((0xFF, 0xFB, 0x90, 0x64))
    complete_frame = header + bytes(417 - len(header))
    assert (
        inspect_audio(complete_frame, track_id="battle", name="Battle").media_type == "audio/mpeg"
    )
    with pytest.raises(PresentationInvalidAudioError, match="complete"):
        inspect_audio(complete_frame[:-1], track_id="battle", name="Battle")


def test_presentation_store_rejects_canonical_command_state_tampering() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLitePresentationStore(connection)
    command = _upload()
    store.execute(command, epoch_ms=1_000)
    forged = command.model_copy(update={"name": "Forged"})
    connection.execute(
        "UPDATE _vtt_presentation_event_log SET command_json = ? WHERE table_id = ?",
        (
            json.dumps(
                forged.model_dump(mode="json"),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "table-a",
        ),
    )
    connection.commit()
    with pytest.raises(PresentationStoreCorruptionError, match="history state"):
        store.snapshot("table-a")
    with pytest.raises(PresentationStoreCorruptionError, match="history state"):
        store.events_after("table-a", 0)
    with pytest.raises(PresentationStoreCorruptionError, match="history state"):
        store.replay(forged)
    connection.close()


def test_presentation_store_deletes_unreferenced_library_records_and_disables_state() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLitePresentationStore(connection)
    store.execute(_upload(), epoch_ms=1_000)
    store.execute(
        SoundPlaylistPutCommand(
            table_id="table-a",
            command_id="playlist",
            expected_revision=1,
            playlist=SoundPlaylistRecord(
                playlist_id="ambience",
                name="Ambience",
                track_ids=("vault-hum",),
            ),
        ),
        epoch_ms=1_000,
    )
    store.execute(
        PlaybackPlayCommand(
            table_id="table-a",
            command_id="play",
            expected_revision=2,
            track_id="vault-hum",
            playlist_id="ambience",
            audience=("all",),
        ),
        epoch_ms=1_000,
    )
    with pytest.raises(PresentationReferenceError, match="referenced"):
        store.execute(
            SoundTrackDeleteCommand(
                table_id="table-a",
                command_id="premature-delete",
                expected_revision=3,
                track_id="vault-hum",
            ),
            epoch_ms=1_000,
        )
    assert store.revision("table-a") == 3
    for command in (
        PlaybackStopCommand(table_id="table-a", command_id="stop", expected_revision=3),
        SoundPlaylistDeleteCommand(
            table_id="table-a",
            command_id="delete-playlist",
            expected_revision=4,
            playlist_id="ambience",
        ),
        SoundTrackDeleteCommand(
            table_id="table-a",
            command_id="delete-track",
            expected_revision=5,
            track_id="vault-hum",
        ),
        CameraShareCommand(
            table_id="table-a",
            command_id="camera",
            expected_revision=6,
            scene_id="echo-vault",
            center_x_ft=1.0,
            center_y_ft=1.0,
            zoom=1.0,
        ),
        CameraDisableCommand(
            table_id="table-a",
            command_id="camera-off",
            expected_revision=7,
        ),
    ):
        store.execute(command, epoch_ms=1_000)
    snapshot = store.snapshot("table-a")
    assert snapshot.revision == 8
    assert snapshot.tracks == snapshot.playlists == ()
    assert snapshot.playback.status == "stopped"
    assert snapshot.camera.enabled is False
    assert snapshot.camera.epoch == 2
    connection.close()
