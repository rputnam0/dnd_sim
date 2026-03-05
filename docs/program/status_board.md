# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/backlog.csv`

Use this document as the human dashboard.  
Use `docs/program/backlog.csv` as the task-level source of truth for status, dependencies, owners, and branch names.

Legend: `not_started` | `in_progress` | `blocked` | `pr_open` | `merged`

## Merged baseline history

| Baseline scope | Status | Notes |
|---|---|---|
| Waves 1 through 4 | merged/completed | Backfilled as merged baseline history. |
| Repo cleanup program | merged/completed | Backfilled as merged baseline history. |
| Legacy decommission program | merged/completed | Backfilled as merged baseline history. |

## Active completion tracks

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | merged | 5A-doc-control | `DOC-01` through `DOC-06` are `merged` in `backlog.csv`; Documentation Control track is complete. |
| ARC | Runtime Decomposition | not_started | 5B-runtime-decomposition | All ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | All CAP tasks are `not_started` in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | pr_open | 5D-observability | `OBS-02` and `OBS-03` are `pr_open` in `backlog.csv`; remaining OBS tasks are `not_started`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| OBS-02 | `codex/feat/obs-02-emit-turn-declaration-and-action-resolution-traces` | observability_b | pr_open | Turn declaration/action trace emission and deterministic trace-order coverage tests are implemented and under review. |
| OBS-03 | `codex/feat/obs-03-emit-actor-state-delta-and-effect-lifecycle-traces` | observability_c | pr_open | Actor before/after state-delta and effect lifecycle transition trace builders are implemented with no-op suppression coverage. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| OBS-02 | [#109](https://github.com/rputnam0/dnd_sim/pull/109) | observability_b | pending | Emits declaration validation, action selection, action resolution, and action outcome traces per turn. |
| OBS-03 | [#129](https://github.com/rputnam0/dnd_sim/pull/129) | observability_c | pending | Emits actor state delta payloads and effect lifecycle transition traces for apply/tick/refresh/expire/concentration break. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; active branch and open PR queues are cleared.
- `OBS-03` is in PR review and depends on `OBS-01` and `ARC-05` per `backlog.csv`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
