from __future__ import annotations

from dnd_sim.strategies.defaults import _expected_damage_against


class _Target:
    def __init__(self, ac: int) -> None:
        self.ac = ac


def test_expected_damage_ignores_non_dict_effect_entries() -> None:
    target = _Target(ac=14)
    action = {
        "action_type": "save",
        "damage": "2d6",
        "save_dc": 14,
        "save_ability": "dex",
        "half_on_save": True,
        "effects": [
            "legacy_effect_entry",
            {"effect_type": "damage", "damage": "1d6", "apply_on": "save_fail", "target": "target"},
        ],
        "mechanics": ["legacy_mechanic_entry"],
    }

    score = _expected_damage_against(action, target, save_mod=2)

    assert score > 0.0
