from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

_TARGET_HELPERS = {
    "_ensure_resource_cap",
    "_apply_inferred_wizard_resources",
    "_apply_arcane_recovery",
    "_iter_spell_slot_levels_desc",
    "_recover_spell_slots_with_budget",
}


def test_engine_cleanup_helpers_have_single_top_level_definition() -> None:
    engine_path = Path(__file__).resolve().parents[1] / "src" / "dnd_sim" / "engine.py"
    module = ast.parse(engine_path.read_text(encoding="utf-8"))
    counts = Counter(
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    for helper_name in sorted(_TARGET_HELPERS):
        assert counts[helper_name] == 1
