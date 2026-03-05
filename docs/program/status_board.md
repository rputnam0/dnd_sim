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
| ARC | Runtime Decomposition | in_progress | 5B-runtime-decomposition | `ARC-01`, `ARC-02`, `ARC-03`, `ARC-04`, `ARC-05`, `ARC-06`, and `ARC-08` are `in_progress`; `ARC-07` is `pr_open`; remaining ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | in_progress | 5C-capability-manifest | `CAP-03`, `CAP-04`, and `CAP-05` are `in_progress` in `backlog.csv`; remaining CAP tasks are `not_started`. |
| OBS | Replay, Logging, and Observability | in_progress | 5D-observability | `OBS-02` is `in_progress` in `backlog.csv`; remaining OBS tasks are `not_started`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | pr_open | 5F-ai-hardening | `AI-01` is `pr_open`; remaining AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| AI-01 | `codex/feat/ai-01-normalize-candidate-action-enumeration-and-scoring` | ai_core | pr_open | Introduces `src/dnd_sim/ai/scoring.py` candidate enumeration with normalized scoring inputs and routes optimal strategy selection through legal candidate snapshots. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| AI-01 | `pending` | ai_core | pending | PR opening from `codex/feat/ai-01-normalize-candidate-action-enumeration-and-scoring` to `int/5f-ai-hardening`; replace with PR link after creation. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; AI-01 is in PR review state and other queues remain unchanged.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
