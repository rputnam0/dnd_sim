from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dnd_sim.parser import parse_markdown_to_character_db
from dnd_sim.telemetry import emit_event

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse character markdown into JSON character DB.")
    parser.add_argument(
        "--input", required=True, type=Path, help="Path to character_sheets_extracted.md"
    )
    parser.add_argument("--out", required=True, type=Path, help="Output DB directory")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args()
    records = parse_markdown_to_character_db(args.input, args.out)
    emit_event(
        logger,
        event_type="characters_parsed",
        source=__name__,
        payload={
            "count": len(records),
            "input_path": str(args.input),
            "output_path": str(args.out),
        },
    )


if __name__ == "__main__":
    main()
