# Agent Feature Assignments (Wave/Bundle Model)

This file supersedes the older one-branch-per-phase mapping and aligns with the full backlog in `docs/program/backlog.csv`.

## Source of Truth
- Task details and dependencies: `docs/program/backlog.csv`
- Task-to-agent ownership: `docs/program/agent_assignment.csv`
- Live progress: `docs/program/status_board.md`

## Ownership Model

### Wave 1 (Foundations)
- `agent_w1_a`: FND-01
- `agent_w1_b`: FND-02
- `agent_w1_c`: FND-03
- `agent_w1_d`: FND-04
- `agent_w1_e`: FND-05
- `agent_w1_f`: FND-06

### Wave 2 (Bug/Combat Bundles)
- `agent_w2_b1` reaction/interrupt bundle: BUG-03, BUG-04, BUG-05, BUG-14, BUG-17, COM-01, COM-07
- `agent_w2_b2` martial/action-economy bundle: BUG-02, BUG-06, BUG-07, BUG-08, BUG-09, BUG-22, COM-06
- `agent_w2_b3` condition/defense bundle: BUG-10, BUG-11, BUG-18, BUG-19
- `agent_w2_b4` movement/path bundle: BUG-12, BUG-21, COM-02
- `agent_w2_b5` geometry/zone bundle: BUG-01, BUG-20, COM-03, COM-04, COM-05
- `agent_w2_b6` timing/import bundle: BUG-13, BUG-15, BUG-16

### Wave 3
- `agent_w3_c1`: COM-08
- `agent_w3_c2`: COM-09
- `agent_w3_c3`: COM-10
- `agent_w3_c4`: CHR-01, CHR-03
- `agent_w3_c5`: CHR-02
- `agent_w3_c6`: SPL-01

### Wave 4 (Class/Spell Family)
- `agent_w4_barbarian`: CHR-04
- `agent_w4_bard`: CHR-05
- `agent_w4_cleric`: CHR-06
- `agent_w4_druid`: CHR-07
- `agent_w4_fighter`: CHR-08
- `agent_w4_monk`: CHR-09
- `agent_w4_paladin`: CHR-10
- `agent_w4_ranger`: CHR-11
- `agent_w4_rogue`: CHR-12
- `agent_w4_sorcerer`: CHR-13
- `agent_w4_warlock`: CHR-14
- `agent_w4_wizard`: CHR-15
- `agent_w4_content`: CHR-16
- `agent_w4_spell_single`: SPL-02
- `agent_w4_spell_area`: SPL-03
- `agent_w4_spell_summon`: SPL-04
- `agent_w4_spell_special`: SPL-05

### Wave 5
- `agent_w5_sys01`: SYS-01
- `agent_w5_sys02`: SYS-02
- `agent_w5_sys03`: SYS-03
- `agent_w5_sys04`: SYS-04
- `agent_w5_sys05`: SYS-05
- `agent_w5_sys06`: SYS-06
- `agent_w5_sys07`: SYS-07
- `agent_w5_sys08`: SYS-08

## Delivery Contract
- One PR per task ID.
- TDD loop for every task.
- Required unit + integration + negative tests.
- Determinism check with fixed seed.
- Migration notes when API/schema changes.
