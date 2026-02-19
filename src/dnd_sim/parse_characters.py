from __future__ import annotations

import argparse
from pathlib import Path

from dnd_sim.parser import parse_markdown_to_character_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse character markdown into JSON character DB.")
    parser.add_argument(
        "--input", required=True, type=Path, help="Path to character_sheets_extracted.md"
    )
    parser.add_argument("--out", required=True, type=Path, help="Output DB directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = parse_markdown_to_character_db(args.input, args.out)
    print(f"Parsed {len(records)} characters into {args.out}")


if __name__ == "__main__":
    main()
