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
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | in_progress | 5I-completion-gates | `FIN-01`, `FIN-02`, `FIN-03`, and `FIN-04` are `in_progress`; `FIN-06` prep is active; remaining FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| FIN-01 | codex/feat/fin-01-enforce-program-doc-sync-gate-and-purge-stale-live | integration_doc_gate | in_progress | Enforcing docs sync gate and stale-live-doc purge checks before completion gates proceed. |
| FIN-02 | codex/feat/fin-02-enforce-full-capability-manifest-green-gate-for-sh | integration_content_gate | in_progress | Enforcing capability-manifest completion gate for shipped 2014 scope with manifest completeness and support-state coverage checks. |
| FIN-03 | codex/feat/fin-03-enforce-deterministic-replay-corpus-gate-across-co | integration_replay_gate | in_progress | Enforcing deterministic replay corpus gate for combat and world scenarios with unapproved drift detection. |
| FIN-04 | codex/feat/fin-04-enforce-integrated-campaign-world-and-combat-scena | integration_world_gate | in_progress | Enforcing integrated campaign/world/combat scenario gate with artifact-backed full-flow integration tests. |
| FIN-06 | codex/feat/fin-06-cut-release-baseline-archive-prior-program-artifac | release_lead | in_progress | FIN-06 release baseline cutover preparation and completion-closeout updates are in progress. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; Track 5A dependencies are fully merged.
- `FIN-01` is active to enforce doc sync gating and stale-live-doc absence before downstream FIN tasks.
- `FIN-02` is active and depends on `CAP-06`, `FIX-07`, and `WLD-11` per `backlog.csv`.
- `FIN-03` is active and depends on `OBS-07` and `WLD-12` per `backlog.csv`.
- `FIN-04` is active and depends on `WLD-09`, `WLD-10`, `WLD-12`, and `DBS-06` per `backlog.csv`.
- `FIN-06` is active for release-baseline cutover and final archive/status synchronization.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
