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

derive_branch_name() {
  local task_id="${1}"
  local normalized

  normalized="$(printf '%s' "${task_id}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9._-' '-')"
  normalized="${normalized#-}"
  normalized="${normalized%-}"
  if [ -z "${normalized}" ]; then
    normalized="task"
  fi

  printf "auto/%s" "${normalized}"
}

mkdir -p "${worktree_root}" "${log_root}"

pid_file="${log_root}/pids.tsv"
printf "task_id\tpid\tbranch\tworktree\tlog\tfinal\tlaunch_state\n" > "${pid_file}"

# Launch only not_started tasks with dependencies merged.
while IFS=$'\t' read -r task_id title branch files_hint; do
  [ -z "${task_id}" ] && continue

  if [ -z "${branch}" ]; then
    branch="$(derive_branch_name "${task_id}")"
  fi

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
  function trim(s) {
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
    return s
  }
  function canonical_header(s, lowered) {
    lowered=tolower(trim(s))
    gsub(/[^a-z0-9]+/, "_", lowered)
    gsub(/^_+|_+$/, "", lowered)
    return lowered
  }
  function normalize_status(s, lowered) {
    lowered=tolower(trim(s))
    gsub(/[ -]+/, "_", lowered)
    return lowered
  }
  function normalize_wave(s, lowered) {
    lowered=tolower(trim(s))
    if (lowered ~ /^wave[ _-]*[0-9]+$/) {
      sub(/^wave[ _-]*/, "", lowered)
      return "wave" lowered
    }
    if (lowered ~ /^[0-9]+$/) {
      return "wave" lowered
    }
    return lowered
  }
  function get_col(a, b, c, d, e) {
    if (a != "" && a in header_col) return header_col[a]
    if (b != "" && b in header_col) return header_col[b]
    if (c != "" && c in header_col) return header_col[c]
    if (d != "" && d in header_col) return header_col[d]
    if (e != "" && e in header_col) return header_col[e]
    return 0
  }
  function value_at(idx, val) {
    if (idx <= 0 || idx > NF) return ""
    val=trim($idx)
    sub(/^"/, "", val)
    sub(/"$/, "", val)
    return val
  }
  NR==1 {
    for (i=1; i<=NF; i++) {
      header_col[canonical_header($i)]=i
    }

    task_col=get_col("task_id", "id", "task", "", "")
    title_col=get_col("title", "work_item", "task_name", "", "")
    wave_col=get_col("wave", "", "", "", "")
    deps_col=get_col("depends_on", "deps", "dependencies", "dependency_ids", "")
    branch_col=get_col("branch", "branch_name", "git_branch", "worktree_branch", "")
    files_col=get_col("files", "files_hint", "likely_files", "paths", "")
    status_col=get_col("status", "task_status", "state", "", "")

    if (task_col == 0 || wave_col == 0 || status_col == 0) {
      print "launch_wave_agents.sh: required backlog columns missing (need task/id, wave, status)" > "/dev/stderr"
      exit 2
    }

    normalized_target_wave=normalize_wave(target_wave)
    next
  }
  {
    task=value_at(task_col)
    title=value_at(title_col)
    task_wave=normalize_wave(value_at(wave_col))
    deps=value_at(deps_col)
    branch=value_at(branch_col)
    files=value_at(files_col)
    status=normalize_status(value_at(status_col))

    if (task == "") next
    if (title == "") title=task

    st[task]=status
    w[task]=task_wave
    d[task]=deps
    t[task]=title
    b[task]=branch
    f[task]=files
  }
  END {
    for (task in w) {
      if (w[task] != normalized_target_wave) continue
      if (st[task] != "not_started") continue

      ready=1
      deps=d[task]
      if (deps_col != 0 && deps != "") {
        n=split(deps, arr, /[;|]/)
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
