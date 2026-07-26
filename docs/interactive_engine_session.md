# Interactive Engine Session

`dnd_sim.interactive` is the transport-independent command/event boundary for a future VTT. It
does not implement D&D rules and it does not expose HTTP or WebSocket endpoints. A deterministic
rules driver owns mechanical legality and resolution; `EngineSession` owns transactional execution,
revisions, event ordering, idempotency, reactions, and recovery.

## Guarantees

- Preview runs against cloned state and a cloned RNG, then discards both.
- Commit runs against cloned state and a cloned RNG and swaps them into the session only after the
  driver returns a valid transition.
- An accepted command advances the revision exactly once and emits contiguous per-session events.
- Retrying an identical committed `command_id` returns its original receipt without another
  mutation. Reusing the ID for different content fails with `command_id_conflict`.
- The idempotency lookup happens before stale-revision validation, so a reconnect retry remains safe.
- Snapshots include canonical state, structured MT19937 state, ordered events, committed command
  receipts, an open reaction, and a SHA-256 integrity checksum.
- Snapshot restore and command-log replay preserve deterministic continuation.
- Engine, rules, and content version pins travel with every command, event, receipt, and snapshot;
  incompatible commands and restores fail closed.
- Commands, events, receipts, reactions, and snapshots reject unknown fields and non-JSON values.

Canonical event bytes contain no wall-clock timestamp. Presentation timing and network arrival
order therefore cannot alter replay output.

## Driver Boundary

An `EngineSessionDriver` implements five methods:

```python
class EngineSessionDriver(Protocol):
    version_pins: EngineVersionPins

    def encode_state(self, state: Any) -> Mapping[str, Any]: ...
    def decode_state(self, payload: Mapping[str, Any]) -> Any: ...
    def preview(self, state, command, rng) -> PreviewOutcome: ...
    def commit(self, state, command, rng) -> EngineTransition: ...
    def respond_to_reaction(self, state, command, pending_reaction, rng) -> EngineTransition: ...
```

`encode_state` and `decode_state` define the full durable state codec and must be deterministic.
Preview and transition methods receive isolated state plus an isolated `random.Random`. The driver
returns event drafts; the session assigns immutable IDs, sequence numbers, revisions, command
causation, and audience policies.

## Command Flow

```python
from dnd_sim.interactive import EngineSession, EngineVersionPins, SessionCommand

version_pins = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="2014@1",
    content_version="campaign-7@3",
)
driver.version_pins = version_pins

session = EngineSession("encounter-7", initial_state, driver, seed=20260726)

preview = session.execute(
    SessionCommand(
        command_id="preview-1",
        session_id="encounter-7",
        actor_id="fighter-1",
        expected_revision=0,
        mode="preview",
        kind="combat.turn",
        version_pins=version_pins,
        payload={"declaration": turn_payload},
    )
)

receipt = session.execute(
    SessionCommand(
        command_id="commit-1",
        session_id="encounter-7",
        actor_id="fighter-1",
        expected_revision=0,
        mode="commit",
        kind="combat.turn",
        version_pins=version_pins,
        payload={"declaration": turn_payload},
    )
)

checkpoint_json = session.snapshot_json()
restored = EngineSession.restore(session.snapshot(), driver)
tail = restored.events_since(receipt.last_sequence or 0)
```

The service layer must serialize commands for each session; `EngineSession` is intentionally a
single-owner state machine rather than a lock manager or database transaction coordinator.

## Current Integration Limit

The existing D&D runtime still owns a complete encounter inside one batch loop. Its declared-turn
resolver can mutate movement before validating later action steps, its snapshots are reporting-only,
and its reactions resolve synchronously. For that reason this module does not claim a live D&D
driver yet. The next engine change is to extract a serializable whole-turn state machine that:

1. advances automatic phases until an input prompt;
2. resolves one existing `TurnDeclaration` on isolated state and RNG;
3. makes the batch simulator and interactive driver call the same rules path; and
4. initially keeps reactions explicitly auto-only until reaction continuations are extracted.

This constraint prevents the VTT from becoming a second, subtly different rules engine.
