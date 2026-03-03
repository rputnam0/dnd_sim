#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backlog="${1:-"${repo_root}/docs/program/backlog.csv"}"
wave="${2:-1}"
worktree_root="${3:-"${repo_root}/../dnd_sim_agents"}"
run_id="${4:-"$(date +%Y%m%d_%H%M%S)"}"
start_delay="${5:-1}"
log_root="${worktree_root}/_agent_logs/${run_id}"

if [ ! -f "${backlog}" ]; then
  echo "missing backlog: ${backlog}" >&2
  exit 1
fi

mkdir -p "${worktree_root}" "${log_root}"

pid_file="${log_root}/pids.tsv"
printf "task_id\tpid\tbranch\tworktree\tlog\tfinal\tlaunch_state\n" > "${pid_file}"

# Launch only not_started tasks with dependencies merged.
while IFS=$'\t' read -r task_id title branch files_hint; do
  [ -z "${task_id}" ] && continue

  worktree_path="${worktree_root}/${branch//\//__}"
  log_path="${log_root}/${task_id}.log"
  final_path="${log_root}/${task_id}.final.txt"

  if [ ! -d "${worktree_path}" ]; then
    git -C "${repo_root}" worktree add "${worktree_path}" "${branch}" 2>/dev/null || \
      git -C "${repo_root}" worktree add -b "${branch}" "${worktree_path}" origin/main
  fi

  prompt="You are implementing ${task_id}: ${title}.

Hard requirements:
- Work only within this task scope.
- Follow TDD: failing test first, then minimal fix, then refactor.
- Add at least one unit test, one integration/golden test, and one negative test.
- Preserve deterministic seeded behavior unless this task intentionally changes rules behavior.
- Run targeted tests then full suite.
- Run black on changed files.
- Commit logically scoped changes when ready.

Likely files:
${files_hint}

At end provide:
1) summary of changes
2) tests run + results
3) blockers or follow-ups"

  nohup codex exec \
    --full-auto \
    -C "${worktree_path}" \
    --output-last-message "${final_path}" \
    "${prompt}" > "${log_path}" 2>&1 &
  pid=$!

  sleep "${start_delay}"
  launch_state="running"
  if ! kill -0 "${pid}" 2>/dev/null; then
    launch_state="early_exit"
  fi

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${task_id}" "${pid}" "${branch}" "${worktree_path}" "${log_path}" "${final_path}" "${launch_state}" >> "${pid_file}"
done < <(
  awk -F',' -v target_wave="${wave}" '
  function trim(s) { gsub(/^ +| +$/, "", s); return s }
  NR==1 { next }
  {
    task=$1
    title=$2
    task_wave=$3
    deps=$7
    branch=$8
    files=$10
    status=$17

    st[task]=status
    w[task]=task_wave
    d[task]=deps
    t[task]=title
    b[task]=branch
    f[task]=files
  }
  END {
    for (task in w) {
      if (w[task] != target_wave) continue
      if (st[task] != "not_started") continue

      ready=1
      deps=d[task]
      if (deps != "") {
        n=split(deps, arr, ";")
        for (i=1; i<=n; i++) {
          dep=trim(arr[i])
          if (dep == "") continue
          if (st[dep] != "merged") {
            ready=0
            break
          }
        }
      }

      if (ready) {
        printf "%s\t%s\t%s\t%s\n", task, t[task], b[task], f[task]
      }
    }
  }
  ' "${backlog}" | sort
)

echo "run_id=${run_id}"
echo "log_root=${log_root}"
echo "pid_file=${pid_file}"
