# VTT Milestone 0 Implementation Plan

Status: implementation complete; D&D driver extraction remains follow-on
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
- [ ] Open a pull request and record the handoff.

## Follow-on Work

- Implement a `dnd_sim` combat driver on top of a resumable turn state machine.
- Add session persistence adapters and audience-filtered read models.
- Add the HTTP/WebSocket gateway only after the engine driver is real and replay-safe.
