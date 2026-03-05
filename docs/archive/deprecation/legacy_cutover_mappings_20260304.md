Status: historical
Owner: program-control
Last updated: 2026-03-04
Canonical source: docs/archive/README.md
Historical note: Recovered from docs/deprecation/legacy_cutover_mappings_20260304.md at commit 3033ecc62c6b1df3bb815bf908bffda62d108b8a.

# Legacy Cutover Mappings (2026-03-04)

## Strategy Interface
| Legacy Surface | Canonical Replacement | Action |
|---|---|---|
| `choose_action(actor, state)` | `declare_turn(actor, state).action.action_name` | Remove legacy runtime call path |
| `choose_targets(actor, intent, state)` | `declare_turn(actor, state).action.targets[]` | Remove legacy runtime call path |
| `decide_resource_spend(actor, intent, state)` | `declare_turn(actor, state).action.resource_spend` | Remove legacy runtime call path |
| `ActionIntent` transport | `TurnDeclaration` only | Remove from runtime contract |

## Canonical Schema Mapping
| Legacy Field/Value | Canonical Field/Value | Notes |
|---|---|---|
| top-level trait `type` | top-level trait `source_type` | `metamagic` maps to `class` source_type |
| mechanics row `type` (executable) | mechanics row `effect_type` | Runtime executable rows must use `effect_type` |
| mechanics row `type` (annotation) | mechanics row `meta_type` | Non-runtime metadata rows preserved as `meta_type` |
| mechanics row `event_trigger` | mechanics row `trigger` | Canonical trigger field |
| character `class_level` text | character `class_levels` mapping | `class_level` removed from canonical contract/runtime payloads |

## Canonical Effect Alias Removal
| Legacy Effect Alias | Canonical Effect Type |
|---|---|
| `shapechange` | `transform` |
| `summon_creature` | `summon` |
| `command_construct_companion` | `command_allied` |
| `antimagic` | `antimagic_field` |
| `antimagic_zone` | `antimagic_field` |

## Duplicate Spell Lookup Keys (0)
