from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.rules_profiles import (
    DEFAULT_RULES_PROFILE_ID,
    DEFAULT_RULES_PROFILE_VERSION,
    RULES_RUNTIME_API_VERSION,
    ActorKind,
    SupportedRulesProfile,
    load_supported_rules_profile,
)


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "profile_id": "test_combat_profile",
        "profile_version": "1.2.3",
        "ruleset": "5e-2014",
        "compatibility": {"rules_runtime_api": "1.0"},
        "zero_hit_point_policy": {
            "player_character": "death_saves",
            "monster": "dead",
            "summon": "dead",
            "construct": "dead",
            "allow_explicit_actor_override": True,
        },
    }
    payload.update(overrides)
    return payload


def test_canonical_rules_profile_is_version_pinned_and_strict() -> None:
    profile = load_supported_rules_profile()

    assert profile.profile_id == DEFAULT_RULES_PROFILE_ID
    assert profile.profile_version == DEFAULT_RULES_PROFILE_VERSION
    assert profile.ruleset == "5e-2014"
    assert profile.schema_version == "1.0"
    assert profile.compatibility.rules_runtime_api == RULES_RUNTIME_API_VERSION
    assert profile.model_config["extra"] == "forbid"
    assert SupportedRulesProfile.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize(
    ("actor_kind", "expected"),
    [
        ("player_character", True),
        ("monster", False),
        ("summon", False),
        ("construct", False),
    ],
)
def test_canonical_zero_hp_defaults_are_actor_kind_specific(
    actor_kind: ActorKind,
    expected: bool,
) -> None:
    profile = load_supported_rules_profile()

    assert profile.resolve_uses_death_saves(actor_kind=actor_kind) is expected


def test_explicit_actor_override_is_resolved_by_profile_policy() -> None:
    profile = load_supported_rules_profile()

    assert profile.resolve_uses_death_saves(actor_kind="monster", explicit=True) is True
    assert profile.resolve_uses_death_saves(actor_kind="player_character", explicit=False) is False

    locked_payload = _profile_payload()
    zero_hp = locked_payload["zero_hit_point_policy"]
    assert isinstance(zero_hp, dict)
    zero_hp["allow_explicit_actor_override"] = False
    locked = SupportedRulesProfile.model_validate(locked_payload)

    with pytest.raises(ValueError, match="does not allow explicit actor overrides"):
        locked.resolve_uses_death_saves(actor_kind="monster", explicit=True)


def test_profile_loader_rejects_unknown_mismatched_and_unsafe_references(tmp_path: Path) -> None:
    profile_path = tmp_path / "test_combat_profile" / "1.2.3.json"
    profile_path.parent.mkdir()
    profile_path.write_text(json.dumps(_profile_payload()), encoding="utf-8")

    loaded = load_supported_rules_profile(
        profile_id="test_combat_profile",
        profile_version="1.2.3",
        profiles_dir=tmp_path,
    )
    assert loaded.profile_id == "test_combat_profile"

    (profile_path.parent / "9.9.9.json").write_text(
        json.dumps(_profile_payload()),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="version mismatch"):
        load_supported_rules_profile(
            profile_id="test_combat_profile",
            profile_version="9.9.9",
            profiles_dir=tmp_path,
        )

    with pytest.raises(ValueError, match="safe lowercase snake_case"):
        load_supported_rules_profile(
            profile_id="../outside",
            profile_version="1.2.3",
            profiles_dir=tmp_path,
        )

    with pytest.raises(ValueError, match="not found"):
        load_supported_rules_profile(
            profile_id="missing_profile",
            profile_version="1.0.0",
            profiles_dir=tmp_path,
        )


def test_rules_profile_schema_rejects_unknown_fields_and_invalid_versions() -> None:
    with pytest.raises(ValidationError):
        SupportedRulesProfile.model_validate(_profile_payload(unexpected=True))

    with pytest.raises(ValidationError, match="profile_version"):
        SupportedRulesProfile.model_validate(_profile_payload(profile_version="latest"))

    with pytest.raises(ValidationError, match="rules_runtime_api"):
        SupportedRulesProfile.model_validate(
            _profile_payload(compatibility={"rules_runtime_api": "2.0"})
        )

    internal_name_payload = _profile_payload()
    zero_hp = internal_name_payload["zero_hit_point_policy"]
    assert isinstance(zero_hp, dict)
    zero_hp["construct_actor"] = zero_hp.pop("construct")
    with pytest.raises(ValidationError, match="construct"):
        SupportedRulesProfile.model_validate(internal_name_payload)


def test_loader_can_retain_multiple_exact_profile_versions(tmp_path: Path) -> None:
    profile_dir = tmp_path / "test_combat_profile"
    profile_dir.mkdir()
    (profile_dir / "1.2.3.json").write_text(
        json.dumps(_profile_payload(profile_version="1.2.3")),
        encoding="utf-8",
    )
    (profile_dir / "1.2.4.json").write_text(
        json.dumps(_profile_payload(profile_version="1.2.4")),
        encoding="utf-8",
    )

    first = load_supported_rules_profile(
        profile_id="test_combat_profile",
        profile_version="1.2.3",
        profiles_dir=tmp_path,
    )
    second = load_supported_rules_profile(
        profile_id="test_combat_profile",
        profile_version="1.2.4",
        profiles_dir=tmp_path,
    )

    assert first.profile_version == "1.2.3"
    assert second.profile_version == "1.2.4"
