"""Locked ownership and durable commit orchestration for one VTT session."""

from __future__ import annotations

import threading
from typing import Any

from dnd_sim.interactive.contracts import CommandReceipt, JSONValue, PreviewReceipt
from dnd_sim.interactive.session import EngineSession, EngineSessionDriver

from .contracts import (
    VTTCommand,
    VTTCommitResponse,
    VTTPreviewResponse,
    VTTResponse,
    VTTVersionInfo,
)
from .event_store import SQLiteSessionEventStore


class VTTSessionServiceError(ValueError):
    """Raised when a command cannot be routed to this service's session."""


class VTTSessionService:
    """Own one engine session and persist every successful non-preview command."""

    def __init__(
        self,
        *,
        session: EngineSession,
        driver: EngineSessionDriver,
        event_store: SQLiteSessionEventStore,
    ) -> None:
        self._lock = threading.RLock()
        self._session = session
        self._driver = driver
        self._event_store = event_store

    @classmethod
    def open(
        cls,
        *,
        session_id: str,
        initial_state: Any,
        driver: EngineSessionDriver,
        seed: int,
        event_store: SQLiteSessionEventStore,
    ) -> "VTTSessionService":
        """Create a new session or restore its latest atomically stored snapshot."""

        normalized_session_id = str(session_id).strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")
        if not isinstance(event_store, SQLiteSessionEventStore):
            raise TypeError("event_store must be a SQLiteSessionEventStore")

        latest = event_store.load_latest_snapshot(normalized_session_id)
        if latest is None:
            session = EngineSession(
                normalized_session_id,
                initial_state,
                driver,
                seed=seed,
            )
        else:
            session = EngineSession.restore(latest.snapshot, driver)
            if session.session_id != normalized_session_id:
                raise VTTSessionServiceError("the stored snapshot belongs to a different session")
        return cls(session=session, driver=driver, event_store=event_store)

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def revision(self) -> int:
        with self._lock:
            return self._session.revision

    @property
    def state(self) -> dict[str, JSONValue]:
        with self._lock:
            return self._session.state

    @property
    def versions(self) -> VTTVersionInfo:
        with self._lock:
            return VTTVersionInfo.from_engine(self._session.version_pins)

    def execute(self, command: VTTCommand) -> VTTResponse:
        """Execute a translated command and durably append each successful commit."""

        if not isinstance(command, VTTCommand):
            raise TypeError("command must be a VTTCommand")
        command = VTTCommand.model_validate(command.model_dump(mode="json"))

        with self._lock:
            if command.session_id != self._session.session_id:
                raise VTTSessionServiceError("command.session_id does not match the open session")

            engine_command = command.to_session_command(self._session.version_pins)
            if command.mode == "preview":
                receipt = self._session.execute(engine_command)
                if not isinstance(receipt, PreviewReceipt):
                    raise RuntimeError("the engine returned a commit receipt for a preview")
                return VTTPreviewResponse.from_engine(receipt)

            before_command = self._session.snapshot()
            receipt = self._session.execute(engine_command)
            if not isinstance(receipt, CommandReceipt):
                raise RuntimeError("the engine returned a preview receipt for a commit")

            try:
                response = VTTCommitResponse.from_engine(receipt)
                append_result = self._event_store.append_commit(
                    session_id=self._session.session_id,
                    command_id=command.command_id,
                    command=command.model_dump(mode="json"),
                    receipt=response.model_dump(mode="json"),
                    snapshot=self._session.snapshot().model_dump(mode="json"),
                )
                durable_response = VTTCommitResponse.model_validate(append_result.record.receipt)
            except Exception:
                self._session = EngineSession.restore(before_command, self._driver)
                raise

            if append_result.replayed:
                return durable_response.model_copy(update={"replayed": True})
            return durable_response


__all__ = ["VTTSessionService", "VTTSessionServiceError"]
