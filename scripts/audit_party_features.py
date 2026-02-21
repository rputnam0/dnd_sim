from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dnd_sim.engine import _build_actor_from_character
from dnd_sim.io import load_character_db, load_scenario, load_traits_db


def _has_spell_payload(action: dict[str, Any]) -> bool:
    if action.get("healing"):
        return True
    if action.get("damage") and action.get("damage_type"):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit party spells/traits coverage.")
    parser.add_argument("--scenario", required=True, type=Path, help="Scenario JSON path")
    args = parser.parse_args()

    loaded = load_scenario(args.scenario)
    db = load_character_db(Path(loaded.config.character_db_dir))
    canonical_traits_dir = Path("db/rules/2014/traits")
    traits_db = load_traits_db(canonical_traits_dir)
    local_traits_dir = Path(loaded.config.character_db_dir).parent / "traits"
    if local_traits_dir.exists():
        traits_db.update(load_traits_db(local_traits_dir))

    print(f"Scenario: {loaded.config.scenario_id}")
    print("")

    for cid in loaded.config.party:
        character = db[cid]
        actor = _build_actor_from_character(character, traits_db=traits_db)
        print(f"- {cid} ({actor.name})")
        # Traits in actor.traits are normalized keys, even if trait DB is empty.
        interesting = [k for k in actor.traits.keys() if k in {"gnomish cunning", "fey ancestry", "blind fighting"}]
        if interesting:
            print(f"  traits: {interesting}")
        unresolved_traits = sorted([k for k, v in actor.traits.items() if not v])
        print(
            f"  traits_total: {len(actor.traits)} (unresolved_in_db: {len(unresolved_traits)})"
        )
        if unresolved_traits:
            print(
                f"  unresolved: {unresolved_traits[:16]}{' ...' if len(unresolved_traits) > 16 else ''}"
            )

        # Spell extraction happens inside engine; reproduce the extracted list by calling build again.
        spells = character.get("spells") or []
        if not spells:
            # Import lazily so this script doesn't become part of runtime surface area.
            from dnd_sim.engine import _extract_spells_from_raw_fields

            spells = _extract_spells_from_raw_fields(character)

        if spells:
            missing = [s["name"] for s in spells if not _has_spell_payload(s)]
            print(f"  spells_extracted: {len(spells)} (missing payload: {len(missing)})")
            if missing:
                print(f"  missing: {missing[:12]}{' ...' if len(missing) > 12 else ''}")
        else:
            print("  spells_extracted: 0")
        print("")

    # Output a machine-readable summary too.
    payload = {"scenario_id": loaded.config.scenario_id, "party": loaded.config.party}
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
