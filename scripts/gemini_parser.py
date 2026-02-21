import json
import os
import time
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

def sanitize_name(name):
    return name.lower().replace(" ", "_").replace("'", "").replace("-", "_").replace(":", "_")

def main():
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY environment variable to use the parser.")
        return

    client = genai.Client(api_key=api_key)
    
    root = Path(__file__).resolve().parents[1]
    raw_feats_file = root / "db" / "raw" / "5etools" / "feats.json"
    traits_db_dir = root / "db" / "rules" / "2014" / "traits"
    
    existing_traits = set()
    if traits_db_dir.exists():
        for f in traits_db_dir.glob("*.json"):
            existing_traits.add(f.stem)
            
    if not raw_feats_file.exists():
        print(f"No raw feats found at {raw_feats_file}.")
        return

    sys_prompt = """You are an expert D&D 5e mechanics parser for a python combat simulator.
The user will provide you with the raw JSON structured text of a D&D Feat from 5e.tools.
You must output a single JSON object matching this schema exactly:
{
    "name": "The exact name of the feat",
    "type": "feat",
    "description": "A synthesized plain-text description of the feat",
    "mechanics": [
        // A list of objects detailing the explicit mechanics, e.g.:
        // {"effect_type": "stat_increase", "stat": "str", "amount": 1, "max": 20},
        // {"effect_type": "advantage_attack", "trigger": "grappled_by_you"},
        // {"effect_type": "bonus_action_attack", "weapon_type": "hand_crossbow", "prerequisite_action": "attack"},
        // {"effect_type": "initiative_bonus", "bonus": 5}
    ]
}
If there are no programmatic mechanics, leave the list empty.
Return ONLY valid JSON. Your response will be parsed directly via json.loads().
"""

    raw_data = json.loads(raw_feats_file.read_text())
    feats_array = raw_data.get("feat", [])
    print(f"Found {len(feats_array)} raw feats in 5etools database.")
    
    processed = 0
    model_name = "gemini-3-flash-preview"
    
    for feat_data in feats_array:
        feat_name = feat_data.get("name", "Unknown")
        safe_name = sanitize_name(feat_name)
        
        if safe_name in existing_traits:
            # print(f"Skipping {safe_name}, already in parsed traits DB.")
            continue
            
        print(f"Parsing {safe_name} via {model_name}...")
        
        # Convert the json object back to a string so the LLM can read the structure
        content_string = json.dumps(feat_data, indent=2)
        
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=content_string,
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    response_mime_type="application/json",
                    temperature=0.1
                ),
            )
            
            # Save the parsed output
            parsed_json = json.loads(response.text)
            out_path = traits_db_dir / f"{safe_name}.json"
            out_path.write_text(json.dumps(parsed_json, indent=2))
            print(f"  -> Saved {out_path.name}")
            processed += 1
            
            # Rate limiting
            time.sleep(2)
            
        except Exception as e:
            print(f"Failed to parse {safe_name}: {e}")

    print(f"\nSuccessfully parsed {processed} new feats using {model_name}.")

if __name__ == "__main__":
    main()
