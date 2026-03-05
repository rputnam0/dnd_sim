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

- Hard-cut track `int/6a-hard-cut` merged to `main` via [#179](https://github.com/rputnam0/dnd_sim/pull/179) after task PRs W6-CUT-01 [#167](https://github.com/rputnam0/dnd_sim/pull/167), W6-CUT-02 [#169](https://github.com/rputnam0/dnd_sim/pull/169), W6-CUT-03 [#162](https://github.com/rputnam0/dnd_sim/pull/162), and W6-CUT-04 [#165](https://github.com/rputnam0/dnd_sim/pull/165).
- Unification track `int/6b-unification` merged to `main` via [#180](https://github.com/rputnam0/dnd_sim/pull/180) after task PRs W6-UNI-01 [#166](https://github.com/rputnam0/dnd_sim/pull/166), W6-UNI-02 [#170](https://github.com/rputnam0/dnd_sim/pull/170), W6-UNI-03 [#164](https://github.com/rputnam0/dnd_sim/pull/164), and W6-UNI-04 [#163](https://github.com/rputnam0/dnd_sim/pull/163).
- Parity track `int/6c-parity` merged to `main` via [#181](https://github.com/rputnam0/dnd_sim/pull/181) after W6-PAR-01 [#168](https://github.com/rputnam0/dnd_sim/pull/168), W6-PAR-02 [#173](https://github.com/rputnam0/dnd_sim/pull/173), and W6-PAR-03 shard PRs [#171](https://github.com/rputnam0/dnd_sim/pull/171), [#174](https://github.com/rputnam0/dnd_sim/pull/174), [#175](https://github.com/rputnam0/dnd_sim/pull/175), [#176](https://github.com/rputnam0/dnd_sim/pull/176), [#177](https://github.com/rputnam0/dnd_sim/pull/177), [#178](https://github.com/rputnam0/dnd_sim/pull/178).
- Gate track `int/6d-gates` merged to `main` via [#182](https://github.com/rputnam0/dnd_sim/pull/182) and final closeout W6-GATE-02 merged via [#183](https://github.com/rputnam0/dnd_sim/pull/183).

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
| CUT | Wave 6 Hard-Cut Remediation | merged | 6a-hard-cut | W6-CUT-01/02/03/04 merged and track integrated to `main` via #179. |
| UNI | Wave 6 API Unification | merged | 6b-unification | W6-UNI-01/02/03/04 merged and track integrated to `main` via #180. |
| PAR | Wave 6 Capability Parity Closure | merged | 6c-parity | W6-PAR-01, W6-PAR-02, and W6-PAR-03 shard batch merged and integrated via #181. |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |

## Active branches

No backlog tasks are currently marked `in_progress`.

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|

## Open PRs

No backlog tasks are currently marked `pr_open`.

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- Wave 6 dependencies are fully satisfied and merged on `main` for CUT, UNI, PAR, and GATE tracks.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
