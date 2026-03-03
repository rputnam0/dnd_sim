# Codex Multiagent Execution Runbook

## Objective
Run implementation with Codex built-in multiagent tooling while keeping deterministic and merge-safe delivery.

## Agent Roles
- `worker`: implements code + tests for assigned tasks.
- `explorer`: performs focused code review and risk audit per completed task.
- `awaiter`: runs long-running checks (full test suites, long simulations, validation sweeps).

## Branch and Ownership Rules
- One branch per task ID: `feat/<task-id>-<slug>`.
- One PR per task ID.
- One owner agent per task (no shared write ownership).
- Agents must ignore unrelated edits and not revert others.

## Per-Task Worker Prompt Contract
Each spawned worker gets:
- Task ID and exact acceptance criteria.
- In-scope files/modules and out-of-scope boundaries.
- Required tests: at least one unit, one integration/golden, one negative.
- Determinism requirement and seed behavior constraint.
- Commit and PR naming template.

## Orchestration Flow (Per Wave)
1. Build ready set from `backlog.csv` where dependencies are complete.
2. Spawn one worker per ready task.
3. Wait for all workers in the batch.
4. For each completed worker task, spawn one explorer for review findings.
5. Address findings on task branch until explorer sign-off.
6. Queue task PRs for integration merge in dependency order.
7. Run awaiter on full wave checks.
8. Merge wave integration PR when all gates pass.

## Required Checks Before Task PR Is Marked Ready
- Targeted tests for touched area pass.
- Added tests for unit/integration/negative coverage pass.
- Deterministic replay/golden checks pass (or intentional delta documented).
- Formatting/lint checks required by repo pass.
- Migration notes included when public API/schema changes.

## Required Checks Before Wave Merge
- All task PRs merged into `int/wave-<n>-integration`.
- `uv run python -m pytest` passes.
- Deterministic corpus check passes.
- No unresolved critical/high explorer findings.
- `docs/program/status_board.md` updated.

## Failure Handling
- If task branch repeatedly fails merge/rebase: pause task, rebase onto latest integration branch, rerun tests.
- If deterministic drift appears: block merge until drift triage is documented and approved.
- If schema changes break import: task cannot merge without migration note and validation test updates.

## Logging and Traceability
Track in `docs/program/status_board.md`:
- Task ID
- Owner agent
- Branch
- PR URL
- Test gate results
- Determinism status
- Merge status
