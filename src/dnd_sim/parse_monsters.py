import json
import re
from pathlib import Path
from typing import Any

_MONSTER_BLOCK_RE = re.compile(
    r"^(.*?)\n"
    r"(.*?)\n"
    r"Armor Class (\d+)(.*?)\n"
    r"Hit Points (\d+) \((.*?)\)\n"
    r"Speed (.*?)\n"
    r"STR DEX CON INT WIS CHA\n"
    r"(\d+) \([^)]+\) (\d+) \([^)]+\) (\d+) \([^)]+\) (\d+) \([^)]+\) (\d+) \([^)]+\) (\d+) \([^)]+\)",
    re.MULTILINE,
)


def parse_monsters(raw_text: str) -> list[dict[str, Any]]:
    start_idx = raw_text.find("Monsters (A)")
    end_match = re.search(r"Appendix PH-A:\s*", raw_text)
    if start_idx == -1 or end_match is None:
        return []
    end_idx = end_match.start()

    text = raw_text[start_idx:end_idx]
    monsters: list[dict[str, Any]] = []

    for match in _MONSTER_BLOCK_RE.finditer(text):
        name = match.group(1).strip()
        if name in {"Actions", "Legendary Actions", "Reactions"} or "---PAGE" in name:
            continue

        meta = match.group(2).strip()
        ac = int(match.group(3))
        hp = int(match.group(5))
        hp_formula = match.group(6)

        scores = {
            "str": int(match.group(8)),
            "dex": int(match.group(9)),
            "con": int(match.group(10)),
            "int": int(match.group(11)),
            "wis": int(match.group(12)),
            "cha": int(match.group(13)),
        }

        block_start = match.end()
        next_match = _MONSTER_BLOCK_RE.search(text, block_start)
        block_end = next_match.start() if next_match else len(text)
        block_text = text[block_start:block_end]

        cr_match = re.search(r"Challenge ([\d/]+)", block_text)
        saves_match = re.search(r"Saving Throws (.*?)\n", block_text)

        monsters.append(
            {
                "name": name,
                "meta": meta,
                "ac": ac,
                "hp": hp,
                "hp_formula": hp_formula,
                "ability_scores": scores,
                "cr": cr_match.group(1) if cr_match else "0",
                "saving_throws_text": saves_match.group(1).strip() if saves_match else "",
            }
        )

    return monsters


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    raw_path = root / "db" / "rules" / "2014" / "srd_raw.txt"
    out_dir = root / "db" / "rules" / "2014" / "monsters"

    if not raw_path.exists():
        print(f"Missing {raw_path}")
        return

    raw_text = raw_path.read_text(encoding="utf-8")
    monsters = parse_monsters(raw_text)

    print(f"Parsed {len(monsters)} monsters.")

    out_dir.mkdir(parents=True, exist_ok=True)
    for monster in monsters:
        safe_name = re.sub(r"[^a-z0-9]+", "_", monster["name"].lower()).strip("_")
        if len(safe_name) > 50:
            continue
        (out_dir / f"{safe_name}.json").write_text(json.dumps(monster, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
