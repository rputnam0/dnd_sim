from __future__ import annotations

import pytest

from dnd_sim.rules_profiles import load_supported_rules_profile
from dnd_sim.simulate import _validate_custom_output_provenance


def _profiled_output() -> tuple[dict[str, object], list[dict[str, object]]]:
    profile = load_supported_rules_profile()
    reference = {
        "rules_profile_id": profile.profile_id,
        "rules_profile_version": profile.profile_version,
    }
    return ({**reference, "trials": 1}, [{**reference, "trial_index": 0}])


def test_custom_runner_must_declare_exact_rules_profile_on_every_artifact() -> None:
    profile = load_supported_rules_profile()
    summary, rows = _profiled_output()

    _validate_custom_output_provenance(
        summary_payload=summary,
        trial_rows=rows,
        rules_profile=profile,
    )

    with pytest.raises(ValueError, match="summary rules profile"):
        _validate_custom_output_provenance(
            summary_payload={"trials": 1},
            trial_rows=rows,
            rules_profile=profile,
        )

    with pytest.raises(ValueError, match="trial row 0 rules profile"):
        _validate_custom_output_provenance(
            summary_payload=summary,
            trial_rows=[{"trial_index": 0}],
            rules_profile=profile,
        )
