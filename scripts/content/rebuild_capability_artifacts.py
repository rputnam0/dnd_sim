from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from dnd_sim.capability_manifest import (
    MANIFEST_VERSION,
    build_class_capability_manifest,
    build_feature_capability_manifest,
    build_item_capability_manifest,
    build_manifest,
    build_monster_capability_manifest,
    build_spell_capability_manifest,
    build_subclass_capability_manifest,
    write_manifest,
)

MANIFEST_PATH = REPO_ROOT / "artifacts" / "capabilities" / "manifest_2014.json"


def rebuild_manifest() -> None:
    base = REPO_ROOT / "db" / "rules" / "2014"
    records = []
    for manifest in (
        build_spell_capability_manifest(spells_dir=base / "spells"),
        build_feature_capability_manifest(features_dir=base / "traits"),
        build_monster_capability_manifest(monsters_dir=base / "monsters"),
        build_item_capability_manifest(items_dir=base / "items"),
        build_class_capability_manifest(classes_dir=base / "classes"),
        build_subclass_capability_manifest(subclasses_dir=base / "subclasses"),
    ):
        records.extend(record.model_dump(mode="json") for record in manifest.records)

    manifest = build_manifest(
        records=records,
        manifest_version=MANIFEST_VERSION,
        generated_at=None,
    )
    write_manifest(manifest, MANIFEST_PATH)


def rebuild_report() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "content" / "render_capability_report.py"),
            "--last-updated",
            "2026-03-08",
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def main() -> None:
    rebuild_manifest()
    rebuild_report()
    print(f"Rebuilt capability artifacts under {MANIFEST_PATH.parent}")


if __name__ == "__main__":
    main()
