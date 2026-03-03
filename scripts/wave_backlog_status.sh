#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backlog="${1:-"${repo_root}/docs/program/backlog.csv"}"

if [ ! -f "${backlog}" ]; then
  echo "missing backlog: ${backlog}" >&2
  exit 1
fi

# Print per-wave completion summary from backlog status column.
awk -F',' '
NR==1 { next }
{
  wave=$3
  status=$17
  key=wave":"status
  counts[key]++
  total[wave]++
}
END {
  for (w=1; w<=5; w++) {
    printf "wave %d\n", w
    printf "  total: %d\n", total[w]+0
    printf "  not_started: %d\n", counts[w":not_started"]+0
    printf "  in_progress: %d\n", counts[w":in_progress"]+0
    printf "  blocked: %d\n", counts[w":blocked"]+0
    printf "  pr_open: %d\n", counts[w":pr_open"]+0
    printf "  merged: %d\n", counts[w":merged"]+0
  }
}
' "${backlog}"
