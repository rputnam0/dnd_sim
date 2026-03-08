from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from dnd_sim import io as io_module

_SCOPE_MAP = {
    "all": None,
    "spell": {"spell"},
    "feature": {"feat", "trait", "background", "species"},
    "item": {"item"},
    "class": {"class", "subclass"},
    "monster": {
        "monster",
        "monster_action",
        "monster_reaction",
        "monster_legendary_action",
        "monster_lair_action",
        "monster_recharge",
        "monster_innate_spellcasting",
    },
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify capability manifest gates for shipped 2014 content.",
    )
    parser.add_argument(
        "--scope",
        choices=sorted(_SCOPE_MAP),
        default="all",
        help="Capability scope to verify (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report issues without failing the command.",
    )
    return parser.parse_args(argv)


def verify_capabilities(scope: str) -> list[str]:
    required_content_types = _SCOPE_MAP[scope]
    return io_module.capability_gate_issues_for_types(required_content_types=required_content_types)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    issues = verify_capabilities(args.scope)

    if issues:
        print(
            f"Capability gate issues detected for scope '{args.scope}': " f"{len(issues)} issue(s)."
        )
        for issue in issues:
            print(f"- {issue}")
        if args.dry_run:
            print("Capability gate dry-run completed with issues.")
            return 0
        return 1

    print(f"Capability gates passed for scope '{args.scope}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
