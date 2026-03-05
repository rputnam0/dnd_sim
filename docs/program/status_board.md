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

Wave 5 baseline remains merged to `main`.

Wave 6 remediation state:

- Hard-cut track `int/6a-hard-cut` has merged W6-CUT-01 [#167](https://github.com/rputnam0/dnd_sim/pull/167), W6-CUT-03 [#162](https://github.com/rputnam0/dnd_sim/pull/162), and W6-CUT-04 [#165](https://github.com/rputnam0/dnd_sim/pull/165).
- Unification track `int/6b-unification` has merged W6-UNI-01 [#166](https://github.com/rputnam0/dnd_sim/pull/166), W6-UNI-03 [#164](https://github.com/rputnam0/dnd_sim/pull/164), and W6-UNI-04 [#163](https://github.com/rputnam0/dnd_sim/pull/163).
- Gate track `int/6d-gates` currently has W6-GATE-01 in progress for docs truth sync.

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
| CUT | Wave 6 Hard-Cut Remediation | merged | 6a-hard-cut | W6-CUT-01, W6-CUT-03, and W6-CUT-04 merged to `int/6a-hard-cut`. |
| UNI | Wave 6 API Unification | merged | 6b-unification | W6-UNI-01, W6-UNI-03, and W6-UNI-04 merged to `int/6b-unification`. |
| GATE | Wave 6 Gate Truth Sync | in_progress | 6d-gates | W6-GATE-01 is active on `codex/feat/w6-gate-01-doc-truth-sync`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| W6-GATE-01 | codex/feat/w6-gate-01-doc-truth-sync | program_control | in_progress | Sync docs/backlog/checklist truth for current Wave 6 state and clean stale maintenance waivers. |

## Open PRs

No backlog tasks are currently marked `pr_open`.

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- W6-GATE-01 depends on merged CUT and UNI remediation tasks (W6-CUT-01/03/04 and W6-UNI-01/03/04).
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
