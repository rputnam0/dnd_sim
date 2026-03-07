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
- Subsequent continuation merges including [#221](https://github.com/rputnam0/dnd_sim/pull/221), [#225](https://github.com/rputnam0/dnd_sim/pull/225), [#226](https://github.com/rputnam0/dnd_sim/pull/226), [#224](https://github.com/rputnam0/dnd_sim/pull/224), [#227](https://github.com/rputnam0/dnd_sim/pull/227), BATCH-00 [#228](https://github.com/rputnam0/dnd_sim/pull/228), G1-B [#231](https://github.com/rputnam0/dnd_sim/pull/231), and open G1-D [#233](https://github.com/rputnam0/dnd_sim/pull/233) reduced the live strict backlog on this branch to 60 blocked shipped-2014 records.
- `docs/program/parity_batch_registry.csv` is the exact current execution map for the remaining blockers: 50 `spell` records with `missing_runtime_mechanics` and 10 `trait` records with `missing_runtime_hook_family`.
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
| PAR | Wave 6 Capability Parity Closure | in_progress | 6c-parity | W6-PAR-01/02/03/04 are merged; the live strict backlog on this branch is 60 blockers, and `docs/program/parity_batch_registry.csv` is the execution map for the remaining J1/J2/G1 lanes. |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| W6-PAR-05 | codex/feat/w6-par-05-strict-parity-closure | remediation_parity | in_progress | Umbrella row for the remaining Wave 6 strict-parity closeout. The live baseline on this branch is 60 blocked records, and `docs/program/parity_batch_registry.csv` is the exact current execution map. |
| W6-PAR-05G | codex/feat/w6-par-05g-trait-hooks-e | remediation_parity | in_progress | Runtime-touching trait umbrella remains active only for G1. The remaining live trait blockers are batched as G1-A, G1-C, and G1-D after G1-B merged; draft carryovers #220/#222 remain superseded. |
| W6-PAR-05G1 | codex/feat/w6-par-05g1-trait-reaction-retaliation | remediation_parity | in_progress | Remaining live reaction and retaliation trait work is tracked in `docs/program/parity_batch_registry.csv`; 10 blocked traits remain on this branch. |
| G1-A | codex/feat/g1-a-trait-reaction-retaliation | remediation_parity | in_progress | Active 10-item trait lane for the first remaining G1 slice from `docs/program/parity_batch_registry.csv`. |
| G1-C | codex/feat/g1-c-trait-reaction-retaliation | remediation_parity | in_progress | Active 10-item trait lane for the third remaining G1 slice after G1-B merged. |
| G1-D | codex/feat/g1-d-trait-reaction-retaliation | remediation_parity | pr_open | Open PR for the final 8-item trait lane; this branch reduces the live trait blocker count from 28 to 20. |
| W6-PAR-05J | codex/feat/w6-par-05j-spell-mechanics-e | remediation_parity | in_progress | Remaining live spell mechanics work is batched via `docs/program/parity_batch_registry.csv`; 50 blocked spell records remain on this branch after the in-progress J1-D lane closes its owned 9-item slice. |
| W6-PAR-05J1 | codex/feat/w6-par-05j1-spell-summon-command-control | remediation_parity | in_progress | J1 now owns 20 remaining summon, conjure, command, and control spell blockers on this branch, with J1-B and J1-D as the active lanes. |
| J1-B | codex/feat/j1-b-summon-conjure-command-control | remediation_parity | in_progress | Active 10-item spell lane for the current J1-B slice from `docs/program/parity_batch_registry.csv`. |
| J1-D | codex/feat/j1-d-summon-conjure-command-control | remediation_parity | in_progress | Active final 9-item spell lane for the current J1-D slice from `docs/program/parity_batch_registry.csv`. |
| W6-PAR-05J2 | codex/feat/w6-par-05j2-spell-hazard-zone-utility | remediation_parity | in_progress | J2 now owns 50 remaining hazard, zone, darkness, and utility spell blockers, with J2-B as the current active lane. |
| J2-B | codex/feat/j2-b-spell-hazard-zone-utility | remediation_parity | in_progress | Active 10-item spell lane for the current J2-B slice from `docs/program/parity_batch_registry.csv`. |

## Queued execution batches

| Batch ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| J1-C | codex/feat/j1-c-summon-conjure-command-control | remediation_parity | not_started | Queued third 10-item J1 spell batch. |
| J2-C | codex/feat/j2-c-spell-hazard-zone-utility | remediation_parity | not_started | Queued third 10-item J2 spell batch. |
| J2-D | codex/feat/j2-d-spell-hazard-zone-utility | remediation_parity | not_started | Queued fourth 10-item J2 spell batch. |
| J2-E | codex/feat/j2-e-spell-hazard-zone-utility | remediation_parity | not_started | Queued fifth 10-item J2 spell batch. |
| J2-F | codex/feat/j2-f-spell-hazard-zone-utility | remediation_parity | not_started | Queued final 10-item J2 spell batch. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| G1-D | [#233](https://github.com/rputnam0/dnd_sim/pull/233) | remediation_parity | leaf tests green; strict red globally | Batch-scoped review lane for the final 8-item G1 reaction and retaliation slice. |

Draft carryovers [#220](https://github.com/rputnam0/dnd_sim/pull/220) and [#222](https://github.com/rputnam0/dnd_sim/pull/222) remain closed and excluded from live execution.

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- Wave 6 CUT, UNI, and GATE dependencies are satisfied and merged on `main`; PAR continuation remains active under W6-PAR-05 and is now executed through the live J1/J2/G1 batch rows on `codex/int/w6-parity-closeout`.
- Strict FIN-02 at this sync point reports 60 blocked shipped records: 50 `spell` records and 10 `trait` records.
- Remaining strict unsupported-reason families are 50 `missing_runtime_mechanics` and 10 `missing_runtime_hook_family`.
- Live batch ownership remains tracked in `docs/program/parity_batch_registry.csv`; active lanes are G1-A, G1-C, J1-B, J1-D, and J2-B, with G1-D under review in PR #233.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
