from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


def test_engine_has_no_duplicate_top_level_function_definitions() -> None:
    engine_path = Path(__file__).resolve().parents[1] / "src" / "dnd_sim" / "engine.py"
    module = ast.parse(engine_path.read_text(encoding="utf-8"))
    counts = Counter(
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    duplicates = {name: count for name, count in counts.items() if count > 1}
    assert duplicates == {}
