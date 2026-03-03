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
function get_col(a, b, c, d) {
  if (a != "" && a in header_col) return header_col[a]
  if (b != "" && b in header_col) return header_col[b]
  if (c != "" && c in header_col) return header_col[c]
  if (d != "" && d in header_col) return header_col[d]
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

  wave_col=get_col("wave", "", "", "")
  status_col=get_col("status", "task_status", "state", "")

  if (wave_col == 0 || status_col == 0) {
    print "wave_backlog_status.sh: required backlog columns missing (need wave, status)" > "/dev/stderr"
    exit 2
  }

  next
}
{
  wave=normalize_wave(value_at(wave_col))
  status=normalize_status(value_at(status_col))

  if (wave == "" || status == "") next

  key=wave":"status
  counts[key]++
  total[wave]++
}
END {
  for (w=1; w<=5; w++) {
    wave_key="wave" w
    printf "wave %d\n", w
    printf "  total: %d\n", total[wave_key]+0
    printf "  not_started: %d\n", counts[wave_key":not_started"]+0
    printf "  in_progress: %d\n", counts[wave_key":in_progress"]+0
    printf "  blocked: %d\n", counts[wave_key":blocked"]+0
    printf "  pr_open: %d\n", counts[wave_key":pr_open"]+0
    printf "  merged: %d\n", counts[wave_key":merged"]+0
  }
}
' "${backlog}"
