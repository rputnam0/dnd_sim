# Merge and Review Runbook

Status: canonical  
Owner: integration-review  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

## Integration strategy

Use one integration branch per track:

- `int/5a-doc-control`
- `int/5b-runtime-decomposition`
- `int/5c-capability-manifest`
- `int/5d-observability`
- `int/5e-persistence`
- `int/5f-ai-hardening`
- `int/5g-rules-closure`
- `int/5h-world-systems`
- `int/5i-completion-gates`

Merge tracks in dependency order.

## Hotspot merge rules

The following hotspots require dependency-ordered merges and rebases after every merge:

- `src/dnd_sim/engine.py`
- `src/dnd_sim/spatial.py`
- `src/dnd_sim/rules_2014.py`
- `src/dnd_sim/strategy_api.py`
- `src/dnd_sim/strategies/defaults.py`
- `src/dnd_sim/db.py`
- `docs/agent_index.yaml`
- `docs/program/backlog.csv`
- `docs/program/status_board.md`

## PR review checklist

Explorer review must confirm all of the following:

- task scope matches `backlog.csv`,
- no unrelated runtime logic moved into the branch,
- new runtime modules have ownership and invariants in `docs/agent_index.yaml`,
- required tests exist and pass,
- deterministic behavior is unchanged or intentionally documented,
- structured telemetry was added for runtime-touching tasks,
- live docs changed with the code,
- no new compatibility shim was introduced without a removal task,
- hotspot file size moved in the correct direction when the task is a decomposition task.

## Wave gate checklist

A track integration branch is mergeable only when:

- all scheduled task branches for the batch are merged into the integration branch,
- full `uv run python -m pytest` passes,
- deterministic replay/golden checks pass,
- doc consistency checks pass,
- status board entries for the merged tasks are updated,
- no critical or high explorer findings remain.

## Main branch merge rules

- Merge one track integration PR to `main` at a time.
- After each merge, run the smoke suite on `main`.
- Update `docs/program/status_board.md` to merged for the completed track.
- Tag the baseline after `FIN-06`.

## Backout policy

- Revert the smallest offending merge commit.
- Reopen the task ID in `backlog.csv` and `status_board.md`.
- Preserve the replay diff and failing trace artifacts for the follow-up fix branch.
