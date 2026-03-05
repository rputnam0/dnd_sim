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
| DBS | Persistence and Query Model | in_progress | 5E-persistence | `DBS-01` and `DBS-02` are `pr_open`; `DBS-04` and `DBS-05` are `in_progress`; remaining DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| DBS-01 | `codex/feat/dbs-01-add-canonical-metadata-tables-for-content-and-supp` | persistence_a | pr_open | Canonical metadata tables and migration/rollback coverage are in PR review. |
| DBS-02 | `codex/feat/dbs-02-add-schema-version-source-lineage-and-content-hash` | persistence_b | pr_open | Lineage columns plus stable source/canonicalization hash persistence and replay ordering are in PR review. |
| DBS-04 | `codex/feat/dbs-04-add-campaign-state-persistence-schema-and-round-tr` | persistence_campaign | in_progress | Implementing `campaign_states` and `encounter_states` deterministic persistence with round-trip/compatibility/corruption tests in `tests/test_campaign_persistence.py`. |
| DBS-05 | `codex/feat/dbs-05-add-world-flags-objectives-factions-and-encounter` | persistence_world | in_progress | Implementing `world_states` and `faction_states` deterministic persistence with world/objective/faction lifecycle tests in `tests/test_world_state_persistence.py`. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| DBS-01 | [#98](https://github.com/rputnam0/dnd_sim/pull/98) | persistence_a | pending | DBS-01 metadata schema and migration/rollback checks are under review. |
| DBS-02 | [#102](https://github.com/rputnam0/dnd_sim/pull/102) | persistence_b | pending | DBS-02 lineage fields and hash stability checks are under review. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; DBS-01 and DBS-02 remain in PR review while DBS-04 and DBS-05 persistence schema work is in progress on assigned branches.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
