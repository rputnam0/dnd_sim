from __future__ import annotations

import argparse
import json
from pathlib import Path

from dnd_sim.replay import diff_replay_bundles, load_replay_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two replay bundles and emit deterministic structured diff output."
    )
    parser.add_argument("left", type=Path, help="Path to the left replay bundle JSON file.")
    parser.add_argument("right", type=Path, help="Path to the right replay bundle JSON file.")
    parser.add_argument(
        "--ignore-path",
        action="append",
        default=[],
        help="Exact flattened path to ignore (repeatable).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional destination JSON file for the diff report. Defaults to stdout.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    left_path = args.left.resolve()
    right_path = args.right.resolve()
    left_bundle = load_replay_bundle(left_path)
    right_bundle = load_replay_bundle(right_path)
    report = diff_replay_bundles(
        left_bundle,
        right_bundle,
        ignore_paths=set(args.ignore_path),
    )
    report["left_path"] = str(left_path)
    report["right_path"] = str(right_path)

    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)
    if args.out is None:
        print(encoded)
    else:
        destination = args.out.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded + "\n", encoding="utf-8")

    return 0 if bool(report["equal"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
