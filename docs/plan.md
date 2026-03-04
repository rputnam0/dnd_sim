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

## Wave 4 Milestones (Execution Tracking)

- [x] Subwave 4A complete (`CHR-04`, `CHR-08`, `CHR-09`, `CHR-12`) - merged via PRs `#62`, `#64`, `#65`, `#63` on 2026-03-03.
- [x] Subwave 4B complete (`CHR-05`, `CHR-06`, `CHR-11`, `CHR-14`) - merged via PRs `#67`, `#68`, `#66`, `#69` on 2026-03-03.
- [x] Subwave 4C complete (`CHR-07`, `CHR-10`, `CHR-13`, `CHR-15`) - merged via PRs `#72`, `#73`, `#71`, `#70` on 2026-03-03.
- [x] Subwave 4D complete (`CHR-16`, All 2014 Sources scope) - merged via PR `#74` on 2026-03-03.
- [x] Subwave 4E complete (`SPL-02`, `SPL-05`) - merged via PRs `#75`, `#76` on 2026-03-04.
- [x] Subwave 4F complete (`SPL-03`, `SPL-04`) - merged via PRs `#78`, `#77` on 2026-03-04.
- [x] Integration gate complete on `int/wave-4-integration` (full suite + tracker sync) - passed on `c7e3777` on 2026-03-04.
- [ ] Final consolidation PR merged (`int/wave-4-integration` -> `main`).
