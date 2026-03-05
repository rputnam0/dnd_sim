# Implementation Review Checklist

Status: canonical  
Owner: integration-review  
Last updated: 2026-03-05  
Canonical source: `docs/program/status_board.md`

This checklist is the program closeout gate. Do not mark the backend complete until every item is checked in the repository.

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


## Final review gate

- [x] Full `uv run python -m pytest` passes.
- [x] Deterministic replay corpus passes.
- [x] Capability manifest gate passes.
- [x] Campaign/world/combat integration gate passes.
- [x] Agent-only maintenance gate passes.
- [x] `docs/program/status_board.md` and `docs/program/backlog.csv` are synchronized for the merged completion wave.
