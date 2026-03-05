# AI Benchmark Corpus

Status: canonical  
Owner: ai_benchmark  
Last updated: 2026-03-05

This folder stores the AI-06 benchmark corpus and tuning thresholds used by `scripts/ai/run_benchmarks.py`.

## Files

- `corpus.json`: benchmark case definitions, strategy thresholds, and required category coverage.

## Coverage Contract

The benchmark corpus includes one deterministic case for each required AI-06 category:

- `hazard_heavy`
- `objective_heavy`
- `summon_heavy`
- `legendary_recharge`

The benchmark gate requires:

- the primary tactical AI (`optimal_expected_damage`) to beat `base_strategy` and `highest_threat` by configured objective-adjusted margins, and
- full rationale coverage for primary tactical decisions.
