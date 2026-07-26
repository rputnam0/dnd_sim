# Trustworthy D&D Engine Implementation Checklist

Status: working implementation plan  
Owner: engine-foundation  
Last updated: 2026-07-26  
Product roadmap: `docs/roadmap/README.md`

## Objective

Build a deterministic, auditable D&D 5e-2014 headless game engine that first supports
trustworthy encounter simulation and then exposes stable session contracts for VTT and CRPG
adapters.

This checklist is the implementation companion to the product roadmap. It does not replace the
repository's canonical program-control documents. Items are checked only after their tests pass
and their implementation is included in a pull request.

## Delivery order

### Milestone 0 — Simulation truth gate

- [ ] Every shipped public scenario executes in CI.
- [ ] Tactical strategies and authoritative legality share one reachability contract.
- [ ] Encounter results distinguish victory, defeat, draw, and timeout/censored outcomes.
- [ ] NPC and PC zero-hit-point policies are explicit and rules-profile driven.
- [ ] Unknown mechanic types fail validation with a path-specific diagnostic.
- [ ] Actionless production monsters fail validation instead of receiving a synthetic attack.
- [ ] Capability states are derived independently and `tested` links to behavioral evidence.
- [ ] Strict mechanics coverage is a required CI gate for the declared supported content pack.

### Milestone 1 — Executable rules and content pack

- [ ] Publish a versioned supported-rules profile for 5e-2014 combat.
- [ ] Populate executable monster actions, traits, defenses, spellcasting, and recharge behavior.
- [ ] Implement typed triggers, conditions, auras, zones, summons, transformations, and choices.
- [ ] Complete combat-relevant spell semantics and upcasting.
- [ ] Complete class/subclass combat features by level.
- [ ] Complete core conditions, creature size/space, movement modes, grappling, and cover.
- [ ] Model qualified defenses, rests, dying, stabilization, and NPC defeat policy.
- [ ] Add independently adjudicated rules-conformance and golden encounter tests.

### Milestone 2 — Defensible encounter difficulty

- [ ] Extract a pure `run_trial(seed, scenario, policies)` boundary.
- [ ] Derive and record independent deterministic seeds for every trial.
- [ ] Implement complete action, bonus-action, movement, reaction, and resource planning.
- [ ] Ship novice, typical, conservative, and optimized tactical policy profiles.
- [ ] Report win, TPK, death, down, timeout, remaining-HP, resource, and round distributions.
- [ ] Add confidence intervals, convergence diagnostics, and adaptive sample-size targets.
- [ ] Add tactical-policy and parameter-sensitivity envelopes.
- [ ] Calibrate against analytical microcases, independent adjudications, and playtest data.

### Milestone 3 — Creator-safe homebrew platform

- [ ] Version strict schemas for actors, actions, effects, encounters, maps, and objectives.
- [ ] Add content-pack manifests, dependencies, version pins, and migrations.
- [ ] Provide a declarative mechanic registry/DSL with no silent fallback behavior.
- [ ] Provide validator diagnostics, import/export, and round-trip tests.
- [ ] Provide encounter, monster, party, and report builder APIs.
- [ ] Recreate a complex boss encounter entirely through public data without Python hooks.

### Milestone 4 — Reusable authoritative session kernel

- [ ] Introduce serializable `EncounterState` and versioned command schemas.
- [ ] Route every authoritative mutation through legality, resolution, and event contracts.
- [ ] Introduce deterministic domain events and a state reducer.
- [ ] Support inspect, preview, commit, reaction, advance, snapshot, restore, and replay.
- [ ] Record rules, content, strategy, engine, and RNG versions in every session/replay.
- [ ] Decompose batch orchestration from combat resolution and campaign services.

### Milestone 5 — VTT adapter

- [ ] Add authoritative multiplayer session and transport services.
- [ ] Add command sequencing, idempotency, authorization, reconnect, and state deltas.
- [ ] Add map, wall, door, token footprint, ownership, fog-of-war, chat, and asset models.
- [ ] Add tactical player/GM read models and encounter-editing APIs.

### Milestone 6 — CRPG adapter

- [ ] Add scene, dialogue, quest, interaction, navigation, and area-transition domains.
- [ ] Add NPC/party behavior, bounded AI-DM integration, and authored fallback behavior.
- [ ] Add durable save migrations and content/module lifecycle support.
- [ ] Add renderer-neutral presentation, input, animation, audio, and asset contracts.

## Current implementation slice

Branch: `codex/trustworthy-engine-foundation`

The first pull request is limited to Milestone 0. It must include red/green regression evidence
for the shipped scenario, terminal outcome semantics, strict mechanic validation, monster fallback
removal, and truthful capability gates. Broader rules content and session APIs follow in separate
feature branches after this trust gate is reviewable.

## Required verification for Milestone 0

```bash
uv run python -m pytest <targeted regression paths>
uv run python scripts/mechanics_coverage.py --strict --supported-pack db/rules/2014/supported_packs/combat_primitives_v0.json
uv run python scripts/content/verify_completion_capabilities.py
uv run python scripts/content/verify_completion_capabilities.py --supported-pack db/rules/2014/supported_packs/combat_primitives_v0.json
uv run python scripts/docs/verify_program_docs.py
uv run python -m black --check .
uv run python -m pytest
```

The legacy all-shipped `--strict` capability and mechanics modes remain intentionally red until
every canonical record is implemented and evidenced. They are audit tools, not the declared-pack
release gate.
