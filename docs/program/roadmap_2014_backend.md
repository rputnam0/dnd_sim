# Roadmap: Full D&D 5e 2014 Backend

## Summary
This roadmap operationalizes the full backlog into deterministic waves with strict dependency gates.
Execution model:
- Foundation tasks first (Wave 1).
- Bug/combat bundles second (Wave 2).
- Systems enabling class/content scale third (Wave 3).
- Class and spell content expansion fourth (Wave 4).
- Noncombat/full-backend systems fifth (Wave 5).

Global contract for every task:
- Code changes
- Unit tests
- Integration/golden tests
- Negative test
- Deterministic seed stability (unless intentionally changed)
- Migration notes for API/schema changes
- One PR per task ID

## Waves

### Wave 1 (Foundations)
- FND-01 Formal event/timing engine
- FND-02 Source-aware effect instances
- FND-03 Canonical weapon/equipment identity
- FND-04 Typed damage packets
- FND-05 Proper spellcasting core
- FND-06 Full legal turn declaration in strategy API

### Wave 2 (Defects + Combat Core)
- BUG-01..BUG-22
- COM-01..COM-07

### Wave 3 (Mid-Core Enablement)
- COM-08..COM-10
- CHR-01..CHR-03
- SPL-01

### Wave 4 (Class + Spell Completion)
- CHR-04..CHR-16
- SPL-02..SPL-05

### Wave 5 (Full Backend Systems)
- SYS-01..SYS-08

## Task Inventory

### Foundation
- FND-01 Introduce formal event/timing engine
- FND-02 Replace flat conditions with source-aware effect instances
- FND-03 Preserve weapon/equipment identity through action resolution
- FND-04 Introduce typed damage packets
- FND-05 Build proper spellcasting core
- FND-06 Expand strategy API to full legal turn declaration

### Bug Fixes
- BUG-01 Fix AoE target expansion runtime crash
- BUG-02 Make Rage activation apply Rage
- BUG-03 Canonicalize action/spell IDs for reaction matching
- BUG-04 Implement correct Counterspell logic
- BUG-05 Implement Shield as persistent timed effect
- BUG-06 Correct Martial Arts vs Flurry of Blows
- BUG-07 Correct baseline two-weapon fighting and style interaction
- BUG-08 Make Sneak Attack truly once per turn
- BUG-09 Clear GWM bonus trigger correctly
- BUG-10 Correct prone/stunned/paralyzed/unconscious semantics
- BUG-11 Fix death/dying/temp HP/instant death handling
- BUG-12 Forced movement does not consume movement or provoke normal OA
- BUG-13 Correct lair/legendary timing
- BUG-14 Implement real Ready action support
- BUG-15 Fix spell extraction for prepared vs known casters
- BUG-16 Support "slot of spell level or higher" and upcasting
- BUG-17 Enforce bonus-action spellcasting restriction
- BUG-18 Apply cover correctly to attacks and Dex saves
- BUG-19 Enforce reach/range/ranged-in-melee disadvantage
- BUG-20 Add hazard lifecycle processing
- BUG-21 Replace pathfinding stub with legal routing
- BUG-22 Remove engine-owned hidden tactics

### Combat Systems
- COM-01 Opportunity attacks/disengage/reach hooks
- COM-02 Grapple/shove/escape/drag/stand from prone
- COM-03 Vision/obscurity/invisibility/senses model
- COM-04 Full AoE geometry templates
- COM-05 Persistent zones/walls/environment effects
- COM-06 Attack replacement + multiattack framework
- COM-07 Concentration dependency graph
- COM-08 Rest cycle and adventuring-day engine
- COM-09 Monster recharge/legendary resistance/innate casting/custom actions
- COM-10 Summons/companions/mounts/allied controllers

### Character/Progression
- CHR-01 Character progression + multiclass framework
- CHR-02 Inventory/equipment/ammunition/shields/attunement
- CHR-03 Unified feat/species/background/subclass hook system
- CHR-04 Barbarian package
- CHR-05 Bard package
- CHR-06 Cleric package
- CHR-07 Druid package + Wild Shape framework
- CHR-08 Fighter package
- CHR-09 Monk package
- CHR-10 Paladin package
- CHR-11 Ranger package
- CHR-12 Rogue package
- CHR-13 Sorcerer package
- CHR-14 Warlock package
- CHR-15 Wizard package
- CHR-16 Non-class content completeness pass

### Spell/Content
- SPL-01 Canonical spell database + schema validation
- SPL-02 Single-target spell family implementation
- SPL-03 Area spell family implementation
- SPL-04 Summon/conjure/transform spell family
- SPL-05 Rituals/dispels/antimagic/special-case spell framework

### Systems
- SYS-01 Ability checks/skills/contests/passives/tools
- SYS-02 Exploration turn structure/travel/time/light
- SYS-03 Exhaustion/suffocation/drowning/falling/disease/poison/environment
- SYS-04 Economy/loot/vendors/crafting/downtime/encumbrance
- SYS-05 Quest/faction/world flags/persistence
- SYS-06 Encounter scripting/waves/objectives/map hooks
- SYS-07 Data schema/validation/import/content IDs
- SYS-08 Regression corpus/performance/replay diff harness

## Wave Gates

A wave is mergeable only when all are true:
- All tasks in the wave have open PRs and passed acceptance criteria.
- Full `uv run python -m pytest` is green on wave integration branch.
- Golden deterministic scenario checks are green or approved as intentional deltas.
- Schema validation passes for all modified data classes.
- Migration notes are present for all API/schema changes.

## Definition of Done (Program)
Backend is complete only when:
- A legal turn is fully declarable via public API.
- 2014 combat legality and timing windows are enforced.
- Character/item/spell/monster/map content is validated and data-driven.
- Multi-encounter adventuring day and campaign persistence work.
- Noncombat systems are supported.
- Regression corpus proves deterministic stability.
