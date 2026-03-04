# Codex Multi-Agent Execution Runbook

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

## Objective

Execute the completion program with native Codex multi-agent tooling while keeping merges deterministic, reviewable, and aligned to the live docs.

## Agent roles

- `worker` implements one task ID on one branch.
- `explorer` reviews one completed task branch for correctness, risk, and missing coverage.
- `awaiter` runs the full wave checks, deterministic corpora, and migration sweeps.
- `doc-warden` verifies that touched live docs changed with the code and that `status_board.md` matches `backlog.csv`.

## Branch rules

- One branch per task ID: `feat/<task-id>-<slug>`.
- One task ID per PR.
- One owner agent per task branch.
- Explorer findings are fixed on the same task branch.
- Doc updates are part of the task branch. Do not split docs into a later follow-up branch.

## Worker prompt contract

Each worker prompt must include:

- task ID and exact title from `backlog.csv`,
- dependencies from `backlog.csv`,
- target modules from `backlog.csv`,
- required tests from `backlog.csv`,
- required docs from `backlog.csv`,
- acceptance text from `backlog.csv`,
- any runtime ownership updates required in `docs/agent_index.yaml`.

## Execution order

1. Run the full Documentation Control track first.
2. Do not start ARC work until `DOC-01`, `DOC-03`, and `DOC-06` are merged.
3. Run Capability Manifest and Observability as soon as their dependencies are ready.
4. Start Persistence and AI only after the required ARC modules are extracted.
5. Start World Systems only after Persistence is ready for campaign/world state.
6. Run Completion Gates last and block release until every `FIN-*` task is green.

## Required checks before a task PR is ready

- direct unit tests pass,
- integration or golden tests pass,
- negative tests pass,
- deterministic seed behavior is unchanged or the change is explicitly documented,
- touched live docs are updated,
- `docs/agent_index.yaml` is updated when boundaries changed,
- no unrelated file churn is present.

## Required checks before a track integration merge

- every task in the ready batch has an open PR,
- explorer review is complete for every task,
- awaiter full-suite run passes,
- deterministic replay/golden checks pass,
- `status_board.md` and `backlog.csv` are synchronized,
- no critical or high findings remain open.

## Failure handling

- If a hotspot task conflicts on `engine.py`, `spatial.py`, `rules_2014.py`, `strategy_api.py`, `strategies/defaults.py`, `db.py`, or `docs/program/*`, rebase that task before any further code changes.
- If deterministic drift appears, block merge and open a replay diff report in the same branch.
- If a task adds a runtime module without updating `docs/agent_index.yaml`, the task is not ready.
- If a task changes live planning docs without updating `status_board.md`, the task is not ready.
