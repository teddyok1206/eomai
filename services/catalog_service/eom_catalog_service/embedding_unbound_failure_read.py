"""Root-only original failed-controller/no-grant read; no effect, grant or retry."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationRequest,
    parse_embedding_gpu_control_bytes,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from eom_workflow.embedding_unbound_control_failure import UnboundEmbeddingControlFailure

from eom_catalog_service.embedding_batch_control_connection import BATCH_CONTROL_TEMPLATE_SHA256
from eom_catalog_service.embedding_batch_control_workspace import BATCH_CONTROL_TEMPLATE
from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_RUNTIME_ROOT,
    GPU_BATCH_SERVICE_SHA256,
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
    parse_native_embedding_gpu_batch_environment,
)
from eom_catalog_service.embedding_gpu_batch_unit_descriptor import (
    embedding_gpu_batch_descriptor_bytes,
    embedding_gpu_batch_descriptor_path,
    inspect_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_failed_gpu_unit_metadata,
    observe_uninvoked_embedding_gpu_batch_unit,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_UNBOUND_CONTROL_FAILURE_UNCERTAIN")


def _empty_cgroup(unit: str) -> None:
    try:
        processes = root_owned_unit_processes(unit)
    except FileNotFoundError:
        _require(not (Path("/sys/fs/cgroup/system.slice") / unit).exists())
        processes = ()
    _require(not processes)


def _controller(proof: UnboundEmbeddingControlFailure, unit: str) -> CpuUnitObservation:
    observed = inspect_cpu_unit(unit, template=BATCH_CONTROL_TEMPLATE)
    _require(
        observed.invocation_id == proof.controller_invocation_id
        and observed.main_pid == 0
        and not observed.drop_in_paths
        and not observed.status.need_daemon_reload
        and gpu_unit_terminal_outcome(observed) == "FAILED"
    )
    pid, descriptors = observe_failed_gpu_unit_metadata(
        unit, template=BATCH_CONTROL_TEMPLATE, expected=observed
    )
    _require(pid == proof.controller_pid and descriptors == 0)
    _empty_cgroup(unit)
    return observed


def _native(unit: str) -> tuple[CpuUnitObservation, StoppedGpuUnit]:
    observed = inspect_embedding_gpu_batch_unit(unit, template=GPU_BATCH_TEMPLATE)
    _require(observed.fresh)
    stopped = observe_uninvoked_embedding_gpu_batch_unit(unit)
    _require(stopped.invocation_id == "" and stopped.stored_descriptors == 0)
    _empty_cgroup(unit)
    return observed, stopped


def _no_grant(directory: Path) -> None:
    try:
        (directory / "input-grant.json").lstat()
    except FileNotFoundError:
        return
    raise ValueError("EMBEDDING_UNBOUND_CONTROL_INPUT_ALREADY_GRANTED")


@dataclass(frozen=True, slots=True)
class ResolvedUnboundControlFailure:
    proof: UnboundEmbeddingControlFailure
    allocation: EmbeddingGpuAllocationRequest


@contextmanager
def read_unbound_embedding_control_failure(
    proof: UnboundEmbeddingControlFailure,
) -> Iterator[ResolvedUnboundControlFailure]:
    """Keep both actual OS/file fences inside the short owner's mutation root.

    Empty immutable handoff and absent grant prove NOT_GRANTED, not that a CUDA
    process was historically never initialized. No numerical retirement or BUSY
    observation is emitted. An unrelated running allocation is not touched.
    """
    _require(os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0))
    proof = UnboundEmbeddingControlFailure.model_validate(proof)
    boot = (
        read_live_runtime_os_file(Path("/proc/sys/kernel/random/boot_id"), maximum=64, owner_uid=0)
        .decode("ascii")
        .strip()
    )
    _require(boot == proof.boot_id and proof.observed_at <= datetime.now(UTC))
    attempt = proof.allocation_attempt_id.removeprefix("embeddingallocation_")
    root_unit = BATCH_CONTROL_TEMPLATE.replace("@.service", f"@{attempt}.service")
    native_unit = native_embedding_gpu_batch_unit(attempt)
    before_root, before_native = _controller(proof, root_unit), _native(native_unit)
    files = NumericalRuntimeFileSnapshots()
    for template, expected in (
        # systemd's fixed-template helper uses a plain hexadecimal constant;
        # the protected-file reader requires the typed sha256: representation.
        (BATCH_CONTROL_TEMPLATE, "sha256:" + BATCH_CONTROL_TEMPLATE_SHA256),
        (GPU_BATCH_TEMPLATE, GPU_BATCH_SERVICE_SHA256),
    ):
        files.read(Path("/etc/systemd/system") / template, sha256=expected, maximum=65536)
    directory = GPU_BATCH_RUNTIME_ROOT / attempt
    raw = files.read(
        directory / "allocation.json", sha256=proof.allocation_raw_sha256, maximum=32768
    )
    allocation = parse_embedding_gpu_control_bytes(raw)
    _require(isinstance(allocation, EmbeddingGpuAllocationRequest))
    assert isinstance(allocation, EmbeddingGpuAllocationRequest)
    _require(
        allocation.allocation_attempt_id == proof.allocation_attempt_id
        and allocation.parent_request_sha256 == proof.parent_request_sha256
        and allocation.message_sha256 == proof.allocation_request_sha256
        and allocation.purpose == "INDEX"
        and allocation.expires_monotonic_ns < time.monotonic_ns()
    )
    launch = parse_native_embedding_gpu_batch_environment(
        files.read(directory / "launch.env", sha256=proof.launch_raw_sha256, maximum=4096),
        attempt_hex=attempt,
    )
    _require(
        launch.root_pid == proof.controller_pid
        and launch.allocation_raw_sha256 == sha256_bytes(raw)
    )
    descriptor = files.read(
        embedding_gpu_batch_descriptor_path(attempt),
        sha256=proof.descriptor_raw_sha256,
        maximum=4096,
    )
    _require(descriptor == embedding_gpu_batch_descriptor_bytes(attempt))
    gid = fixed_owner_identity().owner_gid
    for name, mode in (("input.json", 0o600), ("result.json", 0o640), ("vectors.f32", 0o640)):
        path = directory / name
        _require(files.observe_protected_member_bytes(path, maximum=1).raw == b"")
        metadata = path.lstat()
        _require(metadata.st_gid == gid and stat.S_IMODE(metadata.st_mode) == mode)
    _no_grant(directory)
    files.assert_unchanged()
    yield ResolvedUnboundControlFailure(proof, allocation)
    files.assert_unchanged()
    _no_grant(directory)
    _require(_controller(proof, root_unit) == before_root and _native(native_unit) == before_native)
