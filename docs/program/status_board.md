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
| ARC | Runtime Decomposition | in_progress | 5B-runtime-decomposition | `ARC-01`, `ARC-02`, `ARC-03`, and `ARC-04` are `in_progress`; remaining ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | All CAP tasks are `not_started` in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | All OBS tasks are `not_started` in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| ARC-01 | `codex/feat/arc-01-extract-simulation-session-and-turn-loop-orchestra` | runtime_a | in_progress | Extracting session setup, initiative loop, and round progression into `src/dnd_sim/engine_runtime.py` with `engine.py` facade retained. |
| ARC-02 | `codex/feat/arc-02-extract-turn-declaration-validation-and-legal-acti` | runtime_b | in_progress | Extracting turn declaration validation and action-legality checks into `src/dnd_sim/action_legality.py` and routing engine/strategy validation through it. |
| ARC-03 | `codex/feat/arc-03-extract-movement-routing-and-spatial-legality-serv` | runtime_c | in_progress | Extracting movement budget/routing/spatial legality helpers into `src/dnd_sim/movement_runtime.py` and delegating movement internals from `engine.py`. |
| ARC-04 | `codex/feat/arc-04-extract-action-resolution-pipeline` | runtime_d | in_progress | Extracting action dispatch/target application/hit-save handling into `src/dnd_sim/action_resolution.py` and routing `engine.py` combat execution through the new module. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; ARC-01, ARC-02, ARC-03, and ARC-04 runtime decomposition work is currently in progress on assigned branches.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
