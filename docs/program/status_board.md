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
| ARC | Runtime Decomposition | in_progress | 5B-runtime-decomposition | `ARC-01`, `ARC-02`, `ARC-03`, `ARC-04`, `ARC-05`, `ARC-06`, and `ARC-08` are `in_progress`; `ARC-07` is `pr_open`; remaining ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | in_progress | 5C-capability-manifest | `CAP-03`, `CAP-04`, and `CAP-05` are `in_progress` in `backlog.csv`; remaining CAP tasks are `not_started`. |
| OBS | Replay, Logging, and Observability | in_progress | 5D-observability | `OBS-02` is `in_progress` in `backlog.csv`; remaining OBS tasks are `not_started`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | in_progress | 5H-world-systems | `WLD-01` is `in_progress`; remaining WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| ARC-01 | `codex/feat/arc-01-extract-simulation-session-and-turn-loop-orchestra` | runtime_a | in_progress | Extracting session setup, initiative loop, and round progression into `src/dnd_sim/engine_runtime.py` with `engine.py` facade retained. |
| ARC-02 | `codex/feat/arc-02-extract-turn-declaration-validation-and-legal-acti` | runtime_b | in_progress | Extracting turn declaration validation and action-legality checks into `src/dnd_sim/action_legality.py` and routing engine/strategy validation through it. |
| ARC-03 | `codex/feat/arc-03-extract-movement-routing-and-spatial-legality-serv` | runtime_c | in_progress | Extracting movement budget/routing/spatial legality helpers into `src/dnd_sim/movement_runtime.py` and delegating movement internals from `engine.py`. |
| ARC-04 | `codex/feat/arc-04-extract-action-resolution-pipeline` | runtime_d | in_progress | Extracting action dispatch/target application/hit-save handling into `src/dnd_sim/action_resolution.py` and routing `engine.py` combat execution through the new module. |
| ARC-05 | `codex/feat/arc-05-extract-effect-lifecycle-condition-state-and-conce` | runtime_e | in_progress | Extracting effect lifecycle/condition state/concentration graph behavior into `src/dnd_sim/effects_runtime.py` and delegating condition/concentration internals from `engine.py`. |
| ARC-06 | `codex/feat/arc-06-extract-reactions-interrupts-and-ready-action-wind` | runtime_f | in_progress | Extracting reaction windows, trigger matching, ready-action release, and interrupt ordering into `src/dnd_sim/reaction_runtime.py` with engine delegation retained. |
| ARC-07 | `codex/feat/arc-07-extract-spell-execution-pipeline-and-target-resolu` | runtime_spell | pr_open | Extracted spell declaration normalization, upcast handling, target adapters, and spell-result application into `src/dnd_sim/spell_runtime.py` and delegated spell branches from the engine runtime path. |
| ARC-08 | `codex/feat/arc-08-extract-replay-reporting-adapter-layer-and-reduce` | runtime_report | in_progress | Extracting replay/reporting adapters into `src/dnd_sim/replay.py` and `src/dnd_sim/reporting_runtime.py`, routing emission through them, and reducing `engine.py` to an orchestration facade. |
| CAP-03 | `codex/feat/cap-03-generate-feat-trait-background-and-species-capabil` | content_manifest_feat | in_progress | Building feat/trait/background/species capability records with runtime hook family and support-state labeling. |
| CAP-04 | `codex/feat/cap-04-generate-monster-and-monster-action-capability-man` | content_manifest_monster | in_progress | Building monster capability records for actions, reactions, legendary/lair/recharge entries, and innate spellcasting support-state coverage. |
| CAP-05 | `codex/feat/cap-05-enforce-capability-manifest-gates-in-import-paths` | content_manifest_gate | in_progress | Enforcing import/CI capability gates for schema-valid tested scope and explicit unsupported-reason codes for blocked scope. |
| OBS-02 | `feat/obs-02-emit-turn-declaration-and-action-resolution-traces` | observability_b | in_progress | Emitting declaration validation, action selection, action resolution, and action outcome traces for each declared turn. |
| WLD-01 | `codex/feat/wld-01-build-ability-check-contest-passive-and-dc-resolut` | world_rules_a | in_progress | Implementing deterministic noncombat ability checks, contests, passive checks, and DC evaluation core. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| ARC-07 | [#112](https://github.com/rputnam0/dnd_sim/pull/112) | runtime_spell | pending | Extracts spell runtime pipeline and target adapters from the engine path; awaiting automated + reviewer checks. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; ARC-01, ARC-02, ARC-03, ARC-04, ARC-05, ARC-06, and ARC-08 runtime decomposition work is in progress, and ARC-07 is in PR review state on its assigned branch.
- `WLD-01` is active and depends on `ARC-02` per `backlog.csv`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
