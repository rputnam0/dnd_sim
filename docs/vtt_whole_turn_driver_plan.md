# VTT Whole-Turn Driver Plan

This checklist turns the generic interactive session kernel into a real D&D
turn driver before browser transport or rendering is added. The batch simulator
and VTT must resolve a declared turn through the same domain function.

## Milestone 1: Atomic declared-turn kernel

- [x] Add a complete in-memory state boundary for declared-turn resolution.
- [x] Prove rejected declarations do not mutate actors, metrics, hazards,
      telemetry, rule trace, timing state, or RNG state.
- [x] Prove preview and commit from identical state and RNG produce identical
      candidates.
- [x] Route batch and atomic session candidates through the same public
      declared-turn resolver.
- [x] Prove fixed-seed batch replay remains deterministic.

## Milestone 2: Prompt-bound combat state

- [x] Extract one synchronous actor-turn kernel containing start automation,
      the decision seam, action/bonus resolution, turn end, and legendary actions.
- [x] Persist combat only at `awaiting_declaration` or `terminal` boundaries.
- [x] Extract deterministic automatic phases (turn start, hazards, death saves,
      forced dodge, turn end, legendary actions) around the prompted turn.
- [x] Keep reactions explicitly auto-resolved until a resumable reaction
      continuation is implemented.
- [x] Make batch strategy selection and interactive commands call the same
      prompted-turn resolver.

## Milestone 3: D&D interactive driver

- [x] Define a strict JSON turn-declaration command payload.
- [x] Implement a complete, versioned state codec rather than serializing
      reporting snapshots or runtime objects directly.
- [x] Implement preview, commit, restore, idempotent retry, and fixed-seed replay
      through `EngineSession`.
- [x] Project public action metadata, initiative, HP/effects, and rules events
      without exposing hidden engine state.
- [ ] Add an authoritative legal-choice read model for movement, actions, and
      targets rather than deriving candidates in the browser.

## Milestone 4: Solo Table v0

- [x] Add an append-only SQLite command/receipt/snapshot store.
- [x] Add a single-session VTT application boundary over the engine session and store.
- [x] Add an HTTP JSON gateway with a separate `vtt.command.v1` transport
      contract.
- [x] Add a reconnectable Server-Sent Events gateway with an exclusive event
      cursor and heartbeat.
- [x] Add an original fixed encounter with a square-grid scene and tokens.
- [x] Add the browser table: selection, movement preview/commit, action palette,
      target selection, initiative, HP/effects, public rules log, and win/loss.
- [x] Add an end-to-end service test that completes the encounter, restarts the
      service, reloads the exact terminal view, and retries without duplicate
      mutation.
- [ ] Add a browser-driven end-to-end test and a second fresh-database replay
      comparison.

## Verification gates

- Targeted tests must pass after each TDD increment.
- `uv run python -m black .` must pass before review.
- `uv run python -m pytest` must pass before this branch is published.
- New turn-driver commits will be re-stacked onto merged foundation branches so
  the eventual pull request contains only this milestone's changes.
