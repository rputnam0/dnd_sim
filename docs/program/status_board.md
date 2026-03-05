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

## Active completion track rollup (from backlog.csv)

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | in_progress | 5A-doc-control | `DOC-01`, `DOC-02`, and `DOC-04` are active on `feat/doc-01-establish-canonical-docs-entrypoints-and-source-of`, `codex/feat/doc-02-archive-stale-planning-and-historical-run-artifact`, and `feat/doc-04-add-doc-freshness-metadata-and-registry`. |
| ARC | Runtime Decomposition | not_started | 5B-runtime-decomposition | Start from the first unmerged dependency in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | Start from the first unmerged dependency in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | Start from the first unmerged dependency in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | Start from the first unmerged dependency in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | Start from the first unmerged dependency in `backlog.csv`. |
| FIX | Rules Closure | not_started | 5G-rules-closure | Start from the first unmerged dependency in `backlog.csv`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | Start from the first unmerged dependency in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | Start from the first unmerged dependency in `backlog.csv`. |

## Active task branches (non-merged task statuses)

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| DOC-01 | feat/doc-01-establish-canonical-docs-entrypoints-and-source-of | doc_control_lead | in_progress | Matches `docs/program/backlog.csv`. |
| DOC-02 | codex/feat/doc-02-archive-stale-planning-and-historical-run-artifact | doc_control_a | pr_open | Archive backfill and canonical-link cleanup in PR #90. |
| DOC-04 | feat/doc-04-add-doc-freshness-metadata-and-registry | doc_control_a | pr_open | Metadata freshness headers and governance ownership registry submitted for integration review. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| DOC-02 | [#90](https://github.com/rputnam0/dnd_sim/pull/90) | doc_control_a | pending review | Targets `int/5a-doc-control`. |
| DOC-04 | [#89](https://github.com/rputnam0/dnd_sim/pull/89) | doc_control_a | pending | Targets `int/5a-doc-control`. |

## Dependency notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
