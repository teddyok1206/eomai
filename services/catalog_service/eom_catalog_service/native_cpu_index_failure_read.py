"""Root-only exact terminated CPU INDEX evidence; no source reads, reset or launch."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.native_embedding_index_systemd import (
    INDEX_TEMPLATE,
    INDEX_TEMPLATE_SHA256,
    PREPARE_TEMPLATE,
    PREPARE_TEMPLATE_SHA256,
    native_index_unit_names,
)
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from eom_workflow.embedding_cpu_failure_recovery import RetiredNativeCpuIndexFailure
from eom_workflow.embedding_cpu_preparation_failure import RetiredNativeCpuPreparationFailure

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}
_CGROUP_ROOT = Path("/sys/fs/cgroup/system.slice")
_FAILED_RESULTS = frozenset(("timeout", "exit-code", "signal", "core-dump", "oom-kill"))


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("NATIVE_CPU_INDEX_FAILURE_UNPROVEN")


def _root() -> None:
    _require(os.getresuid() == (0, 0, 0))


def _empty_original_unit(unit: str) -> None:
    """An absent cgroup requires the separately proven original terminal unit."""
    observed = subprocess.run(
        ("/usr/bin/systemctl", "show", unit, "-p", "NFileDescriptorStore,ControlGroup"),
        check=True,
        capture_output=True,
        timeout=10,
        env=_ENV,
    )
    _require(len(observed.stdout) <= 4096 and len(observed.stderr) <= 4096)
    fields: dict[str, str] = {}
    for line in observed.stdout.decode("utf-8", errors="strict").splitlines():
        key, separator, value = line.partition("=")
        _require(bool(separator) and key not in fields)
        fields[key] = value
    _require(
        set(fields) == {"NFileDescriptorStore", "ControlGroup"}
        and fields["NFileDescriptorStore"] == "0"
        and fields["ControlGroup"] in {"", "/system.slice/" + unit}
    )
    try:
        _require(root_owned_unit_processes(unit) == ())
    except FileNotFoundError as error:
        # Missing hierarchy/proc file or a symlink must not become proof of emptiness.
        _require(error.filename == str(_CGROUP_ROOT / unit))
        base = _CGROUP_ROOT.lstat()
        _require(stat.S_ISDIR(base.st_mode) and base.st_uid == 0 and not base.st_mode & 0o022)
        try:
            (_CGROUP_ROOT / unit).lstat()
        except FileNotFoundError:
            return
        raise ValueError("NATIVE_CPU_INDEX_FAILURE_UNPROVEN") from None


def _boot_id() -> str:
    with Path("/proc/sys/kernel/random/boot_id").open("rb") as stream:
        raw = stream.read(65)
    _require(len(raw) == 37 and raw.endswith(b"\n"))
    value = raw[:-1].decode("ascii", errors="strict")
    _require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None)
    return value


def validate_retired_native_cpu_index_units(
    prepare: CpuUnitObservation, numeric: CpuUnitObservation
) -> None:
    """Generic CPU timeout stays UNCERTAIN; maintenance proves stronger termination."""
    status = numeric.status
    _require(
        prepare.succeeded
        and numeric.main_pid == 0
        and status.active_state == "failed"
        and status.sub_state == "failed"
        and status.result in _FAILED_RESULTS
        and status.exec_main_code in {1, 2, 3}
        and 0 <= status.exec_main_status <= 255
        and status.exec_main_started_monotonic > 0
        and numeric.exited_monotonic >= status.exec_main_started_monotonic
        and re.fullmatch(r"[0-9a-f]{32}", numeric.invocation_id) is not None
        and prepare.invocation_id != numeric.invocation_id
    )


def _observe(native_job_id: str) -> RetiredNativeCpuIndexFailure:
    _root()
    _require(re.fullmatch(r"job_[0-9a-f]{32}", native_job_id) is not None)
    prepare_unit, numeric_unit = native_index_unit_names(native_job_id.removeprefix("job_"))
    prepare = inspect_cpu_unit(prepare_unit, template=PREPARE_TEMPLATE)
    numeric = inspect_cpu_unit(numeric_unit, template=INDEX_TEMPLATE)
    validate_retired_native_cpu_index_units(prepare, numeric)
    for unit in (prepare_unit, numeric_unit):
        _empty_original_unit(unit)
    body = dict(
        kind="NATIVE_CPU_INDEX_FAILED",
        native_launch_job_id=native_job_id,
        boot_id=_boot_id(),
        prepare_invocation_id=prepare.invocation_id,
        numeric_invocation_id=numeric.invocation_id,
        prepare_template_sha256="sha256:" + PREPARE_TEMPLATE_SHA256,
        numeric_template_sha256="sha256:" + INDEX_TEMPLATE_SHA256,
        numeric_started_monotonic_us=numeric.status.exec_main_started_monotonic,
        numeric_exited_monotonic_us=numeric.exited_monotonic,
        numeric_result=numeric.status.result,
        numeric_exec_main_code=numeric.status.exec_main_code,
        numeric_exec_main_status=numeric.status.exec_main_status,
        original_outcome="FAILED",
        stored_descriptors=0,
    )
    return RetiredNativeCpuIndexFailure.model_validate(
        body | {"proof_sha256": content_sha256(body)}
    )


def validate_retired_native_cpu_preparation_units(
    prepare: CpuUnitObservation, numeric: CpuUnitObservation
) -> None:
    """A failed preparer is not a failed numeric invocation or permission to restart it."""
    status = prepare.status
    _require(
        prepare.main_pid == 0
        and status.active_state == status.sub_state == "failed"
        and status.result in _FAILED_RESULTS
        and status.exec_main_code in {1, 2, 3}
        and 0 <= status.exec_main_status <= 255
        and status.exec_main_started_monotonic > 0
        and prepare.exited_monotonic >= status.exec_main_started_monotonic
        and re.fullmatch(r"[0-9a-f]{32}", prepare.invocation_id) is not None
        and numeric.main_pid == 0
        and numeric.fresh
        and not numeric.invocation_id
        and numeric.exited_monotonic == 0
    )


def _observe_preparation(native_job_id: str) -> RetiredNativeCpuPreparationFailure:
    _root()
    _require(re.fullmatch(r"job_[0-9a-f]{32}", native_job_id) is not None)
    units = native_index_unit_names(native_job_id.removeprefix("job_"))
    prepare = inspect_cpu_unit(units[0], template=PREPARE_TEMPLATE)
    numeric = inspect_cpu_unit(units[1], template=INDEX_TEMPLATE)
    validate_retired_native_cpu_preparation_units(prepare, numeric)
    for unit in units:
        _empty_original_unit(unit)
    body = dict(
        kind="NATIVE_CPU_INDEX_PREPARATION_FAILED",
        native_launch_job_id=native_job_id,
        boot_id=_boot_id(),
        prepare_invocation_id=prepare.invocation_id,
        prepare_template_sha256="sha256:" + PREPARE_TEMPLATE_SHA256,
        numeric_template_sha256="sha256:" + INDEX_TEMPLATE_SHA256,
        prepare_started_monotonic_us=prepare.status.exec_main_started_monotonic,
        prepare_exited_monotonic_us=prepare.exited_monotonic,
        prepare_result=prepare.status.result,
        prepare_exec_main_code=prepare.status.exec_main_code,
        prepare_exec_main_status=prepare.status.exec_main_status,
        numeric_state="NOT_STARTED",
        original_outcome="FAILED",
        stored_descriptors=0,
    )
    return RetiredNativeCpuPreparationFailure.model_validate(
        body | {"proof_sha256": content_sha256(body)}
    )


def _templates(reader: NumericalRuntimeFileSnapshots) -> None:
    for template, expected in (
        (PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256),
        (INDEX_TEMPLATE, INDEX_TEMPLATE_SHA256),
    ):
        raw = reader.observe_protected_member_bytes(
            Path("/etc/systemd/system") / template, maximum=65536
        ).raw
        _require(sha256_bytes(raw) == "sha256:" + expected)


@dataclass(frozen=True, slots=True)
class ResolvedRetiredNativeCpuIndexFailure:
    proof: RetiredNativeCpuIndexFailure | RetiredNativeCpuPreparationFailure


def capture_retired_native_cpu_index_failure(native_job_id: str) -> RetiredNativeCpuIndexFailure:
    """Read-only preparation; the returned value is not a mutation capability."""
    _root()
    reader = NumericalRuntimeFileSnapshots()
    _templates(reader)
    proof = _observe(native_job_id)
    reader.assert_unchanged()
    _require(_observe(native_job_id) == proof)
    return proof


def capture_retired_native_cpu_preparation_failure(
    native_job_id: str,
) -> RetiredNativeCpuPreparationFailure:
    """Observe only the original prepare failure, without reset/start/file writes."""
    _root()
    reader = NumericalRuntimeFileSnapshots()
    _templates(reader)
    proof = _observe_preparation(native_job_id)
    reader.assert_unchanged()
    _require(_observe_preparation(native_job_id) == proof)
    return proof


@contextmanager
def read_retired_native_cpu_index_failure(
    proof: RetiredNativeCpuIndexFailure | RetiredNativeCpuPreparationFailure,
) -> Iterator[ResolvedRetiredNativeCpuIndexFailure]:
    """Stay inside a short owner root; late identity changes roll back all its writes."""
    _root()
    observe: Callable[[str], RetiredNativeCpuIndexFailure | RetiredNativeCpuPreparationFailure]
    if isinstance(proof, RetiredNativeCpuPreparationFailure):
        proof = RetiredNativeCpuPreparationFailure.model_validate(proof)
        observe = _observe_preparation
    else:
        proof = RetiredNativeCpuIndexFailure.model_validate(proof)
        observe = _observe
    reader = NumericalRuntimeFileSnapshots()
    _templates(reader)
    _require(observe(proof.native_launch_job_id) == proof)
    yield ResolvedRetiredNativeCpuIndexFailure(proof)
    reader.assert_unchanged()
    _require(observe(proof.native_launch_job_id) == proof)
