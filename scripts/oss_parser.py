import json
import os
import re
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency at runtime only
    OpenAI = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency at runtime only

    def load_dotenv() -> bool:
        return False


def sanitize_name(name: str) -> str:
    value = str(name).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def main() -> None:
    if OpenAI is None:
        print("Install the 'openai' package to use this parser.")
        return

    load_dotenv()
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        print("Set DEEPINFRA_API_KEY environment variable to use the parser.")
        return

    client = OpenAI(api_key=api_key, base_url="https://api.deepinfra.com/v1/openai")

    root = Path(__file__).resolve().parents[1]
    raw_spells_file = root / "db" / "raw" / "5etools" / "spells" / "spells-phb.json"
    spells_db_dir = root / "db" / "rules" / "2014" / "spells"
    spells_db_dir.mkdir(parents=True, exist_ok=True)

    existing_spells = {file.stem for file in spells_db_dir.glob("*.json")}

    if not raw_spells_file.exists():
        print(f"No raw spells found at {raw_spells_file}.")
        return

    sys_prompt = """You are an expert D&D 5e mechanics parser for a python combat simulator.
The user will provide you with the raw JSON structured text of a D&D Spell from 5e.tools.
You must output a single JSON object matching this schema exactly:
{
    "name": "The exact name of the spell",
    "type": "spell",
    "level": 0,
    "school": "Abjuration",
    "casting_time": "action",
    "range_ft": 60,
    "concentration": false,
    "duration_rounds": 10,
    "description": "A synthesized plain-text description",
    "save_ability": "dex",
    "damage_type": "fire",
    "mechanics": []
}
Return ONLY valid JSON. Your response will be parsed directly via json.loads().
"""

    raw_data = json.loads(raw_spells_file.read_text(encoding="utf-8"))
    spells_array = raw_data.get("spell", [])
    print(f"Found {len(spells_array)} raw spells in 5etools PHB database.")

    processed = 0
    model_name = "openai/gpt-oss-120b"

    for spell_data in spells_array:
        spell_name = spell_data.get("name", "Unknown")
        safe_name = sanitize_name(spell_name)

        if safe_name in existing_spells:
            continue

        print(f"Parsing {safe_name} via {model_name}...")
        content_string = json.dumps(spell_data, indent=2)

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": content_string},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            parsed_text = response.choices[0].message.content
            if not parsed_text:
                print(f"Failed to parse {safe_name}: empty response content")
                continue
            parsed_json = json.loads(parsed_text)
            out_path = spells_db_dir / f"{safe_name}.json"
            out_path.write_text(json.dumps(parsed_json, indent=2), encoding="utf-8")
            print(f"  -> Saved {out_path.name}")
            processed += 1
            time.sleep(1)

        except Exception as exc:  # pragma: no cover - network/runtime errors
            print(f"Failed to parse {safe_name}: {exc}")

    print(f"\nSuccessfully parsed {processed} new spells using {model_name}.")


if __name__ == "__main__":
    main()
