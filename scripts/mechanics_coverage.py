from __future__ import annotations

import argparse
import json
from pathlib import Path

from dnd_sim.mechanics_schema import build_mechanics_coverage_report, validate_mechanics_directories


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
        "--strict",
        action="store_true",
        help="Exit non-zero when mechanics schema validation issues are found.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    coverage = build_mechanics_coverage_report(
        traits_dir=args.traits_dir,
        spells_dir=args.spells_dir,
        monsters_dir=args.monsters_dir,
    )
    validation = validate_mechanics_directories(
        traits_dir=args.traits_dir,
        spells_dir=args.spells_dir,
        monsters_dir=args.monsters_dir,
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

    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
        print(f"Wrote mechanics report to {args.out}")
    else:
        print(encoded)

    if args.strict and issue_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
