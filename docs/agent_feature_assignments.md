# Agent Feature Assignments

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/agent_assignment.csv`

This file is a human-readable pointer for the machine-readable assignment map.

## Canonical sources

- Task inventory: `docs/program/backlog.csv`
- Task ownership: `docs/program/agent_assignment.csv`
- Live status: `docs/program/status_board.md`
- Runtime ownership contracts: `docs/agent_index.yaml`

## Agent pools

- `doc_control_*` owns documentation-control and status-sync tasks.
- `runtime_*` owns engine decomposition tasks.
- `content_manifest_*` owns capability-manifest tasks.
- `observability_*` owns trace, replay, and logging tasks.
- `persistence_*` owns schema and campaign/world persistence tasks.
- `ai_*` owns tactical scoring and benchmark tasks.
- `rules_*` owns rules-closure tasks.
- `world_*` owns world-system and campaign-platform tasks.
- `integration_*` owns completion gates and release closure.

Do not create ad hoc ownership outside `docs/program/agent_assignment.csv`.
