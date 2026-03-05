# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/backlog.csv`

Use this document as the human dashboard.  
Use `docs/program/backlog.csv` as the task-level source of truth for status, dependencies, owners, and branch names.

Legend: `not_started` | `in_progress` | `blocked` | `pr_open` | `merged`

## Merged baseline history

| Baseline scope | Status | Notes |
|---|---|---|
| Waves 1 through 4 | merged/completed | Backfilled as merged baseline history. |
| Repo cleanup program | merged/completed | Backfilled as merged baseline history. |
| Legacy decommission program | merged/completed | Backfilled as merged baseline history. |

## Active completion tracks

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | in_progress | 5A-doc-control | `DOC-01` and `DOC-05` are `in_progress`; `DOC-02`, `DOC-03`, and `DOC-04` are `pr_open`; remaining DOC tasks are `not_started` in `backlog.csv`. |
| ARC | Runtime Decomposition | not_started | 5B-runtime-decomposition | All ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | All CAP tasks are `not_started` in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | All OBS tasks are `not_started` in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | All FIX tasks are `not_started` in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| DOC-01 | feat/doc-01-establish-canonical-docs-entrypoints-and-source-of | doc_control_lead | in_progress | Matches `docs/program/backlog.csv`. |
| DOC-02 | codex/feat/doc-02-archive-stale-planning-and-historical-run-artifact | doc_control_a | pr_open | Matches `docs/program/backlog.csv`. |
| DOC-03 | feat/doc-03-normalize-status-board-and-merged-baseline-history | doc_control_b | pr_open | Matches `docs/program/backlog.csv`. |
| DOC-04 | feat/doc-04-add-doc-freshness-metadata-and-registry | doc_control_a | pr_open | Matches `docs/program/backlog.csv`. |
| DOC-05 | feat/doc-05-add-doc-consistency-checker-and-ci-gate | doc_control_ci | in_progress | Matches `docs/program/backlog.csv`. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| DOC-03 | [#87](https://github.com/rputnam0/dnd_sim/pull/87) | doc_control_b | open | Status-board normalization and baseline history remediation. |
| DOC-02 | [#90](https://github.com/rputnam0/dnd_sim/pull/90) | doc_control_a | merged | Landed in `int/5a-doc-control`. |
| DOC-04 | [#89](https://github.com/rputnam0/dnd_sim/pull/89) | doc_control_a | merged | Landed in `int/5a-doc-control`. |

## Dependency notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
