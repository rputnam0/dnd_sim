Status: historical
Owner: program-control
Last updated: 2026-03-04
Canonical source: docs/archive/README.md
Historical note: Recovered from docs/program/wave3_gap_report.md at commit 3033ecc62c6b1df3bb815bf908bffda62d108b8a.

# Wave 3 Gap Report

Generated from multi-agent audit swarm on `int/wave-3-integration` (base `origin/main@5bb7648`).

## COM-08 — Rest Cycle and Adventuring Day Engine
Status: partial

Implemented:
- Multi-encounter sequencing, branching, and checkpoint snapshots in `run_simulation`.
- Short-rest hook between encounters.

Missing:
- Long-rest lifecycle integration in encounter flow.
- Exploration-leg attrition wiring inside campaign loop.
- Full rest fidelity state (hit-dice/rest-cadence semantics).

Primary files:
- `src/dnd_sim/engine.py`
- `src/dnd_sim/io.py`
- `src/dnd_sim/models.py`
- `tests/test_campaign_sequencing.py`
- `tests/test_io_schema.py`

Required tests:
- Unit: long-rest/short-rest edge behavior.
- Integration: long-rest boundary and exploration attrition.
- Negative: invalid rest policy and encounter-step overflow.

## COM-09 — Monster Recharge, Legendary Resistance, Innate Casting, Custom Actions
Status: partial

Implemented:
- Recharge and legendary resistance runtime scaffolding exists.
- Generic custom action/effects runtime exists.

Missing:
- Recharge parsing correctness for `5-6` and `Recharge 6` variants.
- Parser/backfill support for legendary resistance resources.
- Innate spellcasting extraction and runtime wiring.
- End-to-end data pipeline for modern monster payloads.

Primary files:
- `src/dnd_sim/engine.py`
- `src/dnd_sim/parse_monsters.py`
- `src/dnd_sim/monster_backfill.py`
- `src/dnd_sim/io.py`
- `scripts/backfill_monster_entries.py`

Required tests:
- Unit: recharge parse + legendary resistance decrement behavior.
- Integration: recharge usage/recovery and innate-casting usage limits.
- Negative: invalid recharge/innate spell references.

## COM-10 — Summons, Companions, Mounts, Allied Controllers
Status: partial

Implemented:
- Summon/conjure creation and concentration-linked cleanup.
- Companion owner metadata and command gating primitives.

Missing:
- Mount subsystem.
- Generic allied-controller system beyond construct-specific command.
- Summon/companion schema normalization for command/mount/summon effects.
- Initiative ordering bug: duplicated `_reorder_initiative_for_construct_companions` with no-op override.

Primary files:
- `src/dnd_sim/engine.py`
- `src/dnd_sim/models.py`
- `src/dnd_sim/io.py`
- `src/dnd_sim/mechanics_schema.py`
- `src/dnd_sim/strategies/defaults.py`

Required tests:
- Unit: companion initiative ordering and command legality.
- Integration: command flow and summon timing determinism.
- Negative: non-owned command targets and malformed summon payloads.

## CHR-01 — Character Progression and Multiclass Framework
Status: partial

Implemented:
- XP/level progression utilities.
- Runtime `class_levels` scaffolding.

Missing:
- Canonical CHR-01 module (`src/dnd_sim/characters.py`) and structured multiclass progression API.
- Multiclass prerequisite validation.
- True multiclass slot progression integration.
- Parser/schema migration from freeform `class_level` text.

Primary files:
- `src/dnd_sim/progression.py`
- `src/dnd_sim/engine.py`
- `src/dnd_sim/models.py`
- `src/dnd_sim/parser.py`
- `src/dnd_sim/io.py`

Required tests:
- Unit: multiclass parse/prereq/slot progression rules.
- Integration: actor build + rest/resource behavior for multiclass payloads.
- Negative: invalid class-level encodings and illegal multiclass transitions.

## CHR-02 — Inventory, Equipment, Ammo, Shields, Attunement
Status: partial

Implemented:
- Inventory/currency/attunement primitives.
- Inventory hydration to actor runtime.

Missing:
- Equip/unequip subsystem and slot legality.
- Ammunition requirements and consumption.
- Physical shield equipment semantics (distinct from Shield spell).
- Trait-driven attunement-limit modifiers and item-effect gating.

Primary files:
- `src/dnd_sim/inventory.py`
- `src/dnd_sim/engine.py`
- `src/dnd_sim/models.py`
- `src/dnd_sim/parser.py`
- `db/rules/2014/traits/magic_item_*.json`

Required tests:
- Unit: equip/unequip + ammo consume + attunement-limit validation.
- Integration: ammo spending and shield-dependent behavior.
- Negative: equip unknown item, wrong ammo type, attunement limit overflow.

## CHR-03 — Unified Feat/Species/Background/Subclass Hook System
Status: missing

Implemented:
- Some trait/mechanics ingestion primitives and isolated runtime hook behavior.

Missing:
- Source-aware hook registry model.
- Unified data-driven hook dispatch replacing hardcoded trait-name checks.
- Normalized hook schema across trait data.
- Background/subclass parity in runtime hook execution.

Primary files:
- `src/dnd_sim/models.py`
- `src/dnd_sim/parser.py`
- `src/dnd_sim/io.py`
- `src/dnd_sim/engine.py`
- `src/dnd_sim/rules_2014.py`
- `src/dnd_sim/mechanics_schema.py`

Required tests:
- Unit: source-aware hook registration and deterministic ordering.
- Integration: mixed-source hook dispatch via one pipeline.
- Negative: unknown effect types and invalid source types.

## SPL-01 — Canonical Spell Database and Schema Validation
Status: partial

Implemented:
- Large spell corpus exists and runtime spell mechanics are broadly exercised.

Missing:
- Canonical spell payload schema enforcement across corpus.
- Mixed legacy/typed spell normalization in data pipeline.
- Deterministic duplicate spell ID/name conflict handling.
- Dedicated `src/dnd_sim/spells.py` schema/loader module (referenced by backlog).

Primary files:
- `src/dnd_sim/io.py`
- `src/dnd_sim/engine.py`
- `src/dnd_sim/parse_spells.py`
- `scripts/oss_parser.py`
- `src/dnd_sim/mechanics_schema.py`
- `db/rules/2014/spells/*.json`

Required tests:
- Unit: schema validation and duplicate detection.
- Integration: strict full-directory spell validation + deterministic lookup.
- Negative: reject/migrate legacy-shape records and duplicate conflicts.

## Batch Plan
- Batch A launch now: `COM-08`, `CHR-01`, `CHR-02`, `CHR-03`, `SPL-01`
- Batch B launch after Batch A merge/rebase pass: `COM-09`, `COM-10`

## Shared Risks
- `src/dnd_sim/engine.py` is the top conflict hotspot.
- Determinism drift risk is high for `COM-08`, `COM-10`, and `SPL-01`.
- Data-shape migrations in `db/rules/2014/*` must be tightly validated before merge.
