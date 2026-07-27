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

- [x] Every shipped public scenario executes in CI.
- [x] Tactical strategies and authoritative legality share one reachability contract.
- [x] Encounter results distinguish victory, defeat, draw, and timeout/censored outcomes.
- [x] NPC and PC zero-hit-point policies are explicit and rules-profile driven.
- [x] Unknown mechanic types fail validation with a path-specific diagnostic.
- [x] Actionless production monsters fail validation instead of receiving a synthetic attack.
- [x] Capability states are derived independently and `tested` links to behavioral evidence.
- [x] Strict mechanics coverage is a required CI gate for the declared supported content pack.

### Milestone 1 — Executable rules and content pack

- [x] Publish a versioned supported-rules profile for 5e-2014 combat.
- [ ] Populate executable monster actions, traits, defenses, spellcasting, and recharge behavior.
- [ ] Implement typed triggers, conditions, auras, zones, summons, transformations, and choices.
- [ ] Complete combat-relevant spell semantics and upcasting.
- [ ] Complete class/subclass combat features by level.
- [ ] Complete core conditions, creature size/space, movement modes, grappling, and cover.
- [x] Model dying, stabilization, stable recovery, and NPC defeat policy.
- [x] Resolve immediate attack damage and on-hit riders through one typed damage bundle.
- [ ] Complete qualified defenses and the remaining rest semantics.
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

Active stack:

- Draft PR `#251`, `codex/trustworthy-engine-foundation`: deterministic trust gate, strict
  mechanic validation, truthful capability evidence, and terminal-outcome vocabulary.
- Draft PR `#252`, `codex/rules-profile-foundation`: versioned 5e-2014 rules profile, explicit
  attack delivery, stabilization, stable recovery, and canonical supporting content.
- Draft PR `#253`, `codex/nonlethal-knockout`: declared melee knockout intent, mortality
  disposition, neutralized encounter outcomes, distinct mortality metrics, and mutual-defeat draws.
- Draft PR `#254`, `codex/unified-attack-damage`: one typed attack-damage bundle for primary
  damage and immediate hit riders, including effect-only attacks and ordered effect telemetry.
- Draft PR `#255`, `codex/reaction-command-surface`: normalized readied-action triggers and
  zero-HP intent propagated through release, telemetry, actor views, snapshots, and cleanup.
- Draft PR `#256`, `codex/typed-reaction-decisions`: deterministic typed opportunity-reaction
  windows, validated use/pass decisions, explicit attack and knockout choices, strategy routing,
  and reaction lifecycle telemetry.

The next rules slice corrects reaction refresh timing and migrates special, trait, and spell
reactions onto the same typed decision surface. Broader content and session APIs follow after the
authoritative combat core is complete.

## Required verification for Milestone 0

```bash
uv run python -m pytest <targeted regression paths>
uv run python scripts/mechanics_coverage.py --strict --supported-pack db/rules/2014/supported_packs/combat_primitives_v1.json
uv run python scripts/content/verify_completion_capabilities.py
uv run python scripts/content/verify_completion_capabilities.py --supported-pack db/rules/2014/supported_packs/combat_primitives_v1.json
uv run python scripts/docs/verify_program_docs.py
uv run python -m black --check .
uv run python -m pytest
```

The legacy all-shipped `--strict` capability and mechanics modes remain intentionally red until
every canonical record is implemented and evidenced. They are audit tools, not the declared-pack
release gate.
