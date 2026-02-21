# Implementation Review Checklist

This checklist tracks a systematic review of recent combat-engine and parser changes.
Each section is intended to be delivered and reviewed in a separate pull request.

## PR-1: Engine Stability (Crash/Contract Regressions)

- [x] Add regression tests for passive trait application at actor build time.
- [x] Add regression tests for grapple/shove execution path.
- [x] Add regression tests for divine smite damage composition.
- [x] Add regression tests for hazard key compatibility with spatial visibility.
- [x] Add regression tests for strategy metadata fields used by heuristics.
- [x] Fix actor runtime model gaps used by combat hooks.
- [x] Ensure full test suite passes.

## PR-2: Feat/Class Behavior Correctness

- [x] Audit trait key normalization (`space`, `_`, `-`) and unify checks.
- [ ] Verify Lucky attacker/defender/save behavior with deterministic tests.
- [ ] Verify GWM/Sharpshooter toggles and damage math under advantage/disadvantage.
- [ ] Verify Shield Master / War Caster / Mage Slayer interactions.
- [ ] Verify Sentinel and opportunity/reaction constraints.
- [ ] Verify Rage damage/resistance edge cases.
- [ ] Ensure full test suite passes.

## PR-3: Spatial, Vision, and Cover Integration

- [x] Add attack-loop tests for unseen attacker/unseen target cancellation.
- [x] Add tests for magical darkness + darkvision/truesight/blindsight behavior.
- [x] Add tests for cover states and AC modification integration.
- [ ] Verify strategy scoring inputs use current round hazards and geometry fields.
- [x] Ensure full test suite passes.

## PR-4: Parser and Data Pipeline Validation

- [x] Add contract tests for parser outputs (`spells`, `monsters`, `traits`) against expected schema.
- [x] Validate normalization assumptions for generated JSON names/keys.
- [x] Add fixture-based tests for key parser edge cases.
- [x] Ensure full test suite passes.

## PR-5: Integration and Simulation Invariants

- [x] Add integration tests for newly introduced action/effect combinations.
- [x] Add invariants for resource accounting and per-round state resets.
- [x] Add invariants for concentration and condition duration lifecycle.
- [x] Ensure full test suite passes.

## Review Gate (for every PR)

- [ ] `uv run python -m black <changed-files>`
- [ ] `uv run python -m pytest`
- [ ] Include explicit risk/impact notes in PR description.
