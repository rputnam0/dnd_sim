import argparse
import json
import logging
from pathlib import Path

import fitz  # PyMuPDF

from dnd_sim.telemetry import emit_event

logger = logging.getLogger(__name__)


def extract_raw_text(pdf_path: Path, out_path: Path) -> None:
    """Extract raw text using block parsing to maintain paragraph integrity."""
    doc = fitz.open(pdf_path)
    text_pages = []

    for i, page in enumerate(doc):
        # type 0 is text. Separate into left and right columns for D&D 2-column layout
        blocks = page.get_text("blocks")
        mid_x = page.rect.width / 2

        left_blocks = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right_blocks = [b for b in blocks if b[0] >= mid_x and b[6] == 0]

        left_blocks.sort(key=lambda b: b[1])
        right_blocks.sort(key=lambda b: b[1])

        page_lines = []
        for b in left_blocks + right_blocks:
            text = b[4].replace("\u00a0", " ").strip()
            # Remove intra-line weirdness
            text = " ".join(text.split())
            if text:
                page_lines.append(text)

        text_pages.append(f"---PAGE {i + 1}---\n" + "\n".join(page_lines))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(text_pages), encoding="utf-8")
    emit_event(
        logger,
        event_type="srd_text_extracted",
        source=__name__,
        payload={
            "input_path": str(pdf_path),
            "output_path": str(out_path),
            "page_count": len(text_pages),
        },
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Ingest 2014 SRD rules from PDF.")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("rules/2014/SRD_CC_v5.1.pdf"),
        help="Path to SRD PDF",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("db/rules/2014/srd_raw.txt"),
        help="Output raw text file",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    pdf_path = root / args.pdf
    raw_out = root / args.out

    if not pdf_path.exists():
        emit_event(
            logger,
            event_type="srd_pdf_missing",
            source=__name__,
            payload={"input_path": str(pdf_path)},
            level=logging.ERROR,
        )
        return

    extract_raw_text(pdf_path, raw_out)


if __name__ == "__main__":
    main()
