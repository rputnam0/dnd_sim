# Labels and Milestones

## Labels
- `wave:1` `wave:2` `wave:3` `wave:4` `wave:5`
- `type:foundation` `type:bug` `type:combat` `type:character` `type:spell` `type:system`
- `status:blocked` `status:ready` `status:in-progress` `status:review` `status:merged`
- `risk:high` `risk:medium` `risk:low`
- `determinism:required`
- `migration:required`

## Milestones
- `Wave 1 - Foundations`
- `Wave 2 - Combat Defects and Core`
- `Wave 3 - Core Expansion`
- `Wave 4 - Class and Spell Completion`
- `Wave 5 - Full Backend Systems`
- `Program Complete - 5e 2014 Backend`

## Issue Assignment Rules
- Every task issue gets one `wave:*` and one `type:*` label.
- Any task touching core engine timing or schemas gets `risk:high`.
- All tasks include `determinism:required`.
- Tasks with public API/schema changes include `migration:required`.
