# Merge and Review Runbook

## Integration Strategy
- Create one integration branch per wave: `int/wave-<n>-integration` from `origin/main` (or prior wave tag).
- Merge tasks in dependency order, not completion order.
- Resolve conflicts on task branch first, then merge into integration branch.

## Dependency-Ordered Merge Rules
- Do not merge tasks with unresolved dependencies from `backlog.csv`.
- If two tasks touch same hotspot (`engine.py`, rules core, strategy schema), merge lower-level dependency first.
- Rebase outstanding task branches after each hotspot merge.

## PR Review Process
1. Worker opens PR for one task ID.
2. Explorer reviews for:
- rules correctness
- regression risk
- missing tests
- deterministic behavior drift
3. Required findings are fixed on the same branch.
4. PR is approved only when all gates are green.

## Comment and Issue Handling
- Use GitHub API (`gh api`) to fetch PR comments/reviews.
- Address actionable items in code/tests.
- Reply inline with resolution summary and commit reference.

## Wave Gate Checklist
- All task PRs for wave merged into integration branch.
- Full test suite pass on integration branch.
- Determinism/golden checks pass.
- Documentation updates complete.
- Status board updated to `merged` for tasks.

## Main Branch Merge Rules
- Merge one wave PR to `main` at a time.
- After merge:
  - run smoke tests on `main`
  - tag baseline (`wave-<n>-green`)
  - prune merged feature branches

## Backout Policy
- If post-merge regressions occur, revert the minimal offending task merge commit.
- Reopen task issue with failure context and expected fix scope.
