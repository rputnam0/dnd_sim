# Repo Cleanup Inventory 20260304

Generated: 2026-03-04T02:12:55Z (UTC)
Branch: codex/repo-cleanup-20260304
Base: origin/main

## Snapshot Summary
- Local branches: 102
- Worktrees: 83
- Worktree entries flagged prunable: 24
- Remote heads under origin: 68
- Local branches not merged into origin/main: 2
- Open PR head branches: 0

## Artifacts
- Branch inventory: docs/cleanup/repo_cleanup_branches_20260304.tsv
- Worktree inventory: docs/cleanup/repo_cleanup_worktrees_20260304.tsv
- Remote head inventory: docs/cleanup/repo_cleanup_remote_heads_20260304.tsv
- Archive tag mapping: docs/cleanup/repo_cleanup_archive_tags_20260304.tsv
- Open PR heads list: /tmp/repo_cleanup_open_pr_heads_20260304.txt
- Safety bundle: artifacts/repo_cleanup_20260304.bundle (7.7M)

## Non-Merged Local Branches Archived
- chore/purge-homebaked-agent-orchestration -> archive/repo-cleanup-20260304/chore__purge-homebaked-agent-orchestration (6e71c8aa60aabb9b3cb6dff190eac29aa4ca1020)
- rescue/wild-shape-salvage-20260303 -> archive/repo-cleanup-20260304/rescue__wild-shape-salvage-20260303 (e942bdd4c3038aab85ac895c6e46e33ca7902cb9)

## Delete Policy Inputs Captured
- Protected branch allowlist: main, codex/repo-cleanup-20260304
- Protected worktree allowlist: active cleanup worktree + worktrees attached to allowlisted branches
- Remote deletion exclude set: origin/main + open PR heads from /tmp/repo_cleanup_open_pr_heads_20260304.txt
