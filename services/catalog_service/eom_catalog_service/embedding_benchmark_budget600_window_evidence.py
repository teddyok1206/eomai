"""Read the one protected finite benchmark window; never reopen or mutate it."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_identifiers import canonical_json_bytes

from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

WINDOW_ROOT = Path("/var/lib/eom-gpu-benchmark-budget600-20261022-a7a80a1c")
CONTROLLER_UNIT = "eom-gpu-benchmark-budget600-a7a80a1c-v4.service"
OWNER_UNITS = (
    "eom-embedding-index-owner.service",
    "eom-reference-query-owner.service",
)
_PROPERTIES = frozenset(
    (
        "ActiveState",
        "ControlGroup",
        "ControlPID",
        "DropInPaths",
        "ExecMainPID",
        "ExecMainStatus",
        "FragmentPath",
        "Group",
        "Id",
        "InvocationID",
        "Job",
        "LoadState",
        "MainPID",
        "NFileDescriptorStore",
        "NRestarts",
        "NeedDaemonReload",
        "Restart",
        "Result",
        "SubState",
        "User",
    )
)
_ACL = frozenset(("system.posix_acl_access", "system.posix_acl_default"))


def _require(value: bool) -> None:
    if not value:
        raise ValueError("BENCHMARK_BUDGET600_WINDOW_INVALID")


def _directory(path: Path, owner_uid: int, *, mode: int) -> None:
    value = path.lstat()
    _require(
        stat.S_ISDIR(value.st_mode)
        and value.st_uid == owner_uid
        and stat.S_IMODE(value.st_mode) == mode
        and not _ACL.intersection(os.listxattr(path, follow_symlinks=False))
    )


def _read(
    files: NumericalRuntimeFileSnapshots, path: Path, *, owner_uid: int
) -> tuple[dict[str, Any], str]:
    value = path.lstat()
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == owner_uid
        and stat.S_IMODE(value.st_mode) == 0o400
        and value.st_nlink == 1
        and not _ACL.intersection(os.listxattr(path, follow_symlinks=False))
    )
    observed = files.observe_protected_member_bytes(path, maximum=65536)
    document = parse_rootlocal_evidence_document(observed.raw, 65536)
    _require(canonical_json_bytes(document) == observed.raw)
    return document, observed.sha256


def _rows(document: object, phase: str) -> dict[str, dict[str, str]]:
    if not isinstance(document, dict):
        raise ValueError("BENCHMARK_BUDGET600_WINDOW_INVALID")
    _require(set(document) == set(OWNER_UNITS))
    result: dict[str, dict[str, str]] = {}
    for name in OWNER_UNITS:
        row = document[name]
        _require(
            isinstance(row, dict)
            and set(row) == _PROPERTIES
            and all(type(value) is str for value in row.values())
            and row["Id"] == name
            and row["LoadState"] == "loaded"
            and row["FragmentPath"] == "/etc/systemd/system/" + name
            and row["DropInPaths"] == ""
            and row["NeedDaemonReload"] == "no"
            and row["Job"] in ("", "0")
            and row["ControlPID"] == row["NFileDescriptorStore"] == row["NRestarts"] == "0"
            and row["Restart"] == "no"
            and re.fullmatch(r"[0-9a-f]{32}", row["InvocationID"]) is not None
        )
        if phase == "STOPPED":
            _require(
                (row["ActiveState"], row["SubState"], row["Result"], row["MainPID"])
                == ("inactive", "dead", "success", "0")
                and row["ControlGroup"] == ""
            )
        else:
            _require(
                (row["ActiveState"], row["SubState"], row["Result"])
                == ("active", "running", "success")
                and row["MainPID"].isdecimal()
                and int(row["MainPID"]) > 0
                and row["MainPID"] == row["ExecMainPID"]
                and row["ControlGroup"] == "/system.slice/" + name
            )
        result[name] = row
    return result


@dataclass(frozen=True, slots=True)
class CapturedBudget600Window:
    before_raw_sha256: str
    stopped_raw_sha256: str
    restored_raw_sha256: str
    retired_service_template_sha256: str
    retired_socket_template_sha256: str
    files: NumericalRuntimeFileSnapshots
    protected_paths: tuple[Path, ...]
    retired_load_paths: tuple[Path, Path]

    def assert_current(self) -> None:
        self.files.assert_unchanged()
        for path in self.protected_paths:
            _require(not _ACL.intersection(os.listxattr(path, follow_symlinks=False)))
        _require(not any(os.path.lexists(path) for path in self.retired_load_paths))


def capture_budget600_window(
    request: BenchmarkOwnerRequest,
    *,
    controller_invocation_id: str,
    root: Path = WINDOW_ROOT,
    owner_uid: int = 0,
) -> CapturedBudget600Window:
    """Root-only bounded records and retired fixed bytes; no state-changing operation."""
    _require(os.getresuid() == (owner_uid,) * 3)
    if owner_uid == 0:
        _require(os.getresgid() == (0,) * 3)
    _require(re.fullmatch(r"[0-9a-f]{32}", controller_invocation_id) is not None)
    _directory(root, owner_uid, mode=0o755)
    retired_root = root / "retired-templates"
    _directory(retired_root, owner_uid, mode=0o700)
    files = NumericalRuntimeFileSnapshots(owner_uid)
    paths = (
        root,
        retired_root,
        root / "window-before.json",
        root / "window-stopped.json",
        root / "window-restored.json",
    )
    before, before_hash = _read(files, paths[2], owner_uid=owner_uid)
    stopped, stopped_hash = _read(files, paths[3], owner_uid=owner_uid)
    restored, restored_hash = _read(files, paths[4], owner_uid=owner_uid)
    _require(
        set(before) == {"schema_version", "controller_unit", "invocation_id", "before"}
        and before["schema_version"] == "finite-benchmark-window/1.0"
        and before["controller_unit"] == CONTROLLER_UNIT
        and before["invocation_id"] == controller_invocation_id
    )
    original = _rows(before["before"], "RUNNING")
    drained = _rows(stopped, "STOPPED")
    resumed = _rows(restored, "RUNNING")
    for name in OWNER_UNITS:
        _require(
            drained[name]["InvocationID"] == original[name]["InvocationID"]
            and resumed[name]["InvocationID"] != original[name]["InvocationID"]
            and (original[name]["User"], original[name]["Group"])
            == (drained[name]["User"], drained[name]["Group"])
            == (resumed[name]["User"], resumed[name]["Group"])
        )
    cpu = benchmark_unit_family("CPU", request.execution_policy)
    _require(cpu.timeout_seconds == 600)
    service = retired_root / cpu.service_template
    socket = retired_root / cpu.socket_template
    for path, expected in ((service, cpu.service_sha256), (socket, cpu.socket_sha256)):
        document = files.observe_protected_member_bytes(path, maximum=65536)
        value = path.lstat()
        _require(
            document.sha256 == expected
            and value.st_uid == owner_uid
            and stat.S_IMODE(value.st_mode) == 0o400
            and value.st_nlink == 1
            and not _ACL.intersection(os.listxattr(path, follow_symlinks=False))
        )
    load_paths = (
        Path("/etc/systemd/system") / cpu.service_template,
        Path("/etc/systemd/system") / cpu.socket_template,
    )
    _require(not any(os.path.lexists(path) for path in load_paths))
    result = CapturedBudget600Window(
        before_hash,
        stopped_hash,
        restored_hash,
        cpu.service_sha256,
        cpu.socket_sha256,
        files,
        (*paths, service, socket),
        load_paths,
    )
    result.assert_current()
    return result
