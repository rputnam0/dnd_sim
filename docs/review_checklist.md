# Implementation Review Checklist

Status: canonical  
Owner: integration-review  
Last updated: 2026-03-05  
Canonical source: `docs/program/status_board.md`

This checklist is the program closeout gate. Do not mark the backend complete until every item is checked in the repository.

## Documentation Control

- [ ] DOC-01 canonical docs entrypoints are in place.
- [ ] DOC-02 stale planning and historical run artifacts are archived or explicitly marked historical.
- [ ] DOC-03 status board reflects the merged baseline and the current backlog.
- [ ] DOC-04 live planning docs have metadata headers and ownership.
- [ ] DOC-05 doc consistency CI gate is green.
- [ ] DOC-06 `docs/agent_index.yaml` covers every live runtime boundary.

## Runtime Decomposition

- [ ] ARC-01 session and turn-loop orchestration extracted.
- [ ] ARC-02 turn declaration validation extracted.
- [ ] ARC-03 movement and spatial legality extracted.
- [ ] ARC-04 action resolution extracted.
- [ ] ARC-05 effect lifecycle and concentration graph extracted.
- [ ] ARC-06 reactions and ready-action window manager extracted.
- [ ] ARC-07 spell execution pipeline extracted.
- [ ] ARC-08 replay/reporting adapters extracted and `engine.py` reduced below the declared limit.

## Capability Manifest

- [ ] CAP-01 Define capability manifest schema, storage format, and CLI
- [ ] CAP-02 Generate spell capability manifest from canonical spell data
- [ ] CAP-03 Generate feat, trait, background, and species capability manifest
- [ ] CAP-04 Generate monster and monster-action capability manifest
- [ ] CAP-05 Enforce capability manifest gates in import paths and CI
- [ ] CAP-06 Publish machine-readable and markdown coverage reports

## Rules Closure

- [ ] FIX-01 Close Lucky attacker, defender, and saving throw correctness
- [ ] FIX-02 Close Great Weapon Master and Sharpshooter toggle correctness (active on `codex/feat/fix-02-close-great-weapon-master-and-sharpshooter-toggle`)
- [x] FIX-03 Close Shield Master reaction, save, and shove correctness
- [ ] FIX-04 Close War Caster opportunity casting and concentration correctness (in review on [#124](https://github.com/rputnam0/dnd_sim/pull/124))
- [ ] FIX-05 Close Mage Slayer and Sentinel reaction constraints (in review on [#114](https://github.com/rputnam0/dnd_sim/pull/114))
- [ ] FIX-06 Close Rage damage, resistance, and illegal state edge cases (active on `codex/feat/fix-06-close-rage-damage-resistance-and-illegal-state-edg`)
- [ ] FIX-07 Integrate hazard-aware strategy scoring and close the review checklist (active on `codex/feat/fix-07-integrate-hazard-aware-strategy-scoring-and-close`)

Current in-progress focus: `FIX-01`, `FIX-02`, `FIX-06`, and `FIX-07` on their assigned codex feature branches for rules-closure correctness.
Checklist closure rule: keep `FIX-07` unchecked until every `FIX-*` row in `docs/program/backlog.csv` is `merged`.

## Tactical AI Hardening

- [ ] AI-01 Normalize candidate action enumeration and scoring inputs
- [ ] AI-02 Implement hazard, geometry, cover, and line-of-effect scoring
- [ ] AI-03 Implement concentration breaking, control value, and disable value scoring
- [ ] AI-04 Implement retreat, survival, objective race, and focus-fire tradeoff scoring
- [ ] AI-05 Implement recharge, legendary, reaction-bait, and limited-resource timing heuristics
- [ ] AI-06 Build benchmark corpus, tuning thresholds, and decision-quality gates

## Replay, Logging, and Observability

- [ ] OBS-01 Introduce structured event schema and module-level loggers
- [ ] OBS-02 Emit turn declaration and action resolution traces
- [ ] OBS-03 Emit actor state delta and effect lifecycle traces
- [ ] OBS-04 Emit AI candidate scoring and rationale traces
- [ ] OBS-05 Emit resource delta, RNG audit, and invariant violation events
- [ ] OBS-06 Build replay bundle writer, loader, and diff harness
- [ ] OBS-07 Establish golden trace corpus and trace review gate

## Persistence and Query Model

- [ ] DBS-01 Add canonical metadata tables for content and support records
- [ ] DBS-02 Add schema version, source lineage, and content hash persistence
- [ ] DBS-03 Add query APIs and CLI for support coverage, schema version, and lineage
- [ ] DBS-04 Add campaign state persistence schema and round-trip tests
- [ ] DBS-05 Add world flags, objectives, factions, and encounter state persistence schema
- [ ] DBS-06 Migrate existing JSON/blob content to the canonical metadata model

## World Systems and Campaign Platform

- [ ] WLD-01 Build ability check, contest, passive, and DC resolution core
- [ ] WLD-02 Build skill, tool, proficiency, and specialist data plumbing
- [ ] WLD-03 Build exploration turn structure, time advancement, and light tracking
- [ ] WLD-04 Build travel pace, navigation, foraging, resting, and day-cycle integration
- [ ] WLD-05 Build environmental exposure, falling, suffocation, drowning, disease, and poison world rules
- [ ] WLD-06 Build economy, loot, vendor inventory, and pricing model
- [ ] WLD-07 Build crafting, downtime, encumbrance, and service actions
- [ ] WLD-08 Build quest, faction, reputation, and world-flag lifecycle
- [ ] WLD-09 Build multi-encounter adventuring-day persistence and recovery flow
- [ ] WLD-10 Build encounter scripting, waves, objectives, and map hooks
- [ ] WLD-11 Hard-cut schema, import, and content IDs across all content classes
- [ ] WLD-12 Build performance harness, regression corpus, and world-scale replay diff suite

## Completion Gates

- [ ] FIN-01 Enforce program doc sync gate and purge stale live planning docs
- [ ] FIN-02 Enforce full capability manifest green gate for shipped 2014 scope
- [ ] FIN-03 Enforce deterministic replay corpus gate across combat and world scenarios
- [ ] FIN-04 Enforce integrated campaign, world, and combat scenario gate
- [ ] FIN-05 Enforce agent-only maintenance gate
- [ ] FIN-06 Cut release baseline, archive prior program artifacts, and mark backend complete


## Final review gate

- [ ] Full `uv run python -m pytest` passes.
- [ ] Deterministic replay corpus passes.
- [ ] Capability manifest gate passes.
- [ ] Campaign/world/combat integration gate passes.
- [ ] Agent-only maintenance gate passes.
- [ ] `docs/program/status_board.md` and `docs/program/backlog.csv` are synchronized.
