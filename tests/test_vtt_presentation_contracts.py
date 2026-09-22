import base64

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.presentation_contracts import (
    CameraState,
    PlaybackState,
    PresentationView,
    SoundTrackRecord,
    SoundTrackUploadCommand,
)


def _wav_bytes() -> bytes:
    payload = b"\x00\x00"
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


def test_sound_upload_is_canonical_bounded_audio() -> None:
    command = SoundTrackUploadCommand(
        table_id="table-1",
        command_id="sound-1",
        expected_revision=0,
        track_id="vault-hum",
        name="Vault hum",
        content_base64=base64.b64encode(_wav_bytes()).decode("ascii"),
    )
    assert command.content_bytes() == _wav_bytes()

    with pytest.raises(ValidationError, match="canonical base64"):
        SoundTrackUploadCommand(**{**command.model_dump(), "content_base64": "not base64"})


def test_playback_and_camera_states_fail_closed_on_inconsistent_shapes() -> None:
    with pytest.raises(ValidationError, match="stopped playback"):
        PlaybackState(status="stopped", track_id="secret", audience=("all",))
    with pytest.raises(ValidationError, match="enabled camera"):
        CameraState(enabled=True, scene_id=None, center_x_ft=None, center_y_ft=None)


def test_presentation_view_requires_sorted_unique_library_records() -> None:
    track = SoundTrackRecord(
        track_id="b",
        name="B",
        media_type="audio/wav",
        content_path="/api/v1/sound-assets/b/content.wav",
        sha256="a" * 64,
        byte_size=46,
    )
    track_a = SoundTrackRecord(
        track_id="a",
        name="A",
        media_type="audio/wav",
        content_path="/api/v1/sound-assets/a/content.wav",
        sha256="b" * 64,
        byte_size=46,
    )
    with pytest.raises(ValidationError, match="sorted"):
        PresentationView(
            session_id="session-1",
            table_id="table-1",
            revision=1,
            server_epoch_ms=1,
            tracks=(track, track_a),
        )
