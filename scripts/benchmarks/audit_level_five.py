"""Audit a completed benchmark's data, source fingerprints, and every saved replay."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from dnd_sim.benchmarks.level_five import REPO, load_party, replay_sample
from dnd_sim.benchmarks.trials import derive_trial_seed
from dnd_sim.engine_runtime import _build_actor_from_character


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    root = args.summary.parent
    report = json.loads(args.summary.read_text())
    rows = [
        json.loads(line)
        for line in gzip.decompress((root / "trials.jsonl.gz").read_bytes()).decode().splitlines()
    ]
    grouped = defaultdict(list)
    party = {key: _build_actor_from_character(row, {}) for key, row in load_party().items()}
    maximum_hp = sum(actor.max_hp for actor in party.values())
    for row in rows:
        grouped[(row["scenario"], row["policy"])].append(row)
        assert row["seed"] == derive_trial_seed(
            report["master_seed"], row["scenario"], row["trial_index"]
        )
        assert 0 <= row["party_hp"] <= maximum_hp
        assert sum(row["actions"].values()) <= row["turns"]
        assert sum(row["bonuses"].values()) <= row["turns"]
        for resource, spent in row["resources_spent"].items():
            actor, key = resource.split(":", 1)
            assert 0 <= spent <= party[actor].resources[key]
    assert len(grouped) == len(report["groups"])
    for group in report["groups"]:
        data = grouped[(group["scenario"], group["policy"])]
        n = group["summary"]["n"]
        assert len(data) == n == report["trials_per_group"]
        assert {row["trial_index"] for row in data} == set(range(n))
        counts = Counter(row["outcome"] for row in data)
        for metric, count in {
            "win": counts["party_victory"],
            "defeat": counts["enemy_victory"],
            **{
                key: sum(row[key] for row in data)
                for key in ("any_down", "any_death", "all_dead_at_stop", "censored")
            },
        }.items():
            reported = group["summary"][metric]
            assert reported["count"] == count
            assert reported["rate"] == count / n
            assert reported["ci95"][0] - 1e-12 <= count / n <= reported["ci95"][1] + 1e-12
    for path, expected in report["provenance"]["files"].items():
        assert hashlib.sha256((REPO / path).read_bytes()).hexdigest() == expected, path
    sample_paths = [
        root / sample["path"] for group in report["groups"] for sample in group["samples"]
    ]
    for path in sample_paths:
        replay_sample(path)
        payload = json.loads(gzip.decompress(path.read_bytes()))
        for row in payload["result"]["telemetry"]:
            if row.get("team") != "party" or row.get("bonus_action_plan") != "off_hand_attack":
                continue
            catalog = {a.name: a for a in party[row["actor_id"]].actions}
            assert catalog[row["action_plan"]].weapon_id != catalog["off_hand_attack"].weapon_id
    assert set(sample_paths) == set((root / "samples").glob("*.json.gz")), "Unlisted stale samples"
    audit = dict(
        status="passed",
        trials=len(rows),
        groups=len(grouped),
        replayed_samples=len(sample_paths),
        source_files_verified=len(report["provenance"]["files"]),
        censored_trials=sum(row["censored"] for row in rows),
        checks=[
            "fixed sample sizes and trial identity",
            "outcome counts recomputed from all rows",
            "HP and resource bounds",
            "source file fingerprints",
            "exact full sample replay",
            "distinct main/off-hand weapons in saved turns",
            "no unlisted stale samples",
        ],
        validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    (root / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
