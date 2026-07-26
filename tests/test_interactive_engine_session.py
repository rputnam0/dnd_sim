from __future__ import annotations

import random
import time
import hashlib
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from dnd_sim.interactive import (
    COMMAND_SCHEMA_VERSION,
    CommandReceipt,
    EngineSession,
    EngineSessionError,
    EngineTransition,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PendingReactionDraft,
    PreviewOutcome,
    PreviewReceipt,
    SessionCommand,
)

COUNTER_VERSION_PINS = EngineVersionPins(
    engine_version="counter-engine@1",
    rules_version="counter-rules@1",
    content_version="counter-content@1",
)


def recompute_snapshot_checksum(payload: dict[str, Any]) -> None:
    unsigned = {key: value for key, value in payload.items() if key != "checksum"}
    canonical = json.dumps(
        unsigned,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload["checksum"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CounterDriver:
    """Small deterministic driver used to prove orchestration without duplicating game rules."""

    def __init__(self, *, content_version: str = "counter-content@1") -> None:
        self.version_pins = EngineVersionPins(
            engine_version="counter-engine@1",
            rules_version="counter-rules@1",
            content_version=content_version,
        )

    def encode_state(self, state: dict[str, Any]) -> Mapping[str, Any]:
        return dict(state)

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return dict(payload)

    def preview(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        state["preview_was_isolated"] = True
        predicted_roll = rng.randint(1, 6)
        return PreviewOutcome(
            projection={
                "current_total": int(state.get("total", 0)),
                "predicted_roll": predicted_roll,
                "requested_amount": int(command.payload.get("amount", 0)),
            },
            events=(
                EventDraft(
                    kind="counter.previewed",
                    payload={"predicted_roll": predicted_roll},
                    audience=(str(command.actor_id),),
                ),
            ),
        )

    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        roll = rng.randint(1, 6)
        amount = int(command.payload.get("amount", 0))
        state["total"] = int(state.get("total", 0)) + amount + roll
        if command.kind == "counter.explode":
            raise RuntimeError("driver failed after mutating its working copy")

        pending_reaction = None
        if command.kind == "counter.open_reaction":
            pending_reaction = PendingReactionDraft(
                reaction_id=str(command.payload["reaction_id"]),
                eligible_actor_ids=tuple(command.payload["eligible_actor_ids"]),
                prompt={"message": "React?"},
            )

        return EngineTransition(
            state=state,
            events=(
                EventDraft(
                    kind="counter.changed",
                    payload={"amount": amount, "roll": roll, "total": state["total"]},
                ),
            ),
            pending_reaction=pending_reaction,
        )

    def respond_to_reaction(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        state["reaction"] = str(command.payload["choice"])
        state["reaction_roll"] = rng.randint(1, 6)
        return EngineTransition(
            state=state,
            events=(
                EventDraft(
                    kind="reaction.resolved",
                    payload={
                        "reaction_id": pending_reaction.reaction_id,
                        "choice": state["reaction"],
                        "roll": state["reaction_roll"],
                    },
                ),
            ),
            pending_reaction=None,
        )


class SlowCounterDriver(CounterDriver):
    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        time.sleep(0.02)
        return super().commit(state, command, rng)


class EmptyEventDriver(CounterDriver):
    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        state["total"] = rng.randint(1, 6)
        return EngineTransition(state=state)


class GeneratorEventDriver(CounterDriver):
    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        state["total"] = rng.randint(1, 6)
        events = (
            event
            for event in (EventDraft(kind="counter.changed", payload={"total": state["total"]}),)
        )
        return EngineTransition(state=state, events=events)  # type: ignore[arg-type]


class BoolCoercingDriver(CounterDriver):
    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"total": bool(payload["total"])}


class MutatingDriver(CounterDriver):
    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        command.payload["amount"] = 99
        return super().commit(state, command, rng)

    def respond_to_reaction(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        pending_reaction.prompt["message"] = "corrupted"
        rng.randint(1, 6)
        raise RuntimeError("reaction driver failed after mutating its inputs")


@dataclass
class DomainCounterState:
    total: int


class DomainCounterDriver:
    version_pins = COUNTER_VERSION_PINS

    def encode_state(self, state: DomainCounterState) -> Mapping[str, Any]:
        if not isinstance(state, DomainCounterState):
            raise TypeError("expected decoded DomainCounterState")
        return {"total": state.total}

    def decode_state(self, payload: Mapping[str, Any]) -> DomainCounterState:
        return DomainCounterState(total=int(payload["total"]))

    def preview(
        self,
        state: DomainCounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        return PreviewOutcome(projection={"total": state.total})

    def commit(
        self,
        state: DomainCounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        state.total += int(command.payload["amount"]) + rng.randint(1, 6)
        return EngineTransition(
            state=state,
            events=(EventDraft(kind="domain.changed", payload={"total": state.total}),),
        )

    def respond_to_reaction(
        self,
        state: DomainCounterState,
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise NotImplementedError


def command(
    command_id: str,
    *,
    expected_revision: int,
    mode: str = "commit",
    kind: str = "counter.add",
    actor_id: str | None = "hero",
    payload: dict[str, Any] | None = None,
) -> SessionCommand:
    return SessionCommand(
        schema_version=COMMAND_SCHEMA_VERSION,
        command_id=command_id,
        session_id="session-1",
        actor_id=actor_id,
        expected_revision=expected_revision,
        mode=mode,
        kind=kind,
        payload=payload or {"amount": 2},
        version_pins=COUNTER_VERSION_PINS,
    )


def test_command_contract_rejects_unknown_fields_invalid_values_and_versions() -> None:
    with pytest.raises(ValidationError):
        SessionCommand(
            command_id="cmd-1",
            session_id="session-1",
            expected_revision=0,
            mode="commit",
            kind="counter.add",
            unexpected=True,
        )

    with pytest.raises(ValidationError, match="reaction_id"):
        command("cmd-2", expected_revision=0, mode="reaction", payload={"choice": "yes"})

    with pytest.raises(ValidationError):
        command("cmd-3", expected_revision=True)

    with pytest.raises(ValidationError):
        SessionCommand(
            schema_version="engine.command.v999",
            command_id="cmd-4",
            session_id="session-1",
            expected_revision=0,
            mode="commit",
            kind="counter.add",
        )

    with pytest.raises(ValidationError, match="NaN"):
        command("cmd-5", expected_revision=0, payload={"amount": float("nan")})

    with pytest.raises(ValidationError, match="audience"):
        EventDraft(kind="counter.changed", audience="alice")

    with pytest.raises(ValidationError, match="audience"):
        EventDraft(kind="counter.changed", audience={"alice", "bob"})


def test_preview_is_read_only_and_does_not_consume_canonical_rng() -> None:
    driver = CounterDriver()
    previewed = EngineSession("session-1", {"total": 0}, driver, seed=17)
    direct = EngineSession("session-1", {"total": 0}, driver, seed=17)

    preview = previewed.execute(
        command("preview-1", expected_revision=0, mode="preview", payload={"amount": 3})
    )

    assert isinstance(preview, PreviewReceipt)
    assert preview.revision == 0
    assert preview.projection["current_total"] == 0
    assert previewed.state == {"total": 0}
    assert previewed.revision == 0
    assert previewed.events == ()

    after_preview = previewed.execute(
        command("commit-1", expected_revision=0, payload={"amount": 3})
    )
    without_preview = direct.execute(
        command("commit-1", expected_revision=0, payload={"amount": 3})
    )

    assert isinstance(after_preview, CommandReceipt)
    assert after_preview == without_preview
    assert preview.projection["predicted_roll"] == after_preview.events[0].payload["roll"]
    assert previewed.snapshot() == direct.snapshot()


def test_commit_advances_revision_and_emits_ordered_deterministic_events() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=7)

    first = session.execute(command("commit-1", expected_revision=0))
    second = session.execute(command("commit-2", expected_revision=1))

    assert isinstance(first, CommandReceipt)
    assert isinstance(second, CommandReceipt)
    assert first.revision == 1
    assert first.first_sequence == first.last_sequence == 1
    assert second.revision == 2
    assert second.first_sequence == second.last_sequence == 2
    assert [event.sequence for event in session.events] == [1, 2]
    assert [event.revision for event in session.events] == [1, 2]
    assert all(event.event_id.startswith("evt_") for event in session.events)
    assert all(event.version_pins == COUNTER_VERSION_PINS for event in session.events)
    assert session.events_since(1) == (session.events[1],)


def test_session_serializes_concurrent_commands_at_the_revision_boundary() -> None:
    session = EngineSession("session-1", {"total": 0}, SlowCounterDriver(), seed=7)

    def execute(index: int) -> CommandReceipt | str:
        try:
            result = session.execute(command(f"commit-{index}", expected_revision=0))
        except EngineSessionError as exc:
            return exc.code
        assert isinstance(result, CommandReceipt)
        return result

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(execute, range(8)))

    assert len([result for result in results if isinstance(result, CommandReceipt)]) == 1
    assert results.count("stale_revision") == 7
    assert session.revision == 1
    assert len(session.events) == 1


def test_duplicate_commit_is_idempotent_and_conflicting_reuse_is_rejected() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=7)
    original_command = command("commit-1", expected_revision=0)
    first = session.execute(original_command)
    state_after_first = session.state

    duplicate = session.execute(original_command)

    assert isinstance(first, CommandReceipt)
    assert isinstance(duplicate, CommandReceipt)
    assert duplicate.replayed is True
    assert duplicate.events == first.events
    assert session.state == state_after_first
    assert session.revision == 1
    assert len(session.events) == 1

    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(command("commit-1", expected_revision=0, payload={"amount": 99}))

    assert exc_info.value.code == "command_id_conflict"
    assert session.state == state_after_first


def test_returned_contracts_cannot_mutate_canonical_session_history() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=7)
    original_command = command("commit-1", expected_revision=0)
    receipt = session.execute(original_command)
    snapshot_before_mutation = session.snapshot()

    assert isinstance(receipt, CommandReceipt)
    original_command.payload["amount"] = 999
    receipt.events[0].payload["total"] = 999
    session.events[0].payload["total"] = 999

    assert session.snapshot() == snapshot_before_mutation
    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(original_command)
    assert exc_info.value.code == "command_id_conflict"


def test_stale_revision_and_driver_failure_leave_state_rng_and_events_unchanged() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=31)
    before = session.snapshot()

    with pytest.raises(EngineSessionError) as stale_error:
        session.execute(command("stale", expected_revision=1))
    assert stale_error.value.code == "stale_revision"
    assert session.snapshot() == before

    with pytest.raises(EngineSessionError) as driver_error:
        session.execute(command("explode", expected_revision=0, kind="counter.explode"))
    assert driver_error.value.code == "driver_failure"
    assert session.snapshot() == before

    recovered = session.execute(command("commit-1", expected_revision=0))
    fresh = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=31).execute(
        command("commit-1", expected_revision=0)
    )
    assert recovered == fresh


@pytest.mark.parametrize("driver", [EmptyEventDriver(), GeneratorEventDriver()])
def test_transition_without_a_nonempty_event_tuple_is_rejected_atomically(
    driver: CounterDriver,
) -> None:
    session = EngineSession("session-1", {"total": 0}, driver, seed=31)
    before = session.snapshot()

    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(command("commit-1", expected_revision=0))

    assert exc_info.value.code == "driver_failure"
    assert session.snapshot() == before


def test_driver_cannot_mutate_stored_command_or_pending_reaction_inputs() -> None:
    driver = MutatingDriver()
    session = EngineSession("session-1", {"total": 0}, driver, seed=31)
    committed_command = command("commit-1", expected_revision=0)
    session.execute(committed_command)

    assert session.execute(committed_command).replayed is True
    assert session.snapshot().command_records[0].command.payload["amount"] == 2

    session.execute(
        command(
            "open-1",
            expected_revision=1,
            kind="counter.open_reaction",
            payload={
                "amount": 1,
                "reaction_id": "reaction-1",
                "eligible_actor_ids": ["rogue"],
            },
        )
    )
    before_failed_reaction = session.snapshot()
    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(
            command(
                "reaction-1-response",
                expected_revision=2,
                mode="reaction",
                actor_id="rogue",
                payload={"reaction_id": "reaction-1", "choice": "yes"},
            )
        )

    assert exc_info.value.code == "driver_failure"
    assert session.snapshot() == before_failed_reaction


def test_version_mismatch_rejects_commands_and_incompatible_restore() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=31)
    before = session.snapshot()
    mismatched_pins = EngineVersionPins(
        engine_version="counter-engine@1",
        rules_version="counter-rules@1",
        content_version="counter-content@2",
    )
    mismatched_command = command("commit-1", expected_revision=0).model_copy(
        update={"version_pins": mismatched_pins}
    )

    with pytest.raises(EngineSessionError) as command_error:
        session.execute(mismatched_command)
    assert command_error.value.code == "version_mismatch"
    assert session.snapshot() == before

    with pytest.raises(EngineSessionError) as restore_error:
        EngineSession.restore(before, CounterDriver(content_version="counter-content@2"))
    assert restore_error.value.code == "version_mismatch"


def test_pending_reaction_blocks_commits_and_accepts_only_the_eligible_response() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=5)
    opened = session.execute(
        command(
            "open-1",
            expected_revision=0,
            kind="counter.open_reaction",
            payload={
                "amount": 1,
                "reaction_id": "reaction-1",
                "eligible_actor_ids": ["rogue"],
            },
        )
    )

    assert isinstance(opened, CommandReceipt)
    assert session.pending_reaction is not None
    assert session.pending_reaction.reaction_id == "reaction-1"
    assert session.pending_reaction.opened_revision == 1

    with pytest.raises(EngineSessionError) as pending_error:
        session.execute(command("commit-2", expected_revision=1))
    assert pending_error.value.code == "pending_reaction"

    with pytest.raises(EngineSessionError) as actor_error:
        session.execute(
            command(
                "reaction-wrong-actor",
                expected_revision=1,
                mode="reaction",
                actor_id="hero",
                payload={"reaction_id": "reaction-1", "choice": "yes"},
            )
        )
    assert actor_error.value.code == "reaction_actor_not_eligible"

    resolved_command = command(
        "reaction-1-response",
        expected_revision=1,
        mode="reaction",
        actor_id="rogue",
        payload={"reaction_id": "reaction-1", "choice": "yes"},
    )
    resolved = session.execute(resolved_command)

    assert isinstance(resolved, CommandReceipt)
    assert resolved.revision == 2
    assert session.pending_reaction is None
    assert session.state["reaction"] == "yes"
    assert [event.kind for event in session.events] == [
        "counter.changed",
        "reaction.resolved",
    ]
    assert session.execute(resolved_command).replayed is True


def test_snapshot_restore_preserves_rng_events_pending_state_and_idempotency() -> None:
    driver = CounterDriver()
    uninterrupted = EngineSession("session-1", {"total": 0}, driver, seed=41)
    first_command = command("commit-1", expected_revision=0)
    first_receipt = uninterrupted.execute(first_command)
    snapshot = uninterrupted.snapshot()
    restored = EngineSession.restore(snapshot.model_dump(mode="json"), driver)

    assert restored.snapshot() == snapshot
    assert restored.execute(first_command).replayed is True

    next_command = command("commit-2", expected_revision=1, payload={"amount": 5})
    uninterrupted_receipt = uninterrupted.execute(next_command)
    restored_receipt = restored.execute(next_command)

    assert restored_receipt == uninterrupted_receipt
    assert restored.snapshot() == uninterrupted.snapshot()
    assert first_receipt.events[0] == restored.events[0]


def test_restore_decodes_non_mapping_domain_state_before_continuing() -> None:
    driver = DomainCounterDriver()
    uninterrupted = EngineSession(
        "session-1",
        DomainCounterState(total=0),
        driver,
        seed=41,
    )
    uninterrupted.execute(command("commit-1", expected_revision=0))
    restored = EngineSession.restore(uninterrupted.snapshot(), driver)

    next_command = command("commit-2", expected_revision=1, payload={"amount": 5})
    assert restored.execute(next_command) == uninterrupted.execute(next_command)
    assert restored.snapshot() == uninterrupted.snapshot()


def test_restore_rejects_a_codec_that_changes_json_scalar_types() -> None:
    snapshot = EngineSession(
        "session-1",
        {"total": 1},
        CounterDriver(),
        seed=41,
    ).snapshot()

    with pytest.raises(EngineSessionError) as exc_info:
        EngineSession.restore(snapshot, BoolCoercingDriver())

    assert exc_info.value.code == "invalid_snapshot"


def test_snapshot_restore_preserves_an_open_reaction_without_aliasing() -> None:
    driver = CounterDriver()
    session = EngineSession("session-1", {"total": 0}, driver, seed=19)
    session.execute(
        command(
            "open-1",
            expected_revision=0,
            kind="counter.open_reaction",
            payload={
                "amount": 1,
                "reaction_id": "reaction-1",
                "eligible_actor_ids": ["rogue"],
            },
        )
    )
    snapshot = session.snapshot()
    restored = EngineSession.restore(snapshot, driver)

    assert restored.pending_reaction == session.pending_reaction
    assert restored.snapshot() == snapshot

    assert restored.pending_reaction is not None
    restored.pending_reaction.prompt["message"] = "tampered"
    assert restored.snapshot() == snapshot


def test_tampered_snapshot_is_rejected() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=13)
    session.execute(command("commit-1", expected_revision=0))
    payload = session.snapshot().model_dump(mode="json")
    payload["state"]["total"] = 999

    with pytest.raises(EngineSessionError) as exc_info:
        EngineSession.restore(payload, CounterDriver())

    assert exc_info.value.code == "invalid_snapshot_checksum"


def test_checksum_consistent_snapshot_with_divergent_receipt_events_is_rejected() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=13)
    session.execute(command("commit-1", expected_revision=0))
    payload = session.snapshot().model_dump(mode="json")
    receipt = payload["command_records"][0]["receipt"]
    receipt["events"] = []
    receipt["first_sequence"] = None
    receipt["last_sequence"] = None
    recompute_snapshot_checksum(payload)

    with pytest.raises(EngineSessionError) as exc_info:
        EngineSession.restore(payload, CounterDriver())

    assert exc_info.value.code == "invalid_snapshot"


def test_checksum_consistent_snapshot_with_stale_pending_reaction_is_rejected() -> None:
    session = EngineSession("session-1", {"total": 0}, CounterDriver(), seed=13)
    session.execute(command("commit-1", expected_revision=0))
    session.execute(
        command(
            "open-1",
            expected_revision=1,
            kind="counter.open_reaction",
            payload={
                "amount": 1,
                "reaction_id": "reaction-1",
                "eligible_actor_ids": ["rogue"],
            },
        )
    )
    payload = session.snapshot().model_dump(mode="json")
    payload["pending_reaction"]["opened_by_command_id"] = "commit-1"
    payload["pending_reaction"]["opened_revision"] = 1
    recompute_snapshot_checksum(payload)

    with pytest.raises(EngineSessionError) as exc_info:
        EngineSession.restore(payload, CounterDriver())

    assert exc_info.value.code == "invalid_snapshot"


def test_replay_of_same_commands_is_byte_stable() -> None:
    commands = (
        command("commit-1", expected_revision=0, payload={"amount": 1}),
        command("commit-2", expected_revision=1, payload={"amount": 4}),
    )

    first = EngineSession.replay(
        session_id="session-1",
        initial_state={"total": 0},
        driver=CounterDriver(),
        seed=101,
        commands=commands,
    )
    second = EngineSession.replay(
        session_id="session-1",
        initial_state={"total": 0},
        driver=CounterDriver(),
        seed=101,
        commands=commands,
    )

    assert first.snapshot_json() == second.snapshot_json()
    assert first.events == second.events
