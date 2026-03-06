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
- Post-merge parity continuation work through [#193](https://github.com/rputnam0/dnd_sim/pull/193), [#194](https://github.com/rputnam0/dnd_sim/pull/194), [#195](https://github.com/rputnam0/dnd_sim/pull/195), [#196](https://github.com/rputnam0/dnd_sim/pull/196), [#197](https://github.com/rputnam0/dnd_sim/pull/197), [#198](https://github.com/rputnam0/dnd_sim/pull/198), [#199](https://github.com/rputnam0/dnd_sim/pull/199), and the integration merge [#200](https://github.com/rputnam0/dnd_sim/pull/200) reduced strict blockers to the current generated baseline: 1225 blocked shipped records.
- W6-PAR-05A1 merged to `codex/int/w6-parity-closeout` via [#201](https://github.com/rputnam0/dnd_sim/pull/201), reconciling the live parity surfaces to the 1225-blocker baseline, adding `docs/program/parity_leaf_registry.csv`, and expanding W6-PAR-05 execution into explicit leaf tasks while keeping W6-PAR-05B through W6-PAR-05L as umbrella rows.
- Batch 1 leaf execution is active on `codex/int/w6-parity-closeout`: W6-PAR-05B1, W6-PAR-05C1, W6-PAR-05D1, W6-PAR-05E1, W6-PAR-05L1, and W6-PAR-05L2 each own a dedicated worktree, branch, and pending PR lane.

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
| PAR | Wave 6 Capability Parity Closure | in_progress | 6c-parity | W6-PAR-01/02/03/04 merged; W6-PAR-05 now tracks child leaf execution on `codex/int/w6-parity-closeout` with `docs/program/parity_leaf_registry.csv` as the exact blocker-to-leaf map (strict blockers: 1225). |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| W6-PAR-05 | codex/feat/w6-par-05-strict-parity-closure | remediation_parity | in_progress | Umbrella tracking row for W6-PAR-05A through W6-PAR-05M and their executable leaf tasks on `codex/int/w6-parity-closeout`. |
| W6-PAR-05B | codex/feat/w6-par-05b-background-hooks-c | remediation_parity | in_progress | Umbrella row for the background meta closeout leaves; no direct PR opens on this row. |
| W6-PAR-05B1 | codex/feat/w6-par-05b1-background-meta-closeout | remediation_parity | in_progress | Batch 1 leaf is active in its dedicated worktree and owns all remaining background meta blockers from `docs/program/parity_leaf_registry.csv`. |
| W6-PAR-05C | codex/feat/w6-par-05c-species-hooks-c | remediation_parity | in_progress | Umbrella row for passive/meta species leaves; execution happens through child leaf tasks only. |
| W6-PAR-05C1 | codex/feat/w6-par-05c1-species-meta-closeout | remediation_parity | in_progress | Batch 1 leaf is active in its dedicated worktree and owns the passive/meta species closeout records. |
| W6-PAR-05D | codex/feat/w6-par-05d-species-hooks-d | remediation_parity | in_progress | Umbrella row for active/effect species leaves; execution happens through child leaf tasks only. |
| W6-PAR-05D1 | codex/feat/w6-par-05d1-species-active-effects | remediation_parity | in_progress | Batch 1 leaf is active in its dedicated worktree and owns the active/effect species closeout records. |
| W6-PAR-05E | codex/feat/w6-par-05e-trait-hooks-c | remediation_parity | in_progress | Umbrella row for trait meta leaves; execution happens through child leaf tasks only. |
| W6-PAR-05E1 | codex/feat/w6-par-05e1-trait-meta-options | remediation_parity | in_progress | Batch 1 leaf is active in its dedicated worktree and owns the trait meta options/proficiencies records. |
| W6-PAR-05F | codex/feat/w6-par-05f-trait-hooks-d | remediation_parity | in_progress | Umbrella row for passive combat trait leaves; execution happens through child leaf tasks only. |
| W6-PAR-05G | codex/feat/w6-par-05g-trait-hooks-e | remediation_parity | in_progress | Umbrella row for reaction/resource trait leaves; execution happens through child leaf tasks only. |
| W6-PAR-05G1A | codex/feat/w6-par-05g1a-reaction-defense-continuation | remediation_parity | in_progress | Fresh continuation branch packages the isolated six-trait G1 slice from current integration with regenerated parity artifacts and no stale generated-file merges. |
| W6-PAR-05H | codex/feat/w6-par-05h-trait-hooks-f | remediation_parity | in_progress | Umbrella row for summon/transform trait leaves; execution happens through child leaf tasks only. |
| W6-PAR-05I | codex/feat/w6-par-05i-spell-mechanics-d | remediation_parity | in_progress | Umbrella row for spell mechanics damage/support leaves; execution happens through child leaf tasks only. |
| W6-PAR-05J | codex/feat/w6-par-05j-spell-mechanics-e | remediation_parity | in_progress | Umbrella row for summon/control/utility spell leaves; execution happens through child leaf tasks only. |
| W6-PAR-05K | codex/feat/w6-par-05k-spell-effect-support-f | remediation_parity | in_progress | Umbrella row for spell effect-family normalization and residual support leaves; execution happens through child leaf tasks only. |
| W6-PAR-05L | codex/feat/w6-par-05l-spell-schema-cleanup-g | remediation_parity | in_progress | Umbrella row for spell schema repair leaves; execution happens through child leaf tasks only. |
| W6-PAR-05L1 | codex/feat/w6-par-05l1-spell-schema-repair | remediation_parity | in_progress | Batch 1 hotspot leaf is active in its dedicated worktree and owns the exact invalid mechanics schema blockers from the leaf registry. |
| W6-PAR-05L2 | codex/feat/w6-par-05l2-spell-executable-conversion | remediation_parity | in_progress | Batch 1 hotspot leaf is active in its dedicated worktree and owns the exact non-executable mechanics blockers from the leaf registry. |

## Open PRs

No backlog tasks are currently marked `pr_open`.

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|

## Dependency and blocker notes (from backlog.csv)

- Wave 5 dependencies remain fully satisfied and merged on `main`.
- Wave 6 CUT, UNI, and GATE dependencies are satisfied and merged on `main`; PAR continuation remains active under W6-PAR-05 and is now executed through leaf-task PRs on `codex/int/w6-parity-closeout`.
- Strict FIN-02 gate currently reports 1225 blocked shipped records (background 43, species 45, spell 529, trait 608).
- Remaining strict unsupported-reason families are 696 `missing_runtime_hook_family`, 424 `missing_runtime_mechanics`, 66 `unsupported_effect_type`, 30 `non_executable_mechanics`, and 9 `invalid_mechanics_schema`.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
