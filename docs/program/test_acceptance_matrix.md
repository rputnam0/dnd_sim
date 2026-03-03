# Test Acceptance Matrix

## Global Requirements (All Tasks)
- Minimum one direct unit test.
- Minimum one integration (or golden combat) test.
- Minimum one negative/invalidity test.
- Existing tests remain green.
- Deterministic behavior preserved for identical seeds unless task explicitly changes rules behavior.

## Foundation Tasks (FND)
- Event ordering determinism tests.
- API/schema migration tests when public types change.
- Cross-module integration tests for engine, rules, and strategy API.

## Bug Tasks (BUG)
- Regression test that fails on pre-fix behavior.
- Positive coverage for corrected behavior.
- Negative coverage for illegal/edge behavior.

## Combat Tasks (COM)
- Initiative/timing order integration tests.
- Geometry/range/path legality tests where relevant.
- Reaction window and concentration lifecycle tests where relevant.

## Character Tasks (CHR)
- Progression/resource accounting tests.
- Class feature timing/resource legality tests.
- Multiclass and prerequisite validation tests (where relevant).

## Spell Tasks (SPL)
- Schema validation and import tests.
- Slot legality and upcast scaling tests.
- Targeting/cover/line-of-effect legality tests.

## System Tasks (SYS)
- Persistence round-trip tests.
- Economy/resource invariants.
- Time advancement and world-state lifecycle tests.

## Wave-Level Test Gates
- Full `uv run python -m pytest` pass.
- Deterministic scenario corpus pass.
- Any golden log diffs reviewed and approved when expected.
