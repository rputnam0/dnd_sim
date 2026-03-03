#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

backlog="${tmp_dir}/backlog.csv"
compact_backlog="${tmp_dir}/compact_backlog.csv"

assert_eq() {
  local expected="${1}"
  local actual="${2}"
  local message="${3}"
  if [ "${actual}" != "${expected}" ]; then
    echo "${message}: expected '${expected}', got '${actual}'" >&2
    exit 1
  fi
}

assert_has_line() {
  local text="${1}"
  local line="${2}"
  local message="${3}"
  if ! printf '%s\n' "${text}" | grep -Fqx "${line}"; then
    echo "${message}: missing line '${line}'" >&2
    exit 1
  fi
}

cat > "${backlog}" <<'CSV'
task_id,title,wave,c4,c5,c6,deps,branch,c9,files,c11,c12,c13,c14,c15,status_old,status
DEP-1,Dependency one,1,,,,,feat/dep1,,src/dep1.py,,,,,,not_started,merged
DEP-2,Dependency two,1,,,,,feat/dep2,,src/dep2.py,,,,,,merged,in_progress
TASK-BLOCKED,Blocked task,1,,,,DEP-2,feat/task-blocked,,src/blocked.py,,,,,,not_started,not_started
TASK-READY,Ready task,1,,,,DEP-1,feat/task-ready,,src/ready.py,,,,,,not_started,not_started
CSV

expected_ready=$'TASK-READY'
actual_ready="$("${repo_root}/scripts/backlog_ready_tasks.sh" "${backlog}" wave1)"
assert_eq "${expected_ready}" "${actual_ready}" "legacy backlog_ready_tasks.sh failed"

summary="$("${repo_root}/scripts/wave_backlog_status.sh" "${backlog}")"
expected_summary_lines=(
  "wave 1"
  "  total: 4"
  "  not_started: 2"
  "  in_progress: 1"
  "  merged: 1"
)
for line in "${expected_summary_lines[@]}"; do
  assert_has_line "${summary}" "${line}" "legacy wave_backlog_status.sh failed"
done

cat > "${compact_backlog}" <<'CSV'
id,work_item,wave,status,branch,files,notes
CMP-MERGED,Compact merged dep,wave1,merged,feat/cmp-merged,src/cmp_merged.py,
CMP-READY,Compact ready task,wave1,not_started,feat/cmp-ready,src/cmp_ready.py,
CMP-BLOCKED,Compact blocked task,wave1,blocked,feat/cmp-blocked,src/cmp_blocked.py,
CMP-WAVE2,Compact wave 2 task,wave2,not_started,feat/cmp-wave2,src/cmp_wave2.py,
CSV

expected_compact_ready=$'CMP-READY'
compact_ready_numeric="$("${repo_root}/scripts/backlog_ready_tasks.sh" "${compact_backlog}" 1)"
assert_eq "${expected_compact_ready}" "${compact_ready_numeric}" "compact numeric-wave backlog_ready_tasks.sh failed"
compact_ready_prefixed="$("${repo_root}/scripts/backlog_ready_tasks.sh" "${compact_backlog}" wave1)"
assert_eq "${expected_compact_ready}" "${compact_ready_prefixed}" "compact wave-prefixed backlog_ready_tasks.sh failed"

compact_summary="$("${repo_root}/scripts/wave_backlog_status.sh" "${compact_backlog}")"
compact_summary_lines=(
  "wave 1"
  "  total: 3"
  "  not_started: 1"
  "  blocked: 1"
  "  merged: 1"
  "wave 2"
  "  total: 1"
  "  not_started: 1"
)
for line in "${compact_summary_lines[@]}"; do
  assert_has_line "${compact_summary}" "${line}" "compact wave_backlog_status.sh failed"
done

# Negative check: previous fixed-position parsing returns incorrect compact readiness.
old_ready_fixed_columns="$(awk -F',' '
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
    if (task_wave[task] != 1) continue
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
' "${compact_backlog}" | sort)"
if [ "${old_ready_fixed_columns}" = "${expected_compact_ready}" ]; then
  echo "negative check failed: old fixed-column parsing unexpectedly matched compact readiness" >&2
  exit 1
fi

# Negative check: exact-wave matching misses wave1 when target is numeric 1.
old_ready_no_wave_normalization="$(awk -F',' -v target_wave="1" '
NR==1 { next }
{
  if ($3 == target_wave && $4 == "not_started") {
    print $1
  }
}
' "${compact_backlog}" | sort)"
if [ "${old_ready_no_wave_normalization}" = "${expected_compact_ready}" ]; then
  echo "negative check failed: old exact wave matching unexpectedly handled wave normalization" >&2
  exit 1
fi

stub_bin="${tmp_dir}/bin"
mkdir -p "${stub_bin}"
cat > "${stub_bin}/codex" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "${CODEX_STUB_LOG:?}"
exit 0
STUB
chmod +x "${stub_bin}/codex"

export CODEX_STUB_LOG="${tmp_dir}/codex.log"
export PATH="${stub_bin}:${PATH}"

worktree_root="${tmp_dir}/worktrees"
mkdir -p "${worktree_root}/feat__dep1" \
         "${worktree_root}/feat__dep2" \
         "${worktree_root}/feat__task-blocked" \
         "${worktree_root}/feat__task-ready" \
         "${worktree_root}/feat__cmp-merged" \
         "${worktree_root}/feat__cmp-ready" \
         "${worktree_root}/feat__cmp-blocked" \
         "${worktree_root}/feat__cmp-wave2"

"${repo_root}/scripts/launch_wave_agents.sh" "${backlog}" wave1 "${worktree_root}" "legacy" 0 >/dev/null

pid_file="${worktree_root}/_agent_logs/legacy/pids.tsv"
if [ ! -f "${pid_file}" ]; then
  echo "legacy launch_wave_agents.sh failed: missing pid file ${pid_file}" >&2
  exit 1
fi

launched_tasks="$(awk 'NR>1 { print $1 }' "${pid_file}")"
assert_eq "${expected_ready}" "${launched_tasks}" "legacy launch_wave_agents.sh failed"

"${repo_root}/scripts/launch_wave_agents.sh" "${compact_backlog}" 1 "${worktree_root}" "compact" 0 >/dev/null

compact_pid_file="${worktree_root}/_agent_logs/compact/pids.tsv"
if [ ! -f "${compact_pid_file}" ]; then
  echo "compact launch_wave_agents.sh failed: missing pid file ${compact_pid_file}" >&2
  exit 1
fi

compact_launched_tasks="$(awk 'NR>1 { print $1 }' "${compact_pid_file}")"
assert_eq "${expected_compact_ready}" "${compact_launched_tasks}" "compact launch_wave_agents.sh failed"

echo "wave status column checks passed"
