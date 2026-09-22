"""Strict contracts for shared VTT sound and synchronized player view."""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .participants import validate_audience_selectors

PRESENTATION_TRACK_SCHEMA_VERSION = "vtt.sound_track.v1"
PRESENTATION_PLAYLIST_SCHEMA_VERSION = "vtt.sound_playlist.v1"
PRESENTATION_PLAYBACK_SCHEMA_VERSION = "vtt.sound_playback.v1"
PRESENTATION_CAMERA_SCHEMA_VERSION = "vtt.presentation_camera.v1"
PRESENTATION_COMMAND_SCHEMA_VERSION = "vtt.presentation_command.v1"
PRESENTATION_SIGNAL_SCHEMA_VERSION = "vtt.presentation_signal.v1"
PRESENTATION_RECEIPT_SCHEMA_VERSION = "vtt.presentation_receipt.v1"
PRESENTATION_VIEW_SCHEMA_VERSION = "vtt.presentation_view.v1"
PRESENTATION_REQUEST_SCHEMA_VERSION = "vtt.presentation_request.v1"
PRESENTATION_RESPONSE_SCHEMA_VERSION = "vtt.presentation_response.v1"

MAX_SOUND_ASSET_BYTES = 12 * 1024 * 1024
MAX_SOUND_ASSET_BASE64_LENGTH = 4 * ((MAX_SOUND_ASSET_BYTES + 2) // 3)
MAX_SOUND_TRACKS = 256
MAX_SOUND_PLAYLISTS = 64
MAX_PLAYLIST_TRACKS = 128
MAX_PLAYBACK_POSITION_MS = 24 * 60 * 60 * 1_000

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
FiniteCoordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Zoom = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=1.0, le=4.0)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _text(value: Any, *, field_name: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be nonempty without surrounding whitespace")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{field_name} contains an unsupported control character")
    return value


def _identity(value: Any, *, field_name: str) -> str:
    return _text(value, field_name=field_name, maximum=128)


def _url_id(value: Any, *, field_name: str) -> str:
    value = _identity(value, field_name=field_name)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError(f"{field_name} must be a URL-safe identifier")
    return value


def _audience(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > 128:
        raise ValueError("audience must contain 1-128 selectors")
    selectors = validate_audience_selectors(value)
    for selector in selectors:
        if selector in {"all", "role:gm", "role:player", "role:spectator"}:
            continue
        prefix, suffix = selector.split(":", 1)
        if prefix not in {"participant", "actor"}:
            raise ValueError("audience contains an unsupported selector")
        _identity(suffix, field_name="audience identity")
        if ":" in suffix:
            raise ValueError("audience identity must not contain ':'")
    return selectors


class SoundTrackRecord(_StrictModel):
    schema_version: Literal[PRESENTATION_TRACK_SCHEMA_VERSION] = PRESENTATION_TRACK_SCHEMA_VERSION
    track_id: str
    name: str
    media_type: Literal["audio/mpeg", "audio/ogg", "audio/wav"]
    content_path: str
    sha256: str
    byte_size: Annotated[int, Field(strict=True, ge=1, le=MAX_SOUND_ASSET_BYTES)]

    @field_validator("track_id")
    @classmethod
    def validate_track_id(cls, value: str) -> str:
        return _url_id(value, field_name="track_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _text(value, field_name="track name", maximum=160)

    @field_validator("content_path")
    @classmethod
    def validate_content_path(cls, value: str) -> str:
        value = _text(value, field_name="content_path", maximum=512)
        if not value.startswith("/api/v1/sound-assets/") or "?" in value or "#" in value:
            raise ValueError("content_path must use the sound asset API")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_path_identity(self) -> Self:
        extension = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav"}[self.media_type]
        if self.content_path != f"/api/v1/sound-assets/{self.track_id}/content.{extension}":
            raise ValueError("content_path does not match track identity")
        return self


class SoundPlaylistRecord(_StrictModel):
    schema_version: Literal[PRESENTATION_PLAYLIST_SCHEMA_VERSION] = (
        PRESENTATION_PLAYLIST_SCHEMA_VERSION
    )
    playlist_id: str
    name: str
    track_ids: tuple[str, ...]

    @field_validator("playlist_id")
    @classmethod
    def validate_playlist_id(cls, value: str) -> str:
        return _url_id(value, field_name="playlist_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _text(value, field_name="playlist name", maximum=160)

    @field_validator("track_ids", mode="before")
    @classmethod
    def validate_track_ids(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_PLAYLIST_TRACKS:
            raise ValueError(f"track_ids must contain 1-{MAX_PLAYLIST_TRACKS} entries")
        values = tuple(_url_id(item, field_name="track_id") for item in value)
        if len(values) != len(set(values)):
            raise ValueError("track_ids must be unique")
        return values


class PlaybackState(_StrictModel):
    schema_version: Literal[PRESENTATION_PLAYBACK_SCHEMA_VERSION] = (
        PRESENTATION_PLAYBACK_SCHEMA_VERSION
    )
    status: Literal["stopped", "playing", "paused"] = "stopped"
    track_id: str | None = None
    playlist_id: str | None = None
    position_ms: Annotated[int, Field(strict=True, ge=0, le=MAX_PLAYBACK_POSITION_MS)] = 0
    loop: bool = False
    audience: tuple[str, ...] = ()
    started_at_ms: NonNegativeInt | None = None

    @field_validator("track_id", "playlist_id")
    @classmethod
    def validate_optional_id(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _url_id(value, field_name=info.field_name)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        if value in ((), []):
            return ()
        return _audience(value)

    @model_validator(mode="after")
    def validate_state_shape(self) -> Self:
        if self.status == "stopped":
            if (
                self.track_id is not None
                or self.playlist_id is not None
                or self.position_ms != 0
                or self.loop
                or self.audience
                or self.started_at_ms is not None
            ):
                raise ValueError("stopped playback must not carry track state")
            return self
        if self.track_id is None or not self.audience:
            raise ValueError("active playback requires a track and audience")
        if self.status == "playing" and self.started_at_ms is None:
            raise ValueError("playing playback requires started_at_ms")
        if self.status == "paused" and self.started_at_ms is not None:
            raise ValueError("paused playback must not carry started_at_ms")
        return self


class CameraState(_StrictModel):
    schema_version: Literal[PRESENTATION_CAMERA_SCHEMA_VERSION] = PRESENTATION_CAMERA_SCHEMA_VERSION
    enabled: bool = False
    epoch: NonNegativeInt = 0
    scene_id: str | None = None
    center_x_ft: FiniteCoordinate | None = None
    center_y_ft: FiniteCoordinate | None = None
    zoom: Zoom | None = None

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str | None) -> str | None:
        return None if value is None else _identity(value, field_name="scene_id")

    @model_validator(mode="after")
    def validate_state_shape(self) -> Self:
        values = (self.scene_id, self.center_x_ft, self.center_y_ft, self.zoom)
        if self.enabled and any(value is None for value in values):
            raise ValueError("enabled camera requires scene, center, and zoom")
        if not self.enabled and any(value is not None for value in values):
            raise ValueError("disabled camera must not carry scene geometry")
        return self


class _Command(_StrictModel):
    schema_version: Literal[PRESENTATION_COMMAND_SCHEMA_VERSION] = (
        PRESENTATION_COMMAND_SCHEMA_VERSION
    )
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _identity(value, field_name=info.field_name)


class SoundTrackUploadCommand(_Command):
    command_type: Literal["upload_track"] = "upload_track"
    track_id: str
    name: str
    content_base64: str

    @field_validator("track_id")
    @classmethod
    def validate_track_id(cls, value: str) -> str:
        return _url_id(value, field_name="track_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _text(value, field_name="track name", maximum=160)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > MAX_SOUND_ASSET_BASE64_LENGTH:
            raise ValueError("content_base64 exceeds the sound asset size limit")
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("content_base64 must be canonical base64") from exc
        if not decoded or len(decoded) > MAX_SOUND_ASSET_BYTES:
            raise ValueError("decoded sound asset size is outside the allowed range")
        if base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("content_base64 must be canonical base64")
        return value

    def content_bytes(self) -> bytes:
        return base64.b64decode(self.content_base64, validate=True)


class SoundTrackDeleteCommand(_Command):
    command_type: Literal["delete_track"] = "delete_track"
    track_id: str

    @field_validator("track_id")
    @classmethod
    def validate_track_id(cls, value: str) -> str:
        return _url_id(value, field_name="track_id")


class SoundPlaylistPutCommand(_Command):
    command_type: Literal["put_playlist"] = "put_playlist"
    playlist: SoundPlaylistRecord


class SoundPlaylistDeleteCommand(_Command):
    command_type: Literal["delete_playlist"] = "delete_playlist"
    playlist_id: str

    @field_validator("playlist_id")
    @classmethod
    def validate_playlist_id(cls, value: str) -> str:
        return _url_id(value, field_name="playlist_id")


class PlaybackPlayCommand(_Command):
    command_type: Literal["play"] = "play"
    track_id: str
    playlist_id: str | None = None
    position_ms: Annotated[int, Field(strict=True, ge=0, le=MAX_PLAYBACK_POSITION_MS)] = 0
    loop: bool = False
    audience: tuple[str, ...] = ("all",)

    @field_validator("track_id", "playlist_id")
    @classmethod
    def validate_optional_id(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _url_id(value, field_name=info.field_name)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return _audience(value)


class PlaybackPauseCommand(_Command):
    command_type: Literal["pause"] = "pause"


class PlaybackStopCommand(_Command):
    command_type: Literal["stop"] = "stop"


class CameraShareCommand(_Command):
    command_type: Literal["share_camera"] = "share_camera"
    scene_id: str
    center_x_ft: FiniteCoordinate
    center_y_ft: FiniteCoordinate
    zoom: Zoom

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _identity(value, field_name="scene_id")


class CameraDisableCommand(_Command):
    command_type: Literal["disable_camera"] = "disable_camera"


PresentationCommand: TypeAlias = Annotated[
    SoundTrackUploadCommand
    | SoundTrackDeleteCommand
    | SoundPlaylistPutCommand
    | SoundPlaylistDeleteCommand
    | PlaybackPlayCommand
    | PlaybackPauseCommand
    | PlaybackStopCommand
    | CameraShareCommand
    | CameraDisableCommand,
    Field(discriminator="command_type"),
]
_COMMAND_ADAPTER = TypeAdapter(PresentationCommand)


class PresentationSignal(_StrictModel):
    schema_version: Literal[PRESENTATION_SIGNAL_SCHEMA_VERSION] = PRESENTATION_SIGNAL_SCHEMA_VERSION
    sequence: PositiveInt
    revision: PositiveInt

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("presentation signal sequence must equal revision")
        return self


class PresentationReceipt(_StrictModel):
    schema_version: Literal[PRESENTATION_RECEIPT_SCHEMA_VERSION] = (
        PRESENTATION_RECEIPT_SCHEMA_VERSION
    )
    table_id: str
    command_id: str
    revision: PositiveInt
    signal: PresentationSignal

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _identity(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.signal.revision != self.revision:
            raise ValueError("presentation receipt revision must match signal")
        return self


class PresentationView(_StrictModel):
    schema_version: Literal[PRESENTATION_VIEW_SCHEMA_VERSION] = PRESENTATION_VIEW_SCHEMA_VERSION
    session_id: str
    table_id: str
    revision: NonNegativeInt
    server_epoch_ms: NonNegativeInt
    tracks: tuple[SoundTrackRecord, ...] = ()
    playlists: tuple[SoundPlaylistRecord, ...] = ()
    playback: PlaybackState = PlaybackState()
    camera: CameraState = CameraState()

    @field_validator("session_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _identity(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_library(self) -> Self:
        track_ids = tuple(track.track_id for track in self.tracks)
        playlist_ids = tuple(playlist.playlist_id for playlist in self.playlists)
        if track_ids != tuple(sorted(set(track_ids))):
            raise ValueError("tracks must be unique and sorted")
        if playlist_ids != tuple(sorted(set(playlist_ids))):
            raise ValueError("playlists must be unique and sorted")
        known_tracks = set(track_ids)
        if any(
            track_id not in known_tracks for item in self.playlists for track_id in item.track_ids
        ):
            raise ValueError("playlist references a missing track")
        if self.playback.track_id is not None and self.playback.track_id not in known_tracks:
            raise ValueError("playback references a missing track")
        if self.playback.playlist_id is not None:
            playlist = next(
                (item for item in self.playlists if item.playlist_id == self.playback.playlist_id),
                None,
            )
            if playlist is None or self.playback.track_id not in playlist.track_ids:
                raise ValueError("playback references an invalid playlist")
        return self


class PresentationRequest(_StrictModel):
    schema_version: Literal[PRESENTATION_REQUEST_SCHEMA_VERSION] = (
        PRESENTATION_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: PresentationCommand

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _identity(value, field_name="session_id")


class PresentationResponse(_StrictModel):
    schema_version: Literal[PRESENTATION_RESPONSE_SCHEMA_VERSION] = (
        PRESENTATION_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    replayed: bool
    receipt: PresentationReceipt

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _identity(value, field_name="session_id")


def parse_presentation_command(value: Any) -> PresentationCommand:
    return _COMMAND_ADAPTER.validate_python(value, strict=True)


__all__ = [
    name for name in globals() if name.startswith("Presentation") or name.startswith("Sound")
]
__all__ += [
    "CameraDisableCommand",
    "CameraShareCommand",
    "CameraState",
    "MAX_PLAYBACK_POSITION_MS",
    "MAX_SOUND_ASSET_BYTES",
    "MAX_SOUND_PLAYLISTS",
    "MAX_SOUND_TRACKS",
    "PlaybackPauseCommand",
    "PlaybackPlayCommand",
    "PlaybackState",
    "PlaybackStopCommand",
    "parse_presentation_command",
]
