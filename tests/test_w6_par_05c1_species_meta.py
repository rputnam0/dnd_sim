from __future__ import annotations

import json
from pathlib import Path

from dnd_sim import io
from dnd_sim.capability_manifest import build_feature_capability_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNED_SPECIES_IDS = {
    "species:age",
    "species:alignment",
    "species:astral_knowledge",
    "species:brittle_bones",
    "species:creature_type",
    "species:dwarven_resilience",
    "species:dwarven_toughness",
    "species:elf_culture",
    "species:equine_build",
    "species:expert_duplication",
    "species:hunter_s_lore",
    "species:kender_curiosity",
    "species:kenku_recall",
    "species:khenra_weapon_training",
    "species:kor_climbing",
    "species:language",
    "species:languages",
    "species:limited_amphibiousness",
    "species:limited_telepathy",
    "species:magic_resistance",
    "species:mental_discipline",
    "species:mimicry",
    "species:mountain_born",
    "species:observant_athletic",
    "species:otherworldly_perception",
    "species:poison_affinity",
    "species:resourceful",
    "species:sentry_s_rest",
    "species:size",
    "species:skill_versatility",
    "species:specialized_design",
    "species:stonecunning",
    "species:sunlight_sensitivity",
    "species:swim_speed",
    "species:variable_trait",
    "species:versatile",
    "species:water_dependency",
}
CANONICAL_PROFICIENCY_FILES = {
    "astral_knowledge": 2,
    "hunter_s_lore": 1,
    "kender_curiosity": 1,
    "kenku_recall": 1,
    "khenra_weapon_training": 1,
    "poison_affinity": 1,
    "skill_versatility": 1,
    "specialized_design": 1,
}
SKILL_PROFICIENCY_LIST_FILES = {
    "kor_climbing": ["Athletics", "Acrobatics"],
    "observant_athletic": ["Athletics", "Perception"],
}
REPRESENTATIVE_META_TYPES = {
    "age": {"age"},
    "alignment": {"alignment"},
    "brittle_bones": {"damage_vulnerability"},
    "creature_type": {"creature_type"},
    "dwarven_resilience": {"damage_resistance", "saving_throw_advantage"},
    "limited_amphibiousness": {"breathing", "restriction"},
    "limited_telepathy": {"communication"},
    "mimicry": {"mimic_speech"},
    "stonecunning": {"double_proficiency_bonus", "skill_proficiency"},
    "swim_speed": {"speed"},
    "variable_trait": {"choice"},
    "versatile": {"grant_feat"},
    "water_dependency": {"restriction"},
}


def test_species_meta_leaf_records_are_supported_in_feature_manifest() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(OWNED_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(OWNED_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_species_meta_leaf_records_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(OWNED_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(OWNED_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_species_meta_leaf_records_use_only_canonical_meta_rows() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for content_id in sorted(OWNED_SPECIES_IDS):
        slug = content_id.split(":", maxsplit=1)[1]
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload["mechanics"]

        assert mechanics
        assert all(isinstance(row, dict) for row in mechanics)
        assert all(str(row.get("meta_type", "")).strip() for row in mechanics)
        assert all("effect_type" not in row for row in mechanics)


def test_species_meta_leaf_proficiency_records_use_canonical_nested_shape() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for slug, expected_count in sorted(CANONICAL_PROFICIENCY_FILES.items()):
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload["mechanics"]

        canonical_rows = [
            row
            for row in mechanics
            if row.get("meta_type") == "grant_proficiencies"
            and isinstance(row.get("grant_proficiency"), dict)
        ]

        assert len(canonical_rows) == expected_count
        assert all("gainProficiency" not in row for row in mechanics)
        assert all("gainProficiencies" not in row for row in mechanics)


def test_species_meta_leaf_skill_proficiency_records_use_direct_list_shape() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for slug, expected_skills in sorted(SKILL_PROFICIENCY_LIST_FILES.items()):
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload["mechanics"]

        canonical_rows = [
            row
            for row in mechanics
            if row.get("meta_type") == "skill_proficiency"
            and isinstance(row.get("skill_proficiency"), list)
        ]

        assert len(canonical_rows) == 1
        assert canonical_rows[0]["skill_proficiency"] == expected_skills
        assert "grant_proficiency" not in canonical_rows[0]
        assert "gainProficiency" not in canonical_rows[0]
        assert "gainProficiencies" not in canonical_rows[0]


def test_species_meta_leaf_representative_records_use_expected_meta_types() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for slug, expected_meta_types in sorted(REPRESENTATIVE_META_TYPES.items()):
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        seen_meta_types = {
            str(row.get("meta_type", "")).strip()
            for row in payload["mechanics"]
            if isinstance(row, dict)
        }
        assert expected_meta_types <= seen_meta_types
