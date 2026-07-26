from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_engine_trust_workflow_runs_public_scenario_terminal_contract_and_full_suite() -> None:
    workflow = (REPO_ROOT / ".github/workflows/engine-trust-gate.yml").read_text(encoding="utf-8")

    assert '"src/dnd_sim/**"' in workflow
    assert '"tests/**"' in workflow
    assert (
        "uv run python -m pytest tests/test_shipped_phase2_simulation.py "
        "tests/test_terminal_outcomes.py" in workflow
    )
    assert "uv run python -m black --check ." in workflow
    assert "uv run python -m pytest" in workflow
