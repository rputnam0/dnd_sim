import json
import logging
import re
from pathlib import Path
from typing import Any

from dnd_sim.telemetry import emit_event

logger = logging.getLogger(__name__)

_HEADER_LINE_RE = {
    "casting_time": re.compile(r"Casting Time:\s*(.*?)\s*Range:"),
    "range": re.compile(r"Range:\s*(.*?)\s*Components:"),
    "components": re.compile(r"Components:\s*(.*?)\s*Duration:"),
    "duration": re.compile(r"Duration:\s*(.*)"),
}
_NAME_SUFFIX_RE = re.compile(
    r"\s+(?:\d+(?:st|nd|rd|th)-level\s+\w+|[1-9](?:st|nd|rd|th)-level\s+\w+|\w+\s+cantrip)$",
    re.IGNORECASE,
)


def _extract_spell_name(meta_line: str) -> str:
    cleaned = meta_line.strip()
    cleaned = _NAME_SUFFIX_RE.sub("", cleaned)
    return cleaned.strip()


def _find_spell_meta_line(lines: list[str], casting_index: int) -> str | None:
    for idx in range(casting_index - 1, max(-1, casting_index - 4), -1):
        if idx < 0:
            break
        value = lines[idx].strip()
        if not value:
            continue
        if value.startswith(("---", "System")):
            continue
        return value
    return None


def parse_spells(raw_text: str) -> list[dict[str, Any]]:
    lines = raw_text.split("\n")
    spells: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        if not line.startswith("Casting Time:"):
            continue

        meta_line = _find_spell_meta_line(lines, i)
        if not meta_line:
            continue

        matches = {key: pattern.search(line) for key, pattern in _HEADER_LINE_RE.items()}
        if not all(matches.values()):
            continue

        desc_lines: list[str] = []
        j = i + 1
        while j < len(lines):
            next_line = lines[j].strip()

            if next_line.startswith("Casting Time:"):
                break
            if next_line.startswith("---") or next_line.startswith("System"):
                j += 1
                continue

            # Stop at blank line before next spell heading.
            if not next_line and j + 2 < len(lines):
                maybe_name = lines[j + 1].strip()
                maybe_casting = lines[j + 2].strip()
                if maybe_name and maybe_casting.startswith("Casting Time:"):
                    break

            if next_line:
                desc_lines.append(next_line)

            j += 1
            if j - i > 100:
                break

        spell = {
            "name": _extract_spell_name(meta_line),
            "meta": meta_line,
            "casting_time": matches["casting_time"].group(1).strip(),
            "range": matches["range"].group(1).strip(),
            "components": matches["components"].group(1).strip(),
            "duration": matches["duration"].group(1).strip(),
            "description": " ".join(desc_lines),
        }
        spells.append(spell)

    return spells


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(__file__).resolve().parents[2]
    raw_path = root / "db" / "rules" / "2014" / "srd_raw.txt"
    out_dir = root / "db" / "rules" / "2014" / "spells"

    if not raw_path.exists():
        emit_event(
            logger,
            event_type="spells_parse_input_missing",
            source=__name__,
            payload={"input_path": str(raw_path)},
            level=logging.ERROR,
        )
        return

    raw_text = raw_path.read_text(encoding="utf-8")
    spells = parse_spells(raw_text)

    emit_event(
        logger,
        event_type="spells_parsed",
        source=__name__,
        payload={"count": len(spells), "input_path": str(raw_path)},
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    for spell in spells:
        safe_name = re.sub(r"[^a-z0-9]+", "_", spell["name"].lower()).strip("_")
        if len(safe_name) > 50:
            continue
        (out_dir / f"{safe_name}.json").write_text(json.dumps(spell, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
