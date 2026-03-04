# Repo Cleanup Inventory 20260304

Generated: 2026-03-04T02:12:55Z (UTC)
Branch: codex/repo-cleanup-20260304
Base: origin/main

## Snapshot Summary
- Local branches: 102
- Worktrees: 83
- Worktree entries flagged prunable: 24
- Remote heads under origin: 68
- Local branches not merged into origin/main: 2
- Open PR head branches: 0

## Artifacts
- Branch inventory: docs/cleanup/repo_cleanup_branches_20260304.tsv
- Worktree inventory: docs/cleanup/repo_cleanup_worktrees_20260304.tsv
- Remote head inventory: docs/cleanup/repo_cleanup_remote_heads_20260304.tsv
- Archive tag mapping: docs/cleanup/repo_cleanup_archive_tags_20260304.tsv
- Open PR heads list: /tmp/repo_cleanup_open_pr_heads_20260304.txt
- Safety bundle: artifacts/repo_cleanup_20260304.bundle (7.7M)

## Non-Merged Local Branches Archived
- chore/purge-homebaked-agent-orchestration -> archive/repo-cleanup-20260304/chore__purge-homebaked-agent-orchestration (6e71c8aa60aabb9b3cb6dff190eac29aa4ca1020)
- rescue/wild-shape-salvage-20260303 -> archive/repo-cleanup-20260304/rescue__wild-shape-salvage-20260303 (e942bdd4c3038aab85ac895c6e46e33ca7902cb9)

## Delete Policy Inputs Captured
- Protected branch allowlist: main, codex/repo-cleanup-20260304
- Protected worktree allowlist: active cleanup worktree + worktrees attached to allowlisted branches
- Remote deletion exclude set: origin/main + open PR heads from /tmp/repo_cleanup_open_pr_heads_20260304.txt

## Subwave B Outcomes (Git Surface Pruning)
- Local branch pruning: deleted `100` branches; remaining local branches: `main`, `codex/repo-cleanup-20260304`.
- Remote branch pruning (`origin`): deleted `66` merged branches; remaining remote branch: `origin/main`.
- Worktree pruning: retained only allowlisted worktrees:
  - `/Users/rexputnam/Documents/projects/dnd_sim` (`main`)
  - `/Users/rexputnam/Documents/projects/dnd_sim_worktrees/repo-cleanup` (`codex/repo-cleanup-20260304`)
- Integrity check: `git fsck --full` completed successfully (dangling object notices only, no fatal errors).

## Subwave C-D Outcomes (Code/Pattern Cleanup + Refactor)
- Duplicate engine helpers removed to single definitions for:
  - `_ensure_resource_cap`
  - `_apply_inferred_wizard_resources`
  - `_iter_spell_slot_levels_desc`
  - `_recover_spell_slots_with_budget`
  - `_apply_arcane_recovery`
- Agent-native strategy validation enabled in `src/dnd_sim/strategy_api.py`:
  - declare-turn-first strategies are valid without legacy fallback trio.
  - legacy fallback path remains supported when `declare_turn` is absent.
- Resource/recovery helper extraction completed:
  - Added `src/dnd_sim/engine_resources.py`
  - `src/dnd_sim/engine.py` now delegates resource inference/recovery helpers.
- Spell-target inference helper extraction completed:
  - Added `src/dnd_sim/engine_spell_inference.py`
  - `src/dnd_sim/engine.py` now imports and uses extracted inference helpers.
- Dead script removal completed (unreferenced, not in docs/test/CI flows):
  - Removed `scripts/audit_party_features.py`
  - Removed `scripts/gemini_parser.py`
  - Removed `scripts/migrate_to_sqlite.py`
- Maintainability map added:
  - `docs/agent_index.yaml`
- Engine file-size reduction:
  - Baseline: `15,969` lines
  - Current: `15,558` lines
  - Net reduction: `411` lines

## Subwave E Validation Outcomes
- Targeted cleanup regression tests:
  - `uv run python -m pytest -q tests/test_engine_cleanup_regressions.py tests/test_fnd06_turn_declaration.py` ✅
- Full suite gate:
  - `uv run --with pytest python -m pytest -q` ✅
- Determinism spot-check corpus (10 fixed seeds across 10 scenario profiles) ✅:
  - `test_fixed_seed_is_deterministic` (seed `9`)
  - `fighter action-surge deterministic` (seed `37`)
  - `chr05 bard deterministic` (seed `61`)
  - `chr06 cleric deterministic` (seed `29`)
  - `chr07 druid deterministic` (seed `73`)
  - `chr10 paladin deterministic` (seed `53`)
  - `chr13 sorcerer deterministic` (seed `43`)
  - `chr14 warlock deterministic` (seed `88`)
  - `chr15 wizard deterministic` (seed `95`)
  - `spl04 spell family deterministic` (seed `101`)

## Post-Merge Safety Hotfix (2026-03-04)
- Context:
  - After merge of cleanup PR `#82`, a runtime gap was identified:
    declare-turn-only strategies were accepted by validation, but if `declare_turn()` returned
    `None`, engine fallback could call missing legacy methods.
- Fix applied:
  - `src/dnd_sim/engine.py` now safely handles `declare_turn() -> None` when legacy fallback
    methods are absent by ending turn as a no-op and emitting a decision telemetry event with
    `fallback_reason=declare_turn_none_no_legacy_fallback`.
  - Legacy fallback remains active when legacy methods exist.
- Regression coverage added in `tests/test_fnd06_turn_declaration.py`:
  - no-legacy no-op runtime path is accepted and telemetry-tagged.
  - mixed-mode fallback path (`declare_turn() -> None` + legacy methods present) still executes
    legacy decisions.
- Revalidation:
  - `uv run --with pytest python -m pytest tests/test_fnd06_turn_declaration.py -q` ✅
  - `uv run --with pytest python -m pytest -q` ✅
  - Determinism pack (10 selected tests) ✅
