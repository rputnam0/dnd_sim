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

## Completion Summary

Wave 5 tracks are merged to `main` and no open integration PRs remain.

Merged integration PR chain:

- Documentation Control: [#92](https://github.com/rputnam0/dnd_sim/pull/92)
- Runtime Decomposition: [#152](https://github.com/rputnam0/dnd_sim/pull/152)
- Capability Manifest: [#154](https://github.com/rputnam0/dnd_sim/pull/154)
- Replay, Logging, and Observability: [#155](https://github.com/rputnam0/dnd_sim/pull/155)
- Persistence and Query Model: [#156](https://github.com/rputnam0/dnd_sim/pull/156)
- Tactical AI Hardening: [#159](https://github.com/rputnam0/dnd_sim/pull/159)
- World Systems and Campaign Platform: [#158](https://github.com/rputnam0/dnd_sim/pull/158)
- Rules Closure: [#157](https://github.com/rputnam0/dnd_sim/pull/157)
- Completion Gates: [#160](https://github.com/rputnam0/dnd_sim/pull/160)

## Active completion tracks

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | merged | 5A-doc-control | Track complete and merged to `main`. |
| ARC | Runtime Decomposition | merged | 5B-runtime-decomposition | Track complete and merged to `main`. |
| CAP | Capability Manifest | merged | 5C-capability-manifest | Track complete and merged to `main`. |
| OBS | Replay, Logging, and Observability | merged | 5D-observability | Track complete and merged to `main`. |
| DBS | Persistence and Query Model | merged | 5E-persistence | Track complete and merged to `main`. |
| AI | Tactical AI Hardening | merged | 5F-ai-hardening | Track complete and merged to `main`. |
| FIX | Rules Closure | merged | 5G-rules-closure | Track complete and merged to `main`. |
| WLD | World Systems and Campaign Platform | merged | 5H-world-systems | Track complete and merged to `main`. |
| FIN | Completion Gates | merged | 5I-completion-gates | Track complete and merged to `main`. |

## Active branches

No active task branches remain.

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|

## Open PRs

No open PRs remain.

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active blockers remain in `backlog.csv`; all Wave 5 tracks are in `merged` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
