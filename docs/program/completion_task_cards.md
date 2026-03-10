# Completion Task Cards

Status: canonical  
Owner: program-control  
Last updated: 2026-03-08  
Canonical source: `docs/program/backlog.csv`

This file expands the machine-readable backlog into a human-readable task reference for coding agents and reviewers.
Wave 7 is now fully merged; keep using `docs/program/backlog.csv` and `docs/program/status_board.md` for current status, and treat the cards below as task reference plus historical execution context.

## Documentation Control

Collapse the repo onto one canonical planning surface, archive stale planning artifacts, and enforce doc freshness in CI.

### DOC-01 Establish canonical docs entrypoints and source-of-truth rules

- Depends on: none
- Owner pool: `doc_control_lead`
- Target modules: docs/plan.md; docs/program/README.md; docs/agent_feature_assignments.md
- Required tests: docs link sweep; path existence check; stale-reference grep
- Required docs: docs/plan.md; docs/program/README.md; docs/agent_feature_assignments.md
- Exit criteria: Replace root planning entrypoints so they point only to docs/program/README.md; declare docs/program/README.md the single canonical planning entrypoint; mark every other planning doc as canonical or historical.

### DOC-02 Archive stale planning and historical run artifacts

- Depends on: DOC-01
- Owner pool: `doc_control_a`
- Target modules: docs/archive/README.md; docs/archive/program_runs/; docs/archive/cleanup/; docs/archive/deprecation/
- Required tests: archive index generation; no live doc points at archived file without explicit historical label
- Required docs: docs/archive/README.md; docs/program/README.md; docs/program/status_board.md
- Exit criteria: Create docs/archive/README.md; reconstruct deleted Wave 3/4 run artifacts plus cleanup/deprecation records from git history into docs/archive/; remove archived files from canonical entrypoint links.

### DOC-03 Normalize status board and merged baseline history

- Depends on: DOC-01
- Owner pool: `doc_control_b`
- Target modules: docs/program/status_board.md; docs/plan.md
- Required tests: status/backlog consistency check; merged baseline presence check
- Required docs: docs/program/status_board.md; docs/plan.md
- Exit criteria: Backfill Wave 1-4, repo cleanup, and legacy decommission as merged/completed baseline; remove stale in_progress states for already-merged work; make backlog.csv the task-level source of truth and status_board.md the human dashboard.

### DOC-04 Add doc freshness metadata and registry

- Depends on: DOC-01
- Owner pool: `doc_control_a`
- Target modules: docs/program/doc_governance.md; docs/program/README.md; docs/program/status_board.md; docs/program/roadmap_2014_backend.md
- Required tests: metadata header parser test; registry completeness check
- Required docs: docs/program/doc_governance.md; docs/program/README.md; docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Require Status, Owner, Last updated, and Canonical source headers on every live planning doc; add a registry of live planning docs and ownership in docs/program/doc_governance.md.

### DOC-05 Add doc consistency checker and CI gate

- Depends on: DOC-04
- Owner pool: `doc_control_ci`
- Target modules: scripts/docs/verify_program_docs.py; .github/workflows/*docs*; docs/program/doc_governance.md
- Required tests: unit tests for parser/rules; CI dry-run; failure fixture for stale status and missing metadata
- Required docs: docs/program/doc_governance.md; docs/program/test_acceptance_matrix.md; docs/program/status_board.md
- Exit criteria: Fail CI when status_board.md, backlog.csv, or live planning headers drift; fail CI on broken internal doc links; fail CI when archived files remain linked from live entrypoints.

### DOC-06 Expand agent ownership map for target runtime boundaries

- Depends on: DOC-01
- Owner pool: `doc_control_lead`
- Target modules: docs/agent_index.yaml; docs/program/backlog.csv; docs/program/agent_assignment.csv
- Required tests: agent index schema validation; ownership coverage check for every target runtime module
- Required docs: docs/agent_index.yaml; docs/program/agent_assignment.csv; docs/program/backlog.csv
- Exit criteria: Add ownership and invariants for each planned runtime module introduced by ARC tasks; require every runtime-affecting PR to update docs/agent_index.yaml in the same branch.

## Runtime Decomposition

Decompose the engine monolith into bounded runtime modules with explicit ownership and stable entrypoints.

### ARC-01 Extract simulation session and turn-loop orchestration from engine.py

- Depends on: DOC-06
- Owner pool: `runtime_a`
- Target modules: src/dnd_sim/engine.py; src/dnd_sim/engine_runtime.py; tests/test_engine_runtime*.py; docs/agent_index.yaml
- Required tests: runtime contract tests; deterministic seed replay tests; integration smoke tests
- Required docs: docs/agent_index.yaml; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/engine_runtime.py and move session setup, initiative loop, and round progression into it; leave engine.py as a stable facade; reduce engine.py line count on this task.

### ARC-02 Extract turn declaration validation and legal action service

- Depends on: ARC-01
- Owner pool: `runtime_b`
- Target modules: src/dnd_sim/action_legality.py; src/dnd_sim/engine.py; src/dnd_sim/strategy_api.py; tests/test_action_legality*.py; docs/agent_index.yaml
- Required tests: unit legality tests; invalid declaration tests; integration tests for legal turn declaration
- Required docs: docs/agent_index.yaml; docs/program/completion_task_cards.md
- Exit criteria: Create src/dnd_sim/action_legality.py for declaration validation, action economy checks, and structured legality errors; route engine and strategy API validation through it.
- Implementation note (2026-03-05): ARC-02 is in progress on `codex/feat/arc-02-extract-turn-declaration-validation-and-legal-acti`.

### ARC-03 Extract movement, routing, and spatial legality service

- Depends on: ARC-01
- Owner pool: `runtime_c`
- Target modules: src/dnd_sim/movement_runtime.py; src/dnd_sim/spatial.py; src/dnd_sim/engine.py; tests/test_movement_runtime*.py; docs/agent_index.yaml
- Required tests: path legality tests; movement cost tests; forced movement and opportunity attack tests
- Required docs: docs/agent_index.yaml; docs/program/completion_task_cards.md
- Exit criteria: Create src/dnd_sim/movement_runtime.py to own movement budget, routing, difficult terrain, forced movement, and spatial legality; remove duplicate movement logic from engine.py.
- Implementation checkpoint: extract movement budget math, declared path validation, difficult-terrain routing inputs, forced-movement destination resolution, and opportunity-attack reach transition helpers into `src/dnd_sim/movement_runtime.py`.

### ARC-04 Extract action resolution pipeline

- Depends on: ARC-02;ARC-03
- Owner pool: `runtime_d`
- Target modules: src/dnd_sim/action_resolution.py; src/dnd_sim/engine.py; tests/test_action_resolution*.py; docs/agent_index.yaml
- Required tests: attack/spell/item action integration tests; invalid target negative tests; deterministic combat regressions
- Required docs: docs/agent_index.yaml; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/action_resolution.py to own action dispatch, target application, hit/save handling, and result objects; route all combat action execution through the new module.

### ARC-05 Extract effect lifecycle, condition state, and concentration graph service

- Depends on: ARC-04
- Owner pool: `runtime_e`
- Target modules: src/dnd_sim/effects_runtime.py; src/dnd_sim/engine.py; src/dnd_sim/mechanics_schema.py; tests/test_effects_runtime*.py; docs/agent_index.yaml
- Required tests: effect duration tests; concentration lifecycle tests; condition stacking and cleanup tests
- Required docs: docs/agent_index.yaml; docs/review_checklist.md
- Exit criteria: Create src/dnd_sim/effects_runtime.py to own effect creation, ticking, expiration, concentration graph updates, and derived state recomputation.

### ARC-06 Extract reactions, interrupts, and ready-action window manager

- Depends on: ARC-04;ARC-05
- Owner pool: `runtime_f`
- Target modules: src/dnd_sim/reaction_runtime.py; src/dnd_sim/engine.py; tests/test_reaction_runtime*.py; docs/agent_index.yaml
- Required tests: reaction window tests; ready action tests; opportunity attack and interrupt legality tests
- Required docs: docs/agent_index.yaml; docs/review_checklist.md
- Exit criteria: Create src/dnd_sim/reaction_runtime.py to own reaction windows, trigger matching, ready action release, and interrupt ordering; remove reaction timing branches from engine.py.

### ARC-07 Extract spell execution pipeline and target resolution adapters

- Depends on: ARC-02;ARC-04;ARC-05
- Owner pool: `runtime_spell`
- Target modules: src/dnd_sim/spell_runtime.py; src/dnd_sim/spells.py; src/dnd_sim/engine.py; tests/test_spell_runtime*.py; docs/agent_index.yaml
- Required tests: spell family integration tests; upcast legality tests; target mode negative tests
- Required docs: docs/agent_index.yaml; docs/program/roadmap_2014_backend.md
- Exit criteria: Create src/dnd_sim/spell_runtime.py to own spell declaration normalization, slot use, upcast handling, target resolution, and spell-result application; remove spell-specific branches from engine.py.

### ARC-08 Extract replay/reporting adapter layer and reduce engine.py to an orchestration facade

- Depends on: ARC-01;ARC-04
- Owner pool: `runtime_report`
- Target modules: src/dnd_sim/replay.py; src/dnd_sim/reporting_runtime.py; src/dnd_sim/engine.py; tests/test_replay*.py; docs/agent_index.yaml
- Required tests: replay serialization tests; simulation summary tests; deterministic diff tests
- Required docs: docs/agent_index.yaml; docs/program/status_board.md; docs/program/test_acceptance_matrix.md
- Exit criteria: Create src/dnd_sim/replay.py and src/dnd_sim/reporting_runtime.py; route replay/report emission through them; reduce engine.py below 3500 lines and keep every extracted runtime module below 1500 lines.

## Capability Manifest

Generate machine-readable support manifests for spells, feats, monsters, and all executable content.

### CAP-01 Define capability manifest schema, storage format, and CLI

- Depends on: DOC-01
- Owner pool: `content_manifest_lead`
- Target modules: src/dnd_sim/capability_manifest.py; docs/program/roadmap_2014_backend.md; tests/test_capability_manifest_schema.py
- Required tests: schema validation tests; CLI smoke test; manifest round-trip tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/test_acceptance_matrix.md
- Exit criteria: Define a canonical manifest schema with states cataloged, schema_valid, executable, tested, blocked, and unsupported_reason; add a CLI to emit manifest files deterministically.

### CAP-02 Generate spell capability manifest from canonical spell data

- Depends on: CAP-01;ARC-07
- Owner pool: `content_manifest_spell`
- Target modules: src/dnd_sim/capability_manifest.py; src/dnd_sim/spells.py; db/rules/2014/*spell*; tests/test_spell_capability_manifest.py
- Required tests: spell import tests; executable coverage tests; unsupported spell reason tests
- Required docs: docs/program/completion_task_cards.md; docs/review_checklist.md
- Exit criteria: Generate a spell manifest for every canonical 2014 spell and mark each record executable, blocked, or unsupported with a single reason code.
- Execution note: Active on `codex/feat/cap-02-generate-spell-capability-manifest-from-canonical`.

### CAP-03 Generate feat, trait, background, and species capability manifest

- Depends on: CAP-01;ARC-05
- Owner pool: `content_manifest_feat`
- Target modules: src/dnd_sim/capability_manifest.py; db/rules/2014/*feat*; db/rules/2014/*trait*; tests/test_feat_capability_manifest.py
- Required tests: feature manifest tests; duplicate content id tests; unsupported feature reason tests
- Required docs: docs/program/completion_task_cards.md; docs/review_checklist.md
- Exit criteria: Generate manifests for feats, traits, backgrounds, and species content; require each record to declare its runtime hook family and support state.
- Execution note: Active on `codex/feat/cap-03-generate-feat-trait-background-and-species-capabil`.

### CAP-04 Generate monster and monster-action capability manifest

- Depends on: CAP-01;ARC-04
- Owner pool: `content_manifest_monster`
- Target modules: src/dnd_sim/capability_manifest.py; db/rules/2014/*monster*; tests/test_monster_capability_manifest.py
- Required tests: monster parser integration tests; action support tests; unsupported action reason tests
- Required docs: docs/program/completion_task_cards.md; docs/program/status_board.md
- Exit criteria: Generate manifests for monsters, monster actions, reactions, legendary actions, lair actions, recharge features, and innate spellcasting entries.
- Execution note: Active on `codex/feat/cap-04-generate-monster-and-monster-action-capability-man`.

### CAP-05 Enforce capability manifest gates in import paths and CI

- Depends on: CAP-02;CAP-03;CAP-04;DOC-05
- Owner pool: `content_manifest_gate`
- Target modules: src/dnd_sim/io.py; scripts/content/verify_capabilities.py; .github/workflows/*content*; tests/test_capability_gates.py
- Required tests: import failure tests; CI gate dry-run; blocked-record fixture tests
- Required docs: docs/program/test_acceptance_matrix.md; docs/program/status_board.md
- Exit criteria: Fail import or CI when shipped 2014 content lacks schema_valid or tested state for supported scope; require explicit unsupported_reason codes for blocked scope.

### CAP-06 Publish machine-readable and markdown coverage reports

- Depends on: CAP-05
- Owner pool: `content_manifest_report`
- Target modules: artifacts/capabilities/; docs/program/capability_report.md; scripts/content/render_capability_report.py; tests/test_capability_report.py
- Required tests: report generation tests; stable ordering tests; markdown snapshot tests
- Required docs: docs/program/capability_report.md; docs/program/status_board.md
- Exit criteria: Publish deterministic JSON and markdown reports for content coverage and link them from docs/program/README.md.

## Replay, Logging, and Observability

Emit structured traces, state deltas, replay bundles, and invariant events for every simulation run.

### OBS-01 Introduce structured event schema and module-level loggers

- Depends on: DOC-01
- Owner pool: `observability_a`
- Target modules: src/dnd_sim/telemetry.py; src/dnd_sim/*.py; tests/test_telemetry_schema.py; docs/agent_index.yaml
- Required tests: telemetry schema tests; logger presence tests; event serialization tests
- Required docs: docs/agent_index.yaml; docs/program/test_acceptance_matrix.md
- Exit criteria: Create src/dnd_sim/telemetry.py with JSON-compatible event schemas; add module-level loggers to runtime modules; emit structured event envelopes instead of ad hoc print/debug output.

### OBS-02 Emit turn declaration and action resolution traces

- Depends on: OBS-01;ARC-04
- Owner pool: `observability_b`
- Target modules: src/dnd_sim/telemetry.py; src/dnd_sim/action_resolution.py; src/dnd_sim/engine_runtime.py; tests/test_turn_traces.py
- Required tests: trace completeness tests; deterministic ordering tests; illegal action trace tests
- Required docs: docs/program/completion_task_cards.md; docs/review_checklist.md
- Exit criteria: Emit a structured trace record for declaration validation, action selection, action resolution, and final action outcome on every turn.
- Status update (2026-03-05): Implemented structured `declaration_validation`, `action_selection`, `action_resolution`, and `action_outcome` telemetry emissions in declared-turn runtime paths with deterministic ordering checks and illegal action trace coverage in `tests/test_turn_traces.py`.

### OBS-03 Emit actor state delta and effect lifecycle traces

- Depends on: OBS-01;ARC-05
- Owner pool: `observability_c`
- Target modules: src/dnd_sim/telemetry.py; src/dnd_sim/effects_runtime.py; tests/test_state_delta_traces.py
- Required tests: state delta snapshot tests; effect lifecycle trace tests; no-op delta suppression tests
- Required docs: docs/program/completion_task_cards.md; docs/review_checklist.md
- Exit criteria: Emit before/after actor state deltas and effect lifecycle events for apply, tick, refresh, expire, and concentration break transitions.
- Status update (2026-03-05): Added `actor_state_delta` and effect lifecycle event-type coverage in telemetry, introduced `src/dnd_sim/effects_runtime.py` builders for deterministic state-delta and lifecycle payloads, and added `tests/test_state_delta_traces.py` for snapshot, lifecycle, and no-op suppression coverage.

### OBS-04 Emit AI candidate scoring and rationale traces

- Depends on: AI-01;OBS-02
- Owner pool: `observability_ai`
- Target modules: src/dnd_sim/telemetry.py; src/dnd_sim/ai/scoring.py; src/dnd_sim/strategies/defaults.py; tests/test_ai_rationale_traces.py
- Required tests: candidate coverage tests; score component tests; rationale schema tests
- Required docs: docs/program/completion_task_cards.md; docs/program/status_board.md
- Exit criteria: Emit full candidate sets, score components, selected action, and rejection reasons for every AI-controlled turn.

### OBS-05 Emit resource delta, RNG audit, and invariant violation events

- Depends on: OBS-01;ARC-05
- Owner pool: `observability_d`
- Target modules: src/dnd_sim/telemetry.py; src/dnd_sim/engine_resources.py; tests/test_resource_rng_invariant_events.py
- Required tests: resource delta tests; RNG audit determinism tests; invariant emission tests
- Required docs: docs/program/test_acceptance_matrix.md; docs/review_checklist.md
- Exit criteria: Emit structured events for resource spend/recovery, RNG draws keyed by seed and context, and invariant violations with explicit codes.

### OBS-06 Build replay bundle writer, loader, and diff harness

- Depends on: OBS-02;OBS-03;OBS-05;ARC-08
- Owner pool: `observability_replay`
- Target modules: src/dnd_sim/replay.py; src/dnd_sim/replay_schema.py; tests/test_replay_bundle.py; scripts/replay/diff_runs.py
- Required tests: replay round-trip tests; diff harness tests; schema compatibility tests
- Required docs: docs/program/completion_task_cards.md; docs/program/test_acceptance_matrix.md
- Exit criteria: Persist complete replay bundles with inputs, seeds, traces, and outcome summary; provide a deterministic diff harness for comparing two bundles.

### OBS-07 Establish golden trace corpus and trace review gate

- Depends on: OBS-06;DOC-05
- Owner pool: `observability_gate`
- Target modules: artifacts/golden_traces/; tests/test_golden_traces.py; scripts/replay/verify_golden_traces.py
- Required tests: golden trace snapshot tests; intentional delta approval path test
- Required docs: docs/program/status_board.md; docs/review_checklist.md
- Exit criteria: Create a golden trace corpus covering combat, hazards, summons, reactions, and world flows; fail CI on unapproved trace drift.

## Persistence and Query Model

Replace thin blob-centric persistence with canonical metadata tables, lineage, and campaign/world storage.

### DBS-01 Add canonical metadata tables for content and support records

- Depends on: CAP-01
- Owner pool: `persistence_a`
- Target modules: src/dnd_sim/db_schema.py; scripts/migrations/*content_metadata*; tests/test_content_metadata_tables.py
- Required tests: schema migration tests; round-trip insert/query tests; rollback tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Add canonical tables content_records and content_capabilities with content_id, content_type, source_book, schema_version, source_hash, payload_json, support_state, unsupported_reason, and last_verified_commit.

### DBS-02 Add schema version, source lineage, and content hash persistence

- Depends on: DBS-01
- Owner pool: `persistence_b`
- Target modules: src/dnd_sim/db_schema.py; src/dnd_sim/io.py; tests/test_content_lineage.py
- Required tests: hash stability tests; lineage migration tests; duplicate hash handling tests
- Required docs: docs/program/completion_task_cards.md; docs/program/status_board.md
- Exit criteria: Persist schema_version, source_path, source_hash, canonicalization_hash, and imported_at for every content record and replay the lineage deterministically.

DBS-02 implementation contract:
- `content_records` must persist `schema_version`, `source_path`, `source_hash`, `canonicalization_hash`, and `imported_at` for every row.
- Hashing must be stable for semantically equivalent payloads after canonical JSON ordering.
- Lineage replay order must be deterministic by `imported_at` then `content_id`.

### DBS-03 Add query APIs and CLI for support coverage, schema version, and lineage

- Depends on: DBS-02;CAP-05
- Owner pool: `persistence_c`
- Target modules: src/dnd_sim/content_index.py; src/dnd_sim/cli.py; tests/test_content_queries.py
- Required tests: query API tests; CLI output snapshot tests; invalid query tests
- Required docs: docs/program/capability_report.md; docs/program/status_board.md
- Exit criteria: Expose query APIs and CLI commands for content lookup by content_id, type, support_state, unsupported_reason, source_book, and schema version.

### DBS-04 Add campaign state persistence schema and round-trip tests

- Depends on: DBS-01;ARC-08
- Owner pool: `persistence_campaign`
- Target modules: src/dnd_sim/snapshot_store.py; src/dnd_sim/db_schema.py; tests/test_campaign_persistence.py
- Required tests: campaign round-trip tests; snapshot compatibility tests; corruption negative tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Add campaign_states and encounter_states storage with deterministic save/load semantics for party state, resources, active effects, initiative context, and replay linkage.

### DBS-05 Add world flags, objectives, factions, and encounter state persistence schema

- Depends on: DBS-04
- Owner pool: `persistence_world`
- Target modules: src/dnd_sim/snapshot_store.py; src/dnd_sim/db_schema.py; tests/test_world_state_persistence.py
- Required tests: world flag lifecycle tests; objective persistence tests; faction round-trip tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Add world_states and faction_states storage with deterministic lifecycle for flags, reputations, scripted objectives, map state, and encounter wave progression.

### DBS-06 Migrate existing JSON/blob content to the canonical metadata model

- Depends on: DBS-02;DBS-04;DBS-05
- Owner pool: `persistence_migration`
- Target modules: scripts/migrations/*; src/dnd_sim/db_schema.py; tests/test_persistence_migrations.py
- Required tests: backfill tests; rollback tests; mixed-old-new read tests
- Required docs: docs/program/status_board.md; docs/program/roadmap_2014_backend.md
- Exit criteria: Backfill existing persisted records into canonical metadata and state tables; preserve read compatibility during migration and remove transitional paths at completion.

## Tactical AI Hardening

Upgrade enemy decision-making from baseline heuristics to traceable tactical play.

### AI-01 Normalize candidate action enumeration and scoring inputs

- Depends on: ARC-02;ARC-03;ARC-04
- Owner pool: `ai_core`
- Target modules: src/dnd_sim/ai/scoring.py; src/dnd_sim/strategies/defaults.py; tests/test_ai_candidate_enumeration.py
- Required tests: candidate completeness tests; illegal candidate exclusion tests; scoring input snapshot tests
- Required docs: docs/program/completion_task_cards.md; docs/agent_index.yaml
- Exit criteria: Create src/dnd_sim/ai/scoring.py; enumerate all legal candidates for an actor turn with normalized scoring inputs for range, hazard, concentration, control, objective, and resource state.
- Implementation note (2026-03-05): legal candidate enumeration and normalized input snapshots are implemented in `src/dnd_sim/ai/scoring.py` and integrated into `OptimalExpectedDamageStrategy` action selection.

### AI-02 Implement hazard, geometry, cover, and line-of-effect scoring

- Depends on: AI-01;ARC-03
- Owner pool: `ai_spatial`
- Target modules: src/dnd_sim/ai/scoring.py; src/dnd_sim/spatial.py; tests/test_ai_spatial_scoring.py
- Required tests: hazard scenario tests; cover scoring tests; aoe friendly-fire tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Score hazard exposure, route quality, geometry, cover, line-of-effect, and friendly-fire penalties directly in the AI scoring layer.

### AI-03 Implement concentration breaking, control value, and disable value scoring

- Depends on: AI-01;ARC-05
- Owner pool: `ai_control`
- Target modules: src/dnd_sim/ai/scoring.py; tests/test_ai_control_scoring.py
- Required tests: concentration break tests; control spell target tests; disable valuation tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Add scoring components for concentration disruption, control effects, condition application value, and enemy action-denial value.

### AI-04 Implement retreat, survival, objective race, and focus-fire tradeoff scoring

- Depends on: AI-01
- Owner pool: `ai_objective`
- Target modules: src/dnd_sim/ai/scoring.py; tests/test_ai_objective_scoring.py
- Required tests: retreat threshold tests; objective race tests; focus-fire tradeoff tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Add scoring components for survival thresholds, disengage/retreat timing, objective racing, ally rescue, and focus-fire tradeoffs.

### AI-05 Implement recharge, legendary, reaction-bait, and limited-resource timing heuristics

- Depends on: AI-01;ARC-06
- Owner pool: `ai_timing`
- Target modules: src/dnd_sim/ai/scoring.py; src/dnd_sim/strategies/defaults.py; tests/test_ai_timing_scoring.py
- Required tests: recharge timing tests; legendary action tests; reaction bait tests; limited-use timing tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Add scoring and policy hooks for recharge abilities, legendary action timing, reaction baiting, and limited-use ability timing.

### AI-06 Build benchmark corpus, tuning thresholds, and decision-quality gates

- Depends on: AI-02;AI-03;AI-04;AI-05;OBS-04;OBS-06
- Owner pool: `ai_benchmark`
- Target modules: artifacts/ai_benchmarks/; tests/test_ai_benchmarks.py; scripts/ai/run_benchmarks.py
- Required tests: benchmark regression tests; strategy comparison tests; rationale coverage tests
- Required docs: docs/program/status_board.md; docs/review_checklist.md
- Exit criteria: Create a benchmark corpus with hazard-heavy, objective-heavy, summon-heavy, and legendary/recharge encounters; require the primary tactical AI to beat BaseStrategy and HighestThreatStrategy on objective-adjusted outcomes while producing full rationale traces.

## Rules Closure

Close the remaining correctness gaps in feats, reactions, rage, and hazard-aware scoring.

### FIX-01 Close Lucky attacker, defender, and saving throw correctness

- Depends on: ARC-05;ARC-06
- Owner pool: `rules_a`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_lucky_correctness.py
- Required tests: Lucky attacker tests; Lucky defender tests; Lucky save tests; negative use-limit tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Add deterministic tests for Lucky on attacks against and by the character and on saving throws; enforce correct reroll selection and resource use.

### FIX-02 Close Great Weapon Master and Sharpshooter toggle correctness

- Depends on: ARC-04;AI-01
- Owner pool: `rules_b`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_gwm_sharpshooter_correctness.py
- Required tests: damage math tests; advantage/disadvantage tests; illegal toggle tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Add deterministic toggle tests for GWM and Sharpshooter, including damage math, hit modifiers, and legality under advantage/disadvantage.

### FIX-03 Close Shield Master reaction, save, and shove correctness

- Depends on: ARC-06
- Owner pool: `rules_c`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_shield_master_correctness.py
- Required tests: save bonus tests; shove timing tests; illegal sequence tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Implement Shield Master timing and state tests for bonus application, shove sequencing, and illegal use windows.

### FIX-04 Close War Caster opportunity casting and concentration correctness

- Depends on: ARC-06;ARC-07
- Owner pool: `rules_d`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_war_caster_correctness.py
- Required tests: opportunity spell tests; concentration tests; illegal target tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Implement War Caster timing and legality tests for opportunity spellcasting and concentration advantage application.

### FIX-05 Close Mage Slayer and Sentinel reaction constraints

- Depends on: ARC-06
- Owner pool: `rules_e`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_mage_slayer_sentinel_correctness.py
- Required tests: reaction trigger tests; reach/opportunity tests; illegal stacking tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Implement deterministic tests and fixes for Mage Slayer and Sentinel trigger windows, reach rules, and reaction lockout semantics.

### FIX-06 Close Rage damage, resistance, and illegal state edge cases

- Depends on: ARC-05
- Owner pool: `rules_f`
- Target modules: src/dnd_sim/rules_2014.py; tests/test_rage_edge_cases.py
- Required tests: damage bonus tests; resistance tests; illegal activation tests; concentration interaction tests
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Implement deterministic tests and fixes for Rage damage bonus, resistance scope, illegal activation states, and edge-case teardown behavior.

### FIX-07 Integrate hazard-aware strategy scoring and close the review checklist

- Depends on: AI-02;FIX-01;FIX-02;FIX-03;FIX-04;FIX-05;FIX-06
- Owner pool: `rules_gate`
- Target modules: docs/review_checklist.md; tests/test_hazard_strategy_integration.py; src/dnd_sim/strategies/defaults.py
- Required tests: hazard-aware strategy tests; checklist completion test; full suite smoke test
- Required docs: docs/review_checklist.md; docs/program/status_board.md
- Exit criteria: Wire hazard and geometry fields into active strategy scoring paths; mark the review checklist complete only after all listed tests and fixes land.

## World Systems and Campaign Platform

Deliver noncombat, persistence, world-state, encounter scripting, and platform-scale regression systems.

### WLD-01 Build ability check, contest, passive, and DC resolution core

- Depends on: ARC-02
- Owner pool: `world_rules_a`
- Target modules: src/dnd_sim/noncombat_checks.py; src/dnd_sim/rules_2014.py; tests/test_noncombat_checks.py
- Required tests: ability check tests; contest tests; passive check tests; invalid input tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/noncombat_checks.py and implement deterministic ability checks, contests, passive checks, and DC evaluation.

### WLD-02 Build skill, tool, proficiency, and specialist data plumbing

- Depends on: WLD-01
- Owner pool: `world_rules_b`
- Target modules: src/dnd_sim/noncombat_checks.py; db/rules/2014/*; tests/test_skill_tool_data.py
- Required tests: skill modifier tests; tool proficiency tests; expertise tests; missing data negative tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Add skill, tool, expertise, passive, and proficiency data plumbing required for deterministic noncombat resolution.

### WLD-03 Build exploration turn structure, time advancement, and light tracking

- Depends on: DBS-04
- Owner pool: `world_explore_a`
- Target modules: src/dnd_sim/world_contracts.py; src/dnd_sim/snapshot_store.py; tests/test_world_time_and_light.py
- Required tests: time advancement tests; light decay tests; turn structure tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/world_contracts.py with exploration turn structure, calendar/time advancement, and light source tracking.

### WLD-04 Build travel pace, navigation, foraging, resting, and day-cycle integration

- Depends on: WLD-03;WLD-01
- Owner pool: `world_explore_b`
- Target modules: src/dnd_sim/world_contracts.py; tests/test_travel_and_rest.py
- Required tests: travel pace tests; navigation tests; foraging tests; rest integration tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Implement travel pace, navigation outcomes, foraging, random encounter hooks, and resting/day-cycle integration in `src/dnd_sim/world_travel_service.py`.

### WLD-05 Build environmental exposure, falling, suffocation, drowning, disease, and poison world rules

- Depends on: WLD-03
- Owner pool: `world_hazards`
- Target modules: src/dnd_sim/world_hazards.py; src/dnd_sim/world_contracts.py; tests/test_world_hazards.py
- Required tests: falling tests; suffocation tests; drowning tests; environmental exposure tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/world_hazards.py and implement deterministic environmental hazard resolution and persistence.

### WLD-06 Build economy, loot, vendor inventory, and pricing model

- Depends on: DBS-04
- Owner pool: `world_economy_a`
- Target modules: src/dnd_sim/economy.py; src/dnd_sim/snapshot_store.py; tests/test_economy_and_loot.py
- Required tests: loot generation tests; vendor inventory tests; pricing tests; invalid purchase tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/economy.py and implement deterministic item pricing, loot flow, vendor inventory, and transaction handling.

### WLD-07 Build crafting, downtime, encumbrance, and service actions

- Depends on: WLD-06;WLD-02
- Owner pool: `world_economy_b`
- Target modules: src/dnd_sim/economy.py; src/dnd_sim/world_contracts.py; tests/test_crafting_and_downtime.py
- Required tests: crafting tests; downtime tests; encumbrance tests; service action tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Implement deterministic crafting, downtime activities, encumbrance handling, and service actions with persistent world effects.

### WLD-08 Build quest, faction, reputation, and world-flag lifecycle

- Depends on: DBS-05
- Owner pool: `world_state_a`
- Target modules: src/dnd_sim/world_state.py; src/dnd_sim/snapshot_store.py; tests/test_world_flags_and_factions.py
- Required tests: flag lifecycle tests; faction reputation tests; quest state tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/world_state.py and implement persistent quests, factions, reputations, and world-flag transitions.

### WLD-09 Build multi-encounter adventuring-day persistence and recovery flow

- Depends on: WLD-03;DBS-04;DBS-05
- Owner pool: `world_state_b`
- Target modules: src/dnd_sim/campaign_runtime.py; src/dnd_sim/snapshot_store.py; tests/test_adventuring_day_flow.py
- Required tests: multi-encounter persistence tests; short/long rest tests; resource carryover tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Create src/dnd_sim/campaign_runtime.py and persist party state across multiple encounters, rests, and world turns.

### WLD-10 Build encounter scripting, waves, objectives, and map hooks

- Depends on: DBS-05;ARC-08;WLD-08
- Owner pool: `world_script_a`
- Target modules: src/dnd_sim/encounter_script.py; src/dnd_sim/world_state.py; tests/test_encounter_scripts.py
- Required tests: wave progression tests; objective hook tests; map hook tests; invalid script tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md; docs/encounter_schema_full_example.json
- Exit criteria: Create src/dnd_sim/encounter_script.py and create docs/encounter_schema_full_example.json as a new encounter schema example for waves, objectives, scripted triggers, and map hooks.

### WLD-11 Hard-cut schema, import, and content IDs across all content classes

- Depends on: CAP-05;DBS-06
- Owner pool: `world_schema_a`
- Target modules: src/dnd_sim/io.py; src/dnd_sim/db_schema.py; db/rules/2014/*; tests/test_global_content_ids.py
- Required tests: content id uniqueness tests; import contract tests; migration tests
- Required docs: docs/program/roadmap_2014_backend.md; docs/program/status_board.md
- Exit criteria: Apply one canonical content ID model across characters, spells, feats, traits, monsters, items, and world objects; remove transitional ID aliases.

### WLD-12 Build performance harness, regression corpus, and world-scale replay diff suite

- Depends on: OBS-06;WLD-09;WLD-10;WLD-11
- Owner pool: `world_perf_a`
- Target modules: scripts/perf/run_world_regressions.py; tests/test_world_regression_harness.py; artifacts/world_regressions/
- Required tests: world regression tests; replay diff tests; performance baseline tests
- Required docs: docs/program/status_board.md; docs/review_checklist.md
- Exit criteria: Create a world-scale regression harness with deterministic replays, diffing, and recorded runtime baselines; fail CI when replay drift is unapproved or performance regresses above the stored threshold.

## Completion Gates

Run the final program gates and mark the backend complete only after docs, traces, manifests, AI, and world systems are green.

### FIN-01 Enforce program doc sync gate and purge stale live planning docs

- Depends on: DOC-02;DOC-03;DOC-05;DOC-06
- Owner pool: `integration_doc_gate`
- Target modules: docs/program/status_board.md; docs/program/backlog.csv; docs/program/README.md; docs/archive/
- Required tests: doc sync CI gate; stale live doc absence check
- Required docs: docs/program/status_board.md; docs/program/README.md; docs/archive/README.md
- Exit criteria: Block completion until live planning docs are synchronized, stale live plans are archived, and docs/program/README.md resolves every canonical artifact.

### FIN-02 Enforce full capability manifest green gate for shipped 2014 scope

- Depends on: CAP-06;FIX-07;WLD-11
- Owner pool: `integration_content_gate`
- Target modules: artifacts/capabilities/; tests/test_completion_capabilities.py
- Required tests: manifest completeness tests; supported-scope gate tests; unsupported reason coverage tests
- Required docs: docs/program/capability_report.md; docs/program/status_board.md
- Exit criteria: Block completion until every shipped 2014 content record is cataloged, schema_valid, and either executable plus tested or explicitly blocked with a single unsupported reason code.

### FIN-03 Enforce deterministic replay corpus gate across combat and world scenarios

- Depends on: OBS-07;WLD-12
- Owner pool: `integration_replay_gate`
- Target modules: artifacts/golden_traces/; artifacts/world_regressions/; tests/test_completion_replays.py
- Required tests: combat replay gate; world replay gate; diff approval path tests
- Required docs: docs/program/status_board.md; docs/review_checklist.md
- Exit criteria: Block completion until combat and world replay corpora pass under fixed seeds with no unapproved diffs.

### FIN-04 Enforce integrated campaign, world, and combat scenario gate

- Depends on: WLD-09;WLD-10;WLD-12;DBS-06
- Owner pool: `integration_world_gate`
- Target modules: tests/test_full_campaign_integration.py; artifacts/integration_campaigns/
- Required tests: campaign integration tests; encounter-wave integration tests; persistence reload tests
- Required docs: docs/program/status_board.md; docs/program/roadmap_2014_backend.md
- Exit criteria: Block completion until integrated scenarios prove combat, world turns, persistence, scripting, and recovery operate end-to-end.

### FIN-05 Enforce agent-only maintenance gate

- Depends on: ARC-08;OBS-07;DOC-06;FIN-01
- Owner pool: `integration_agent_gate`
- Target modules: docs/agent_index.yaml; src/dnd_sim/*.py; tests/test_agent_maintenance_contracts.py
- Required tests: module ownership coverage tests; structured error tests; trace availability tests; file-size threshold tests
- Required docs: docs/agent_index.yaml; docs/program/status_board.md; docs/program/doc_governance.md
- Exit criteria: Block completion until runtime modules have explicit ownership, structured errors, trace emission, and no hotspot file exceeds the declared size threshold.

### FIN-06 Cut release baseline, archive prior program artifacts, and mark backend complete

- Depends on: FIN-02;FIN-03;FIN-04;FIN-05
- Owner pool: `release_lead`
- Target modules: docs/program/status_board.md; docs/program/README.md; docs/archive/; tags/releases
- Required tests: final full-suite pass; release smoke tests; archive completeness check
- Required docs: docs/program/status_board.md; docs/program/README.md; docs/archive/README.md
- Exit criteria: Tag the completion baseline, archive superseded program artifacts, update status_board.md to merged/completed, and mark the backend complete only after every completion gate is green.
