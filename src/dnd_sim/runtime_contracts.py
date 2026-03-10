from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

DEFAULT_AGENT_INDEX_PATH = Path("docs/agent_index.yaml")
DEFAULT_OWNERSHIP_GLOBS = ("src/dnd_sim/*.py",)
DEFAULT_MAX_FILE_LINES = 1500

STRUCTURED_ERROR_KEYWORDS = (
    "structured error",
    "structured errors",
    "structured failure",
    "structured failures",
)
TRACE_KEYWORDS = (
    "trace",
    "traces",
    "telemetry",
)


@runtime_checkable
class ContentProvider(Protocol):
    def resolve_content_path(self, reference: str, *, scenario_path: Path) -> Path:
        """Resolve a public or internal content reference into a deterministic local path."""


@runtime_checkable
class CampaignStateStore(Protocol):
    def save_campaign_snapshot(self, *, campaign_id: str, snapshot: dict[str, Any]) -> None:
        """Persist one canonical campaign snapshot."""

    def load_campaign_snapshot(self, *, campaign_id: str) -> dict[str, Any]:
        """Load one canonical campaign snapshot."""


@runtime_checkable
class ReplayReporter(Protocol):
    def build_trial_rows(self, trials: list[Any]) -> list[dict[str, Any]]:
        """Project authoritative trial results into deterministic replay rows."""

    def build_summary(
        self,
        *,
        run_id: str,
        scenario_id: str,
        trials: int,
        trial_results: list[Any],
        tracked_resource_names: dict[str, set[str]],
    ) -> Any:
        """Project authoritative trial results into a report-friendly summary object."""


@dataclass(frozen=True, slots=True)
class SubsystemContract:
    name: str
    owner_pool: str
    owner_task: str
    owner_module: str
    invariants: tuple[str, ...]
    safe_edit_boundaries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FileSizeWaiver:
    module: str
    max_lines: int
    reason: str


@dataclass(frozen=True, slots=True)
class MaintenanceGatePolicy:
    ownership_globs: tuple[str, ...] = DEFAULT_OWNERSHIP_GLOBS
    default_max_file_lines: int = DEFAULT_MAX_FILE_LINES
    file_size_waivers: tuple[FileSizeWaiver, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentIndexContracts:
    subsystems: tuple[SubsystemContract, ...]
    maintenance_gate: MaintenanceGatePolicy


@dataclass(frozen=True, slots=True)
class MaintenanceIssue:
    code: str
    check: str
    message: str
    module: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "check": self.check,
            "message": self.message,
            "module": self.module,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    issues: tuple[MaintenanceIssue, ...]
    trace: tuple[dict[str, Any], ...]


class AgentMaintenanceContractError(ValueError):
    def __init__(self, *, code: str, message: str, details: dict[str, Any]) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _strip_yaml_scalar(value: str) -> str:
    scalar = value.strip()
    if not scalar:
        return ""
    if scalar[0] == scalar[-1] and scalar[0] in {"'", '"'} and len(scalar) >= 2:
        return scalar[1:-1]
    return scalar


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_ignorable(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _parse_yaml_string_list(
    lines: list[str],
    *,
    start_index: int,
    list_indent: int,
) -> tuple[int, list[str]]:
    values: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue

        indent = _line_indent(line)
        if indent < list_indent:
            break
        stripped = line.strip()
        if indent == list_indent and stripped.startswith("- "):
            values.append(_strip_yaml_scalar(stripped[2:]))
            index += 1
            continue
        break
    return index, values


def _parse_subsystem_block(
    name: str,
    lines: list[str],
    *,
    start_index: int,
) -> tuple[int, SubsystemContract]:
    owner_pool: str | None = None
    owner_task: str | None = None
    owner_module: str | None = None
    invariants: list[str] = []
    safe_edit_boundaries: list[str] = []

    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        indent = _line_indent(line)
        if indent <= 2:
            break

        stripped = line.strip()
        if indent == 4 and stripped.startswith("owner_pool:"):
            owner_pool = _strip_yaml_scalar(stripped.split(":", 1)[1])
            index += 1
            continue
        if indent == 4 and stripped.startswith("owner_task:"):
            owner_task = _strip_yaml_scalar(stripped.split(":", 1)[1])
            index += 1
            continue
        if indent == 4 and stripped.startswith("owner_module:"):
            owner_module = _strip_yaml_scalar(stripped.split(":", 1)[1])
            index += 1
            continue
        if indent == 4 and stripped == "invariants:":
            index, invariants = _parse_yaml_string_list(
                lines,
                start_index=index + 1,
                list_indent=6,
            )
            continue
        if indent == 4 and stripped == "safe_edit_boundaries:":
            index, safe_edit_boundaries = _parse_yaml_string_list(
                lines,
                start_index=index + 1,
                list_indent=6,
            )
            continue

        index += 1

    if owner_pool is None or owner_task is None or owner_module is None:
        raise ValueError(f"subsystem '{name}' is missing owner metadata")
    return (
        index,
        SubsystemContract(
            name=name,
            owner_pool=_required_text(owner_pool, field_name="owner_pool"),
            owner_task=_required_text(owner_task, field_name="owner_task"),
            owner_module=_required_text(owner_module, field_name="owner_module"),
            invariants=tuple(_required_text(row, field_name="invariant") for row in invariants),
            safe_edit_boundaries=tuple(
                _required_text(row, field_name="safe_edit_boundary") for row in safe_edit_boundaries
            ),
        ),
    )


def _parse_subsystems(
    lines: list[str], *, start_index: int
) -> tuple[int, tuple[SubsystemContract, ...]]:
    subsystems: list[SubsystemContract] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        indent = _line_indent(line)
        if indent == 0:
            break
        if indent == 2 and line.strip().endswith(":"):
            subsystem_name = _required_text(line.strip()[:-1], field_name="subsystem name")
            index, subsystem = _parse_subsystem_block(
                subsystem_name,
                lines,
                start_index=index + 1,
            )
            subsystems.append(subsystem)
            continue
        index += 1

    return index, tuple(subsystems)


def _parse_file_size_waivers(
    lines: list[str],
    *,
    start_index: int,
) -> tuple[int, tuple[FileSizeWaiver, ...]]:
    waivers: list[FileSizeWaiver] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        indent = _line_indent(line)
        if indent < 6:
            break
        stripped = line.strip()
        if indent != 6 or not stripped.startswith("- "):
            break

        row_payload: dict[str, str] = {}
        first_row = stripped[2:]
        if ":" in first_row:
            key, value = first_row.split(":", 1)
            row_payload[key.strip()] = _strip_yaml_scalar(value)

        index += 1
        while index < len(lines):
            child_line = lines[index]
            if _is_ignorable(child_line):
                index += 1
                continue
            child_indent = _line_indent(child_line)
            if child_indent <= 6:
                break
            if child_indent == 8 and ":" in child_line:
                key, value = child_line.strip().split(":", 1)
                row_payload[key.strip()] = _strip_yaml_scalar(value)
            index += 1

        waivers.append(
            FileSizeWaiver(
                module=_required_text(row_payload.get("module", ""), field_name="waiver.module"),
                max_lines=_required_int(
                    int(row_payload.get("max_lines", "0")),
                    field_name="waiver.max_lines",
                    minimum=1,
                ),
                reason=_required_text(row_payload.get("reason", ""), field_name="waiver.reason"),
            )
        )

    return index, tuple(waivers)


def _parse_maintenance_gate_policy(
    lines: list[str],
    *,
    start_index: int,
) -> tuple[int, MaintenanceGatePolicy]:
    ownership_globs: tuple[str, ...] = DEFAULT_OWNERSHIP_GLOBS
    default_max_file_lines = DEFAULT_MAX_FILE_LINES
    file_size_waivers: tuple[FileSizeWaiver, ...] = ()

    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        indent = _line_indent(line)
        if indent <= 2:
            break
        stripped = line.strip()
        if indent == 4 and stripped == "ownership_globs:":
            index, rows = _parse_yaml_string_list(lines, start_index=index + 1, list_indent=6)
            if rows:
                ownership_globs = tuple(
                    _required_text(row, field_name="ownership_glob") for row in rows
                )
            continue
        if indent == 4 and stripped.startswith("default_max_file_lines:"):
            value = stripped.split(":", 1)[1].strip()
            default_max_file_lines = _required_int(
                int(value),
                field_name="default_max_file_lines",
                minimum=1,
            )
            index += 1
            continue
        if indent == 4 and stripped == "file_size_waivers:":
            index, file_size_waivers = _parse_file_size_waivers(lines, start_index=index + 1)
            continue
        index += 1

    return (
        index,
        MaintenanceGatePolicy(
            ownership_globs=ownership_globs,
            default_max_file_lines=default_max_file_lines,
            file_size_waivers=file_size_waivers,
        ),
    )


def _parse_policies(
    lines: list[str],
    *,
    start_index: int,
) -> tuple[int, MaintenanceGatePolicy]:
    policy = MaintenanceGatePolicy()
    index = start_index
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        indent = _line_indent(line)
        if indent == 0:
            break
        if indent == 2 and line.strip() == "maintenance_gate:":
            index, policy = _parse_maintenance_gate_policy(lines, start_index=index + 1)
            continue
        index += 1
    return index, policy


def load_agent_index_contracts(agent_index_path: Path) -> AgentIndexContracts:
    text = agent_index_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    subsystems: tuple[SubsystemContract, ...] = ()
    policy = MaintenanceGatePolicy()

    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_ignorable(line):
            index += 1
            continue
        stripped = line.strip()
        if stripped == "subsystems:":
            index, subsystems = _parse_subsystems(lines, start_index=index + 1)
            continue
        if stripped == "policies:":
            index, policy = _parse_policies(lines, start_index=index + 1)
            continue
        index += 1

    if not subsystems:
        raise ValueError("agent index must define at least one subsystem")
    return AgentIndexContracts(subsystems=subsystems, maintenance_gate=policy)


def _iter_runtime_modules(repo_root: Path, ownership_globs: tuple[str, ...]) -> tuple[str, ...]:
    modules: set[str] = set()
    for glob in ownership_globs:
        for path in sorted(repo_root.glob(glob)):
            if path.is_file():
                modules.add(path.relative_to(repo_root).as_posix())
    if not modules:
        for path in sorted((repo_root / "src/dnd_sim").glob("*.py")):
            if path.is_file():
                modules.add(path.relative_to(repo_root).as_posix())
    return tuple(sorted(modules))


def _matching_subsystems(
    module_path: str,
    *,
    subsystems: tuple[SubsystemContract, ...],
) -> tuple[SubsystemContract, ...]:
    return tuple(
        subsystem for subsystem in subsystems if fnmatch(module_path, subsystem.owner_module)
    )


def _has_keyword_contract(subsystem: SubsystemContract, keywords: tuple[str, ...]) -> bool:
    for text in subsystem.invariants + subsystem.safe_edit_boundaries:
        lowered = text.lower()
        if any(keyword in lowered for keyword in keywords):
            return True
    return False


def _effective_file_size_threshold(
    module_path: str,
    *,
    default_max_file_lines: int,
    waivers: tuple[FileSizeWaiver, ...],
) -> tuple[int, FileSizeWaiver | None]:
    for waiver in waivers:
        if fnmatch(module_path, waiver.module):
            return waiver.max_lines, waiver
    return default_max_file_lines, None


def evaluate_agent_maintenance_contracts(
    repo_root: Path,
    *,
    agent_index_path: Path | None = None,
) -> MaintenanceReport:
    root = Path(repo_root)
    index_path = agent_index_path or (root / DEFAULT_AGENT_INDEX_PATH)
    contracts = load_agent_index_contracts(index_path)

    modules = _iter_runtime_modules(root, contracts.maintenance_gate.ownership_globs)
    issues: list[MaintenanceIssue] = []
    trace: list[dict[str, Any]] = []

    for module in modules:
        matched = _matching_subsystems(module, subsystems=contracts.subsystems)
        subsystem_names = tuple(subsystem.name for subsystem in matched)

        if not matched:
            issues.append(
                MaintenanceIssue(
                    code="AGENT-MAINT-OWN-001",
                    check="ownership_coverage",
                    module=module,
                    message=f"Missing ownership coverage for {module}",
                    details={"required_owner_field": "owner_module"},
                )
            )
            trace.append(
                {
                    "check": "ownership_coverage",
                    "module": module,
                    "result": "failed",
                    "subsystems": subsystem_names,
                }
            )
            continue
        trace.append(
            {
                "check": "ownership_coverage",
                "module": module,
                "result": "passed",
                "subsystems": subsystem_names,
            }
        )

        if not any(
            _has_keyword_contract(subsystem, STRUCTURED_ERROR_KEYWORDS) for subsystem in matched
        ):
            issues.append(
                MaintenanceIssue(
                    code="AGENT-MAINT-ERR-001",
                    check="structured_error_contract",
                    module=module,
                    message=(
                        f"Missing structured error contract for {module}; "
                        "expected invariant text referencing structured errors"
                    ),
                    details={"keywords": list(STRUCTURED_ERROR_KEYWORDS)},
                )
            )
            trace.append(
                {
                    "check": "structured_error_contract",
                    "module": module,
                    "result": "failed",
                    "subsystems": subsystem_names,
                }
            )
        else:
            trace.append(
                {
                    "check": "structured_error_contract",
                    "module": module,
                    "result": "passed",
                    "subsystems": subsystem_names,
                }
            )

        if not any(_has_keyword_contract(subsystem, TRACE_KEYWORDS) for subsystem in matched):
            issues.append(
                MaintenanceIssue(
                    code="AGENT-MAINT-TRC-001",
                    check="trace_emission_contract",
                    module=module,
                    message=(
                        f"Missing trace emission contract for {module}; "
                        "expected invariant text referencing trace/telemetry emission"
                    ),
                    details={"keywords": list(TRACE_KEYWORDS)},
                )
            )
            trace.append(
                {
                    "check": "trace_emission_contract",
                    "module": module,
                    "result": "failed",
                    "subsystems": subsystem_names,
                }
            )
        else:
            trace.append(
                {
                    "check": "trace_emission_contract",
                    "module": module,
                    "result": "passed",
                    "subsystems": subsystem_names,
                }
            )

        absolute_module = root / module
        line_count = len(absolute_module.read_text(encoding="utf-8").splitlines())
        threshold, waiver = _effective_file_size_threshold(
            module,
            default_max_file_lines=contracts.maintenance_gate.default_max_file_lines,
            waivers=contracts.maintenance_gate.file_size_waivers,
        )
        if line_count > threshold:
            issues.append(
                MaintenanceIssue(
                    code="AGENT-MAINT-SIZE-001",
                    check="file_size_threshold",
                    module=module,
                    message=(
                        f"File-size threshold exceeded for {module}: "
                        f"{line_count} lines > {threshold} lines"
                    ),
                    details={
                        "line_count": line_count,
                        "threshold": threshold,
                        "waiver_reason": waiver.reason if waiver is not None else "",
                    },
                )
            )
            trace.append(
                {
                    "check": "file_size_threshold",
                    "module": module,
                    "result": "failed",
                    "line_count": line_count,
                    "threshold": threshold,
                    "waiver_applied": waiver is not None,
                }
            )
        else:
            trace.append(
                {
                    "check": "file_size_threshold",
                    "module": module,
                    "result": "passed",
                    "line_count": line_count,
                    "threshold": threshold,
                    "waiver_applied": waiver is not None,
                }
            )

    return MaintenanceReport(issues=tuple(issues), trace=tuple(trace))


def assert_agent_maintenance_contracts(
    repo_root: Path,
    *,
    agent_index_path: Path | None = None,
) -> None:
    report = evaluate_agent_maintenance_contracts(
        repo_root,
        agent_index_path=agent_index_path,
    )
    if report.issues:
        raise AgentMaintenanceContractError(
            code="AGENT-MAINT-FAIL",
            message="Agent-only maintenance gate failed",
            details={
                "issues": [issue.to_dict() for issue in report.issues],
                "trace": [dict(row) for row in report.trace],
            },
        )
