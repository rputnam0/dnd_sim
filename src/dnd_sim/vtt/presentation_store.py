"""Restart-safe SQLite aggregate for shared sound and player-view state."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .presentation_contracts import (
    MAX_PLAYBACK_POSITION_MS,
    MAX_SOUND_PLAYLISTS,
    MAX_SOUND_TRACKS,
    CameraDisableCommand,
    CameraShareCommand,
    CameraState,
    PlaybackPauseCommand,
    PlaybackPlayCommand,
    PlaybackState,
    PlaybackStopCommand,
    PresentationCommand,
    PresentationReceipt,
    PresentationSignal,
    SoundPlaylistDeleteCommand,
    SoundPlaylistPutCommand,
    SoundPlaylistRecord,
    SoundTrackDeleteCommand,
    SoundTrackRecord,
    SoundTrackUploadCommand,
    parse_presentation_command,
)

logger = logging.getLogger(__name__)

PRESENTATION_STORE_SCHEMA_VERSION = "vtt.presentation_store.v1"
_METADATA = "_vtt_presentation_store_metadata"
_TRACKS = "_vtt_sound_track"
_PLAYLISTS = "_vtt_sound_playlist"
_STATE = "_vtt_presentation_state"
_EVENTS = "_vtt_presentation_event_log"


class PresentationStoreError(RuntimeError):
    pass


class PresentationStoreSchemaError(PresentationStoreError):
    pass


class PresentationStoreCorruptionError(PresentationStoreError):
    pass


class PresentationCommandConflictError(PresentationStoreError):
    pass


class PresentationRevisionConflictError(PresentationStoreError):
    def __init__(self, *, current_revision: int) -> None:
        super().__init__(f"current presentation revision is {current_revision}")
        self.current_revision = current_revision


class PresentationRecordConflictError(PresentationStoreError):
    pass


class PresentationRecordNotFoundError(PresentationStoreError):
    pass


class PresentationReferenceError(PresentationStoreError):
    pass


class PresentationCapacityError(PresentationStoreError):
    pass


class PresentationInvalidAudioError(PresentationStoreError):
    pass


class PresentationStateError(PresentationStoreError):
    pass


@dataclass(frozen=True, slots=True)
class PresentationSnapshot:
    revision: int
    tracks: tuple[SoundTrackRecord, ...]
    playlists: tuple[SoundPlaylistRecord, ...]
    playback: PlaybackState
    camera: CameraState
    events: tuple[PresentationSignal, ...]


@dataclass(frozen=True, slots=True)
class PresentationExecutionResult:
    receipt: PresentationReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class _PresentationState:
    tracks: tuple[SoundTrackRecord, ...] = ()
    playlists: tuple[SoundPlaylistRecord, ...] = ()
    playback: PlaybackState = PlaybackState()
    camera: CameraState = CameraState()


def _canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _state_payload(state: _PresentationState) -> dict[str, Any]:
    return {
        "tracks": [item.model_dump(mode="json") for item in state.tracks],
        "playlists": [item.model_dump(mode="json") for item in state.playlists],
        "playback": state.playback.model_dump(mode="json"),
        "camera": state.camera.model_dump(mode="json"),
    }


def _advance_state(
    state: _PresentationState,
    command: PresentationCommand,
    *,
    epoch_ms: int,
) -> _PresentationState:
    tracks = {item.track_id: item for item in state.tracks}
    playlists = {item.playlist_id: item for item in state.playlists}
    playback = state.playback
    camera = state.camera
    if isinstance(command, SoundTrackUploadCommand):
        if command.track_id in tracks:
            raise PresentationRecordConflictError("track ID was already used")
        if len(tracks) >= MAX_SOUND_TRACKS:
            raise PresentationCapacityError("sound track capacity is exhausted")
        content = command.content_bytes()
        tracks[command.track_id] = inspect_audio(
            content,
            track_id=command.track_id,
            name=command.name,
        )
    elif isinstance(command, SoundTrackDeleteCommand):
        if command.track_id not in tracks:
            raise PresentationRecordNotFoundError("sound track does not exist")
        if playback.track_id == command.track_id or any(
            command.track_id in playlist.track_ids for playlist in playlists.values()
        ):
            raise PresentationReferenceError("sound track is still referenced")
        tracks.pop(command.track_id)
    elif isinstance(command, SoundPlaylistPutCommand):
        if any(track_id not in tracks for track_id in command.playlist.track_ids):
            raise PresentationReferenceError("playlist references a missing sound track")
        if command.playlist.playlist_id not in playlists and len(playlists) >= MAX_SOUND_PLAYLISTS:
            raise PresentationCapacityError("sound playlist capacity is exhausted")
        playlists[command.playlist.playlist_id] = command.playlist
    elif isinstance(command, SoundPlaylistDeleteCommand):
        if command.playlist_id not in playlists:
            raise PresentationRecordNotFoundError("sound playlist does not exist")
        if playback.playlist_id == command.playlist_id:
            raise PresentationReferenceError("sound playlist is currently playing")
        playlists.pop(command.playlist_id)
    elif isinstance(command, PlaybackPlayCommand):
        if command.track_id not in tracks:
            raise PresentationReferenceError("playback references a missing sound track")
        if command.playlist_id is not None:
            playlist = playlists.get(command.playlist_id)
            if playlist is None or command.track_id not in playlist.track_ids:
                raise PresentationReferenceError("playback references an invalid playlist")
        playback = PlaybackState(
            status="playing",
            track_id=command.track_id,
            playlist_id=command.playlist_id,
            position_ms=command.position_ms,
            loop=command.loop,
            audience=command.audience,
            started_at_ms=epoch_ms,
        )
    elif isinstance(command, PlaybackPauseCommand):
        if playback.status != "playing" or playback.started_at_ms is None:
            raise PresentationStateError("only playing sound can be paused")
        if epoch_ms < playback.started_at_ms:
            raise PresentationStateError("the presentation clock moved backwards")
        playback = PlaybackState(
            status="paused",
            track_id=playback.track_id,
            playlist_id=playback.playlist_id,
            position_ms=min(
                MAX_PLAYBACK_POSITION_MS,
                playback.position_ms + max(0, epoch_ms - playback.started_at_ms),
            ),
            loop=playback.loop,
            audience=playback.audience,
        )
    elif isinstance(command, PlaybackStopCommand):
        if playback.status == "stopped":
            raise PresentationStateError("sound playback is already stopped")
        playback = PlaybackState()
    elif isinstance(command, CameraShareCommand):
        camera = CameraState(
            enabled=True,
            epoch=camera.epoch + 1,
            scene_id=command.scene_id,
            center_x_ft=command.center_x_ft,
            center_y_ft=command.center_y_ft,
            zoom=command.zoom,
        )
    elif isinstance(command, CameraDisableCommand):
        if not camera.enabled:
            raise PresentationStateError("shared camera is already disabled")
        camera = CameraState(epoch=camera.epoch + 1)
    return _PresentationState(
        tracks=tuple(sorted(tracks.values(), key=lambda item: item.track_id)),
        playlists=tuple(sorted(playlists.values(), key=lambda item: item.playlist_id)),
        playback=playback,
        camera=camera,
    )


def _inspect_wav(content: bytes) -> bool:
    if (
        len(content) < 44
        or content[:4] != b"RIFF"
        or content[8:12] != b"WAVE"
        or int.from_bytes(content[4:8], "little") + 8 != len(content)
    ):
        return False
    offset = 12
    found_format = False
    found_data = False
    while offset < len(content):
        if offset + 8 > len(content):
            return False
        chunk_type = content[offset : offset + 4]
        chunk_size = int.from_bytes(content[offset + 4 : offset + 8], "little")
        offset += 8
        if offset + chunk_size > len(content):
            return False
        found_format = found_format or chunk_type == b"fmt " and chunk_size >= 16
        found_data = found_data or chunk_type == b"data" and chunk_size > 0
        offset += chunk_size + (chunk_size % 2)
    return offset == len(content) and found_format and found_data


def _inspect_ogg(content: bytes) -> bool:
    offset = 0
    last_header_type = 0
    pages = 0
    while offset < len(content):
        if offset + 27 > len(content) or content[offset : offset + 4] != b"OggS":
            return False
        if content[offset + 4] != 0:
            return False
        last_header_type = content[offset + 5]
        segment_count = content[offset + 26]
        if offset + 27 + segment_count > len(content):
            return False
        body_size = sum(content[offset + 27 : offset + 27 + segment_count])
        offset += 27 + segment_count + body_size
        if offset > len(content):
            return False
        pages += 1
    return pages > 0 and offset == len(content) and bool(last_header_type & 0x04)


def _inspect_mp3(content: bytes) -> bool:
    if len(content) < 4:
        return False
    offset = 0
    if content.startswith(b"ID3"):
        if len(content) < 14 or any(byte & 0x80 for byte in content[6:10]):
            return False
        tag_size = sum(content[6 + index] << (21 - index * 7) for index in range(4))
        offset = 10 + tag_size
    frame_count = 0
    mpeg1_bitrates = {
        3: (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
        2: (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
        1: (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    }
    mpeg2_bitrates = {
        3: (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
        2: (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
        1: (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    }
    while offset < len(content):
        if len(content) - offset == 128 and content[offset : offset + 3] == b"TAG":
            offset = len(content)
            break
        if (
            offset + 4 > len(content)
            or content[offset] != 0xFF
            or content[offset + 1] & 0xE0 != 0xE0
        ):
            return False
        version = (content[offset + 1] >> 3) & 0x03
        layer = (content[offset + 1] >> 1) & 0x03
        bitrate_index = content[offset + 2] >> 4
        sample_index = (content[offset + 2] >> 2) & 0x03
        padding = (content[offset + 2] >> 1) & 0x01
        if version == 1 or layer == 0 or bitrate_index not in range(1, 15) or sample_index == 3:
            return False
        bitrate_table = mpeg1_bitrates if version == 3 else mpeg2_bitrates
        bitrate = bitrate_table[layer][bitrate_index - 1] * 1_000
        sample_rate = (44_100, 48_000, 32_000)[sample_index]
        if version == 2:
            sample_rate //= 2
        elif version == 0:
            sample_rate //= 4
        if layer == 3:
            frame_size = ((12 * bitrate) // sample_rate + padding) * 4
        else:
            coefficient = 72 if layer == 1 and version != 3 else 144
            frame_size = coefficient * bitrate // sample_rate + padding
        if frame_size < 4 or offset + frame_size > len(content):
            return False
        offset += frame_size
        frame_count += 1
    return frame_count > 0 and offset == len(content)


def inspect_audio(content: bytes, *, track_id: str, name: str) -> SoundTrackRecord:
    if _inspect_wav(content):
        media_type, extension = "audio/wav", "wav"
    elif _inspect_ogg(content):
        media_type, extension = "audio/ogg", "ogg"
    elif _inspect_mp3(content):
        media_type, extension = "audio/mpeg", "mp3"
    else:
        raise PresentationInvalidAudioError("sound asset must be a complete MP3, Ogg, or WAV file")
    return SoundTrackRecord(
        track_id=track_id,
        name=name,
        media_type=media_type,
        content_path=f"/api/v1/sound-assets/{track_id}/content.{extension}",
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )


class SQLitePresentationStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise PresentationStoreError("cannot initialize presentation storage in a transaction")
        self._connection = connection
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_METADATA} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL
                )
            """)
            row = self._connection.execute(
                f"SELECT schema_version FROM {_METADATA} WHERE singleton = 1"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    f"INSERT INTO {_METADATA} (singleton, schema_version) VALUES (1, ?)",
                    (PRESENTATION_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != PRESENTATION_STORE_SCHEMA_VERSION:
                raise PresentationStoreSchemaError("unsupported presentation store schema")
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_TRACKS} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    content BLOB NOT NULL,
                    PRIMARY KEY (table_id, track_id)
                )
            """)
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_PLAYLISTS} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    playlist_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY (table_id, playlist_id)
                )
            """)
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_STATE} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT PRIMARY KEY,
                    playback_json TEXT NOT NULL,
                    camera_json TEXT NOT NULL
                )
            """)
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_EVENTS} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence >= 1),
                    revision INTEGER NOT NULL CHECK (revision = sequence),
                    command_id TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL CHECK (epoch_ms >= 0),
                    command_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    PRIMARY KEY (table_id, sequence),
                    UNIQUE (table_id, command_id)
                )
            """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def execute(
        self,
        command: PresentationCommand,
        *,
        epoch_ms: int,
    ) -> PresentationExecutionResult:
        command = parse_presentation_command(command.model_dump(mode="json"))
        if type(epoch_ms) is not int or epoch_ms < 0:
            raise ValueError("epoch_ms must be a non-negative integer")
        content: bytes | None = None
        if isinstance(command, SoundTrackUploadCommand):
            content = command.content_bytes()
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise PresentationStoreError("execute cannot run inside an active transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
                f"epoch_ms, command_json, receipt_json, state_json FROM {_EVENTS} "
                "WHERE table_id = ? AND command_id = ?",
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._snapshot_locked(command.table_id)
                receipt = self._parse_event_row(command.table_id, existing)[1]
                if str(existing[6]) != command_json:
                    raise PresentationCommandConflictError("command ID has different content")
                self._connection.commit()
                return PresentationExecutionResult(receipt=receipt, replayed=True)

            snapshot = self._snapshot_locked(command.table_id)
            if command.expected_revision != snapshot.revision:
                raise PresentationRevisionConflictError(current_revision=snapshot.revision)
            next_state = _advance_state(
                _PresentationState(
                    tracks=snapshot.tracks,
                    playlists=snapshot.playlists,
                    playback=snapshot.playback,
                    camera=snapshot.camera,
                ),
                command,
                epoch_ms=epoch_ms,
            )

            if isinstance(command, SoundTrackUploadCommand):
                assert content is not None
                uploaded_record = next(
                    record for record in next_state.tracks if record.track_id == command.track_id
                )
                self._connection.execute(
                    f"INSERT INTO {_TRACKS} "
                    "(store_schema_version, table_id, track_id, record_json, content) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        PRESENTATION_STORE_SCHEMA_VERSION,
                        command.table_id,
                        command.track_id,
                        _canonical_json(uploaded_record),
                        content,
                    ),
                )
            elif isinstance(command, SoundTrackDeleteCommand):
                self._connection.execute(
                    f"DELETE FROM {_TRACKS} WHERE table_id = ? AND track_id = ?",
                    (command.table_id, command.track_id),
                )
            elif isinstance(command, SoundPlaylistPutCommand):
                self._connection.execute(
                    f"INSERT INTO {_PLAYLISTS} "
                    "(store_schema_version, table_id, playlist_id, record_json) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(table_id, playlist_id) DO UPDATE SET "
                    "store_schema_version = excluded.store_schema_version, "
                    "record_json = excluded.record_json",
                    (
                        PRESENTATION_STORE_SCHEMA_VERSION,
                        command.table_id,
                        command.playlist.playlist_id,
                        _canonical_json(command.playlist),
                    ),
                )
            elif isinstance(command, SoundPlaylistDeleteCommand):
                self._connection.execute(
                    f"DELETE FROM {_PLAYLISTS} WHERE table_id = ? AND playlist_id = ?",
                    (command.table_id, command.playlist_id),
                )

            self._connection.execute(
                f"INSERT INTO {_STATE} "
                "(store_schema_version, table_id, playback_json, camera_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(table_id) DO UPDATE SET "
                "store_schema_version = excluded.store_schema_version, "
                "playback_json = excluded.playback_json, camera_json = excluded.camera_json",
                (
                    PRESENTATION_STORE_SCHEMA_VERSION,
                    command.table_id,
                    _canonical_json(next_state.playback),
                    _canonical_json(next_state.camera),
                ),
            )
            revision = snapshot.revision + 1
            receipt = PresentationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=revision,
                signal=PresentationSignal(sequence=revision, revision=revision),
            )
            self._connection.execute(
                f"INSERT INTO {_EVENTS} "
                "(store_schema_version, table_id, sequence, revision, command_id, epoch_ms, "
                "command_json, receipt_json, state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    PRESENTATION_STORE_SCHEMA_VERSION,
                    command.table_id,
                    revision,
                    revision,
                    command.command_id,
                    epoch_ms,
                    command_json,
                    _canonical_json(receipt),
                    _canonical_json(_state_payload(next_state)),
                ),
            )
            self._connection.commit()
            return PresentationExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def snapshot(self, table_id: str) -> PresentationSnapshot:
        return self._snapshot_locked(table_id)

    def replay(self, command: PresentationCommand) -> PresentationExecutionResult | None:
        """Return an exact receipt without re-evaluating mutable presentation policy."""

        command = parse_presentation_command(command.model_dump(mode="json"))
        row = self._connection.execute(
            f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
            f"epoch_ms, command_json, receipt_json, state_json FROM {_EVENTS} "
            "WHERE table_id = ? AND command_id = ?",
            (command.table_id, command.command_id),
        ).fetchone()
        if row is None:
            return None
        self.snapshot(command.table_id)
        receipt = self._parse_event_row(command.table_id, row)[1]
        if str(row[6]) != _canonical_json(command):
            raise PresentationCommandConflictError("command ID has different content")
        return PresentationExecutionResult(receipt=receipt, replayed=True)

    def revision(self, table_id: str) -> int:
        return self.snapshot(table_id).revision

    def events_after(self, table_id: str, sequence: int) -> tuple[PresentationSignal, ...]:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        signals, _state = self._validated_history(table_id)
        return tuple(signal for signal in signals if signal.sequence > sequence)

    def content(self, table_id: str, track_id: str) -> tuple[SoundTrackRecord, bytes]:
        row = self._connection.execute(
            f"SELECT store_schema_version, record_json, content FROM {_TRACKS} "
            "WHERE table_id = ? AND track_id = ?",
            (table_id, track_id),
        ).fetchone()
        if row is None:
            raise PresentationRecordNotFoundError("sound track does not exist")
        record, content = self._parse_track_row(row)
        if record.track_id != track_id:
            raise PresentationStoreCorruptionError("stored sound track identity is invalid")
        return record, content

    def _snapshot_locked(self, table_id: str) -> PresentationSnapshot:
        events, history_state = self._validated_history(table_id)
        track_rows = self._connection.execute(
            f"SELECT store_schema_version, record_json, content FROM {_TRACKS} "
            "WHERE table_id = ? ORDER BY track_id",
            (table_id,),
        ).fetchall()
        tracks = tuple(self._parse_track_row(row)[0] for row in track_rows)
        playlist_rows = self._connection.execute(
            f"SELECT store_schema_version, record_json FROM {_PLAYLISTS} "
            "WHERE table_id = ? ORDER BY playlist_id",
            (table_id,),
        ).fetchall()
        playlists = tuple(self._parse_playlist_row(row) for row in playlist_rows)
        state_row = self._connection.execute(
            f"SELECT store_schema_version, playback_json, camera_json FROM {_STATE} "
            "WHERE table_id = ?",
            (table_id,),
        ).fetchone()
        if state_row is None:
            playback, camera = PlaybackState(), CameraState()
        else:
            playback, camera = self._parse_state_row(state_row)
        known_tracks = {track.track_id for track in tracks}
        if any(track_id not in known_tracks for item in playlists for track_id in item.track_ids):
            raise PresentationStoreCorruptionError("stored playlist reference is invalid")
        if playback.track_id is not None and playback.track_id not in known_tracks:
            raise PresentationStoreCorruptionError("stored playback track reference is invalid")
        if playback.playlist_id is not None:
            playlist = next(
                (item for item in playlists if item.playlist_id == playback.playlist_id), None
            )
            if playlist is None or playback.track_id not in playlist.track_ids:
                raise PresentationStoreCorruptionError(
                    "stored playback playlist reference is invalid"
                )
        if (
            _PresentationState(
                tracks=tracks,
                playlists=playlists,
                playback=playback,
                camera=camera,
            )
            != history_state
        ):
            raise PresentationStoreCorruptionError(
                "materialized presentation state does not match its history"
            )
        return PresentationSnapshot(
            revision=len(events),
            tracks=tracks,
            playlists=playlists,
            playback=playback,
            camera=camera,
            events=events,
        )

    def _validated_history(
        self,
        table_id: str,
    ) -> tuple[tuple[PresentationSignal, ...], _PresentationState]:
        rows = self._connection.execute(
            f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
            f"epoch_ms, command_json, receipt_json, state_json FROM {_EVENTS} "
            "WHERE table_id = ? ORDER BY sequence",
            (table_id,),
        ).fetchall()
        state = _PresentationState()
        signals: list[PresentationSignal] = []
        for expected, row in enumerate(rows, 1):
            signal, _receipt, command, epoch_ms, stored_state = self._parse_event_row(table_id, row)
            if signal.sequence != expected:
                raise PresentationStoreCorruptionError("presentation history has a gap")
            try:
                expected_state = _advance_state(state, command, epoch_ms=epoch_ms)
            except PresentationStoreError as exc:
                raise PresentationStoreCorruptionError(
                    "presentation history contains an invalid transition"
                ) from exc
            if expected_state != stored_state:
                raise PresentationStoreCorruptionError(
                    "presentation history state does not match its command"
                )
            state = stored_state
            signals.append(signal)
        return tuple(signals), state

    @staticmethod
    def _parse_track_row(row: tuple[Any, ...]) -> tuple[SoundTrackRecord, bytes]:
        try:
            schema, record_json, raw_content = row
            if str(schema) != PRESENTATION_STORE_SCHEMA_VERSION:
                raise PresentationStoreSchemaError("unsupported presentation store schema")
            decoded = json.loads(str(record_json))
            record = SoundTrackRecord.model_validate(decoded)
            if _canonical_json(record) != str(record_json):
                raise ValueError("noncanonical record")
            content = bytes(raw_content)
            if (
                record.byte_size != len(content)
                or record.sha256 != hashlib.sha256(content).hexdigest()
            ):
                raise ValueError("content identity")
            inspected = inspect_audio(content, track_id=record.track_id, name=record.name)
            if inspected != record:
                raise ValueError("media identity")
            return record, content
        except PresentationStoreSchemaError:
            raise
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise PresentationStoreCorruptionError("stored sound track is invalid") from exc

    @staticmethod
    def _parse_playlist_row(row: tuple[Any, ...]) -> SoundPlaylistRecord:
        try:
            schema, record_json = row
            if str(schema) != PRESENTATION_STORE_SCHEMA_VERSION:
                raise PresentationStoreSchemaError("unsupported presentation store schema")
            record = SoundPlaylistRecord.model_validate(json.loads(str(record_json)))
            if _canonical_json(record) != str(record_json):
                raise ValueError("noncanonical playlist")
            return record
        except PresentationStoreSchemaError:
            raise
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise PresentationStoreCorruptionError("stored sound playlist is invalid") from exc

    @staticmethod
    def _parse_state_row(row: tuple[Any, ...]) -> tuple[PlaybackState, CameraState]:
        try:
            schema, playback_json, camera_json = row
            if str(schema) != PRESENTATION_STORE_SCHEMA_VERSION:
                raise PresentationStoreSchemaError("unsupported presentation store schema")
            playback = PlaybackState.model_validate(json.loads(str(playback_json)))
            camera = CameraState.model_validate(json.loads(str(camera_json)))
            if _canonical_json(playback) != str(playback_json) or _canonical_json(camera) != str(
                camera_json
            ):
                raise ValueError("noncanonical state")
            return playback, camera
        except PresentationStoreSchemaError:
            raise
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise PresentationStoreCorruptionError("stored presentation state is invalid") from exc

    @staticmethod
    def _parse_event_row(expected_table_id: str, row: tuple[Any, ...]) -> tuple[
        PresentationSignal,
        PresentationReceipt,
        PresentationCommand,
        int,
        _PresentationState,
    ]:
        try:
            (
                schema,
                table_id,
                sequence,
                revision,
                command_id,
                epoch_ms,
                command_json,
                receipt_json,
                state_json,
            ) = row
            if str(schema) != PRESENTATION_STORE_SCHEMA_VERSION:
                raise PresentationStoreSchemaError("unsupported presentation store schema")
            command = parse_presentation_command(json.loads(str(command_json)))
            receipt = PresentationReceipt.model_validate(json.loads(str(receipt_json)))
            decoded_state = json.loads(str(state_json))
            if not isinstance(decoded_state, dict) or set(decoded_state) != {
                "tracks",
                "playlists",
                "playback",
                "camera",
            }:
                raise ValueError("state shape")
            tracks = tuple(
                SoundTrackRecord.model_validate(item) for item in decoded_state["tracks"]
            )
            playlists = tuple(
                SoundPlaylistRecord.model_validate(item) for item in decoded_state["playlists"]
            )
            if tuple(item.track_id for item in tracks) != tuple(
                sorted({item.track_id for item in tracks})
            ) or tuple(item.playlist_id for item in playlists) != tuple(
                sorted({item.playlist_id for item in playlists})
            ):
                raise ValueError("state order")
            state = _PresentationState(
                tracks=tracks,
                playlists=playlists,
                playback=PlaybackState.model_validate(decoded_state["playback"]),
                camera=CameraState.model_validate(decoded_state["camera"]),
            )
            if (
                str(table_id) != expected_table_id
                or type(sequence) is not int
                or type(revision) is not int
                or sequence != revision
                or sequence < 1
                or type(epoch_ms) is not int
                or epoch_ms < 0
                or command.table_id != table_id
                or command.command_id != str(command_id)
                or command.expected_revision != revision - 1
                or receipt.table_id != table_id
                or receipt.command_id != str(command_id)
                or receipt.revision != revision
                or _canonical_json(command) != str(command_json)
                or _canonical_json(receipt) != str(receipt_json)
                or _canonical_json(_state_payload(state)) != str(state_json)
            ):
                raise ValueError("row identity")
            return receipt.signal, receipt, command, epoch_ms, state
        except PresentationStoreSchemaError:
            raise
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise PresentationStoreCorruptionError("stored presentation event is invalid") from exc


__all__ = [name for name in globals() if name.startswith("Presentation")]
__all__ += ["PRESENTATION_STORE_SCHEMA_VERSION", "SQLitePresentationStore", "inspect_audio"]
