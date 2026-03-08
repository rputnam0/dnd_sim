# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-08  
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

Wave 6 remains closed as historical truth for its declared strict shipped-2014 parity scope.
Wave 7 closeout is merged on `main` and completes the remaining CRPG-core hardening surfaces: canonical itemization, canonical class/subclass progression, and deterministic stealth/search/trap/lock interaction loops.

Wave 6 remediation state:

- Hard-cut track `int/6a-hard-cut` merged to `main` via [#179](https://github.com/rputnam0/dnd_sim/pull/179) after task PRs W6-CUT-01 [#167](https://github.com/rputnam0/dnd_sim/pull/167), W6-CUT-02 [#169](https://github.com/rputnam0/dnd_sim/pull/169), W6-CUT-03 [#162](https://github.com/rputnam0/dnd_sim/pull/162), and W6-CUT-04 [#165](https://github.com/rputnam0/dnd_sim/pull/165).
- Unification track `int/6b-unification` merged to `main` via [#180](https://github.com/rputnam0/dnd_sim/pull/180) after task PRs W6-UNI-01 [#166](https://github.com/rputnam0/dnd_sim/pull/166), W6-UNI-02 [#170](https://github.com/rputnam0/dnd_sim/pull/170), W6-UNI-03 [#164](https://github.com/rputnam0/dnd_sim/pull/164), and W6-UNI-04 [#163](https://github.com/rputnam0/dnd_sim/pull/163).
- Parity track `int/6c-parity` merged to `main` via [#181](https://github.com/rputnam0/dnd_sim/pull/181) after W6-PAR-01 [#168](https://github.com/rputnam0/dnd_sim/pull/168), W6-PAR-02 [#173](https://github.com/rputnam0/dnd_sim/pull/173), and W6-PAR-03 shard PRs [#171](https://github.com/rputnam0/dnd_sim/pull/171), [#174](https://github.com/rputnam0/dnd_sim/pull/174), [#175](https://github.com/rputnam0/dnd_sim/pull/175), [#176](https://github.com/rputnam0/dnd_sim/pull/176), [#177](https://github.com/rputnam0/dnd_sim/pull/177), [#178](https://github.com/rputnam0/dnd_sim/pull/178).
- Gate track `int/6d-gates` merged to `main` via [#182](https://github.com/rputnam0/dnd_sim/pull/182) and final closeout W6-GATE-02 merged via [#183](https://github.com/rputnam0/dnd_sim/pull/183).
- Parity continuation wave W6-PAR-04 merged via [#185](https://github.com/rputnam0/dnd_sim/pull/185), [#186](https://github.com/rputnam0/dnd_sim/pull/186), [#187](https://github.com/rputnam0/dnd_sim/pull/187), [#188](https://github.com/rputnam0/dnd_sim/pull/188), [#189](https://github.com/rputnam0/dnd_sim/pull/189), and [#190](https://github.com/rputnam0/dnd_sim/pull/190).
- Post-merge parity continuation work through [#193](https://github.com/rputnam0/dnd_sim/pull/193), [#194](https://github.com/rputnam0/dnd_sim/pull/194), [#195](https://github.com/rputnam0/dnd_sim/pull/195), [#196](https://github.com/rputnam0/dnd_sim/pull/196), [#197](https://github.com/rputnam0/dnd_sim/pull/197), [#198](https://github.com/rputnam0/dnd_sim/pull/198), [#199](https://github.com/rputnam0/dnd_sim/pull/199), and [#200](https://github.com/rputnam0/dnd_sim/pull/200) prepared the strict parity closeout branch.
- W6-PAR-05 execution completed on `codex/int/w6-parity-closeout` and was promoted to `main` via [#244](https://github.com/rputnam0/dnd_sim/pull/244) after the final batch merges [#233](https://github.com/rputnam0/dnd_sim/pull/233), [#234](https://github.com/rputnam0/dnd_sim/pull/234), [#235](https://github.com/rputnam0/dnd_sim/pull/235), [#236](https://github.com/rputnam0/dnd_sim/pull/236), [#237](https://github.com/rputnam0/dnd_sim/pull/237), [#238](https://github.com/rputnam0/dnd_sim/pull/238), [#239](https://github.com/rputnam0/dnd_sim/pull/239), [#240](https://github.com/rputnam0/dnd_sim/pull/240), [#241](https://github.com/rputnam0/dnd_sim/pull/241), [#242](https://github.com/rputnam0/dnd_sim/pull/242), and [#243](https://github.com/rputnam0/dnd_sim/pull/243).
- Strict FIN-02 is now green on `main` with `blocked=0`; no unsupported-reason families remain.
- `docs/program/parity_leaf_registry.csv` and `docs/program/parity_batch_registry.csv` are retained as canonical historical execution maps for parity closeout.

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
| PAR | Wave 6 Capability Parity Closure | merged | 6c-parity | W6-PAR-01 through W6-PAR-05M are merged and promoted to `main` via #244; strict FIN-02 is green with blocked=0. |
| GATE | Wave 6 Governance and Final Gates | merged | 6d-gates | W6-GATE-01 and W6-GATE-02 merged, including final full green gate via #183. |
| W7DOC | Wave 7 Documentation Truth Reset | merged | 7-doc-truth | W7-DOC-01 merged and the live planning docs now describe Wave 7 as historical closeout work. |
| ITM | Wave 7 Itemization Hard-Cut | merged | 7a-itemization | Canonical raw/canonical item catalogs, runtime hard-cut hooks, and magic-item support are merged. |
| CLS | Wave 7 Class/Subclass Hard-Cut | merged | 7b-classes | Canonical class/subclass catalogs, progression builder wiring, capability coverage, and multiclass edge handling are merged. |
| EXP | Wave 7 Stealth and Dungeon Interaction | merged | 7c-exploration | Hidden/detected/surprised state, interactables, persistence, and lightweight social support are merged. |
| W7GATE | Wave 7 Gates and Closeout | merged | 7d-gates | Capability expansion, CRPG-core scenario gates, artifact rebuilds, and doc truth-sync are merged. |

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
- Wave 6 CUT, UNI, PAR, and GATE dependencies are satisfied and merged on `main`.
- Wave 7 is fully merged in `docs/program/backlog.csv` and promoted as historical closeout truth on `main`.
- Strict FIN-02 is now fully green on `main` with 0 blocked shipped records.
- No strict unsupported-reason families remain.
- `docs/program/parity_batch_registry.csv` is now the historical execution map for the fully merged parity closeout wave.
- No backlog task is currently in `blocked` state.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
