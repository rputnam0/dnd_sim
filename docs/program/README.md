# Program Artifacts

This directory contains the execution artifacts for the full D&D 5e 2014 backend backlog.

## Planning Docs
- `roadmap_2014_backend.md`
- `agent_execution_runbook.md`
- `merge_and_review_runbook.md`
- `test_acceptance_matrix.md`
- `risk_register.md`
- `status_board.md`
- `labels_and_milestones.md`

## Machine Artifacts
- `backlog.csv`
- `agent_assignment.csv`
- `dependency_graph.mmd`

## Orchestration Policy
- Use Codex native multi-agent tooling only (`spawn_agent`, `send_input`, `wait`, `close_agent`).
- Do not add or rely on custom local shell orchestration wrappers for wave execution.
- Keep planning and assignment artifacts in this directory as the source of truth for coordination.
