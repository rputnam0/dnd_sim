# Interactive Engine Session

`dnd_sim.interactive` is the transport-independent command/event boundary for a future VTT. It
does not expose HTTP or WebSocket endpoints. A deterministic rules driver owns mechanical legality
and resolution; `EngineSession` owns transactional execution, revisions, event ordering,
idempotency, reactions, and recovery. `DndCombatTurnDriver` now connects this boundary to the real
D&D combat-turn kernel for one complete synchronous actor turn.

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
from dnd_sim.interactive import (
    DECLARATION_COMMAND_KIND,
    DndCombatTurnDriver,
    EngineSession,
    EngineVersionPins,
    SessionCommand,
    TurnDeclarationPayload,
)

version_pins = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="5e_2014_combat_foundation@1.0.0",
    content_version="solo-table-fixture@1",
)
driver = DndCombatTurnDriver(version_pins=version_pins)
turn_payload = TurnDeclarationPayload.from_domain(turn_declaration).model_dump(mode="json")

session = EngineSession("encounter-7", initial_state, driver, seed=20260726)

preview = session.execute(
    SessionCommand(
        command_id="preview-1",
        session_id="encounter-7",
        actor_id="fighter-1",
        expected_revision=0,
        mode="preview",
        kind=DECLARATION_COMMAND_KIND,
        version_pins=version_pins,
        payload=turn_payload,
    )
)

receipt = session.execute(
    SessionCommand(
        command_id="commit-1",
        session_id="encounter-7",
        actor_id="fighter-1",
        expected_revision=0,
        mode="commit",
        kind=DECLARATION_COMMAND_KIND,
        version_pins=version_pins,
        payload=turn_payload,
    )
)

checkpoint_json = session.snapshot_json()
restored = EngineSession.restore(session.snapshot(), driver)
tail = restored.events_since(receipt.last_sequence or 0)
```

The service layer must serialize commands for each session; `EngineSession` is intentionally a
single-owner state machine rather than a lock manager or database transaction coordinator.

## D&D Driver Boundary and Current Limit

`DndCombatTurnDriver` uses a strict `dnd.declare_turn.v1` payload, a versioned full-state codec, and
the same `resolve_combat_turn` function used by batch simulation. Its codec preserves the complete
95-field actor graph, inventory, spells, effects, wild-shape restoration data, timing sequence, and
all turn metrics. Set-valued fields are sorted so snapshots remain deterministic across Python hash
seeds. Preview, failed commit, restore, and retry therefore exercise real D&D state without relying
on the reporting-only actor snapshot.

The driver currently represents exactly one synchronous actor turn: state is `ready` before the
command and `complete` afterward. Start-of-turn automation occurs inside that transaction, and
reactions remain explicitly auto-resolved. The next extraction must add a prompt-bound encounter
cursor that automatically advances rounds, lair actions, turn starts, death saves, hazards, and
forced paths until it reaches `awaiting_declaration` or `terminal`. That encounter state—not this
one-turn adapter—will back the Solo Table service and browser UI.
