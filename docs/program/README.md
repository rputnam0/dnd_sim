# Program Artifacts

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

This directory is the only canonical planning surface for the DnD Sim completion program.

## Objective

Complete the D&D 5e 2014 simulator as an agent-maintainable VTT backbone. The program now covers documentation control, runtime decomposition, capability reporting, replayable observability, persistence hardening, tactical AI, rules closure, world systems, and final completion gates.

## Start order

1. `docs/program/doc_governance.md`
2. `docs/program/roadmap_2014_backend.md`
3. `docs/program/backlog.csv`
4. `docs/program/agent_assignment.csv`
5. `docs/program/status_board.md`
6. `docs/program/agent_execution_runbook.md`

## Canonical live files

- `README.md`
- `doc_governance.md`
- `roadmap_2014_backend.md`
- `backlog.csv`
- `agent_assignment.csv`
- `dependency_graph.mmd`
- `agent_execution_runbook.md`
- `merge_and_review_runbook.md`
- `test_acceptance_matrix.md`
- `risk_register.md`
- `labels_and_milestones.md`
- `status_board.md`
- `completion_task_cards.md`
- `capability_report.md` once `CAP-06` lands

## Non-canonical content policy

- Historical wave run reports belong in `docs/archive/`.
- Cleanup and deprecation snapshots are historical records, not live planning state.
- No new planning file becomes canonical until this README links to it and `docs/program/doc_governance.md` registers it.

## Multi-agent policy

- Use the native Codex multi-agent framework only.
- One branch per task ID.
- One PR per task ID.
- Update docs and task status in the same PR as the code change.
