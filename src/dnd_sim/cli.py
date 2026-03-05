from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dnd_sim import content_index
from dnd_sim import db as db_module

logger = logging.getLogger(__name__)


def _add_query_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", type=Path, default=db_module.get_db_path())
    parser.add_argument("--content-id", default=None)
    parser.add_argument("--content-type", default=None)
    parser.add_argument("--support-state", default=None)
    parser.add_argument("--unsupported-reason", default=None)
    parser.add_argument("--source-book", default=None)
    parser.add_argument("--schema-version", default=None)
    parser.add_argument("--limit", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query canonical persistence coverage, schema-version, and lineage records."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_parser = subparsers.add_parser(
        "query-content",
        help="List canonical content records with optional filters.",
    )
    _add_query_filters(query_parser)

    coverage_parser = subparsers.add_parser(
        "content-coverage",
        help="Summarize support-state and schema-version coverage for filtered records.",
    )
    _add_query_filters(coverage_parser)
    return parser


def _query_records(args: argparse.Namespace) -> list[dict[str, object]]:
    return content_index.query_content_records_from_db(
        db_path=args.db_path,
        content_id=args.content_id,
        content_type=args.content_type,
        support_state=args.support_state,
        unsupported_reason=args.unsupported_reason,
        source_book=args.source_book,
        schema_version=args.schema_version,
        limit=args.limit,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    try:
        records = _query_records(args)
        if args.command == "query-content":
            print(json.dumps(records, indent=2, sort_keys=True))
            return 0
        if args.command == "content-coverage":
            print(
                json.dumps(
                    content_index.summarize_content_coverage(records), indent=2, sort_keys=True
                )
            )
            return 0
        raise ValueError(f"Unsupported command: {args.command}")
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
