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
- Subsequent continuation merges including [#221](https://github.com/rputnam0/dnd_sim/pull/221), [#224](https://github.com/rputnam0/dnd_sim/pull/224), [#225](https://github.com/rputnam0/dnd_sim/pull/225), [#226](https://github.com/rputnam0/dnd_sim/pull/226), [#227](https://github.com/rputnam0/dnd_sim/pull/227), BATCH-00 [#228](https://github.com/rputnam0/dnd_sim/pull/228), G1-B [#231](https://github.com/rputnam0/dnd_sim/pull/231), and J2-B [#236](https://github.com/rputnam0/dnd_sim/pull/236) reduced the integration baseline to 79 blocked shipped-2014 records; the current J2-C branch-local conversions reduce that to 59 blocked records in this worktree.
- `docs/program/parity_batch_registry.csv` is the exact current execution map for the remaining blockers on this branch: 49 `spell` records with `missing_runtime_mechanics` and 10 `trait` records with `missing_runtime_hook_family`.
- Current open PRs targeting `codex/int/w6-parity-closeout` are G1-C [#237](https://github.com/rputnam0/dnd_sim/pull/237), J1-C [#238](https://github.com/rputnam0/dnd_sim/pull/238), J1-D [#239](https://github.com/rputnam0/dnd_sim/pull/239), J2-C [#240](https://github.com/rputnam0/dnd_sim/pull/240), J2-E [#241](https://github.com/rputnam0/dnd_sim/pull/241), and J2-D [#242](https://github.com/rputnam0/dnd_sim/pull/242).
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
| PAR | Wave 6 Capability Parity Closure | in_progress | 6c-parity | W6-PAR-01/02/03/04 are merged; the live strict backlog on this branch is 59 blockers, and `docs/program/parity_batch_registry.csv` is the execution map for the remaining J1/J2/G1 lanes. |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| W6-PAR-05 | codex/feat/w6-par-05-strict-parity-closure | remediation_parity | in_progress | Umbrella row for the remaining Wave 6 strict-parity closeout. The live baseline on this branch is 59 blocked records, and `docs/program/parity_batch_registry.csv` is the exact current execution map. |
| W6-PAR-05G | codex/feat/w6-par-05g-trait-hooks-e | remediation_parity | in_progress | Runtime-touching trait umbrella now has 10 remaining blocked G1 trait records on this branch, all carried by the open G1-C lane. |
| W6-PAR-05G1 | codex/feat/w6-par-05g1-trait-reaction-retaliation | remediation_parity | in_progress | Remaining live reaction and retaliation trait work is tracked in `docs/program/parity_batch_registry.csv`; PR #237 carries the final 10 blocked G1 traits on this branch. |
| G1-C | codex/feat/g1-c-trait-reaction-retaliation | remediation_parity | pr_open | Open PR for the remaining 10-item G1 trait lane from `docs/program/parity_batch_registry.csv`. |
| W6-PAR-05J | codex/feat/w6-par-05j-spell-mechanics-e | remediation_parity | in_progress | Remaining live spell mechanics work is batched via `docs/program/parity_batch_registry.csv`; 49 blocked spell records remain on this branch across the open J1-C, J1-D, J2-C, J2-D, and J2-E lanes plus queued J2-F. |
| W6-PAR-05J1 | codex/feat/w6-par-05j1-spell-summon-command-control | remediation_parity | in_progress | J1 now owns 19 remaining summon, conjure, command, and control spell blockers, carried by open PRs #238 and #239. |
| J1-C | codex/feat/j1-c-summon-conjure-command-control | remediation_parity | pr_open | Open PR for the third 10-item J1 spell lane from `docs/program/parity_batch_registry.csv`. |
| J1-D | codex/feat/j1-d-summon-conjure-command-control | remediation_parity | pr_open | Open PR for the final 9-item J1 spell lane from `docs/program/parity_batch_registry.csv`. |
| W6-PAR-05J2 | codex/feat/w6-par-05j2-spell-hazard-zone-utility | remediation_parity | in_progress | J2 now owns 30 remaining blocked hazard, zone, darkness, and utility spell records on this branch after the local J2-C conversions, with open PRs #240, #241, and #242 carrying the active lanes ahead of queued J2-F. |
| J2-C | codex/feat/j2-c-spell-hazard-zone-utility | remediation_parity | pr_open | Open PR for the third 10-item J2 spell lane; this branch converts all owned J2-C rows to supported canonical mechanics. |
| J2-D | codex/feat/j2-d-spell-hazard-zone-utility | remediation_parity | pr_open | Open PR for the fourth 10-item J2 spell lane from `docs/program/parity_batch_registry.csv`. |
| J2-E | codex/feat/j2-e-spell-hazard-zone-utility | remediation_parity | pr_open | Open PR for the fifth 10-item J2 spell lane from `docs/program/parity_batch_registry.csv`. |

## Queued execution batches

| Batch ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| J2-F | codex/feat/j2-f-spell-hazard-zone-utility | remediation_parity | not_started | Queued final 10-item J2 spell batch after the currently open J2-C through J2-E lanes. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| G1-C | [#237](https://github.com/rputnam0/dnd_sim/pull/237) | remediation_parity | leaf tests green; strict red globally | Open PR for the remaining 10-item G1 reaction and retaliation slice on this branch. |
| J1-C | [#238](https://github.com/rputnam0/dnd_sim/pull/238) | remediation_parity | leaf tests green; strict red globally | Open PR for the third J1 summon, conjure, command, and control spell slice. |
| J1-D | [#239](https://github.com/rputnam0/dnd_sim/pull/239) | remediation_parity | leaf tests green; strict red globally | Open PR for the final J1 summon, conjure, command, and control spell slice. |
| J2-C | [#240](https://github.com/rputnam0/dnd_sim/pull/240) | remediation_parity | leaf tests green; strict red globally | Open PR for the third J2 hazard, zone, darkness, and utility spell slice. |
| J2-E | [#241](https://github.com/rputnam0/dnd_sim/pull/241) | remediation_parity | leaf tests green; strict red globally | Open PR for the fifth J2 hazard, zone, darkness, and utility spell slice. |
| J2-D | [#242](https://github.com/rputnam0/dnd_sim/pull/242) | remediation_parity | leaf tests green; strict red globally | Open PR for the fourth J2 hazard, zone, darkness, and utility spell slice. |

Draft carryovers [#220](https://github.com/rputnam0/dnd_sim/pull/220) and [#222](https://github.com/rputnam0/dnd_sim/pull/222) remain closed and excluded from live execution.

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- Wave 6 CUT, UNI, and GATE dependencies are satisfied and merged on `main`; PAR continuation remains active under W6-PAR-05 and is now executed through the live J1/J2/G1 batch rows on `codex/int/w6-parity-closeout`.
- Strict FIN-02 at this sync point reports 59 blocked shipped records: 49 `spell` records and 10 `trait` records.
- Remaining strict unsupported-reason families are 49 `missing_runtime_mechanics` and 10 `missing_runtime_hook_family`.
- Live batch ownership remains tracked in `docs/program/parity_batch_registry.csv`; active review lanes are G1-C, J1-C, J1-D, J2-C, J2-D, and J2-E, with J2-F still queued.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
