# VTT Milestone 0 Implementation Plan

Status: implementation complete in draft PR #250; D&D driver extraction remains follow-on
Branch: `codex/authoritative-vtt-m0`

This milestone establishes a transport-independent interactive engine-session boundary. It does not
add a web server, browser client, or a second D&D rules implementation.

## Checklist

- [x] Define versioned, JSON-safe command, event, receipt, reaction, and snapshot contracts.
- [x] Add a driver protocol that isolates live-session orchestration from engine internals.
- [x] Guarantee preview isolation, atomic commits, optimistic revision checks, and idempotency.
- [x] Persist and restore canonical state, RNG state, event order, pending reactions, and receipts.
- [x] Prove deterministic replay and post-restore continuation with focused tests.
- [x] Run targeted formatting, focused tests, and the full repository suite (1,161 passed).
- [x] Open draft PR #250 and record the handoff.

## Handoff

- Pull request: https://github.com/rputnam0/dnd_sim/pull/250
- Implementation commit: `556e26f`
- Next slice: extract the batch encounter loop into a serializable whole-turn state machine and
  implement the first real D&D `EngineSessionDriver` without changing fixed-seed batch outcomes.

## Follow-on Work

- Implement a `dnd_sim` combat driver on top of a resumable turn state machine.
- Add session persistence adapters and audience-filtered read models.
- Add the HTTP/WebSocket gateway only after the engine driver is real and replay-safe.
