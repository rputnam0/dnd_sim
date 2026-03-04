# DnD Sim Program Index

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

This file is the only root-level planning entrypoint.

## Start here

1. Open `docs/program/README.md`.
2. Use `docs/program/backlog.csv` as the task-level source of truth.
3. Use `docs/program/status_board.md` as the human dashboard.
4. Start execution at `DOC-01`.

## Program order

1. Documentation Control
2. Runtime Decomposition
3. Capability Manifest
4. Replay, Logging, and Observability
5. Persistence and Query Model
6. Tactical AI Hardening
7. Rules Closure
8. World Systems and Campaign Platform
9. Completion Gates

## Operating rules

- Do not treat any planning document outside `docs/program/` as canonical unless `docs/program/README.md` links to it as live.
- Do not close a task without updating the touched live docs in the same branch.
- Do not add new planning files outside the canonical set declared in `docs/program/doc_governance.md`.
- Do not mark the backend complete until every `FIN-*` task is merged.
