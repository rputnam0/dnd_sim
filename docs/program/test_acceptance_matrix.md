# Test Acceptance Matrix

Status: canonical  
Owner: qa-gate  
Last updated: 2026-03-05  
Canonical source: `docs/program/README.md`

## Global requirements for every task

- minimum one direct unit test,
- minimum one integration or golden test,
- minimum one negative or invalid-input test,
- deterministic seed stability for unchanged behavior,
- live doc updates in the same branch,
- migration tests when schema or persistence changes,
- runtime ownership updates when module boundaries change.

## Documentation Control tasks

Required coverage:
- metadata header parser tests,
- markdown table parser and status-reduction rule tests,
- broken-link tests,
- backlog/status synchronization tests,
- archive-reference tests,
- stale status fixture that fails with `DOC-SYNC-008`,
- missing metadata fixture that fails with `DOC-LIVE-005`,
- doc consistency CI dry-run.

## Runtime Decomposition tasks

Required coverage:
- public facade contract tests,
- deterministic replay comparisons before and after extraction,
- structured legality error tests,
- no-regression combat integration tests.

Structural gates:
- `engine.py` must shrink on every ARC task.
- `engine.py` must end below 3500 lines by `ARC-08`.
- no extracted runtime module may exceed 1500 lines without an explicit waiver in `docs/agent_index.yaml`.

ARC-08 required evidence:
- replay serialization tests for stable trial-row envelopes (`tests/test_replay_serialization.py`),
- simulation summary aggregation tests for reporting adapters (`tests/test_replay_reporting_runtime.py`),
- deterministic replay diff tests for unchanged seeds (`tests/test_replay_serialization.py`; `tests/test_engine_runtime_seed_replay.py`),
- adapter integration coverage through reporting paths (`tests/test_reporting.py`).

## Capability Manifest tasks

Required coverage:
- manifest schema tests,
- coverage-generation tests,
- unsupported-reason tests,
- import/CI gate tests,
- stable ordering snapshot tests.

CAP-01 minimum gate:
- schema validation must require all canonical state fields (`cataloged`, `schema_valid`, `executable`, `tested`, `blocked`, `unsupported_reason`),
- blocked-state negative tests must require `unsupported_reason` only when `blocked=true`,
- manifest round-trip tests must preserve canonical ordering and payload shape,
- CLI smoke test must prove deterministic JSON emission from unordered input payloads.

## Replay, Logging, and Observability tasks

Required coverage:
- event schema tests,
- trace completeness tests,
- state-delta tests,
- RNG audit determinism tests,
- replay round-trip tests,
- replay diff tests,
- golden trace gate tests.

## Persistence and Query Model tasks

Required coverage:
- migration and rollback tests,
- content lineage/hash tests,
- query API tests,
- campaign/world round-trip tests,
- corruption and invalid state negative tests.

## Tactical AI Hardening tasks

Required coverage:
- candidate-enumeration tests,
- illegal-candidate exclusion tests,
- scoring component tests,
- rationale trace tests,
- benchmark regression tests.

AI gate:
- the primary tactical AI must outperform `BaseStrategy` and `HighestThreatStrategy` on the benchmark corpus used by `AI-06`,
- every benchmark turn must emit candidate and rationale traces.

## Rules Closure tasks

Required coverage:
- deterministic feature-specific correctness tests,
- illegal trigger-window tests,
- resource-use tests,
- reaction/concentration interaction tests,
- hazard-aware scoring integration tests.

## World Systems and Campaign Platform tasks

Required coverage:
- ability check and contest tests,
- time and light progression tests,
- travel/rest integration tests,
- world hazard tests,
- economy/downtime tests,
- quest/faction/world-state persistence tests,
- encounter scripting/wave tests,
- world-scale replay and performance regression tests.

## Completion Gates

A completion branch is green only when:

- full `uv run python -m pytest` passes,
- capability manifest gate passes for shipped 2014 scope,
- combat and world replay corpora pass,
- integrated campaign/world/combat scenarios pass,
- agent-only maintenance gate passes,
- doc consistency gate passes.
