# Capability Report

Status: canonical  
Owner: content-manifest  
Last updated: 2026-03-05  
Canonical source: `artifacts/capabilities/`

FIN-02 capability completion gate source of truth:

- manifest file: `artifacts/capabilities/manifest_2014.json`
- verification script: `scripts/content/verify_completion_capabilities.py`
- completion test: `tests/test_completion_capabilities.py`

Gate criteria for shipped 2014 scope:

- every shipped content record in `db/rules/2014/{spells,traits,monsters}` is present in the manifest,
- every record is `cataloged` and `schema_valid`,
- every record is either:
  - `executable` and `tested`, or
  - `blocked` with a single `unsupported_reason` code.
