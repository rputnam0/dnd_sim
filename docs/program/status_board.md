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
| AI | Tactical AI Hardening | pr_open | 5F-ai-hardening | `AI-01`, `AI-02`, `AI-03`, `AI-04`, `AI-05`, and `AI-06` are `pr_open`; remaining AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| ARC-01 | `codex/feat/arc-01-extract-simulation-session-and-turn-loop-orchestra` | runtime_a | in_progress | Extracting simulation session setup, initiative loop, and round progression into `src/dnd_sim/engine_runtime.py`. |
| ARC-02 | `codex/feat/arc-02-extract-turn-declaration-validation-and-legal-acti` | runtime_b | in_progress | Building legal declaration validation and action economy checks in `src/dnd_sim/action_legality.py`. |
| ARC-03 | `codex/feat/arc-03-extract-movement-routing-and-spatial-legality-serv` | runtime_c | in_progress | Implementing movement legality, routing, and spatial runtime extraction in `src/dnd_sim/movement_runtime.py`. |
| ARC-04 | `codex/feat/arc-04-extract-action-resolution-pipeline` | runtime_d | in_progress | Extracting action dispatch and target resolution pipeline into `src/dnd_sim/action_resolution.py`. |
| ARC-05 | `codex/feat/arc-05-extract-effect-lifecycle-condition-state-and-conce` | runtime_e | in_progress | Implementing effect lifecycle, concentration graph, and condition-state runtime extraction in `src/dnd_sim/effects_runtime.py`. |
| ARC-06 | `codex/feat/arc-06-extract-reactions-interrupts-and-ready-action-wind` | runtime_f | in_progress | Building reaction window, interrupt, and ready-action runtime handling in `src/dnd_sim/reaction_runtime.py`. |
| ARC-07 | `codex/feat/arc-07-extract-spell-execution-pipeline-and-target-resolu` | runtime_spell | pr_open | Spell execution and target-resolution runtime extraction is marked `pr_open` in `backlog.csv`. |
| ARC-08 | `codex/feat/arc-08-extract-replay-reporting-adapter-layer-and-reduce` | runtime_report | in_progress | Building replay/reporting adapters and reducing `engine.py` to orchestration facade responsibilities. |
| CAP-03 | `codex/feat/cap-03-generate-feat-trait-background-and-species-capabil` | content_manifest_feat | in_progress | Generating feat/trait/background/species capability manifests and support-state coverage. |
| CAP-04 | `codex/feat/cap-04-generate-monster-and-monster-action-capability-man` | content_manifest_monster | in_progress | Generating monster and monster-action capability manifests with support-state annotation. |
| CAP-05 | `codex/feat/cap-05-enforce-capability-manifest-gates-in-import-paths` | content_manifest_gate | in_progress | Enforcing manifest support gates in import flows and content CI checks. |
| OBS-02 | `feat/obs-02-emit-turn-declaration-and-action-resolution-traces` | observability_b | in_progress | Emitting declaration validation, action selection, and resolution traces for each turn. |
| AI-01 | `codex/feat/ai-01-normalize-candidate-action-enumeration-and-scoring` | ai_core | pr_open | Introduces `src/dnd_sim/ai/scoring.py` candidate enumeration with normalized scoring inputs and routes optimal strategy selection through legal candidate snapshots. |
| AI-03 | `codex/feat/ai-03-implement-concentration-breaking-control-value-and` | ai_control | pr_open | Concentration-break, condition-application, and enemy action-denial scoring components are in PR review for AI-03. |
| AI-04 | `codex/feat/ai-04-implement-retreat-survival-objective-race-and-focu` | ai_objective | pr_open | Retreat/survival, objective-race urgency, ally-rescue valuation, and focus-fire tradeoff scoring are implemented and under review. |
| AI-02 | `codex/feat/ai-02-implement-hazard-geometry-cover-and-line-of-effect` | ai_spatial | pr_open | Implements hazard/geometry/cover/line-of-effect candidate scoring in `src/dnd_sim/ai/scoring.py` with path risk support in `src/dnd_sim/spatial.py` and dedicated tests. |
| AI-05 | `codex/feat/ai-05-implement-recharge-legendary-reaction-bait-and-lim` | ai_timing | pr_open | Adds timing heuristics for recharge readiness, legendary windows, reaction baiting, and limited-resource spend timing in AI candidate scoring. |
| AI-06 | `codex/feat/ai-06-build-benchmark-corpus-tuning-thresholds-and-decis` | ai_benchmark | pr_open | Adds deterministic benchmark corpus coverage and tactical quality gate execution in `scripts/ai/run_benchmarks.py` with AI-06-focused tests. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| ARC-07 | pending | runtime_spell | pending | ARC-07 is marked `pr_open` in `backlog.csv`; spell-runtime extraction review remains open. |
| AI-01 | [#116](https://github.com/rputnam0/dnd_sim/pull/116) | ai_core | pending | Normalized candidate enumeration and scoring inputs are under review for merge into `int/5f-ai-hardening`. |
| AI-03 | [#122](https://github.com/rputnam0/dnd_sim/pull/122) | ai_control | pending | Adds concentration-break, control-value, condition-application, and enemy action-denial scoring with focused deterministic tests. |
| AI-04 | [#119](https://github.com/rputnam0/dnd_sim/pull/119) | ai_objective | pending | Adds survival-threshold, retreat timing, objective-race, ally-rescue, and focus-fire tradeoff scoring snapshots for legal candidates. |
| AI-02 | [#120](https://github.com/rputnam0/dnd_sim/pull/120) | ai_spatial | pending | Hazard/geometry/cover/line-of-effect scoring and route hazard exposure are under review for merge into `int/5f-ai-hardening`. |
| AI-05 | [#128](https://github.com/rputnam0/dnd_sim/pull/128) | ai_timing | pending | Recharge, legendary-window, reaction-bait, and limited-resource timing heuristics are under review for merge into `int/5f-ai-hardening`. |
| AI-06 | [#150](https://github.com/rputnam0/dnd_sim/pull/150) | ai_benchmark | pending | Adds AI benchmark corpus artifacts and benchmark gate execution requiring primary tactical AI outcome margins and rationale coverage. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; AI-01, AI-02, AI-03, AI-04, AI-05, and AI-06 are in PR review while remaining queues are unchanged.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
