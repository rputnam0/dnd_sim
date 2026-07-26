from __future__ import annotations

import hashlib
import hmac
import json
import random
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from .contracts import (
    EVENT_SCHEMA_VERSION,
    RNG_ALGORITHM,
    SNAPSHOT_SCHEMA_VERSION,
    CommandReceipt,
    CommandRecord,
    EngineVersionPins,
    EventDraft,
    JSONValue,
    PendingReaction,
    PendingReactionDraft,
    PreviewOutcome,
    PreviewReceipt,
    SessionCommand,
    SessionEvent,
    SessionSnapshot,
    normalize_json,
)


class EngineSessionError(ValueError):
    """Stable orchestration error returned before any canonical mutation occurs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        normalized = normalize_json(details or {}, path="details")
        self.details = normalized if isinstance(normalized, dict) else {}


@dataclass(frozen=True, slots=True)
class EngineTransition:
    """Candidate state and event drafts produced by an engine driver."""

    state: Any
    events: tuple[EventDraft, ...] = ()
    pending_reaction: PendingReactionDraft | None = None


@runtime_checkable
class EngineSessionDriver(Protocol):
    """Adapter implemented by a deterministic rules engine."""

    version_pins: EngineVersionPins

    def encode_state(self, state: Any) -> Mapping[str, Any]: ...

    def decode_state(self, payload: Mapping[str, Any]) -> Any: ...

    def preview(
        self,
        state: Any,
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome: ...

    def commit(
        self,
        state: Any,
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition: ...

    def respond_to_reaction(
        self,
        state: Any,
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _checksum(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _tuple_tree(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuple_tree(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuple_tree(item) for key, item in value.items()}
    return value


class EngineSession:
    """Transactional command/event boundary for an interactive deterministic engine."""

    def __init__(
        self,
        session_id: str,
        initial_state: Any,
        driver: EngineSessionDriver,
        *,
        seed: int,
    ) -> None:
        normalized_session_id = str(session_id).strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise TypeError("seed must be an integer")

        self._lock = threading.RLock()
        self._session_id = normalized_session_id
        self._driver = driver
        self._version_pins = self._load_version_pins(driver)
        self._rng = random.Random(seed)
        self._revision = 0
        self._next_sequence = 1
        self._events: list[SessionEvent] = []
        self._records: dict[str, CommandRecord] = {}
        self._pending_reaction: PendingReaction | None = None
        self._state = self._decode_state(self._encode_state(initial_state))

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def version_pins(self) -> EngineVersionPins:
        return EngineVersionPins.model_validate(self._version_pins.model_dump(mode="json"))

    @property
    def state(self) -> dict[str, JSONValue]:
        with self._lock:
            return _json_clone(self._encode_state(self._state))

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        with self._lock:
            return tuple(self._copy_event(event) for event in self._events)

    @property
    def pending_reaction(self) -> PendingReaction | None:
        with self._lock:
            if self._pending_reaction is None:
                return None
            return self._copy_reaction(self._pending_reaction)

    def events_since(self, sequence: int) -> tuple[SessionEvent, ...]:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        with self._lock:
            return tuple(
                self._copy_event(event) for event in self._events if event.sequence > sequence
            )

    def execute(self, command: SessionCommand) -> PreviewReceipt | CommandReceipt:
        with self._lock:
            return self._execute_locked(command)

    def _execute_locked(self, command: SessionCommand) -> PreviewReceipt | CommandReceipt:
        if not isinstance(command, SessionCommand):
            raise TypeError("command must be a SessionCommand")
        command = SessionCommand.model_validate(command.model_dump(mode="json"))
        self._validate_session(command)

        if command.mode == "preview":
            self._validate_versions(command)
            self._validate_revision(command)
            if self._pending_reaction is not None:
                raise EngineSessionError(
                    "pending_reaction",
                    "The pending reaction must be resolved before previewing another command.",
                    details={"reaction_id": self._pending_reaction.reaction_id},
                )
            return self._preview(command)

        previous = self._records.get(command.command_id)
        if previous is not None:
            if previous.command != command:
                raise EngineSessionError(
                    "command_id_conflict",
                    "The command_id was already used for a different command.",
                    details={"command_id": command.command_id},
                )
            receipt = CommandReceipt.model_validate(previous.receipt.model_dump(mode="json"))
            return receipt.model_copy(update={"replayed": True})

        self._validate_versions(command)
        self._validate_revision(command)
        if command.mode == "reaction":
            return self._resolve_reaction(command)

        if self._pending_reaction is not None:
            raise EngineSessionError(
                "pending_reaction",
                "The pending reaction must be resolved before another commit.",
                details={"reaction_id": self._pending_reaction.reaction_id},
            )
        return self._commit(command)

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> SessionSnapshot:
        payload: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "rng_algorithm": RNG_ALGORITHM,
            "session_id": self._session_id,
            "revision": self._revision,
            "next_sequence": self._next_sequence,
            "version_pins": self._version_pins.model_dump(mode="json"),
            "state": _json_clone(self._encode_state(self._state)),
            "random_state": normalize_json(self._rng.getstate(), path="random_state"),
            "events": [event.model_dump(mode="json") for event in self._events],
            "command_records": [
                record.model_dump(mode="json") for record in self._records.values()
            ],
            "pending_reaction": (
                self._pending_reaction.model_dump(mode="json")
                if self._pending_reaction is not None
                else None
            ),
        }
        return SessionSnapshot(**payload, checksum=_checksum(payload))

    def snapshot_json(self) -> str:
        return _canonical_json(self.snapshot().model_dump(mode="json"))

    @classmethod
    def restore(
        cls,
        snapshot: SessionSnapshot | Mapping[str, Any],
        driver: EngineSessionDriver,
    ) -> "EngineSession":
        try:
            raw_snapshot = (
                snapshot.model_dump(mode="json")
                if isinstance(snapshot, SessionSnapshot)
                else normalize_json(snapshot, path="snapshot")
            )
            model = SessionSnapshot.model_validate(raw_snapshot)
        except (ValidationError, TypeError, ValueError) as exc:
            raise EngineSessionError(
                "invalid_snapshot",
                "The snapshot does not match the supported contract.",
            ) from exc

        unsigned = model.model_dump(mode="json", exclude={"checksum"})
        expected_checksum = _checksum(unsigned)
        if not hmac.compare_digest(model.checksum, expected_checksum):
            raise EngineSessionError(
                "invalid_snapshot_checksum",
                "The snapshot checksum does not match its contents.",
            )

        cls._validate_snapshot_invariants(model)
        driver_version_pins = cls._load_version_pins(driver)
        if model.version_pins != driver_version_pins:
            raise EngineSessionError(
                "version_mismatch",
                "The snapshot version pins do not match the engine driver.",
                details={
                    "snapshot": model.version_pins.model_dump(mode="json"),
                    "driver": driver_version_pins.model_dump(mode="json"),
                },
            )

        session = cls.__new__(cls)
        session._lock = threading.RLock()
        session._session_id = model.session_id
        session._driver = driver
        session._version_pins = driver_version_pins
        session._rng = random.Random()
        try:
            session._rng.setstate(_tuple_tree(model.random_state))
        except (TypeError, ValueError) as exc:
            raise EngineSessionError(
                "invalid_snapshot",
                "The snapshot contains an invalid RNG state.",
            ) from exc

        try:
            session._state = session._decode_state(model.state)
            if _canonical_json(session._encode_state(session._state)) != _canonical_json(
                model.state
            ):
                raise EngineSessionError(
                    "invalid_snapshot",
                    "The snapshot state does not round-trip through the engine driver.",
                )
        except EngineSessionError as exc:
            if exc.code == "invalid_snapshot":
                raise
            raise EngineSessionError(
                "invalid_snapshot",
                "The snapshot state is incompatible with the engine driver.",
            ) from exc

        session._revision = model.revision
        session._next_sequence = model.next_sequence
        session._events = list(model.events)
        session._records = {record.command.command_id: record for record in model.command_records}
        session._pending_reaction = model.pending_reaction
        return session

    @classmethod
    def replay(
        cls,
        *,
        session_id: str,
        initial_state: Any,
        driver: EngineSessionDriver,
        seed: int,
        commands: Iterable[SessionCommand],
    ) -> "EngineSession":
        session = cls(session_id, initial_state, driver, seed=seed)
        for command in commands:
            session.execute(command)
        return session

    def _preview(self, command: SessionCommand) -> PreviewReceipt:
        working_state = self._decode_state(self._encode_state(self._state))
        working_rng = self._clone_rng()
        try:
            outcome = self._driver.preview(
                working_state,
                self._copy_command(command),
                working_rng,
            )
            if not isinstance(outcome, PreviewOutcome):
                raise TypeError("preview() must return PreviewOutcome")
        except EngineSessionError:
            raise
        except Exception as exc:
            raise self._driver_failure(exc) from exc
        return PreviewReceipt(
            command_id=command.command_id,
            session_id=self._session_id,
            revision=self._revision,
            version_pins=self._version_pins,
            projection=outcome.projection,
            events=outcome.events,
        )

    def _commit(self, command: SessionCommand) -> CommandReceipt:
        return self._apply_transition(
            command,
            lambda state, rng: self._driver.commit(
                state,
                self._copy_command(command),
                rng,
            ),
        )

    def _resolve_reaction(self, command: SessionCommand) -> CommandReceipt:
        pending = self._pending_reaction
        if pending is None:
            raise EngineSessionError(
                "no_pending_reaction",
                "There is no pending reaction to resolve.",
            )
        reaction_id = str(command.payload["reaction_id"])
        if reaction_id != pending.reaction_id:
            raise EngineSessionError(
                "reaction_id_mismatch",
                "The reaction command does not match the pending reaction.",
                details={
                    "expected_reaction_id": pending.reaction_id,
                    "received_reaction_id": reaction_id,
                },
            )
        if command.actor_id not in pending.eligible_actor_ids:
            raise EngineSessionError(
                "reaction_actor_not_eligible",
                "The command actor is not eligible to answer this reaction.",
                details={
                    "actor_id": command.actor_id,
                    "eligible_actor_ids": list(pending.eligible_actor_ids),
                },
            )
        driver_pending = self._copy_reaction(pending)
        return self._apply_transition(
            command,
            lambda state, rng: self._driver.respond_to_reaction(
                state,
                self._copy_command(command),
                driver_pending,
                rng,
            ),
        )

    def _apply_transition(self, command: SessionCommand, operation: Any) -> CommandReceipt:
        working_state = self._decode_state(self._encode_state(self._state))
        working_rng = self._clone_rng()
        try:
            transition = operation(working_state, working_rng)
            if not isinstance(transition, EngineTransition):
                raise TypeError("driver operation must return EngineTransition")
            drafts = transition.events
            if not isinstance(drafts, tuple) or not drafts:
                raise ValueError("accepted transitions must emit a non-empty event tuple")
            if any(not isinstance(event, EventDraft) for event in drafts):
                raise TypeError("transition events must be EventDraft values")
            if transition.pending_reaction is not None and not isinstance(
                transition.pending_reaction, PendingReactionDraft
            ):
                raise TypeError("pending_reaction must be PendingReactionDraft")
            encoded_state = self._encode_state(transition.state)
            canonical_state = self._decode_state(encoded_state)
            new_events = self._materialize_events(command, drafts)
            pending_reaction = self._materialize_pending_reaction(
                command,
                transition.pending_reaction,
            )
        except EngineSessionError:
            raise
        except Exception as exc:
            raise self._driver_failure(exc) from exc

        new_revision = self._revision + 1
        receipt = CommandReceipt(
            command_id=command.command_id,
            session_id=self._session_id,
            revision=new_revision,
            version_pins=self._version_pins,
            first_sequence=new_events[0].sequence if new_events else None,
            last_sequence=new_events[-1].sequence if new_events else None,
            events=new_events,
        )
        record = CommandRecord(command=command, receipt=receipt)

        self._state = canonical_state
        self._rng.setstate(working_rng.getstate())
        self._revision = new_revision
        self._next_sequence += len(new_events)
        self._events.extend(new_events)
        self._records[command.command_id] = record
        self._pending_reaction = pending_reaction
        return CommandReceipt.model_validate(receipt.model_dump(mode="json"))

    def _materialize_events(
        self,
        command: SessionCommand,
        drafts: tuple[EventDraft, ...],
    ) -> tuple[SessionEvent, ...]:
        revision = self._revision + 1
        events: list[SessionEvent] = []
        causation_id: str | None = None
        for offset, draft in enumerate(drafts):
            sequence = self._next_sequence + offset
            identity = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "session_id": self._session_id,
                "sequence": sequence,
                "revision": revision,
                "kind": draft.kind,
                "command_id": command.command_id,
                "version_pins": self._version_pins.model_dump(mode="json"),
                "causation_id": causation_id,
                "audience": list(draft.audience),
                "payload": draft.payload,
            }
            event_id = (
                "evt_" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
            )
            event = SessionEvent(event_id=event_id, **identity)
            events.append(event)
            causation_id = event_id
        return tuple(events)

    def _materialize_pending_reaction(
        self,
        command: SessionCommand,
        draft: PendingReactionDraft | None,
    ) -> PendingReaction | None:
        if draft is None:
            return None
        return PendingReaction(
            reaction_id=draft.reaction_id,
            eligible_actor_ids=draft.eligible_actor_ids,
            prompt=draft.prompt,
            opened_by_command_id=command.command_id,
            opened_revision=self._revision + 1,
        )

    def _encode_state(self, state: Any) -> dict[str, JSONValue]:
        try:
            encoded = normalize_json(self._driver.encode_state(state), path="state")
        except Exception as exc:
            raise EngineSessionError(
                "invalid_state",
                "The engine driver could not encode state as a JSON object.",
            ) from exc
        if not isinstance(encoded, dict):
            raise EngineSessionError(
                "invalid_state",
                "The engine driver must encode state as a JSON object.",
            )
        return encoded

    def _decode_state(self, payload: Mapping[str, Any]) -> Any:
        try:
            return self._driver.decode_state(_json_clone(payload))
        except Exception as exc:
            raise EngineSessionError(
                "invalid_state",
                "The engine driver could not decode canonical state.",
            ) from exc

    def _clone_rng(self) -> random.Random:
        clone = random.Random()
        clone.setstate(self._rng.getstate())
        return clone

    @staticmethod
    def _copy_command(command: SessionCommand) -> SessionCommand:
        return SessionCommand.model_validate(command.model_dump(mode="json"))

    @staticmethod
    def _copy_event(event: SessionEvent) -> SessionEvent:
        return SessionEvent.model_validate(event.model_dump(mode="json"))

    @staticmethod
    def _copy_reaction(reaction: PendingReaction) -> PendingReaction:
        return PendingReaction.model_validate(reaction.model_dump(mode="json"))

    @staticmethod
    def _load_version_pins(driver: EngineSessionDriver) -> EngineVersionPins:
        try:
            raw_pins = driver.version_pins
            payload = (
                raw_pins.model_dump(mode="json")
                if isinstance(raw_pins, EngineVersionPins)
                else raw_pins
            )
            return EngineVersionPins.model_validate(payload)
        except (AttributeError, ValidationError, TypeError, ValueError) as exc:
            raise EngineSessionError(
                "invalid_driver_versions",
                "The engine driver must declare valid engine, rules, and content versions.",
            ) from exc

    def _validate_session(self, command: SessionCommand) -> None:
        if command.session_id != self._session_id:
            raise EngineSessionError(
                "session_id_mismatch",
                "The command belongs to a different session.",
                details={
                    "expected_session_id": self._session_id,
                    "received_session_id": command.session_id,
                },
            )

    def _validate_versions(self, command: SessionCommand) -> None:
        if command.version_pins != self._version_pins:
            raise EngineSessionError(
                "version_mismatch",
                "The command version pins do not match the active engine session.",
                details={
                    "session": self._version_pins.model_dump(mode="json"),
                    "command": command.version_pins.model_dump(mode="json"),
                },
            )

    def _validate_revision(self, command: SessionCommand) -> None:
        if command.expected_revision != self._revision:
            raise EngineSessionError(
                "stale_revision",
                "The command was based on a stale session revision.",
                details={
                    "expected_revision": self._revision,
                    "received_revision": command.expected_revision,
                },
            )

    @staticmethod
    def _driver_failure(exc: Exception) -> EngineSessionError:
        return EngineSessionError(
            "driver_failure",
            "The engine driver rejected or failed the command.",
            details={"exception_type": type(exc).__name__, "message": str(exc)},
        )

    @staticmethod
    def _validate_snapshot_invariants(snapshot: SessionSnapshot) -> None:
        expected_sequence = 1
        previous_revision = 0
        for event in snapshot.events:
            if event.session_id != snapshot.session_id:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot event session IDs are inconsistent.",
                )
            if event.version_pins != snapshot.version_pins:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot event version pins are inconsistent.",
                )
            if event.sequence != expected_sequence:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot event sequences must be contiguous.",
                )
            if event.revision < previous_revision or event.revision > snapshot.revision:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot event revisions are inconsistent.",
                )
            expected_sequence += 1
            previous_revision = event.revision
        if snapshot.next_sequence != expected_sequence:
            raise EngineSessionError(
                "invalid_snapshot",
                "Snapshot next_sequence does not follow the event log.",
            )

        if len(snapshot.command_records) != snapshot.revision:
            raise EngineSessionError(
                "invalid_snapshot",
                "Snapshot revision must equal the number of accepted command records.",
            )

        command_ids: set[str] = set()
        command_revisions: dict[str, int] = {}
        receipt_revisions: list[int] = []
        receipt_events: list[SessionEvent] = []
        for record in snapshot.command_records:
            command_id = record.command.command_id
            if command_id in command_ids:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot command IDs must be unique.",
                )
            command_ids.add(command_id)
            command_revisions[command_id] = record.receipt.revision
            receipt_revisions.append(record.receipt.revision)
            if record.command.session_id != snapshot.session_id:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot command session IDs are inconsistent.",
                )
            if record.command.version_pins != snapshot.version_pins:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot command version pins are inconsistent.",
                )
            if record.receipt.revision > snapshot.revision:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot receipt revisions are inconsistent.",
                )
            if record.receipt.replayed:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Stored command receipts cannot be marked as replayed.",
                )
            if not record.receipt.events:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Every accepted command receipt must contain at least one event.",
                )
            if record.command.expected_revision + 1 != record.receipt.revision:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot command and receipt revisions are inconsistent.",
                )
            if any(event.command_id != command_id for event in record.receipt.events):
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot receipt events reference a different command.",
                )
            if any(event.revision != record.receipt.revision for event in record.receipt.events):
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Snapshot receipt event revisions are inconsistent.",
                )
            receipt_events.extend(record.receipt.events)
            if record.receipt.events:
                assert record.receipt.first_sequence is not None
                assert record.receipt.last_sequence is not None
                start = record.receipt.first_sequence - 1
                stop = record.receipt.last_sequence
                if tuple(snapshot.events[start:stop]) != record.receipt.events:
                    raise EngineSessionError(
                        "invalid_snapshot",
                        "Snapshot receipt events do not match the canonical event log.",
                    )

        if receipt_revisions != list(range(1, snapshot.revision + 1)):
            raise EngineSessionError(
                "invalid_snapshot",
                "Snapshot receipt revisions must be contiguous and ordered.",
            )
        if any(event.command_id not in command_ids for event in snapshot.events):
            raise EngineSessionError(
                "invalid_snapshot",
                "Snapshot events must reference an accepted command record.",
            )
        if tuple(receipt_events) != snapshot.events:
            raise EngineSessionError(
                "invalid_snapshot",
                "Snapshot receipt events must exactly reproduce the canonical event log.",
            )

        if snapshot.pending_reaction is not None:
            if snapshot.pending_reaction.opened_revision != snapshot.revision:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Pending reaction must have opened at the current snapshot revision.",
                )
            if snapshot.pending_reaction.opened_by_command_id not in command_ids:
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Pending reaction does not reference a stored command.",
                )
            if (
                command_revisions[snapshot.pending_reaction.opened_by_command_id]
                != snapshot.pending_reaction.opened_revision
            ):
                raise EngineSessionError(
                    "invalid_snapshot",
                    "Pending reaction command and revision are inconsistent.",
                )
