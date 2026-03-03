# Risk Register

## High-Risk Integration Areas

| Risk ID | Area | Risk | Mitigation | Gate |
|---|---|---|---|---|
| R-01 | `engine.py` timing flow | Event bus migration breaks existing action resolution order | Merge FND-01 first, add event-order golden tests | Wave 1 integration tests |
| R-02 | Condition model | Converting string conditions to effect instances regresses derived checks | Dual-path compatibility tests + explicit derived-state unit tests | FND-02 test gate |
| R-03 | Attack identity | Weapon property assumptions hidden in action names stop working | Canonical weapon IDs + property-based legality tests | FND-03 gate |
| R-04 | Damage resolution | Mixed damage types mitigated incorrectly after typed packets | Packet-level mitigation tests and smite/sneak mixed-damage integration tests | FND-04 gate |
| R-05 | Spell timing | Counterspell/Shield/bonus-action restrictions conflict | Centralized spell declaration/resolution windows + reaction tests | FND-05 + BUG-04/05/17 |
| R-06 | Strategy API | Backward compatibility breaks clients | Migration notes + structured validation errors + adapter shims where needed | FND-06 gate |
| R-07 | Spatial/pathing | Pathfinding and AoE legality drift from existing assumptions | Separate geometry test corpus; no merge without path legality tests | BUG-21 + COM-04 |
| R-08 | Class expansion | Per-class branches diverge in shared hooks | Require CHR-03 hook API first and rebase class branches weekly | Wave 4 merge policy |
| R-09 | Data pipeline | New schema validation blocks existing content | Add migration scripts and fixture updates in same task PR | SYS-07 gate |
| R-10 | Determinism | Parallel merges introduce nondeterministic ordering | Determinism corpus + seeded replay diff in wave gates | Every wave |

## Operational Risks

| Risk ID | Risk | Mitigation |
|---|---|---|
| O-01 | Too many concurrent branches cause conflict churn | Run strict wave batching and dependency-ordered merges |
| O-02 | Review bottleneck delays merges | Assign dedicated explorer reviewers by bundle |
| O-03 | Incomplete task closure | Enforce status board updates and PR checklists |
