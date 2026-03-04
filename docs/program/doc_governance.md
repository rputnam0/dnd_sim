# Documentation Governance

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

This file defines the live documentation surface and the required file moves that eliminate planning drift.

## Live planning surface

These are the only live planning files after `DOC-01` and `DOC-02` merge:

- `docs/plan.md`
- `docs/agent_feature_assignments.md`
- `docs/review_checklist.md`
- `docs/agent_index.yaml`
- `docs/archive/README.md`
- `docs/program/README.md`
- `docs/program/doc_governance.md`
- `docs/program/roadmap_2014_backend.md`
- `docs/program/backlog.csv`
- `docs/program/agent_assignment.csv`
- `docs/program/dependency_graph.mmd`
- `docs/program/agent_execution_runbook.md`
- `docs/program/merge_and_review_runbook.md`
- `docs/program/test_acceptance_matrix.md`
- `docs/program/risk_register.md`
- `docs/program/labels_and_milestones.md`
- `docs/program/status_board.md`
- `docs/program/completion_task_cards.md`
- `docs/program/capability_report.md` after `CAP-06`

## Required file actions

1. Replace `docs/plan.md` with a redirect-only canonical entrypoint.
2. Replace `docs/program/README.md` so it declares the full canonical live surface.
3. Replace `docs/program/roadmap_2014_backend.md` and rename Wave 5 inside the roadmap to `Backbone Hardening, World Systems, and Completion`.
4. Replace `docs/program/backlog.csv`, `docs/program/agent_assignment.csv`, `docs/program/dependency_graph.mmd`, `docs/program/status_board.md`, `docs/program/test_acceptance_matrix.md`, `docs/program/risk_register.md`, and `docs/program/labels_and_milestones.md`.
5. Replace `docs/agent_feature_assignments.md` with a redirect-only root entrypoint that points only to `docs/program/README.md`.
6. Convert `docs/review_checklist.md` into the active closeout checklist for this program.
7. Create `docs/archive/README.md`.
8. Move `docs/program/wave3_gap_report.md`, `docs/program/wave3_run_20260303_085619.md`, and `docs/program/wave4_run_20260303_110536.md` to `docs/archive/program_runs/`.
9. Leave `docs/cleanup/*` and `docs/deprecation/*` in historical scope only. Do not link them from the canonical entrypoint except from archive references.
10. Add metadata headers to every live planning doc with `Status`, `Owner`, `Last updated`, and `Canonical source`.

## Metadata format

Every live planning document starts with:

- `Status: canonical` or `Status: historical`
- `Owner: <team-or-agent-pool>`
- `Last updated: YYYY-MM-DD`
- `Canonical source: <path>`

## Update rules

- Any PR that changes program state must update the touched live docs in the same branch.
- `docs/program/backlog.csv` is the task-level source of truth.
- `docs/program/status_board.md` is the human-readable dashboard and must summarize the same state as `backlog.csv`.
- `docs/program/README.md` must link every live planning file and no historical-only file.
- `docs/agent_index.yaml` must be updated in every PR that adds, renames, or transfers a runtime module boundary.

## CI rules

`DOC-05` adds a doc consistency checker that fails when:

- a live planning file is missing metadata,
- `status_board.md` and `backlog.csv` disagree,
- a historical file is linked from a canonical entrypoint without an explicit historical label,
- a canonical file is not registered in this document,
- an internal doc link is broken.
