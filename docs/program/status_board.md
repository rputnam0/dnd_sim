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
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | All OBS tasks are `not_started` in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | pr_open | 5F-ai-hardening | `AI-01`, `AI-02`, `AI-03`, and `AI-04` are `pr_open` in `backlog.csv`; remaining AI tasks are `not_started`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| AI-01 | `codex/feat/ai-01-normalize-candidate-action-enumeration-and-scoring` | ai_core | pr_open | Introduces `src/dnd_sim/ai/scoring.py` candidate enumeration with normalized scoring inputs and routes optimal strategy selection through legal candidate snapshots. |
| AI-03 | `codex/feat/ai-03-implement-concentration-breaking-control-value-and` | ai_control | pr_open | Concentration-break, condition-application, and enemy action-denial scoring components are in PR review for AI-03. |
| AI-04 | `codex/feat/ai-04-implement-retreat-survival-objective-race-and-focu` | ai_objective | pr_open | Retreat/survival, objective-race urgency, ally-rescue valuation, and focus-fire tradeoff scoring are implemented and under review. |
| AI-02 | `codex/feat/ai-02-implement-hazard-geometry-cover-and-line-of-effect` | ai_spatial | pr_open | Implements hazard/geometry/cover/line-of-effect candidate scoring in `src/dnd_sim/ai/scoring.py` with path risk support in `src/dnd_sim/spatial.py` and dedicated tests. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| AI-01 | [#116](https://github.com/rputnam0/dnd_sim/pull/116) | ai_core | pending | Normalized candidate enumeration and scoring inputs are under review for merge into `int/5f-ai-hardening`. |
| AI-03 | [#122](https://github.com/rputnam0/dnd_sim/pull/122) | ai_control | pending | Adds concentration-break, control-value, condition-application, and enemy action-denial scoring with focused deterministic tests. |
| AI-04 | [#119](https://github.com/rputnam0/dnd_sim/pull/119) | ai_objective | pending | Adds survival-threshold, retreat timing, objective-race, ally-rescue, and focus-fire tradeoff scoring snapshots for legal candidates. |
| AI-02 | [#120](https://github.com/rputnam0/dnd_sim/pull/120) | ai_spatial | pending | Hazard/geometry/cover/line-of-effect scoring and route hazard exposure are under review for merge into `int/5f-ai-hardening`. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; AI-01, AI-02, AI-03, and AI-04 are in PR review while remaining queues are unchanged.
- `AI-03` is in PR review and depends on `AI-01` and `ARC-05` per `backlog.csv`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
