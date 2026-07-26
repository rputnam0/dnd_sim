from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dnd_sim.capability_evidence import load_supported_capability_pack
from dnd_sim.mechanics_schema import build_mechanics_coverage_report, validate_mechanics_directories

_SUPPORTED_PACK_CONTENT_KINDS = {
    "background": "trait",
    "feat": "trait",
    "monster": "monster",
    "species": "trait",
    "spell": "spell",
    "trait": "trait",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate normalized mechanics schema and report mechanics coverage "
            "(ingested/executable/unsupported)."
        )
    )
    parser.add_argument("--traits-dir", type=Path, default=Path("db/rules/2014/traits"))
    parser.add_argument("--spells-dir", type=Path, default=Path("db/rules/2014/spells"))
    parser.add_argument("--monsters-dir", type=Path, default=Path("db/rules/2014/monsters"))
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON output file path")
    parser.add_argument(
        "--supported-pack",
        type=Path,
        default=None,
        help="Validate only canonical content declared by this supported-pack JSON file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when mechanics schema validation issues are found.",
    )
    return parser


def _slug_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _canonical_content_id(*, kind: str, path: Path, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("content_id", "")).strip()
    if explicit and kind != "monster":
        if ":" in explicit:
            return explicit
        if kind == "spell":
            return f"spell:{explicit}"
        source_type = str(payload.get("source_type", "")).strip().lower()
        content_type = source_type if source_type in {"feat", "background", "species"} else "trait"
        return f"{content_type}:{explicit}"

    if kind == "spell":
        return f"spell:{_slug_token(path.stem)}"
    if kind == "trait":
        source_type = str(payload.get("source_type", "")).strip().lower()
        content_type = source_type if source_type in {"feat", "background", "species"} else "trait"
        return f"{content_type}:{_slug_token(path.stem)}"

    identity = payload.get("identity")
    if isinstance(identity, dict):
        identifier = identity.get("enemy_id") or identity.get("name")
    else:
        identifier = payload.get("name")
    return f"monster:{_slug_token(identifier or path.stem)}"


def _discover_supported_pack_files(
    *,
    content_ids: Sequence[str],
    traits_dir: Path,
    spells_dir: Path,
    monsters_dir: Path,
) -> dict[str, tuple[Path, ...]]:
    requested = set(content_ids)
    unsupported_types = sorted(
        {
            content_id.split(":", maxsplit=1)[0]
            for content_id in requested
            if content_id.split(":", maxsplit=1)[0] not in _SUPPORTED_PACK_CONTENT_KINDS
        }
    )
    if unsupported_types:
        raise ValueError(
            "supported pack contains content types outside mechanics coverage: "
            + ", ".join(unsupported_types)
        )

    directories = {
        "trait": traits_dir,
        "spell": spells_dir,
        "monster": monsters_dir,
    }
    selected: dict[str, list[Path]] = {kind: [] for kind in directories}
    found: dict[str, Path] = {}
    for kind, directory in directories.items():
        for path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            content_id = _canonical_content_id(kind=kind, path=path, payload=raw)
            if content_id not in requested:
                continue
            if content_id in found:
                raise ValueError(
                    f"supported-pack content_id resolves to multiple files: {content_id}"
                )
            found[content_id] = path
            selected[kind].append(path)

    missing = sorted(requested - set(found), key=str.casefold)
    if missing:
        raise ValueError(
            "supported-pack content_id was not found in mechanics directories: "
            + ", ".join(missing)
        )

    return {
        kind: tuple(sorted(paths, key=lambda path: str(path).casefold()))
        for kind, paths in selected.items()
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    included_files_by_kind: dict[str, tuple[Path, ...]] | None = None
    pack_metadata: dict[str, object] | None = None
    if args.supported_pack is not None:
        try:
            pack = load_supported_capability_pack(args.supported_pack)
            content_ids = tuple(entry.content_id for entry in pack.entries)
            included_files_by_kind = _discover_supported_pack_files(
                content_ids=content_ids,
                traits_dir=args.traits_dir,
                spells_dir=args.spells_dir,
                monsters_dir=args.monsters_dir,
            )
        except (OSError, ValueError) as exc:
            print(f"Supported-pack mechanics selection failed: {exc}", file=sys.stderr)
            return 2
        pack_metadata = {
            "pack_id": pack.pack_id,
            "ruleset": pack.ruleset,
            "content_ids": sorted(content_ids, key=str.casefold),
        }

    coverage = build_mechanics_coverage_report(
        traits_dir=args.traits_dir,
        spells_dir=args.spells_dir,
        monsters_dir=args.monsters_dir,
        included_files_by_kind=included_files_by_kind,
    )
    validation = validate_mechanics_directories(
        traits_dir=args.traits_dir,
        spells_dir=args.spells_dir,
        monsters_dir=args.monsters_dir,
        included_files_by_kind=included_files_by_kind,
    )

    issue_count = sum(
        len(file_issues)
        for kind_issues in validation.values()
        for file_issues in kind_issues.values()
    )

    payload = {
        "coverage": coverage,
        "validation": validation,
        "validation_issue_count": issue_count,
    }
    if pack_metadata is not None:
        payload["supported_pack"] = pack_metadata

    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
        print(f"Wrote mechanics report to {args.out}")
    else:
        print(encoded)

    if args.strict and issue_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
