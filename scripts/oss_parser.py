from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from openai import OpenAI

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency at runtime only

    def load_dotenv() -> bool:
        return False


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_THREAD_LOCAL = threading.local()
_VALID_KINDS = {
    "spells",
    "feats",
    "class_features",
    "subclass_features",
    "race_traits",
    "background_features",
}

_SPELL_SYSTEM_PROMPT = """You are an expert D&D 5e mechanics parser for a Python combat simulator.
Convert the provided raw 5etools JSON for a spell into exactly one JSON object using this schema:
{
  "name": "Exact spell name",
  "type": "spell",
  "level": 0,
  "school": "Abjuration",
  "casting_time": "action",
  "range_ft": 60,
  "concentration": false,
  "duration_rounds": 10,
  "description": "plain text description",
  "save_ability": "dex",
  "damage_type": "fire",
  "mechanics": []
}
Rules:
- Keep unknown fields out; only return valid JSON object.
- If unknown, use null or sensible defaults.
- Never wrap with markdown fences.
"""

_TRAIT_SYSTEM_PROMPT = """You are an expert D&D 5e mechanics parser for a Python combat simulator.
Convert the provided raw 5etools JSON for a trait-like feature into exactly one JSON object:
{
  "name": "Exact feature name",
  "type": "feat",
  "description": "plain text feature description",
  "mechanics": []
}
Rules:
- type must be one of: feat, class_feature, subclass_feature, racial_trait, background_feature.
- mechanics should contain machine-usable effect objects when possible.
- If no programmatic mechanic can be inferred, return an empty mechanics list.
- Never wrap with markdown fences.
"""


class ParseJob(NamedTuple):
    kind: str
    name: str
    source_file: str
    source_id: str
    payload: dict[str, Any]
    out_path: Path


def sanitize_name(name: str) -> str:
    value = str(name).lower()
    value = _NON_ALNUM_RE.sub("_", value)
    return value.strip("_")


def _traits_out_dir(root: Path) -> Path:
    return root / "db" / "rules" / "2014" / "traits"


def _spells_out_dir(root: Path) -> Path:
    return root / "db" / "rules" / "2014" / "spells"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_spell_jobs(root: Path) -> Iterable[ParseJob]:
    raw_dir = root / "db" / "raw" / "5etools" / "spells"
    out_dir = _spells_out_dir(root)
    for raw_file in sorted(raw_dir.glob("*.json")):
        data = _load_json(raw_file)
        for row in data.get("spell", []):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            stem = sanitize_name(name)
            yield ParseJob(
                kind="spells",
                name=name,
                source_file=str(raw_file),
                source_id=f"{name}|{row.get('source', '')}",
                payload=row,
                out_path=out_dir / f"{stem}.json",
            )


def _iter_feat_jobs(root: Path) -> Iterable[ParseJob]:
    raw_file = root / "db" / "raw" / "5etools" / "feats.json"
    out_dir = _traits_out_dir(root)
    if not raw_file.exists():
        return
    data = _load_json(raw_file)
    for row in data.get("feat", []):
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        stem = sanitize_name(name)
        yield ParseJob(
            kind="feats",
            name=name,
            source_file=str(raw_file),
            source_id=f"{name}|{row.get('source', '')}",
            payload=row,
            out_path=out_dir / f"{stem}.json",
        )


def _iter_class_feature_jobs(root: Path, *, subclass: bool) -> Iterable[ParseJob]:
    raw_dir = root / "db" / "raw" / "5etools" / "classes"
    out_dir = _traits_out_dir(root)
    key = "subclassFeature" if subclass else "classFeature"
    kind = "subclass_features" if subclass else "class_features"
    for raw_file in sorted(raw_dir.glob("class-*.json")):
        data = _load_json(raw_file)
        for row in data.get(key, []):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            stem = sanitize_name(name)
            yield ParseJob(
                kind=kind,
                name=name,
                source_file=str(raw_file),
                source_id=f"{name}|{row.get('source', '')}|{row.get('className', '')}|{row.get('subclassShortName', '')}|{row.get('level', '')}",
                payload=row,
                out_path=out_dir / f"{stem}.json",
            )


def _iter_race_trait_jobs(root: Path) -> Iterable[ParseJob]:
    raw_file = root / "db" / "raw" / "5etools" / "races" / "races.json"
    out_dir = _traits_out_dir(root)
    if not raw_file.exists():
        return
    data = _load_json(raw_file)
    for race in data.get("race", []):
        race_name = str(race.get("name", "")).strip()
        race_source = str(race.get("source", "")).strip()
        for entry in race.get("entries", []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            row = {
                "race_name": race_name,
                "race_source": race_source,
                "entry": entry,
                "name": name,
                "source": race_source,
            }
            stem = sanitize_name(name)
            yield ParseJob(
                kind="race_traits",
                name=name,
                source_file=str(raw_file),
                source_id=f"{name}|{race_name}|{race_source}",
                payload=row,
                out_path=out_dir / f"{stem}.json",
            )


def _iter_background_feature_jobs(root: Path) -> Iterable[ParseJob]:
    raw_file = root / "db" / "raw" / "5etools" / "backgrounds" / "backgrounds.json"
    out_dir = _traits_out_dir(root)
    if not raw_file.exists():
        return
    data = _load_json(raw_file)
    for background in data.get("background", []):
        bg_name = str(background.get("name", "")).strip()
        bg_source = str(background.get("source", "")).strip()
        for entry in background.get("entries", []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            is_feature = bool((entry.get("data") or {}).get("isFeature"))
            if not is_feature and not name.lower().startswith("feature:"):
                continue
            clean_name = name.split(":", 1)[1].strip() if ":" in name else name
            row = {
                "background_name": bg_name,
                "background_source": bg_source,
                "entry": entry,
                "name": clean_name,
                "source": bg_source,
            }
            stem = sanitize_name(clean_name)
            yield ParseJob(
                kind="background_features",
                name=clean_name,
                source_file=str(raw_file),
                source_id=f"{clean_name}|{bg_name}|{bg_source}",
                payload=row,
                out_path=out_dir / f"{stem}.json",
            )


def _resolve_kinds(value: str) -> list[str]:
    raw = [token.strip().lower() for token in value.split(",") if token.strip()]
    if not raw:
        return ["spells"]
    if "all" in raw:
        return sorted(_VALID_KINDS)
    invalid = [token for token in raw if token not in _VALID_KINDS]
    if invalid:
        raise ValueError(f"Unsupported kinds: {', '.join(sorted(invalid))}")
    return raw


def collect_jobs(
    root: Path,
    *,
    kinds: list[str],
    overwrite: bool,
    max_items: int | None,
) -> list[ParseJob]:
    generators: list[Iterable[ParseJob]] = []
    for kind in kinds:
        if kind == "spells":
            generators.append(_iter_spell_jobs(root))
        elif kind == "feats":
            generators.append(_iter_feat_jobs(root))
        elif kind == "class_features":
            generators.append(_iter_class_feature_jobs(root, subclass=False))
        elif kind == "subclass_features":
            generators.append(_iter_class_feature_jobs(root, subclass=True))
        elif kind == "race_traits":
            generators.append(_iter_race_trait_jobs(root))
        elif kind == "background_features":
            generators.append(_iter_background_feature_jobs(root))

    deduped: dict[Path, ParseJob] = {}
    for source in generators:
        for job in source:
            # First producer wins on filename collisions to keep deterministic behavior.
            deduped.setdefault(job.out_path, job)

    jobs = sorted(deduped.values(), key=lambda row: str(row.out_path))
    if not overwrite:
        jobs = [job for job in jobs if not job.out_path.exists()]
    if max_items is not None and max_items > 0:
        jobs = jobs[:max_items]
    return jobs


def _thread_client(api_key: str, base_url: str) -> OpenAI:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = OpenAI(api_key=api_key, base_url=base_url)
        _THREAD_LOCAL.client = client
    return client


def _prompt_for_kind(kind: str) -> str:
    return _SPELL_SYSTEM_PROMPT if kind == "spells" else _TRAIT_SYSTEM_PROMPT


def _type_for_kind(kind: str) -> str:
    if kind == "feats":
        return "feat"
    if kind == "class_features":
        return "class_feature"
    if kind == "subclass_features":
        return "subclass_feature"
    if kind == "race_traits":
        return "racial_trait"
    if kind == "background_features":
        return "background_feature"
    return "feat"


def _normalize_result(kind: str, name: str, result: dict[str, Any]) -> dict[str, Any]:
    if kind == "spells":
        if "name" not in result or not str(result.get("name", "")).strip():
            result["name"] = name
        result.setdefault("type", "spell")
        result.setdefault("mechanics", [])
        return result

    if "name" not in result or not str(result.get("name", "")).strip():
        result["name"] = name
    result["type"] = _type_for_kind(kind)
    result.setdefault("description", "")
    result.setdefault("mechanics", [])
    return result


def _call_llm_for_job(
    *,
    job: ParseJob,
    model: str,
    api_key: str,
    base_url: str,
    retries: int,
    retry_backoff_sec: float,
) -> dict[str, Any]:
    attempt = 0
    payload = {
        "kind": job.kind,
        "source_id": job.source_id,
        "raw": job.payload,
    }
    user_prompt = json.dumps(payload, ensure_ascii=False)
    while True:
        attempt += 1
        try:
            client = _thread_client(api_key, base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _prompt_for_kind(job.kind)},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content
            parsed = json.loads(text)
            return _normalize_result(job.kind, job.name, parsed)
        except Exception:
            if attempt > retries:
                raise
            sleep_time = retry_backoff_sec * (2 ** (attempt - 1))
            time.sleep(sleep_time)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk-parse 5etools raw JSON into canonical rules JSON using OSS LLM."
    )
    parser.add_argument(
        "--kinds",
        default="spells",
        help=(
            "Comma-separated kinds: spells,feats,class_features,subclass_features,"
            "race_traits,background_features or all"
        ),
    )
    parser.add_argument("--model", default="openai/gpt-oss-120b", help="Model id")
    parser.add_argument("--max-concurrency", type=int, default=8, help="Parallel request limit")
    parser.add_argument("--max-items", type=int, default=None, help="Limit number of jobs")
    parser.add_argument("--overwrite", action="store_true", help="Reparse existing output files")
    parser.add_argument("--retries", type=int, default=3, help="Retries per failed request")
    parser.add_argument(
        "--retry-backoff-sec", type=float, default=1.0, help="Base exponential backoff in seconds"
    )
    parser.add_argument("--dry-run", action="store_true", help="List planned jobs and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv()

    root = Path(__file__).resolve().parents[1]
    kinds = _resolve_kinds(args.kinds)
    jobs = collect_jobs(
        root,
        kinds=kinds,
        overwrite=bool(args.overwrite),
        max_items=args.max_items,
    )

    print(f"Kinds: {', '.join(kinds)}")
    print(f"Planned jobs: {len(jobs)}")
    if args.dry_run:
        for job in jobs[:30]:
            print(f"- {job.kind}: {job.name} -> {job.out_path.name}")
        if len(jobs) > 30:
            print(f"... ({len(jobs) - 30} more)")
        return

    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        print("Set DEEPINFRA_API_KEY environment variable to use the parser.")
        return

    failures: list[dict[str, str]] = []
    completed = 0
    started = time.time()

    if not jobs:
        print("No jobs to run.")
        return

    base_url = "https://api.deepinfra.com/v1/openai"
    max_workers = max(1, int(args.max_concurrency))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_job: dict[Future[dict[str, Any]], ParseJob] = {}
        for job in jobs:
            future = executor.submit(
                _call_llm_for_job,
                job=job,
                model=str(args.model),
                api_key=api_key,
                base_url=base_url,
                retries=max(0, int(args.retries)),
                retry_backoff_sec=max(0.1, float(args.retry_backoff_sec)),
            )
            future_to_job[future] = job

        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                payload = future.result()
                _write_json(job.out_path, payload)
                completed += 1
                if completed % 25 == 0 or completed == len(jobs):
                    elapsed = max(0.001, time.time() - started)
                    rate = completed / elapsed
                    print(f"[{completed}/{len(jobs)}] {rate:.2f} items/sec")
            except Exception as exc:  # pragma: no cover - network/runtime behavior
                failures.append(
                    {
                        "kind": job.kind,
                        "name": job.name,
                        "source_file": job.source_file,
                        "source_id": job.source_id,
                        "out_path": str(job.out_path),
                        "error": str(exc),
                    }
                )
                print(f"FAILED: {job.name} ({job.kind}) -> {exc}")

    print("")
    print(f"Completed: {completed}/{len(jobs)}")
    print(f"Failed: {len(failures)}")

    if failures:
        log_dir = root / "db" / "rules" / "2014" / "_parser_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        failure_path = log_dir / f"oss_parser_failures_{stamp}.jsonl"
        with failure_path.open("w", encoding="utf-8") as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Failure log: {failure_path}")


if __name__ == "__main__":
    main()
