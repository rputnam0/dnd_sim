# Roadmap: Full D&D 5e 2014 Backend and VTT Backbone Completion

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/README.md`

## Objective

Complete the simulator as a greenfield, feature-complete D&D 5e 2014 engine and world platform that is maintained primarily by agentic coding agents. Every delivery must optimize for explicit boundaries, deterministic behavior, machine-readable support status, structured errors, and replayable observability.

## Baseline already merged

- Waves 1 through 4 are baseline complete.
- The repo cleanup program is baseline complete.
- The legacy decommission program is baseline complete.

Treat all new work below as the active completion program.

## Renamed Wave 5

Rename the old Wave 5 from `Full Backend Systems` to:

**Wave 5 - Backbone Hardening, World Systems, and Completion**

Wave 5 is now split into nine ordered tracks:

- 5A Documentation Control
- 5B Runtime Decomposition
- 5C Capability Manifest
- 5D Replay, Logging, and Observability
- 5E Persistence and Query Model
- 5F Tactical AI Hardening
- 5G Rules Closure
- 5H World Systems and Campaign Platform
- 5I Completion Gates

## Mapping from old SYS tasks to the renamed Wave 5

- `SYS-01` maps to `WLD-01` and `WLD-02`.
- `SYS-02` maps to `WLD-03` and `WLD-04`.
- `SYS-03` maps to `WLD-05`.
- `SYS-04` maps to `WLD-06` and `WLD-07`.
- `SYS-05` maps to `DBS-04`, `DBS-05`, `WLD-08`, and `WLD-09`.
- `SYS-06` maps to `WLD-10`.
- `SYS-07` maps to `DBS-01`, `DBS-02`, `CAP-01`, and `WLD-11`.
- `SYS-08` maps to `OBS-06`, `OBS-07`, `WLD-12`, `FIN-02`, and `FIN-03`.

## Track definitions

### 5A Documentation Control

Purpose: remove stale planning surfaces, establish one canonical entrypoint, and fail CI on documentation drift.

Tasks:
- DOC-01 Establish canonical docs entrypoints and source-of-truth rules
- DOC-02 Archive stale planning and historical run artifacts
- DOC-03 Normalize status board and merged baseline history
- DOC-04 Add doc freshness metadata and registry
- DOC-05 Add doc consistency checker and CI gate
- DOC-06 Expand agent ownership map for target runtime boundaries

DOC-04 freshness contract:
- Every live planning markdown file carries `Status`, `Owner`, `Last updated`, and `Canonical source`.
- `docs/program/doc_governance.md` owns the registry for all live planning paths and owners.

### 5B Runtime Decomposition

Purpose: split the engine monolith into bounded runtime modules and make `engine.py` a stable orchestration facade.

Tasks:
- ARC-01 Extract simulation session and turn-loop orchestration from engine.py
- ARC-02 Extract turn declaration validation and legal action service
- ARC-03 Extract movement, routing, and spatial legality service
- ARC-04 Extract action resolution pipeline
- ARC-05 Extract effect lifecycle, condition state, and concentration graph service
- ARC-06 Extract reactions, interrupts, and ready-action window manager
- ARC-07 Extract spell execution pipeline and target resolution adapters
- ARC-08 Extract replay/reporting adapter layer and reduce engine.py to an orchestration facade

Current implementation note (2026-03-05):
- ARC-07 delegates spell declaration normalization, upcast handling, target adapters, and spell result application into `src/dnd_sim/spell_runtime.py` with dedicated `tests/test_spell_runtime.py` coverage.

Required structural outcome for 5B:
- `src/dnd_sim/engine.py` must be reduced below 3500 lines by `ARC-08`.
- No extracted runtime module may exceed 1500 lines without an explicit waiver recorded in `docs/agent_index.yaml`.
- The target module set for Wave 5B is:
  - `src/dnd_sim/engine_runtime.py`
  - `src/dnd_sim/action_legality.py`
  - `src/dnd_sim/movement_runtime.py`
  - `src/dnd_sim/action_resolution.py`
  - `src/dnd_sim/effects_runtime.py`
  - `src/dnd_sim/reaction_runtime.py`
  - `src/dnd_sim/spell_runtime.py`
  - `src/dnd_sim/replay.py`
  - `src/dnd_sim/reporting_runtime.py`

### 5C Capability Manifest

Purpose: make content support explicit and queryable for spells, feats, traits, monsters, and world objects.

Tasks:
- CAP-01 Define capability manifest schema, storage format, and CLI
- CAP-02 Generate spell capability manifest from canonical spell data
- CAP-03 Generate feat, trait, background, and species capability manifest
- CAP-04 Generate monster and monster-action capability manifest
- CAP-05 Enforce capability manifest gates in import paths and CI
- CAP-06 Publish machine-readable and markdown coverage reports

Capability states:
- `cataloged`
- `schema_valid`
- `executable`
- `tested`
- `blocked`
- `unsupported_reason`

CAP-01 canonical schema and storage contract:
- Canonical storage format is UTF-8 JSON with deterministic key ordering (`sort_keys=true`) and a trailing newline.
- Canonical manifest root fields are `manifest_version`, `generated_at`, and `records`.
- Every record must include `content_id`, `content_type`, and `states`.
- `states` must include `cataloged`, `schema_valid`, `executable`, `tested`, `blocked`, and `unsupported_reason`.
- `blocked=true` requires a non-empty `unsupported_reason`; `blocked=false` requires `unsupported_reason=null`.
- Canonical emission command is `uv run python -m dnd_sim.capability_manifest --input <source.json> --out artifacts/capabilities/<name>.manifest.json`.
- CLI emission must normalize record ordering by `(content_type, content_id)`.

### 5D Replay, Logging, and Observability

Purpose: emit full-turn traces, state deltas, AI rationale, resource deltas, RNG audits, invariant violations, and replay bundles.

Tasks:
- OBS-01 Introduce structured event schema and module-level loggers
- OBS-02 Emit turn declaration and action resolution traces
- OBS-03 Emit actor state delta and effect lifecycle traces
- OBS-04 Emit AI candidate scoring and rationale traces
- OBS-05 Emit resource delta, RNG audit, and invariant violation events
- OBS-06 Build replay bundle writer, loader, and diff harness
- OBS-07 Establish golden trace corpus and trace review gate

### 5E Persistence and Query Model

Purpose: replace shallow blob-centric persistence with canonical metadata tables and campaign/world state storage.

Tasks:
- DBS-01 Add canonical metadata tables for content and support records
- DBS-02 Add schema version, source lineage, and content hash persistence
- DBS-03 Add query APIs and CLI for support coverage, schema version, and lineage
- DBS-04 Add campaign state persistence schema and round-trip tests
- DBS-05 Add world flags, objectives, factions, and encounter state persistence schema
- DBS-06 Migrate existing JSON/blob content to the canonical metadata model

Current 5E status (2026-03-05):
- `DBS-01` and `DBS-02` are in PR review.
- `DBS-04` is in progress on `codex/feat/dbs-04-add-campaign-state-persistence-schema-and-round-tr` with `campaign_states` and `encounter_states` deterministic snapshot persistence under implementation and test.
- `DBS-05` is in PR review on `codex/feat/dbs-05-add-world-flags-objectives-factions-and-encounter` with `world_states` and `faction_states` deterministic world/objective/faction lifecycle persistence and tests in `tests/test_world_state_persistence.py`.
- `DBS-06` is in PR review on `codex/feat/dbs-06-migrate-existing-json-blob-content-to-the-canonica` with legacy JSON/blob backfill, rollback, and mixed canonical/legacy compatibility-read coverage in `tests/test_persistence_migrations.py`.

Required schema outcome for 5E:
- `content_records`
- `content_capabilities`
- `campaign_states`
- `encounter_states`
- `world_states`
- `faction_states`

DBS-01 canonical metadata contract:
- `content_records` must include `content_id`, `content_type`, `source_book`, `schema_version`, `source_hash`, and `payload_json`.
- `content_capabilities` must include `content_id`, `content_type`, `support_state`, `unsupported_reason`, and `last_verified_commit`.
- `content_capabilities.content_id` must reference `content_records.content_id` for canonical linkage between content payloads and support status.

### 5F Tactical AI Hardening

Purpose: upgrade AI from baseline heuristic action selection to traceable tactical play with hazard, control, retreat, and resource timing awareness.

Tasks:
- AI-01 Normalize candidate action enumeration and scoring inputs
- AI-02 Implement hazard, geometry, cover, and line-of-effect scoring
- AI-03 Implement concentration breaking, control value, and disable value scoring
- AI-04 Implement retreat, survival, objective race, and focus-fire tradeoff scoring
- AI-05 Implement recharge, legendary, reaction-bait, and limited-resource timing heuristics
- AI-06 Build benchmark corpus, tuning thresholds, and decision-quality gates

AI-04 status update (2026-03-05):
- Implemented candidate scoring dimensions for survival thresholds, retreat timing, objective-race urgency, ally rescue, and focus-fire tradeoffs in `src/dnd_sim/ai/scoring.py` with targeted coverage in `tests/test_ai_objective_scoring.py`.

### 5G Rules Closure

Purpose: close the remaining rules gaps and move the review checklist to green.

Tasks:
- FIX-01 Close Lucky attacker, defender, and saving throw correctness
- FIX-02 Close Great Weapon Master and Sharpshooter toggle correctness
- FIX-03 Close Shield Master reaction, save, and shove correctness
- FIX-04 Close War Caster opportunity casting and concentration correctness
- FIX-05 Close Mage Slayer and Sentinel reaction constraints
- FIX-06 Close Rage damage, resistance, and illegal state edge cases
- FIX-07 Integrate hazard-aware strategy scoring and close the review checklist

### 5H World Systems and Campaign Platform

Purpose: deliver the noncombat, exploration, economy, world-state, and campaign platform that makes the simulator full-featured beyond combat.

Tasks:
- WLD-01 Build ability check, contest, passive, and DC resolution core
- WLD-02 Build skill, tool, proficiency, and specialist data plumbing
- WLD-03 Build exploration turn structure, time advancement, and light tracking
- WLD-04 Build travel pace, navigation, foraging, resting, and day-cycle integration
- WLD-05 Build environmental exposure, falling, suffocation, drowning, disease, and poison world rules
- WLD-06 Build economy, loot, vendor inventory, and pricing model
- WLD-07 Build crafting, downtime, encumbrance, and service actions
- WLD-08 Build quest, faction, reputation, and world-flag lifecycle
- WLD-09 Build multi-encounter adventuring-day persistence and recovery flow
- WLD-10 Build encounter scripting, waves, objectives, and map hooks
- WLD-11 Hard-cut schema, import, and content IDs across all content classes
- WLD-12 Build performance harness, regression corpus, and world-scale replay diff suite

Current execution note:
- WLD-01 is in progress on `codex/feat/wld-01-build-ability-check-contest-passive-and-dc-resolut`.
- WLD-02 is in progress on `codex/feat/wld-02-build-skill-tool-proficiency-and-specialist-data-p`.
- WLD-03 is in progress on `codex/feat/wld-03-build-exploration-turn-structure-time-advancement` with exploration turn, world time advancement, and light tracking runtime coverage in `tests/test_world_time_and_light.py`.

### 5I Completion Gates

Purpose: enforce the final blocking gates that decide whether the backend is complete.

Tasks:
- FIN-01 Enforce program doc sync gate and purge stale live planning docs
- FIN-02 Enforce full capability manifest green gate for shipped 2014 scope
- FIN-03 Enforce deterministic replay corpus gate across combat and world scenarios
- FIN-04 Enforce integrated campaign, world, and combat scenario gate
- FIN-05 Enforce agent-only maintenance gate
- FIN-06 Cut release baseline, archive prior program artifacts, and mark backend complete

## Global contract for every task

Every task PR must include all of the following:

- code changes,
- direct unit tests,
- integration or golden tests,
- negative or invalid-input tests,
- deterministic seed stability unless the task intentionally changes rules behavior,
- doc updates for every touched live planning file,
- migration notes for any schema or public API change,
- `docs/agent_index.yaml` updates when runtime boundaries change,
- structured telemetry coverage when runtime behavior changes.

## Definition of complete backend

Mark the backend complete only when all of the following are true:

- A legal turn is fully declarable and validated through the public API.
- 2014 combat legality and timing windows are enforced.
- Character, item, spell, feat, monster, and world content are canonicalized, queryable, and data-driven.
- Campaign persistence and multi-encounter adventuring-day flow work.
- Noncombat, exploration, world-state, and economy systems work.
- Capability manifests are green for the shipped 2014 scope.
- Replay corpora prove deterministic stability.
- AI benchmark gates pass with full rationale traces.
- Documentation is synchronized and stale live plans are purged.
