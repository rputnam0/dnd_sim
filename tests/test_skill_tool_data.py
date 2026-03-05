from __future__ import annotations

import pytest

from dnd_sim.noncombat_checks import (
    load_noncombat_catalog,
    resolve_passive_skill_score,
    resolve_skill_modifier,
    resolve_tool_modifier,
)


def _ability_mods() -> dict[str, int]:
    return {
        "str": 2,
        "dex": 3,
        "con": 1,
        "int": 4,
        "wis": 1,
        "cha": -1,
    }


def test_skill_modifier_uses_ability_and_proficiency_bonus() -> None:
    catalog = load_noncombat_catalog()
    modifier = resolve_skill_modifier(
        skill="arcana",
        ability_modifiers=_ability_mods(),
        proficiency_bonus=2,
        proficient_skills={"arcana"},
        catalog=catalog,
    )

    assert modifier == 6  # int + proficiency -> 4 + 2


def test_tool_modifier_adds_proficiency_when_tool_is_known() -> None:
    catalog = load_noncombat_catalog()
    modifier = resolve_tool_modifier(
        tool="thieves_tools",
        ability_modifiers=_ability_mods(),
        proficiency_bonus=3,
        proficient_tools={"thieves_tools"},
        catalog=catalog,
    )

    assert modifier == 6  # dex + proficiency -> 3 + 3


def test_expertise_doubles_proficiency_for_skill_and_tool() -> None:
    catalog = load_noncombat_catalog()
    skill_modifier = resolve_skill_modifier(
        skill="perception",
        ability_modifiers=_ability_mods(),
        proficiency_bonus=2,
        proficient_skills={"perception"},
        expertise_skills={"perception"},
        catalog=catalog,
    )
    tool_modifier = resolve_tool_modifier(
        tool="thieves_tools",
        ability_modifiers=_ability_mods(),
        proficiency_bonus=2,
        proficient_tools={"thieves_tools"},
        expertise_tools={"thieves_tools"},
        catalog=catalog,
    )

    assert skill_modifier == 5  # wis + (2 * proficiency) -> 1 + 4
    assert tool_modifier == 7  # dex + (2 * proficiency) -> 3 + 4


def test_passive_skill_score_uses_skill_modifier_with_base_10() -> None:
    catalog = load_noncombat_catalog()
    score = resolve_passive_skill_score(
        skill="investigation",
        ability_modifiers=_ability_mods(),
        proficiency_bonus=2,
        proficient_skills={"investigation"},
        catalog=catalog,
    )

    assert score == 16  # 10 + int(4) + proficiency(2)


def test_missing_data_errors_for_unknown_skill_and_missing_ability_modifier() -> None:
    catalog = load_noncombat_catalog()
    with pytest.raises(ValueError, match="Unknown skill"):
        resolve_skill_modifier(
            skill="planar_lore",
            ability_modifiers=_ability_mods(),
            proficiency_bonus=2,
            catalog=catalog,
        )

    with pytest.raises(ValueError, match="Missing ability modifier"):
        resolve_skill_modifier(
            skill="history",
            ability_modifiers={"str": 1},
            proficiency_bonus=2,
            catalog=catalog,
        )


def test_missing_data_errors_for_unknown_tool() -> None:
    catalog = load_noncombat_catalog()
    with pytest.raises(ValueError, match="Unknown tool"):
        resolve_tool_modifier(
            tool="artisan_lens",
            ability_modifiers=_ability_mods(),
            proficiency_bonus=2,
            catalog=catalog,
        )
