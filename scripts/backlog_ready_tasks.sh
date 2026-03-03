#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backlog="${1:-"${repo_root}/docs/program/backlog.csv"}"
wave="${2:-1}"

if [ ! -f "${backlog}" ]; then
  echo "missing backlog: ${backlog}" >&2
  exit 1
fi

# Emits task IDs in the requested wave that are not started and whose dependencies are merged.
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
  wave_col=get_col("wave", "", "", "", "")
  status_col=get_col("status", "task_status", "state", "", "")
  deps_col=get_col("depends_on", "deps", "dependencies", "dependency_ids", "")

  if (task_col == 0 || wave_col == 0 || status_col == 0) {
    print "backlog_ready_tasks.sh: required backlog columns missing (need task/id, wave, status)" > "/dev/stderr"
    exit 2
  }

  normalized_target_wave=normalize_wave(target_wave)
  next
}
{
  task=value_at(task_col)
  wave=normalize_wave(value_at(wave_col))
  deps=value_at(deps_col)
  status=normalize_status(value_at(status_col))

  if (task == "") next

  task_status[task]=status
  task_wave[task]=wave
  task_deps[task]=deps
}
END {
  for (task in task_wave) {
    if (task_wave[task] != normalized_target_wave) continue
    if (task_status[task] != "not_started") continue

    ready=1
    deps=task_deps[task]
    if (deps_col != 0 && deps != "") {
      n=split(deps, arr, /[;|]/)
      for (i=1; i<=n; i++) {
        dep=trim(arr[i])
        if (dep == "") continue
        if (task_status[dep] != "merged") {
          ready=0
          break
        }
      }
    }

    if (ready) print task
  }
}
' "${backlog}" | sort
