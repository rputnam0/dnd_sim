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
function trim(s) { gsub(/^ +| +$/, "", s); return s }
NR==1 { next }
{
  task=$1
  wave=$3
  deps=$7
  status=$17
  task_status[task]=status
  task_wave[task]=wave
  task_deps[task]=deps
}
END {
  for (task in task_wave) {
    if (task_wave[task] != target_wave) continue
    if (task_status[task] != "not_started") continue

    ready=1
    deps=task_deps[task]
    if (deps != "") {
      n=split(deps, arr, ";")
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
