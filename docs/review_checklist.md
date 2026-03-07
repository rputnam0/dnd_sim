# Implementation Review Checklist

Status: canonical  
Owner: integration-review  
Last updated: 2026-03-06  
Canonical source: `docs/program/status_board.md`

This checklist is the program closeout gate. Do not mark the backend complete until every item is checked in the repository.

Wave 5 closeout items below are historical baseline state. Wave 6 remediation items must also be complete before re-affirming final completion.

## Documentation Control

- [x] DOC-01 canonical docs entrypoints are in place.
- [x] DOC-02 stale planning and historical run artifacts are archived or explicitly marked historical.
- [x] DOC-03 status board reflects the merged baseline and the current backlog.
- [x] DOC-04 live planning docs have metadata headers and ownership.
- [x] DOC-05 doc consistency CI gate is green.
- [x] DOC-06 `docs/agent_index.yaml` covers every live runtime boundary.

## Runtime Decomposition

- [x] ARC-01 session and turn-loop orchestration extracted.
- [x] ARC-02 turn declaration validation extracted.
- [x] ARC-03 movement and spatial legality extracted.
- [x] ARC-04 action resolution extracted.
- [x] ARC-05 effect lifecycle and concentration graph extracted.
- [x] ARC-06 reactions and ready-action window manager extracted.
- [x] ARC-07 spell execution pipeline extracted.
- [x] ARC-08 replay/reporting adapters extracted and `engine.py` reduced below the declared limit.

## Capability Manifest

- [x] CAP-01 Define capability manifest schema, storage format, and CLI
- [x] CAP-02 Generate spell capability manifest from canonical spell data
- [x] CAP-03 Generate feat, trait, background, and species capability manifest
- [x] CAP-04 Generate monster and monster-action capability manifest
- [x] CAP-05 Enforce capability manifest gates in import paths and CI
- [x] CAP-06 Publish machine-readable and markdown coverage reports

## Rules Closure

- [x] FIX-01 Close Lucky attacker, defender, and saving throw correctness
- [x] FIX-02 Close Great Weapon Master and Sharpshooter toggle correctness
- [x] FIX-03 Close Shield Master reaction, save, and shove correctness
- [x] FIX-04 Close War Caster opportunity casting and concentration correctness
- [x] FIX-05 Close Mage Slayer and Sentinel reaction constraints
- [x] FIX-06 Close Rage damage, resistance, and illegal state edge cases
- [x] FIX-07 Integrate hazard-aware strategy scoring and close the review checklist

## Tactical AI Hardening

- [x] AI-01 Normalize candidate action enumeration and scoring inputs
- [x] AI-02 Implement hazard, geometry, cover, and line-of-effect scoring
- [x] AI-03 Implement concentration breaking, control value, and disable value scoring
- [x] AI-04 Implement retreat, survival, objective race, and focus-fire tradeoff scoring
- [x] AI-05 Implement recharge, legendary, reaction-bait, and limited-resource timing heuristics
- [x] AI-06 Build benchmark corpus, tuning thresholds, and decision-quality gates

## Replay, Logging, and Observability

- [x] OBS-01 Introduce structured event schema and module-level loggers
- [x] OBS-02 Emit turn declaration and action resolution traces
- [x] OBS-03 Emit actor state delta and effect lifecycle traces
- [x] OBS-04 Emit AI candidate scoring and rationale traces
- [x] OBS-05 Emit resource delta, RNG audit, and invariant violation events
- [x] OBS-06 Build replay bundle writer, loader, and diff harness
- [x] OBS-07 Establish golden trace corpus and trace review gate

## Persistence and Query Model

- [x] DBS-01 Add canonical metadata tables for content and support records
- [x] DBS-02 Add schema version, source lineage, and content hash persistence
- [x] DBS-03 Add query APIs and CLI for support coverage, schema version, and lineage
- [x] DBS-04 Add campaign state persistence schema and round-trip tests
- [x] DBS-05 Add world flags, objectives, factions, and encounter state persistence schema
- [x] DBS-06 Migrate existing JSON/blob content to the canonical metadata model

## World Systems and Campaign Platform

- [x] WLD-01 Build ability check, contest, passive, and DC resolution core
- [x] WLD-02 Build skill, tool, proficiency, and specialist data plumbing
- [x] WLD-03 Build exploration turn structure, time advancement, and light tracking
- [x] WLD-04 Build travel pace, navigation, foraging, resting, and day-cycle integration
- [x] WLD-05 Build environmental exposure, falling, suffocation, drowning, disease, and poison world rules
- [x] WLD-06 Build economy, loot, vendor inventory, and pricing model
- [x] WLD-07 Build crafting, downtime, encumbrance, and service actions
- [x] WLD-08 Build quest, faction, reputation, and world-flag lifecycle
- [x] WLD-09 Build multi-encounter adventuring-day persistence and recovery flow
- [x] WLD-10 Build encounter scripting, waves, objectives, and map hooks
- [x] WLD-11 Hard-cut schema, import, and content IDs across all content classes
- [x] WLD-12 Build performance harness, regression corpus, and world-scale replay diff suite

## Completion Gates

- [x] FIN-01 Enforce program doc sync gate and purge stale live planning docs
- [x] FIN-02 Enforce full capability manifest green gate for shipped 2014 scope
- [x] FIN-03 Enforce deterministic replay corpus gate across combat and world scenarios
- [x] FIN-04 Enforce integrated campaign, world, and combat scenario gate
- [x] FIN-05 Enforce agent-only maintenance gate
- [x] FIN-06 Cut release baseline, archive prior program artifacts, and mark backend complete

## Wave 6 Remediation

- [x] W6-CUT-01 Hard-cut engine facade to explicit API (merged to `int/6a-hard-cut` via #167)
- [x] W6-CUT-02 Relocate legacy helpers and remove `engine_legacy.py` (merged to `int/6a-hard-cut` via #169)
- [x] W6-CUT-03 Hard-cut strategy API to declare_turn-only contract (merged to `int/6a-hard-cut` via #162)
- [x] W6-CUT-04 Decompose io.py into focused modules (merged to `int/6a-hard-cut` via #165)
- [x] W6-UNI-01 Restore canonical DB API surface (merged to `int/6b-unification` via #166)
- [x] W6-UNI-02 Implement canonical snapshot APIs (merged to `int/6b-unification` via #170)
- [x] W6-UNI-03 Unify replay schema to replay.v1 (merged to `int/6b-unification` via #164)
- [x] W6-UNI-04 Canonicalize AI rejection reason API (merged to `int/6b-unification` via #163)
- [x] W6-PAR-01 Hard-cut capability manifest schema to CAP-01 canonical shape (merged to `int/6c-parity` via #168)
- [x] W6-PAR-02 Add strict FIN-02 enforcement mode (merged to `int/6c-parity` via #173)
- [x] W6-PAR-03 Execute parity closure shard batch (merged to `int/6c-parity` via #171/#174/#175/#176/#177/#178)
- [x] W6-PAR-04 Execute parity continuation shard batch B and strict-input manifest sync (merged via #185/#186/#187/#188/#189/#190)
- [x] W6-PAR-05A Umbrella row for baseline truth sync and leaf registry (merged to `codex/int/w6-parity-closeout` via #201)
- [x] W6-PAR-05A1 Reconcile canonical parity surfaces to the 1225-blocker baseline and add `docs/program/parity_leaf_registry.csv` (merged to `codex/int/w6-parity-closeout` via #201)
- [ ] BATCH-00 Sync batch truth and register `docs/program/parity_batch_registry.csv`
- [x] W6-PAR-05B Umbrella row for background meta closeout leaves
- [x] W6-PAR-05B1 Background meta closeout leaf
- [x] W6-PAR-05C Umbrella row for passive species meta leaves
- [x] W6-PAR-05C1 Passive/meta species closeout leaf
- [x] W6-PAR-05D Umbrella row for active species effect leaves
- [x] W6-PAR-05D1 Active/effect species closeout leaf
- [x] W6-PAR-05E Umbrella row for trait meta leaves
- [x] W6-PAR-05E1 Trait meta options/proficiencies leaf
- [x] W6-PAR-05E2 Trait social/access/support meta leaf
- [x] W6-PAR-05F Umbrella row for passive combat trait leaves
- [x] W6-PAR-05F1 Trait passive defense/support leaf (closed via continuation PRs #221 and #225)
- [x] W6-PAR-05F1B Trait passive defense/support finalization continuation (merged via #225)
- [x] W6-PAR-05F2 Trait passive offense/mobility leaf
- [ ] W6-PAR-05G Umbrella row for reaction/resource trait leaves (live batches G1-A through G1-D remain)
- [ ] W6-PAR-05G1 Trait reaction/retaliation leaf (38 live blockers batched as G1-A through G1-D)
- [x] W6-PAR-05G1C Trait reaction/support follow-up slice (merged via #224)
- [x] W6-PAR-05G1D Trait survival/recovery support continuation leaf (merged via #226)
- [x] W6-PAR-05G2 Trait resource-change/turn-gated leaf
- [ ] G1-A First 10-item trait reaction/retaliation batch
- [ ] G1-B Second 10-item trait reaction/retaliation batch (PR #231)
- [ ] G1-C Third 10-item trait reaction/retaliation batch
- [ ] G1-D Final 8-item trait reaction/retaliation batch
- [x] W6-PAR-05H Umbrella row for summon/transform trait leaves
- [x] W6-PAR-05H1 Trait summon/companion/mount leaf
- [x] W6-PAR-05H2 Trait transform/world-linked leaf
- [x] W6-PAR-05I Umbrella row for spell mechanics damage/support leaves
- [x] W6-PAR-05I1 Spell damage/heal/condition mechanics leaf
- [x] W6-PAR-05I2 Spell buff/debuff/mark mechanics leaf (merged via #227)
- [ ] W6-PAR-05J Umbrella row for summon/control/utility spell leaves (live batches J1-A through J1-D and J2-A through J2-F remain)
- [ ] W6-PAR-05J1 Spell summon/command/control mechanics leaf (39 live blockers batched as J1-A through J1-D)
- [ ] J1-A First 10-item summon/command/control spell batch
- [ ] J1-B Second 10-item summon/command/control spell batch
- [ ] J1-C Third 10-item summon/command/control spell batch
- [ ] J1-D Final 9-item summon/command/control spell batch
- [ ] W6-PAR-05J2 Spell hazard/zone/utility mechanics leaf (60 live blockers batched as J2-A through J2-F)
- [ ] J2-A First 10-item hazard/zone/utility spell batch
- [ ] J2-B Second 10-item hazard/zone/utility spell batch
- [ ] J2-C Third 10-item hazard/zone/utility spell batch
- [ ] J2-D Fourth 10-item hazard/zone/utility spell batch
- [ ] J2-E Fifth 10-item hazard/zone/utility spell batch
- [ ] J2-F Final 10-item hazard/zone/utility spell batch
- [x] W6-PAR-05K Umbrella row for spell effect-family normalization leaves
- [x] W6-PAR-05K1 Normalize blocked unsupported spell effect payloads to existing canonical families
- [x] W6-PAR-05K2 Add residual canonical effect-family support after normalization pass
- [x] W6-PAR-05L Umbrella row for spell schema repair leaves
- [x] W6-PAR-05L1 Repair invalid mechanics schema blockers
- [x] W6-PAR-05L2 Convert non-executable mechanics blockers into executable canonical payloads
- [ ] W6-PAR-05M Final strict closeout and parity integration merge
- [x] W6-GATE-01 Sync docs/backlog/checklist truth and maintenance waivers for remediation state (merged via #172)
- [x] W6-GATE-02 Final green gate and closeout pass (merged via #183)


## Final review gate

- [x] Full `uv run python -m pytest` passes.
- [x] Deterministic replay corpus passes.
- [x] Capability manifest gate passes.
- [x] Campaign/world/combat integration gate passes.
- [x] Agent-only maintenance gate passes.
- [ ] Strict FIN-02 parity gate (`verify_completion_capabilities.py --strict`) passes with blocked=0.
- [x] `docs/program/status_board.md` and `docs/program/backlog.csv` are synchronized for the active Wave 6 remediation state.
