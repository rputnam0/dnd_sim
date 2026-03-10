# Roadmap: Full D&D 5e 2014 Backend and VTT Backbone Completion

Status: canonical  
Owner: program-control  
Last updated: 2026-03-09  
Canonical source: `docs/program/README.md`

## Objective

Stabilize the simulator as an authoritative D&D 5e 2014 engine and campaign core that can safely grow toward the Part 1 product. Every delivery must optimize for explicit boundaries, deterministic behavior, machine-readable support status, structured errors, and replayable observability.

Current program rule: do not describe the repository as the complete Part 1 product backend while Wave 8 is active. Wave 8 exists to finish Section 2 stabilization before AI DM, dialogue, live session, and creator-tooling expansion.

## Baseline already merged

- Waves 1 through 4 are baseline complete.
- The repo cleanup program is baseline complete.
- The legacy decommission program is baseline complete.

Treat all new work below as the active completion program.

## Wave 8 stabilization (active)

Wave 8 is the live program wave and maps directly to Section 2 of the product roadmap.

Wave 8 objective:

- keep the current deterministic kernel green and truthful,
- remove machine-local assumptions from live content and tools,
- split creator/public content from internal executable harnesses,
- narrow core runtime responsibilities and record truthful waivers,
- harden persistence/data-integrity contracts before later product expansion.

Wave 8 workstreams:

- 8A Truthful Baseline and Section 1 Gap Audit
- 8B Portability and Environment Hardening
- 8C Creator-Boundary Hardening
- 8D Core Contract Decomposition
- 8E Persistence and Data Integrity Hardening
- 8F Section 2 Gates and Closeout

Wave 8 non-goals:

- building the governed AI DM runtime,
- authored dialogue/cinematic conversation systems,
- live browser-session or multiplayer service architecture,
- creator editor/publishing tooling,
- claiming the Part 1 one-shot product fantasy is already complete.

## Wave 7 closeout (merged)

Wave 6 remains historically complete for its declared strict shipped-2014 parity scope.  
Wave 7 is merged and closes the last CRPG-core surfaces that were not yet first-class:

- canonical itemization (`item` catalogs and runtime item execution),
- canonical class/subclass progression (`class` and `subclass` catalogs),
- stealth/search/trap/lock interaction loops with deterministic persistence.

Wave 7 tracks (all merged):

- 7A Itemization hard-cut (`W7-ITM-01` through `W7-ITM-04`)
- 7B Class/subclass hard-cut (`W7-CLS-01` through `W7-CLS-04`)
- 7C Stealth and dungeon interaction (`W7-EXP-01` through `W7-EXP-04`)
- 7D Gates and closeout (`W7-GATE-01` through `W7-GATE-03`)

Wave 7 delivered `5e + CRPG core`: full 2014 rules parity plus deterministic progression, itemization, stealth/search/trap interaction, persistence, and replayable world-state behavior.  
Dialogue trees, cinematic conversations, and cutscene tooling remain out of scope for this wave.

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

Completion-state note (2026-03-05):
- ARC-07 runtime decomposition outcome: spell declaration normalization, upcast handling, target adapters, and spell result application are delegated into `src/dnd_sim/spell_runtime.py` with dedicated `tests/test_spell_runtime.py` coverage.

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

Completion-state note (2026-03-05):
- Canonical metadata and lineage outcomes are captured through `content_records` and `content_capabilities` plus lineage fields (`schema_version`, `source_path`, `source_hash`, `canonicalization_hash`, `imported_at`) in the persistence schema contract.
- Legacy JSON/blob migration outcomes are captured with canonical backfill, rollback coverage, and compatibility-read validation in `tests/test_persistence_migrations.py`.
- Task lifecycle state is tracked canonically in `docs/program/backlog.csv` and surfaced in `docs/program/status_board.md`.

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

AI-04 completion note (2026-03-05):
- Candidate scoring dimensions for survival thresholds, retreat timing, objective-race urgency, ally rescue, and focus-fire tradeoffs are implemented in `src/dnd_sim/ai/scoring.py` with targeted coverage in `tests/test_ai_objective_scoring.py`.

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

Completion-state note (2026-03-05):
- Exploration turn, time advancement, and light-tracking outcomes are covered in `tests/test_world_time_and_light.py`.
- Economy, loot, vendor inventory, and pricing outcomes are covered in `tests/test_economy_and_loot.py`.
- Crafting, downtime, encumbrance, and service-action outcomes are covered in `tests/test_crafting_and_downtime.py`.
- Multi-encounter adventuring-day persistence and recovery outcomes are covered in `tests/test_adventuring_day_flow.py`.
- Global content ID/schema/import hard-cut outcomes are covered in `tests/test_global_content_ids.py`.
- Branch/task lifecycle state remains canonical in `docs/program/backlog.csv` and `docs/program/status_board.md`.

### 5I Completion Gates

Purpose: enforce the final blocking gates that decide whether the backend is complete.

Tasks:
- FIN-01 Enforce program doc sync gate and purge stale live planning docs
- FIN-02 Enforce full capability manifest green gate for shipped 2014 scope
- FIN-03 Enforce deterministic replay corpus gate across combat and world scenarios
- FIN-04 Enforce integrated campaign, world, and combat scenario gate
- FIN-05 Enforce agent-only maintenance gate
- FIN-06 Cut release baseline, archive prior program artifacts, and mark backend complete

Completion-state note (2026-03-05):
- The FIN track is represented as completion gates (docs sync, capability manifest, deterministic replay corpus, integrated campaign/world/combat scenarios, agent-maintenance invariants, and final release baseline cutover) rather than branch-level execution notes.
- Gate lifecycle and dependency ordering remain canonical in `docs/program/backlog.csv` and `docs/program/status_board.md`.

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
- Character, class, subclass, item, spell, feat, monster, and world content are canonicalized, queryable, and data-driven.
- Campaign persistence and multi-encounter adventuring-day flow work.
- Noncombat, exploration, world-state, and economy systems work.
- Stealth, surprise, search, trap, lock, and container interaction loops are deterministic and replayable.
- Capability manifests are green for the shipped 2014 scope.
- Replay corpora prove deterministic stability.
- AI benchmark gates pass with full rationale traces.
- Documentation is synchronized and stale live plans are purged.
