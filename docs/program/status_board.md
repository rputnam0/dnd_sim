# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-06  
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
- Parity continuation wave W6-PAR-04 merged via [#185](https://github.com/rputnam0/dnd_sim/pull/185), [#186](https://github.com/rputnam0/dnd_sim/pull/186), [#187](https://github.com/rputnam0/dnd_sim/pull/187), [#188](https://github.com/rputnam0/dnd_sim/pull/188), [#189](https://github.com/rputnam0/dnd_sim/pull/189), and [#190](https://github.com/rputnam0/dnd_sim/pull/190), reducing strict blockers but not yet reaching blocked=0.
- Post-merge parity continuation work through [#193](https://github.com/rputnam0/dnd_sim/pull/193), [#194](https://github.com/rputnam0/dnd_sim/pull/194), [#195](https://github.com/rputnam0/dnd_sim/pull/195), [#196](https://github.com/rputnam0/dnd_sim/pull/196), [#197](https://github.com/rputnam0/dnd_sim/pull/197), [#198](https://github.com/rputnam0/dnd_sim/pull/198), [#199](https://github.com/rputnam0/dnd_sim/pull/199), and the integration merge [#200](https://github.com/rputnam0/dnd_sim/pull/200) reduced strict blockers to the Wave 6 continuation baseline before the dedicated parity-closeout branch was created.
- W6-PAR-05A1 merged to `codex/int/w6-parity-closeout` via [#201](https://github.com/rputnam0/dnd_sim/pull/201), reconciling the live parity surfaces, adding `docs/program/parity_leaf_registry.csv`, and expanding W6-PAR-05 execution into explicit leaf tasks while keeping W6-PAR-05B through W6-PAR-05L as umbrella rows.
- Subsequent continuation merges including [#221](https://github.com/rputnam0/dnd_sim/pull/221), [#225](https://github.com/rputnam0/dnd_sim/pull/225), [#226](https://github.com/rputnam0/dnd_sim/pull/226), [#224](https://github.com/rputnam0/dnd_sim/pull/224), [#227](https://github.com/rputnam0/dnd_sim/pull/227), BATCH-00 [#228](https://github.com/rputnam0/dnd_sim/pull/228), G1-B [#231](https://github.com/rputnam0/dnd_sim/pull/231), and open G1-D [#233](https://github.com/rputnam0/dnd_sim/pull/233), plus the in-flight J2-D batch implementation on this branch, reduce the current generated strict backlog to 59 blocked shipped-2014 records.
- `docs/program/parity_batch_registry.csv` is the exact current execution map for the remaining blockers in this branch state: 49 `spell` records with `missing_runtime_mechanics` and 10 `trait` records with `missing_runtime_hook_family`.
- At the moment this support branch was created there were no open PRs targeting `codex/int/w6-parity-closeout`; the active implementation lanes were G1-A, G1-C, G1-D, J1-B, and J2-B.
- Draft carryovers [#220](https://github.com/rputnam0/dnd_sim/pull/220) and [#222](https://github.com/rputnam0/dnd_sim/pull/222) remain closed and are superseded by the current G1 batch plan.

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
| PAR | Wave 6 Capability Parity Closure | merged | 6c-parity | W6-PAR-01 through W6-PAR-05M are now merged on `codex/int/w6-parity-closeout`; strict FIN-02 is green with blocked=0 and the branch is ready to merge to `main`. |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|

## Queued execution batches

| Batch ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

Draft carryovers [#220](https://github.com/rputnam0/dnd_sim/pull/220) and [#222](https://github.com/rputnam0/dnd_sim/pull/222) remain closed and excluded from live execution.

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- Wave 6 CUT, UNI, and GATE dependencies are satisfied and merged on `main`; PAR continuation remains active under W6-PAR-05 and is now executed through the live J1/J2/G1 batch rows on `codex/int/w6-parity-closeout`.
- Strict FIN-02 is now fully green on `codex/int/w6-parity-closeout` with 0 blocked shipped records.
- No strict unsupported-reason families remain.
- `docs/program/parity_batch_registry.csv` is now the historical execution map for the fully merged parity closeout wave.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
