"""Reproducible shared-engine benchmark; run with python -m dnd_sim.benchmarks.level_five."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
import logging
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from dnd_sim.benchmarks.policies import POLICIES, TacticalPolicy
from dnd_sim.benchmarks.reporting import render_report, render_roll_excerpt, summarize, trial_row
from dnd_sim.benchmarks.trials import derive_trial_seed, run_trial
from dnd_sim.io import load_public_scenario
from dnd_sim.models import TrialResult

logger = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "data/benchmarks/level_five"


def load_party() -> dict[str, dict[str, Any]]:
    """Load only versioned benchmark characters, independent of local SQLite state."""
    index = json.loads((FIXTURES / "characters/index.json").read_text())
    return {
        row["character_id"]: json.loads(
            (FIXTURES / "characters" / f"{row['character_id']}.json").read_text()
        )
        for row in index["characters"]
    }


def _write_compressed(path: Path, payload: str) -> None:
    path.write_bytes(gzip.compress(payload.encode(), mtime=0))


def _provenance() -> dict[str, Any]:
    files = sorted(
        list((REPO / "src/dnd_sim").rglob("*.py"))
        + list(FIXTURES.rglob("*.json"))
        + list((REPO / "db/rules").rglob("*.json"))
        + [REPO / "pyproject.toml", REPO / "uv.lock"]
    )
    fingerprints = {
        str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }
    digest = hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()
    return dict(
        source_sha256=digest,
        files=fingerprints,
        python=platform.python_version(),
        rng="Python random.Random (MT19937); independently seeded per trial",
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        seed_derivation="SHA256 dnd-benchmark-seed-v1; policy excluded; see trials.py",
    )


def verify_mechanics(output: Path) -> dict[str, Any]:
    inventory = json.loads((FIXTURES / "mechanics.json").read_text())
    nodes = sorted({node for item in inventory["mechanics"] for node in item["tests"]})
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", *nodes],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.txt").write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Mechanic verification failed; see {output / 'verification.txt'}")
    return dict(status="passed", test_nodes=nodes)


def validate_trial_scope(result: TrialResult, allowed: dict[str, dict[str, str]]) -> None:
    """Fail closed if a turn uses an action outside the versioned evidence inventory."""
    for row in result.telemetry:
        if row.get("telemetry_type") != "decision":
            continue
        actor = row["actor_id"] if row.get("team") == "party" else "enemy"
        for key in ("action_plan", "bonus_action_plan"):
            name = row.get(key)
            if name and name not in allowed.get(actor, {}):
                raise ValueError(f"Unverified action in benchmark: {actor}: {name}")


def replay_sample(path: Path) -> bool:
    """Re-run a saved sample and compare every result, journal fact, and integer draw."""
    payload = json.loads(gzip.decompress(path.read_bytes()))
    scenario = load_public_scenario(FIXTURES / "scenarios" / f"{payload['scenario']}.json")
    replayed = run_trial(
        scenario,
        load_party(),
        {},
        lambda: {"benchmark": TacticalPolicy(payload["policy"])},
        trial_index=payload["result"]["trial_index"],
        seed=payload["seed"],
        record_rolls=True,
    )
    actual = json.loads(json.dumps(asdict(replayed)))
    expected = {key: payload[key] for key in actual}
    if actual != expected:
        raise AssertionError(f"Saved trial no longer replays exactly: {path}")
    return True


def _run_partition(job: dict[str, Any]) -> dict[str, Any]:
    return run_benchmark(**job)


def _run_parallel(*, paths, policies, trials, master_seed, output, verification, workers):
    """Partition independent groups; merge in design order, never completion order."""
    with TemporaryDirectory(prefix=".partitions-", dir=output) as temporary:
        jobs = [
            dict(
                trials=trials,
                master_seed=master_seed,
                output=Path(temporary) / f"{path.stem}__{policy}",
                scenario_ids=[path.stem],
                policies=[policy],
                verification=verification,
            )
            for path in paths
            for policy in policies
        ]
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as executor:
            parts = list(executor.map(_run_partition, jobs))
        report = dict(parts[0])
        report["groups"] = [group for part in parts for group in part["groups"]]
        trial_text, roll_text = [], []
        (output / "samples").mkdir(exist_ok=True)
        for job, part in zip(jobs, parts):
            if (
                part["provenance"] != report["provenance"]
                or part["rules_profile"] != report["rules_profile"]
            ):
                raise RuntimeError("Source or rules changed during partitioned benchmark")
            directory = job["output"]
            trial_text.append(
                gzip.decompress((directory / "trials.jsonl.gz").read_bytes()).decode()
            )
            excerpt = (directory / "rolls.md").read_text()
            roll_text.append(excerpt if not roll_text else "## " + excerpt.split("\n## ", 1)[1])
            for sample in (directory / "samples").glob("*.json.gz"):
                shutil.copyfile(sample, output / "samples" / sample.name)
        _write_compressed(output / "trials.jsonl.gz", "".join(trial_text))
        (output / "rolls.md").write_text("\n".join(roll_text))
        (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (output / "report.md").write_text(render_report(report))
        return report


def run_benchmark(
    *,
    trials: int,
    master_seed: int,
    output: Path,
    scenario_ids: list[str] | None = None,
    policies: list[str] | None = None,
    verification: dict[str, Any] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    if type(trials) is not int or trials < 1:
        raise ValueError("trials must be a positive fixed sample size")
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    policies = list(POLICIES) if policies is None else policies
    if not policies or any(p not in POLICIES for p in policies):
        raise ValueError("Select at least one known policy")
    paths = sorted((FIXTURES / "scenarios").glob("*.json"))
    if scenario_ids is not None:
        if not scenario_ids or set(scenario_ids) - {p.stem for p in paths}:
            raise ValueError("Select at least one known scenario")
        paths = [p for p in paths if p.stem in scenario_ids]
    output.mkdir(parents=True, exist_ok=True)
    if workers > 1 and len(paths) * len(policies) > 1:
        return _run_parallel(
            paths=paths,
            policies=policies,
            trials=trials,
            master_seed=master_seed,
            output=output,
            verification=verification,
            workers=workers,
        )
    (output / "samples").mkdir(exist_ok=True)
    party = load_party()
    inventory = json.loads((FIXTURES / "mechanics.json").read_text())
    groups, all_rows = [], []
    excerpts = [
        "# Recorded roll excerpts",
        "",
        "These are actual engine rolls from deterministic replay, not illustrative dice. "
        "Full samples include every journal fact and integer draw. Below: first 12 facts per sample.",
        "",
    ]
    for path in paths:
        scenario = load_public_scenario(path)
        for policy in policies:
            rows, samples, sampled_outcomes = [], [], set()
            for index in range(trials):
                seed = derive_trial_seed(master_seed, path.stem, index)
                try:
                    trial = run_trial(
                        scenario,
                        party,
                        {},
                        lambda: {"benchmark": TacticalPolicy(policy)},
                        trial_index=index,
                        seed=seed,
                    )
                    validate_trial_scope(trial.result, inventory["allowed_actions"])
                except Exception as exc:
                    raise RuntimeError(
                        f"Benchmark failed: scenario={path.stem}, policy={policy}, "
                        f"index={index}, seed={seed}; no result counted"
                    ) from exc
                row = trial_row(trial, set(party))
                rows.append(row)
                all_rows.append(dict(scenario=path.stem, policy=policy, **row))
                if trial.result.outcome not in sampled_outcomes:
                    recorded = run_trial(
                        scenario,
                        party,
                        {},
                        lambda: {"benchmark": TacticalPolicy(policy)},
                        trial_index=index,
                        seed=seed,
                        record_rolls=True,
                    )
                    if recorded.result != trial.result:
                        raise AssertionError(
                            f"Recording changed result at {path.stem}/{policy}/{index}"
                        )
                    filename = f"{path.stem}__{policy}__{index}.json.gz"
                    _write_compressed(
                        output / "samples" / filename,
                        json.dumps(
                            dict(scenario=path.stem, policy=policy, **asdict(recorded)),
                            sort_keys=True,
                        ),
                    )
                    samples.append(
                        dict(
                            trial_index=index,
                            seed=seed,
                            outcome=trial.result.outcome,
                            path=f"samples/{filename}",
                            replay_matches=True,
                        )
                    )
                    sampled_outcomes.add(trial.result.outcome)
                    excerpts += [
                        f"## {path.stem} / {policy} / trial {index}",
                        "",
                        f"Seed `{seed}`; **{trial.result.outcome}** after {trial.result.rounds} rounds. "
                        f"{len(recorded.random_draws)} integer draws; {len(recorded.roll_records)} journal facts. "
                        f"[Full sample](samples/{filename})",
                        "",
                    ]
                    excerpts += [
                        "First six declared turns (full decisions are in the sample):",
                        "",
                        "| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |",
                        "|---:|---|---|---|---|---|",
                    ]
                    decisions = [
                        row
                        for row in recorded.result.telemetry
                        if row.get("telemetry_type") == "decision"
                    ]
                    for decision in decisions[:6]:
                        excerpts.append(
                            f"| {decision['round']} | {decision['actor_id']} | "
                            f"{decision.get('movement_path')} | {decision.get('action_plan')} → {decision.get('action_targets')} | "
                            f"{decision.get('bonus_action_plan')} → {decision.get('bonus_action_targets')} | {decision.get('reaction_policy')} |"
                        )
                    excerpts += ["", *render_roll_excerpt(recorded.roll_records[:12]), ""]
            groups.append(
                dict(scenario=path.stem, policy=policy, summary=summarize(rows), samples=samples)
            )
            print(
                f"{path.stem} / {policy}: {trials} trials, win={groups[-1]['summary']['win']['rate']:.3f}",
                flush=True,
            )
    report = dict(
        schema_version=1,
        trials_per_group=trials,
        master_seed=master_seed,
        provenance=_provenance(),
        rules_profile=scenario.rules_profile.model_dump(mode="json"),
        verification=verification or dict(status="not run by API; CLI verifies before simulation"),
        groups=groups,
    )
    _write_compressed(
        output / "trials.jsonl.gz",
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in all_rows),
    )
    (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output / "report.md").write_text(render_report(report))
    (output / "rolls.md").write_text("\n".join(excerpts))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--output", type=Path, default=REPO / "artifacts/benchmarks/level_five")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--policy", action="append", dest="policies", choices=POLICIES)
    parser.add_argument("--replay-sample", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.replay_sample:
        replay_sample(args.replay_sample)
        print(f"Exact replay passed: {args.replay_sample}")
        return
    verification = verify_mechanics(args.output)
    run_benchmark(
        trials=args.trials,
        master_seed=args.seed,
        output=args.output,
        scenario_ids=args.scenarios,
        policies=args.policies,
        verification=verification,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
