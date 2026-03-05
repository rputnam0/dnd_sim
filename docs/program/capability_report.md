# Capability Report

Status: canonical  
Owner: content-manifest  
Last updated: 2026-03-05  
Canonical source: `artifacts/capabilities/`

This file is a placeholder until `CAP-06` lands.

Do not populate this report manually. Generate it from the canonical capability manifest pipeline introduced by `CAP-01` through `CAP-06`.

## DBS-03 Query Interfaces

- Python API: `dnd_sim.content_index.query_content_records(...)`
- Coverage summary API: `dnd_sim.content_index.summarize_content_coverage(records)`
- CLI list query:
  `uv run python -m dnd_sim.cli query-content --db-path data/dnd_sim.db --content-type spell --support-state tested`
- CLI coverage summary:
  `uv run python -m dnd_sim.cli content-coverage --db-path data/dnd_sim.db --source-book PHB`
