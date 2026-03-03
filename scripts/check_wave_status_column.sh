#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

backlog="${tmp_dir}/backlog.csv"

cat > "${backlog}" <<'CSV'
task_id,title,wave,c4,c5,c6,deps,branch,c9,files,c11,c12,c13,c14,c15,status_old,status
DEP-1,Dependency one,1,,,,,feat/dep1,,src/dep1.py,,,,,,not_started,merged
DEP-2,Dependency two,1,,,,,feat/dep2,,src/dep2.py,,,,,,merged,in_progress
TASK-BLOCKED,Blocked task,1,,,,DEP-2,feat/task-blocked,,src/blocked.py,,,,,,not_started,not_started
TASK-READY,Ready task,1,,,,DEP-1,feat/task-ready,,src/ready.py,,,,,,not_started,not_started
CSV

expected_ready=$'TASK-READY'
actual_ready="$("${repo_root}/scripts/backlog_ready_tasks.sh" "${backlog}" 1)"
if [ "${actual_ready}" != "${expected_ready}" ]; then
  echo "backlog_ready_tasks.sh failed: expected '${expected_ready}', got '${actual_ready}'" >&2
  exit 1
fi

summary="$("${repo_root}/scripts/wave_backlog_status.sh" "${backlog}")"
expected_summary_lines=(
  "wave 1"
  "  total: 4"
  "  not_started: 2"
  "  in_progress: 1"
  "  merged: 1"
)
for line in "${expected_summary_lines[@]}"; do
  if ! printf '%s\n' "${summary}" | grep -Fqx "${line}"; then
    echo "wave_backlog_status.sh missing expected line: ${line}" >&2
    exit 1
  fi
done

# Negative check: previous column-16 parsing misclassifies readiness.
old_ready="$(awk -F',' '
function trim(s) { gsub(/^ +| +$/, "", s); return s }
NR==1 { next }
{
  task=$1
  wave=$3
  deps=$7
  status=$16
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
' "${backlog}" | sort)"
if [ "${old_ready}" = "${expected_ready}" ]; then
  echo "negative check failed: old column-16 parsing unexpectedly matched correct readiness" >&2
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
         "${worktree_root}/feat__task-ready"

"${repo_root}/scripts/launch_wave_agents.sh" "${backlog}" 1 "${worktree_root}" "statuscol" 0 >/dev/null

pid_file="${worktree_root}/_agent_logs/statuscol/pids.tsv"
if [ ! -f "${pid_file}" ]; then
  echo "launch_wave_agents.sh failed: missing pid file ${pid_file}" >&2
  exit 1
fi

launched_tasks="$(awk 'NR>1 { print $1 }' "${pid_file}")"
if [ "${launched_tasks}" != "${expected_ready}" ]; then
  echo "launch_wave_agents.sh failed: expected launch '${expected_ready}', got '${launched_tasks}'" >&2
  exit 1
fi

echo "wave status column checks passed"
