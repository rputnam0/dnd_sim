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
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | in_progress | 5H-world-systems | `WLD-01`, `WLD-02`, and `WLD-03` are `in_progress`; remaining WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| WLD-01 | codex/feat/wld-01-build-ability-check-contest-passive-and-dc-resolut | world_rules_a | in_progress | Implementing deterministic noncombat ability checks, contests, passive checks, and DC evaluation core. |
| WLD-02 | codex/feat/wld-02-build-skill-tool-proficiency-and-specialist-data-p | world_rules_b | in_progress | Plumbing skill/tool proficiency, expertise, and passive input data for deterministic noncombat resolution. |
| WLD-03 | codex/feat/wld-03-build-exploration-turn-structure-time-advancement | world_explore_a | in_progress | Implementing exploration turn structure, calendar/time advancement, and light tracking with runtime + persistence serialization tests. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; active branch and open PR queues are cleared.
- `WLD-01` is active and depends on `ARC-02` per `backlog.csv`.
- `WLD-02` is active and depends on `WLD-01` per `backlog.csv`.
- `WLD-03` is active and depends on `DBS-04` per `backlog.csv`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
