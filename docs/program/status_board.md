# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-04  
Canonical source: `docs/program/backlog.csv`

Legend: `not_started` | `in_progress` | `blocked` | `pr_open` | `merged`

## Baseline already merged

- Waves 1 through 4
- Repo cleanup program
- Legacy decommission program

## Active completion tracks

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | in_progress | 5A-doc-control | `DOC-01` and `DOC-02` are active on doc-control branches. |
| ARC | Runtime Decomposition | not_started | 5B-runtime-decomposition | Start from the first unmerged dependency in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | Start from the first unmerged dependency in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | Start from the first unmerged dependency in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | Start from the first unmerged dependency in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | Start from the first unmerged dependency in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | Start from the first unmerged dependency in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | Start from the first unmerged dependency in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | Start from the first unmerged dependency in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| DOC-01 | feat/doc-01-establish-canonical-docs-entrypoints-and-source-of | doc_control_lead | in_progress | Canonical planning entrypoint task in flight. |
| DOC-02 | codex/feat/doc-02-archive-stale-planning-and-historical-run-artifact | doc_control_a | pr_open | Archive backfill and canonical-link cleanup in PR #90. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| DOC-02 | [#90](https://github.com/rputnam0/dnd_sim/pull/90) | doc_control_a | pending review | Targets `int/5a-doc-control`. |

## Current blockers

- `DOC-03`, `DOC-04`, and `DOC-06` remain blocked until `DOC-01` merges.
