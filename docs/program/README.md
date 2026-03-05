# Program Artifacts

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/README.md`

This file is the single canonical planning entrypoint for the DnD Sim completion program.

## Start here

1. Use this file as the only planning entrypoint.
2. Use `docs/program/backlog.csv` as the task-level source of truth.
3. Use `docs/program/status_board.md` as the human-readable dashboard.
4. Follow `docs/program/doc_governance.md` for canonical vs historical doc rules.

## Root planning entrypoints

- `docs/plan.md` is canonical and redirect-only.
- `docs/agent_feature_assignments.md` is canonical and redirect-only.
- Both root planning entrypoints must point only to `docs/program/README.md`.

## Planning document registry

| Path | Status | Role |
|---|---|---|
| `docs/plan.md` | canonical | Redirect-only root entrypoint to this README. |
| `docs/agent_feature_assignments.md` | canonical | Redirect-only root entrypoint to this README. |
| `docs/review_checklist.md` | canonical | Program closeout checklist. |
| `docs/agent_index.yaml` | canonical | Runtime module ownership and invariants. |
| `docs/archive/README.md` | canonical | Archive policy index for historical records. |
| `docs/program/README.md` | canonical | Single planning entrypoint. |
| `docs/program/doc_governance.md` | canonical | Live planning surface and governance rules. |
| `docs/program/roadmap_2014_backend.md` | canonical | Program roadmap and sequencing detail. |
| `docs/program/backlog.csv` | canonical | Task-level source of truth. |
| `docs/program/agent_assignment.csv` | canonical | Machine-readable owner assignment map. |
| `docs/program/dependency_graph.mmd` | canonical | Task dependency graph source. |
| `docs/program/agent_execution_runbook.md` | canonical | Multi-agent execution rules. |
| `docs/program/merge_and_review_runbook.md` | canonical | Merge and review sequencing rules. |
| `docs/program/test_acceptance_matrix.md` | canonical | Required test coverage matrix by track. |
| `docs/program/risk_register.md` | canonical | Program risk tracking. |
| `docs/program/labels_and_milestones.md` | canonical | Labeling and milestone mapping. |
| `docs/program/status_board.md` | canonical | Human-readable status dashboard. |
| `docs/program/completion_task_cards.md` | canonical | Human-readable task expansion of backlog. |
| `docs/program/capability_report.md` | canonical after CAP-06 | Capability report output surface. |

## Capability Coverage Reports

- Markdown report: [`docs/program/capability_report.md`](capability_report.md)
- Machine-readable JSON: [`artifacts/capabilities/coverage_report.json`](../../artifacts/capabilities/coverage_report.json)
- Regenerate both outputs with:
  `uv run python scripts/content/render_capability_report.py --last-updated YYYY-MM-DD`

Ownership and metadata-header requirements for this same live planning surface are defined in
`docs/program/doc_governance.md`.

## Historical planning scope

- Any planning file under the archive subtree other than `docs/archive/README.md` is historical and must carry `Status: historical`.
- Cleanup and deprecation snapshots are historical and must carry `Status: historical`.
- Historical files are reference-only and must not be used as planning entrypoints.
- Use `docs/archive/README.md` as the only canonical index for historical artifacts in the program-runs, cleanup, and deprecation archive folders.

## Doc sync gate and stale-live purge

- `FIN-01` enforces the completion precondition that live planning docs stay synchronized between `docs/program/backlog.csv` and `docs/program/status_board.md`.
- Run `uv run python scripts/docs/verify_program_docs.py` before opening completion-gate PRs.
- Keep live planning artifacts under the canonical registry in this README and `docs/program/doc_governance.md`.
- Archive historical planning outputs under the archive subtree and reference them only through `docs/archive/README.md`.

## Multi-agent policy

- Use the native Codex multi-agent framework only.
- One branch per task ID.
- One PR per task ID.
- Update docs and task status in the same PR as the code change.
