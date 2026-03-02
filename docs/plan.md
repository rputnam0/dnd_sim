# Implementation Checklist

- [x] Scaffold package, CLI entrypoints, and tests
- [x] Character parser and JSON DB writer
- [x] Enemy/scenario schema validation and loading
- [x] Rules engine core (2014-first) and combat execution
- [x] Strategy plugin interface and defaults
- [x] Monte Carlo runner + metrics aggregation
- [x] Markdown reporting and chart generation
- [x] Baseline ley_heart phase 1 encounter conversion
- [x] Full test pass and docs polish

## Phase 5: Monster Data Pipeline

- [x] Expand monster ingestion to extract actions/reactions/legendary/lair kits.
- [x] Define normalized mechanics schema for trait/spell/monster payloads.
- [x] Add validation + coverage tooling for ingested vs executable vs unsupported mechanics.
- [x] Add parser QA fixture coverage for high-complexity entities.
- [x] Backfill legacy monster JSON payload migration path for file and SQLite entries.
