from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/mechanics_coverage.py"

spec = importlib.util.spec_from_file_location("mechanics_coverage", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
mechanics_coverage = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mechanics_coverage
spec.loader.exec_module(mechanics_coverage)


def _write_spell(path: Path, *, effect_type: str) -> None:
    path.write_text(
        json.dumps(
            {
                "name": path.stem.replace("_", " ").title(),
                "type": "spell",
                "mechanics": [{"effect_type": effect_type, "damage": "1d6"}],
            }
        ),
        encoding="utf-8",
    )


def _write_pack(path: Path, *content_ids: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "pack_id": "test_pack",
                "ruleset": "2014",
                "support_contract": "test_contract",
                "entries": [
                    {
                        "content_id": content_id,
                        "required_claims": ["primary_resolution"],
                    }
                    for content_id in content_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def _empty_mechanics_directories(tmp_path: Path) -> tuple[Path, Path, Path]:
    traits_dir = tmp_path / "traits"
    spells_dir = tmp_path / "spells"
    monsters_dir = tmp_path / "monsters"
    traits_dir.mkdir()
    spells_dir.mkdir()
    monsters_dir.mkdir()
    return traits_dir, spells_dir, monsters_dir


def test_supported_pack_strict_mode_validates_only_declared_content(tmp_path: Path) -> None:
    traits_dir, spells_dir, monsters_dir = _empty_mechanics_directories(tmp_path)
    _write_spell(spells_dir / "selected_spell.json", effect_type="damage")
    _write_spell(spells_dir / "undeclared_spell.json", effect_type="future_effect")
    pack_path = tmp_path / "supported_pack.json"
    report_path = tmp_path / "pack_report.json"
    _write_pack(pack_path, "spell:selected_spell")

    exit_code = mechanics_coverage.main(
        [
            "--traits-dir",
            str(traits_dir),
            "--spells-dir",
            str(spells_dir),
            "--monsters-dir",
            str(monsters_dir),
            "--supported-pack",
            str(pack_path),
            "--strict",
            "--out",
            str(report_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["supported_pack"] == {
        "content_ids": ["spell:selected_spell"],
        "pack_id": "test_pack",
        "ruleset": "2014",
    }
    assert report["coverage"]["by_kind"]["spell"]["files"] == 1
    assert report["coverage"]["totals"] == {
        "executable": 1,
        "ingested": 1,
        "unsupported": 0,
    }
    assert report["validation_issue_count"] == 0


def test_omitting_supported_pack_preserves_whole_catalog_strict_behavior(
    tmp_path: Path,
) -> None:
    traits_dir, spells_dir, monsters_dir = _empty_mechanics_directories(tmp_path)
    _write_spell(spells_dir / "selected_spell.json", effect_type="damage")
    _write_spell(spells_dir / "undeclared_spell.json", effect_type="future_effect")
    report_path = tmp_path / "catalog_report.json"

    exit_code = mechanics_coverage.main(
        [
            "--traits-dir",
            str(traits_dir),
            "--spells-dir",
            str(spells_dir),
            "--monsters-dir",
            str(monsters_dir),
            "--strict",
            "--out",
            str(report_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "supported_pack" not in report
    assert report["coverage"]["by_kind"]["spell"]["files"] == 2
    assert report["coverage"]["totals"]["unsupported"] == 1
    assert report["validation_issue_count"] == 1


def test_supported_pack_fails_closed_when_declared_content_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    traits_dir, spells_dir, monsters_dir = _empty_mechanics_directories(tmp_path)
    pack_path = tmp_path / "supported_pack.json"
    report_path = tmp_path / "pack_report.json"
    _write_pack(pack_path, "spell:missing_spell")

    exit_code = mechanics_coverage.main(
        [
            "--traits-dir",
            str(traits_dir),
            "--spells-dir",
            str(spells_dir),
            "--monsters-dir",
            str(monsters_dir),
            "--supported-pack",
            str(pack_path),
            "--strict",
            "--out",
            str(report_path),
        ]
    )

    assert exit_code == 2
    assert not report_path.exists()
    assert "spell:missing_spell" in capsys.readouterr().err
