# DnD Engine Program Index (5e 2014 Backend)

This file is now the entrypoint for the full multiagent implementation program.

## Primary Planning Docs

- `docs/program/roadmap_2014_backend.md` - canonical backlog, dependencies, waves, and DoD.
- `docs/program/agent_execution_runbook.md` - Codex multiagent orchestration runbook.
- `docs/program/merge_and_review_runbook.md` - integration, review, and merge protocol.
- `docs/program/test_acceptance_matrix.md` - required unit/integration/negative test coverage.
- `docs/program/risk_register.md` - conflict and integration risk tracking.
- `docs/program/status_board.md` - live status dashboard for tasks, branches, PRs, and gates.

## Machine-Importable Artifacts

- `docs/program/backlog.csv` - task registry (ID/title/wave/deps/branch/test gates).
- `docs/program/agent_assignment.csv` - task-to-agent ownership map.
- `docs/program/dependency_graph.mmd` - Mermaid dependency graph.

## GitHub Workflow Artifacts

- `.github/ISSUE_TEMPLATE/backend_task.yml`
- `.github/ISSUE_TEMPLATE/wave_gate.yml`
- `.github/pull_request_template.md`
- `docs/program/labels_and_milestones.md`

## Working Rules

- One PR per task ID.
- Run wave gates in dependency order.
- Keep deterministic seeded behavior stable unless task explicitly changes rules behavior.
- Do not mark a task complete until tests pass and a PR is open.
