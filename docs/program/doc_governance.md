# Documentation Governance

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/README.md`

This file defines the live planning surface, ownership, and freshness rules.

## Live planning registry and ownership

The table below is the canonical registry for every live planning file.

| Path | Status | Owner | Metadata header | Notes |
|---|---|---|---|---|
| `docs/plan.md` | canonical | program-control | required | Redirect-only root entrypoint. |
| `docs/agent_feature_assignments.md` | canonical | program-control | required | Redirect-only root entrypoint. |
| `docs/review_checklist.md` | canonical | integration-review | required | Program closeout checklist. |
| `docs/agent_index.yaml` | canonical | program-control | not_applicable | Runtime module ownership and invariants. |
| `docs/archive/README.md` | canonical | program-control | required | Archive policy index for historical records. |
| `docs/program/README.md` | canonical | program-control | required | Single planning entrypoint. |
| `docs/program/doc_governance.md` | canonical | program-control | required | Live planning governance contract. |
| `docs/program/roadmap_2014_backend.md` | canonical | program-control | required | Program roadmap and sequencing detail. |
| `docs/program/backlog.csv` | canonical | program-control | not_applicable | Task-level source of truth. |
| `docs/program/agent_assignment.csv` | canonical | program-control | not_applicable | Machine-readable owner assignment map. |
| `docs/program/dependency_graph.mmd` | canonical | program-control | not_applicable | Task dependency graph source. |
| `docs/program/agent_execution_runbook.md` | canonical | program-control | required | Multi-agent execution rules. |
| `docs/program/merge_and_review_runbook.md` | canonical | integration-review | required | Merge and review sequencing rules. |
| `docs/program/test_acceptance_matrix.md` | canonical | qa-gate | required | Required test coverage matrix by track. |
| `docs/program/risk_register.md` | canonical | integration-review | required | Program risk tracking. |
| `docs/program/labels_and_milestones.md` | canonical | program-control | required | Labeling and milestone mapping. |
| `docs/program/status_board.md` | canonical | program-control | required | Human-readable status dashboard. |
| `docs/program/completion_task_cards.md` | canonical | program-control | required | Human-readable task expansion of backlog. |
| `docs/program/capability_report.md` | canonical after CAP-06 | content-manifest | required | Capability report output surface. |

## Metadata format

Every live planning markdown document with `Metadata header: required` starts with:

- `Status: canonical` or `Status: historical`
- `Owner: <team-or-agent-pool>`
- `Last updated: YYYY-MM-DD`
- `Canonical source: <path>`

Structured planning files (`.csv`, `.yaml`, `.mmd`) remain source-specific and therefore use
`Metadata header: not_applicable`; their owner and status are still tracked in the registry above.

## Update rules

- Any PR that changes program state must update the touched live docs in the same branch.
- `docs/program/backlog.csv` is the task-level source of truth.
- `docs/program/status_board.md` is the human-readable dashboard and must summarize the same state as `backlog.csv`.
- `docs/program/README.md` must link every live planning file and no historical-only file.
- `docs/agent_index.yaml` must be updated in every PR that adds, renames, or transfers a runtime module boundary.

## CI rules

`DOC-05` adds `scripts/docs/verify_program_docs.py` plus
`.github/workflows/docs-consistency.yml`.
The checker fails when:

- a live planning markdown file with `Metadata header: required` is missing metadata,
- `status_board.md` and `backlog.csv` disagree,
- a canonical entrypoint links directly to archived files other than `docs/archive/README.md`,
- a canonical file is not registered in this document,
- an internal doc link is broken.

Local dry-run commands:

- `uv sync --frozen --extra dev`
- `uv run python scripts/docs/verify_program_docs.py`
- `uv run python -m pytest tests/test_verify_program_docs.py tests/test_program_doc_governance.py`
