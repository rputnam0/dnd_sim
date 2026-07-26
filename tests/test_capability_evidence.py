from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.capability_evidence import (
    DEFAULT_EVIDENCE_REGISTRY_PATH,
    DEFAULT_SUPPORTED_PACKS_DIR,
    CapabilityEvidenceError,
    CapabilityEvidenceTarget,
    CapabilityTestEvidenceRegistry,
    EvidenceRecord,
    SupportedCapabilityPack,
    SupportedPackEntry,
    build_evidence_overlay,
    build_supported_pack_evidence_plan,
    collect_exact_pytest_nodes,
    load_supported_capability_pack,
    load_test_evidence_registry,
    run_exact_pytest_nodes,
    validate_exact_pytest_node_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _evidence(
    *,
    evidence_id: str = "pytest.spell.test_spell.base_effect.v1",
    content_id: str = "spell:test_spell",
    claims: tuple[str, ...] = ("canonical_hydration", "base_effect_resolution"),
    pytest_node_ids: tuple[str, ...] = (
        "tests/test_capability_evidence.py::test_evidence_record_rejects_duplicate_claims_and_nodes",
    ),
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        kind="pytest",
        content_id=content_id,
        claims=claims,
        pytest_node_ids=pytest_node_ids,
    )


def _registry(*records: EvidenceRecord) -> CapabilityTestEvidenceRegistry:
    return CapabilityTestEvidenceRegistry(
        schema_version="1.0",
        ruleset="2014",
        evidence=records or (_evidence(),),
    )


def _pack(
    *entries: SupportedPackEntry,
    ruleset: str = "2014",
) -> SupportedCapabilityPack:
    return SupportedCapabilityPack(
        schema_version="1.0",
        pack_id="test_combat_pack_v0",
        ruleset=ruleset,
        support_contract="verified_primary_combat_resolution_v1",
        entries=entries
        or (
            SupportedPackEntry(
                content_id="spell:test_spell",
                required_claims=("canonical_hydration", "base_effect_resolution"),
            ),
        ),
    )


def _target(
    content_id: str = "spell:test_spell",
    *,
    schema_valid: bool = True,
    executable: bool = True,
    blocked: bool = False,
) -> CapabilityEvidenceTarget:
    return CapabilityEvidenceTarget(
        content_id=content_id,
        schema_valid=schema_valid,
        executable=executable,
        blocked=blocked,
    )


def test_evidence_models_are_strict_and_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(
            {
                "evidence_id": "pytest.spell.test_spell.base_effect.v1",
                "kind": "pytest",
                "content_id": "spell:test_spell",
                "claims": ("base_effect_resolution",),
                "pytest_node_ids": (
                    "tests/test_capability_evidence.py::test_evidence_models_are_strict_and_forbid_unknown_fields",
                ),
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError):
        CapabilityEvidenceTarget.model_validate(
            {
                "content_id": "spell:test_spell",
                "schema_valid": 1,
                "executable": True,
                "blocked": False,
            }
        )


def test_evidence_record_rejects_duplicate_claims_and_nodes() -> None:
    with pytest.raises(ValidationError, match="duplicate claims"):
        _evidence(claims=("base_effect_resolution", "base_effect_resolution"))

    node_id = (
        "tests/test_capability_evidence.py::test_evidence_record_rejects_duplicate_claims_and_nodes"
    )
    with pytest.raises(ValidationError, match="duplicate pytest_node_ids"):
        _evidence(pytest_node_ids=(node_id, node_id))


def test_registry_rejects_duplicate_evidence_ids_and_node_ownership() -> None:
    first = _evidence()
    with pytest.raises(ValidationError, match="duplicate evidence_id"):
        _registry(first, first)

    with pytest.raises(ValidationError, match="pytest node.*more than one evidence record"):
        _registry(
            first,
            _evidence(
                evidence_id="pytest.spell.other_spell.base_effect.v1",
                content_id="spell:other_spell",
            ),
        )


def test_pack_requires_unique_nonempty_entries_and_claims() -> None:
    entry = SupportedPackEntry(
        content_id="spell:test_spell",
        required_claims=("base_effect_resolution",),
    )
    with pytest.raises(ValidationError, match="duplicate content_id"):
        _pack(entry, entry)

    with pytest.raises(ValidationError):
        SupportedPackEntry(content_id="spell:test_spell", required_claims=())

    with pytest.raises(ValidationError):
        SupportedCapabilityPack(
            schema_version="1.0",
            pack_id="empty_pack",
            ruleset="2014",
            support_contract="verified_primary_combat_resolution_v1",
            entries=(),
        )


def test_overlay_derives_tested_and_exact_evidence_for_each_content() -> None:
    registry = _registry(
        _evidence(
            evidence_id="pytest.spell.test_spell.zeta.v1",
            claims=("zeta_claim",),
        ),
        _evidence(
            evidence_id="pytest.spell.test_spell.alpha.v1",
            claims=("alpha_claim",),
            pytest_node_ids=(
                "tests/test_capability_evidence.py::test_overlay_derives_tested_and_exact_evidence_for_each_content",
            ),
        ),
    )

    overlay = build_evidence_overlay(
        targets=(_target(), _target("spell:untested_spell")),
        registry=registry,
    )

    assert overlay["spell:test_spell"].tested is True
    assert overlay["spell:test_spell"].evidence_ids == (
        "pytest.spell.test_spell.alpha.v1",
        "pytest.spell.test_spell.zeta.v1",
    )
    assert overlay["spell:test_spell"].claims == ("alpha_claim", "zeta_claim")
    assert overlay["spell:untested_spell"].tested is False
    assert overlay["spell:untested_spell"].evidence_ids == ()


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (_target(schema_valid=False), "schema-valid"),
        (_target(executable=False, blocked=True), "executable and unblocked"),
        (_target(executable=True, blocked=True), "executable and unblocked"),
    ],
)
def test_overlay_rejects_evidence_for_ineligible_content(
    target: CapabilityEvidenceTarget,
    message: str,
) -> None:
    with pytest.raises(CapabilityEvidenceError, match=message):
        build_evidence_overlay(targets=(target,), registry=_registry())


def test_overlay_rejects_unknown_evidence_content_and_duplicate_targets() -> None:
    with pytest.raises(CapabilityEvidenceError, match="unknown canonical content_id"):
        build_evidence_overlay(
            targets=(_target("spell:different_spell"),),
            registry=_registry(),
        )

    with pytest.raises(CapabilityEvidenceError, match="duplicate capability target"):
        build_evidence_overlay(
            targets=(_target(), _target()),
            registry=_registry(),
        )


def test_supported_pack_plan_requires_exact_content_claim_coverage() -> None:
    registry = _registry()
    targets = (_target(),)

    plan = build_supported_pack_evidence_plan(
        pack=_pack(),
        registry=registry,
        targets=targets,
    )

    assert plan.pack_id == "test_combat_pack_v0"
    assert plan.content_ids == ("spell:test_spell",)
    assert plan.evidence_ids == ("pytest.spell.test_spell.base_effect.v1",)
    assert plan.pytest_node_ids == _evidence().pytest_node_ids

    missing_claim_pack = _pack(
        SupportedPackEntry(
            content_id="spell:test_spell",
            required_claims=("uncovered_rule_branch",),
        )
    )
    with pytest.raises(
        CapabilityEvidenceError, match="missing required claims.*uncovered_rule_branch"
    ):
        build_supported_pack_evidence_plan(
            pack=missing_claim_pack,
            registry=registry,
            targets=targets,
        )


def test_supported_pack_plan_rejects_unknown_content_and_ruleset_mismatch() -> None:
    with pytest.raises(CapabilityEvidenceError, match="unknown canonical content_id"):
        build_supported_pack_evidence_plan(
            pack=_pack(
                SupportedPackEntry(
                    content_id="spell:missing_spell",
                    required_claims=("base_effect_resolution",),
                )
            ),
            registry=_registry(),
            targets=(_target(),),
        )

    with pytest.raises(CapabilityEvidenceError, match="ruleset mismatch"):
        build_supported_pack_evidence_plan(
            pack=_pack(ruleset="2024"),
            registry=_registry(),
            targets=(_target(),),
        )


def test_exact_pytest_node_validation_rejects_unsafe_or_broad_selectors(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    test_file = repo_root / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_passes():\n    assert True\n", encoding="utf-8")

    node_id = "tests/test_sample.py::test_passes"
    assert validate_exact_pytest_node_id(node_id, repo_root=repo_root) == node_id

    invalid = (
        "tests/test_sample.py",
        "../tests/test_sample.py::test_passes",
        "/tests/test_sample.py::test_passes",
        "src/test_sample.py::test_passes",
        "tests/*.py::test_passes",
        "tests/test_missing.py::test_passes",
        "tests/test_sample.py::TestSample",
    )
    for candidate in invalid:
        with pytest.raises(CapabilityEvidenceError):
            validate_exact_pytest_node_id(candidate, repo_root=repo_root)


def test_collection_requires_exact_leaf_nodes_including_parameter_ids(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    test_file = repo_root / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize(('value',), [(1,), (2,)], ids=('one', 'two'))\n"
        "def test_value(value):\n"
        "    assert value > 0\n",
        encoding="utf-8",
    )

    exact = "tests/test_sample.py::test_value[one]"
    assert collect_exact_pytest_nodes((exact,), repo_root=repo_root) == (exact,)

    with pytest.raises(CapabilityEvidenceError, match="exact pytest leaf"):
        collect_exact_pytest_nodes(
            ("tests/test_sample.py::test_value",),
            repo_root=repo_root,
        )


def test_execution_requires_every_exact_node_to_pass(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    test_file = repo_root / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "import pytest\n\n"
        "def test_passes():\n"
        "    assert True\n\n"
        "@pytest.mark.skip(reason='not evidence')\n"
        "def test_skips():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    passing_node = "tests/test_sample.py::test_passes"
    result = run_exact_pytest_nodes((passing_node,), repo_root=repo_root)
    assert result.node_ids == (passing_node,)
    assert result.passed_count == 1

    with pytest.raises(CapabilityEvidenceError, match="must pass; skipped or xfailed"):
        run_exact_pytest_nodes(
            ("tests/test_sample.py::test_skips",),
            repo_root=repo_root,
        )


def test_repository_seed_registry_and_pack_form_an_exact_supported_plan() -> None:
    registry = load_test_evidence_registry(DEFAULT_EVIDENCE_REGISTRY_PATH)
    pack = load_supported_capability_pack(DEFAULT_SUPPORTED_PACKS_DIR / "combat_primitives_v0.json")
    targets = tuple(_target(entry.content_id) for entry in pack.entries)

    plan = build_supported_pack_evidence_plan(
        pack=pack,
        registry=registry,
        targets=targets,
    )

    assert plan.content_ids == (
        "spell:acid_arrow",
        "spell:cure_wounds",
        "spell:thunderwave",
    )
    assert len(plan.evidence_ids) == 3
    assert len(plan.pytest_node_ids) == 3


def test_registry_loader_rejects_non_json_object(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_test_evidence_registry(path)
