"""Original root GPU batch activation/GRANT/result/retirement, never source or NAS authority."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationBusy,
    EmbeddingGpuAllocationRequest,
    EmbeddingGpuCheckChild,
    EmbeddingGpuComputeGrant,
    EmbeddingGpuResultReady,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
    validate_embedding_gpu_allocation_link,
    validate_embedding_gpu_grant,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    EmbeddingWorkBatchResult,
    parse_embedding_work_batch_result,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_gpu_batch_handoff import bind_embedding_gpu_batch_handoff
from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_gpu_batch_lifetime import (
    GPU_BATCH_LIFETIME_ROOT,
    EmbeddingGpuBatchRetirement,
    apply_embedding_gpu_batch_effect,
    observe_embedding_gpu_batch_terminal,
    require_embedding_gpu_batch_cgroup_empty,
    retire_embedding_gpu_batch,
    retire_failed_ungranted_embedding_gpu_batch,
)
from eom_catalog_service.embedding_gpu_batch_observation import (
    CapturedEmbeddingGpuBatchMachine,
    EmbeddingGpuBatchReadyObservation,
    observe_embedding_gpu_batch_ready,
)
from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_native_cuda_process_status,
)
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_embedding_gpu_batch_terminal_metadata,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    require_unit_effect_phase_absent,
    reserve_unit_effect_phase,
    write_unit_effect_record,
)

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_ACTIVATOR = BenchmarkUnixPeer(1, 0, 0)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_CONTROLLER_INVALID")


class EmbeddingGpuBatchSourceOwner(Protocol):
    """Installed actual-actor owner, not a model-supplied role or default allow callback."""

    def admit_allocation(
        self, request: EmbeddingGpuAllocationRequest, ready: EmbeddingGpuBatchReadyObservation
    ) -> EmbeddingWorkBatchInput:
        """Atomically pin original allocation/route and reserve exact authorized child work."""
        ...

    def authorize_child(self, batch_request_sha256: str, child_request_sha256: str) -> None:
        """Reauthorize the original actual actor, sources, policy and immutable references."""
        ...


@dataclass(frozen=True, slots=True)
class CompletedEmbeddingGpuBatch:
    batch: EmbeddingWorkBatchInput
    grant: EmbeddingGpuComputeGrant
    result: EmbeddingWorkBatchResult
    child_vectors: tuple[memoryview, ...]
    retirement: EmbeddingGpuBatchRetirement


@dataclass(frozen=True, slots=True)
class UnavailableEmbeddingGpuBatch:
    """Root-observed precompute BUSY; source owner still selects/pins any CPU successor."""

    allocation: EmbeddingGpuAllocationBusy
    original_unit: CpuUnitObservation
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


def _unit(captured: CapturedEmbeddingGpuBatchMachine) -> str:
    return native_embedding_gpu_batch_unit(captured.prepared.launch.attempt_hex)


def _socket_effect(action: Literal["start", "stop"], unit: str) -> None:
    _require(
        os.getresuid() == (0, 0, 0)
        and type(action) is str
        and action in {"start", "stop"}
        and type(unit) is str
        and re.fullmatch(r"eom-embedding-native-gpu-batch@[0-9a-f]{32}\.service", unit) is not None
    )
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-ask-password",
            action,
            unit.removesuffix("service") + "socket",
        ),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    _require(result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384)


def _claim_dispatch(captured: CapturedEmbeddingGpuBatchMachine) -> None:
    """No-clobber intent before socket effects; never repair/restart an uncertain attempt."""
    captured.assert_precompute()
    fresh = inspect_cpu_unit(_unit(captured), template=GPU_BATCH_TEMPLATE)
    _require(
        fresh.fresh
        and fresh.fragment_path == "/etc/systemd/system/" + GPU_BATCH_TEMPLATE
        and not fresh.drop_in_paths
        and not fresh.status.need_daemon_reload
    )
    try:
        (captured.execution / "control.sock").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("EMBEDDING_GPU_BATCH_CONTROLLER_INVALID")
    with protected_cpu_handoff_directory(
        captured.execution,
        owner=fixed_owner_identity(),
        uid=0,
        gid=captured.owner_gid,
        mode=0o750,
    ) as directory:
        create_protected_cpu_handoff_member(
            directory,
            "controller-started.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_DISPATCH_INTENT",
                    "root_pid": captured.prepared.launch.root_pid,
                    "allocation_request_sha256": captured.prepared.request.message_sha256,
                }
            ),
            owner_gid=captured.owner_gid,
            mode=0o600,
        )


def _original_unit(unit: CpuUnitObservation, original: CpuUnitObservation) -> None:
    _require(
        unit.fragment_path == original.fragment_path == "/etc/systemd/system/" + GPU_BATCH_TEMPLATE
        and not unit.drop_in_paths
        and not unit.status.need_daemon_reload
        and unit.invocation_id == original.invocation_id
        and re.fullmatch(r"[0-9a-f]{32}", unit.invocation_id) is not None
        and unit.status.exec_main_started_monotonic == original.status.exec_main_started_monotonic
        and unit.status.exec_main_started_monotonic > 0
    )


def _wait_started(captured: CapturedEmbeddingGpuBatchMachine) -> CpuUnitObservation:
    while time.monotonic_ns() < captured.prepared.request.expires_monotonic_ns:
        observed = inspect_cpu_unit(_unit(captured), template=GPU_BATCH_TEMPLATE)
        if observed.main_pid > 0:
            _original_unit(observed, observed)
            _require(
                observed.status.active_state == "activating"
                and observed.status.sub_state == "start"
                and observed.exited_monotonic == 0
            )
            return observed
        # A process that failed before receiving ALLOCATION_REQUEST cannot establish BUSY.
        _require(not observed.status.process_started)
        time.sleep(0.05)
    raise TimeoutError("EMBEDDING_GPU_BATCH_START_UNCERTAIN")


def _wait_terminal(
    captured: CapturedEmbeddingGpuBatchMachine, original: CpuUnitObservation
) -> CpuUnitObservation:
    # Separate cleanup budget, not permission to extend numeric execution or replay it.
    deadline = min(
        captured.prepared.request.expires_monotonic_ns + 30 * 10**9,
        time.monotonic_ns() + 30 * 10**9,
    )
    while time.monotonic_ns() < deadline:
        observed = inspect_cpu_unit(_unit(captured), template=GPU_BATCH_TEMPLATE)
        _original_unit(observed, original)
        if observed.main_pid == 0:
            if observed.succeeded or observed.status.active_state == "failed":
                gpu_unit_terminal_outcome(observed)
                return observed
            # PID1 can briefly report the original process ended before terminal status settles.
            _require(observed.status.active_state in {"activating", "deactivating"})
        else:
            _require(observed.main_pid == original.main_pid)
        time.sleep(0.05)
    raise TimeoutError("EMBEDDING_GPU_BATCH_TERMINATION_UNCERTAIN")


class _WorkerFence:
    """Cheap live identity while computing; terminal tolerance only at protocol boundaries."""

    def __init__(self, captured: CapturedEmbeddingGpuBatchMachine, original: CpuUnitObservation):
        self.captured, self.original = captured, original
        self.phase: Literal["ALLOCATION", "ACTIVE", "TERMINATING"] = "ALLOCATION"
        self.start_ticks = self._live()

    def _live(self) -> int:
        process = Path("/proc") / str(self.original.main_pid)
        captured = self.captured
        raw = read_live_runtime_os_file(
            process / "stat", maximum=65536, owner_uid=captured.worker_uid
        )
        ticks = native_process_start_ticks(raw, self.original.main_pid)
        _require(
            read_live_runtime_os_file(
                process / "cgroup", maximum=4096, owner_uid=captured.worker_uid
            )
            == f"0::/system.slice/{_unit(captured)}\n".encode()
        )
        require_native_cuda_process_status(
            read_live_runtime_os_file(
                process / "status", maximum=128 * 1024, owner_uid=captured.worker_uid
            ),
            uid=captured.worker_uid,
            gid=captured.worker_gid,
            lease_gid=captured.lease_gid,
        )
        return ticks

    def __call__(self, peer: BenchmarkUnixPeer) -> None:
        _require(peer == _ACTIVATOR)
        if self.phase == "ACTIVE":
            _require(self._live() == self.start_ticks)
            return
        observed = inspect_cpu_unit(_unit(self.captured), template=GPU_BATCH_TEMPLATE)
        _original_unit(observed, self.original)
        if observed.main_pid == self.original.main_pid:
            try:
                _require(self._live() == self.start_ticks)
                return
            except (ValueError, OSError):
                # A fast BUSY writer may already be a zombie before PID1 clears
                # MainPID. This is not BUSY proof: wait for the exact original
                # terminal and independently check the claim below the transport.
                observed = _wait_terminal(self.captured, self.original)
        else:
            _require(observed.main_pid == 0)
            if self.phase == "TERMINATING":
                # Exact invocation/start identity is still fenced; the separate terminal
                # observer proves process/cgroup/GPU exit, not this post-ACK transport check.
                return
            observed = _wait_terminal(self.captured, self.original)
        pid, _ = observe_embedding_gpu_batch_terminal_metadata(
            _unit(self.captured), expected=observed
        )
        _require(pid == self.original.main_pid)


def _grant(
    captured: CapturedEmbeddingGpuBatchMachine,
    ready: EmbeddingGpuBatchReadyObservation,
    batch: EmbeddingWorkBatchInput,
) -> tuple[EmbeddingGpuComputeGrant, bytes]:
    raw = canonical_json_bytes(batch.model_dump(mode="json"))
    body = {
        "schema_version": "embedding-gpu-allocation-control/1.0",
        "message_type": "COMPUTE_GRANT",
        "allocation_attempt_id": captured.prepared.request.allocation_attempt_id,
        "allocation_request_sha256": captured.prepared.request.message_sha256,
        "ready_message_sha256": ready.readiness.message_sha256,
        "routing_decision_sha256": batch.routing_decision_sha256,
        "batch_input_raw_sha256": sha256_bytes(raw),
        "batch_request_sha256": batch.request_sha256,
        "batch_input_byte_count": len(raw),
    }
    grant = parse_embedding_gpu_control(body | {"message_sha256": content_sha256(body)})
    _require(type(grant) is EmbeddingGpuComputeGrant)
    assert isinstance(grant, EmbeddingGpuComputeGrant)
    validate_embedding_gpu_grant(captured.prepared.request, ready.readiness, grant)
    return grant, raw


def _materialize_result(
    captured: CapturedEmbeddingGpuBatchMachine,
    batch: EmbeddingWorkBatchInput,
    claim: EmbeddingGpuResultReady,
) -> tuple[EmbeddingWorkBatchResult, tuple[memoryview, ...]]:
    captured.assert_current()
    with protected_cpu_handoff_directory(
        captured.execution, owner=fixed_owner_identity(), uid=0, gid=captured.owner_gid, mode=0o750
    ) as directory:
        outputs = []
        for name, limit in (
            ("result.json", captured.prepared.launch.total_output_max_bytes),
            ("vectors.f32", batch.expected_vector_bytes),
        ):
            outputs.append(
                read_protected_cpu_handoff_member(
                    directory, name, uid=0, gid=captured.owner_gid, mode=0o640, maximum_bytes=limit
                )
            )
    raw, vectors = outputs
    _require(
        len(raw) == claim.result_byte_count
        and sha256_bytes(raw) == claim.result_raw_sha256
        and len(vectors) == claim.vectors_byte_count
        and sha256_bytes(vectors) == claim.vectors_sha256
        and len(raw) + len(vectors) <= captured.prepared.launch.total_output_max_bytes
    )
    value = parse_rootlocal_evidence_document(raw, captured.prepared.launch.total_output_max_bytes)
    _require(canonical_json_bytes(value) == raw)
    result = parse_embedding_work_batch_result(value)
    _require(result.result_sha256 == claim.result_sha256)
    ranges = validate_embedding_work_batch_binary(batch, result, vectors)
    captured.assert_current()
    return result, ranges


def _prove_busy(
    captured: CapturedEmbeddingGpuBatchMachine,
    fence: _WorkerFence,
    busy: EmbeddingGpuAllocationBusy,
) -> UnavailableEmbeddingGpuBatch:
    validate_embedding_gpu_allocation_link(captured.prepared.request, busy)
    _require(
        (busy.pid, busy.start_time_ticks, busy.worker_uid, busy.worker_gid)
        == (fence.original.main_pid, fence.start_ticks, captured.worker_uid, captured.worker_gid)
    )
    unit = _unit(captured)
    terminal = _wait_terminal(captured, fence.original)
    _require(gpu_unit_terminal_outcome(terminal) == "SUCCEEDED")
    _require(
        observe_embedding_gpu_batch_terminal_metadata(unit, expected=terminal) == (busy.pid, 0)
    )
    captured.assert_precompute()
    require_unit_effect_phase_absent(GPU_BATCH_LIFETIME_ROOT, unit, terminal.invocation_id, "ack")
    require_embedding_gpu_batch_cgroup_empty(unit)
    observe_runtime_device(captured.device)
    # An unrelated image/trainer GPU holder is allowed. Only this PID must not be a client.
    _require(busy.pid not in observe_cuda_probe_gpu_clients(captured.device))
    _require(inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE) == terminal)
    record = reserve_unit_effect_phase(
        GPU_BATCH_LIFETIME_ROOT, unit, terminal.invocation_id, "retirement"
    )
    try:
        write_unit_effect_record(
            record,
            "intent.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_BUSY_RETIREMENT_INTENT",
                    "allocation": busy.model_dump(mode="json"),
                    "invocation_id": terminal.invocation_id,
                    "started_monotonic": terminal.status.exec_main_started_monotonic,
                }
            ),
        )
        captured.assert_precompute()
        _require(inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE) == terminal)
        apply_embedding_gpu_batch_effect("STOP", unit)
        _socket_effect("stop", unit)
        stopped = observe_stopped_gpu_unit(
            unit, template=GPU_BATCH_TEMPLATE, invocation=terminal.invocation_id
        )
        _require(stopped.stored_descriptors == 0)
        require_embedding_gpu_batch_cgroup_empty(unit)
        captured.assert_precompute()
        _require(busy.pid not in observe_cuda_probe_gpu_clients(captured.device))
        write_unit_effect_record(
            record,
            "result.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_UNAVAILABLE_NOT_EXECUTED",
                    "allocation_message_sha256": busy.message_sha256,
                    "invocation_id": terminal.invocation_id,
                }
            ),
        )
        return UnavailableEmbeddingGpuBatch(
            busy, terminal, stopped, datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
    finally:
        os.close(record)


def run_embedding_gpu_batch(
    captured: CapturedEmbeddingGpuBatchMachine, *, source_owner: EmbeddingGpuBatchSourceOwner
) -> CompletedEmbeddingGpuBatch | UnavailableEmbeddingGpuBatch:
    """Consume one original attempt, never retry or turn unknown failure into CPU permission.

    Caller owns the captured installation lifetime. On uncertain startup/retirement the
    exclusive intent and original files remain for supported read-only reconciliation.
    No canonical Artifact is committed by this root numerical adapter.
    """
    _require(os.getresuid() == (0, 0, 0) and type(captured) is CapturedEmbeddingGpuBatchMachine)
    _require(callable(source_owner.admit_allocation) and callable(source_owner.authorize_child))
    _claim_dispatch(captured)
    _socket_effect("start", _unit(captured))
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
    channel: EmbeddingGpuControlChannel | None = None
    ready: EmbeddingGpuBatchReadyObservation | None = None
    retirement: EmbeddingGpuBatchRetirement | None = None
    retirement_started = False
    original: CpuUnitObservation | None = None
    try:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        connection.connect(str(captured.execution / "control.sock"))
        original = _wait_started(captured)
        fence = _WorkerFence(captured, original)
        channel = EmbeddingGpuControlChannel(
            connection,
            captured.prepared.request,
            side="ROOT",
            expected_peer=_ACTIVATOR,
            expected_sender=BenchmarkUnixPeer(
                original.main_pid, captured.worker_uid, captured.worker_gid
            ),
            peer_fence=fence,
        )
        channel.send_request()
        allocation = channel.receive_allocation()
        if isinstance(allocation, EmbeddingGpuAllocationBusy):
            channel.close()
            return _prove_busy(captured, fence, allocation)
        ready = observe_embedding_gpu_batch_ready(captured, allocation)
        _require(ready.unit == original and ready.readiness.start_time_ticks == fence.start_ticks)
        fence.phase = "ACTIVE"
        batch = parse_embedding_work_batch_input(
            source_owner.admit_allocation(captured.prepared.request, ready)
        )
        children = tuple(child.request.request_sha256 for child in batch.children)

        def authorize(child_sha256: str) -> None:
            check: Callable[[str, str], object] = source_owner.authorize_child
            _require(check(batch.request_sha256, child_sha256) is None)

        for child in children:
            authorize(child)
        captured.assert_precompute()
        grant, raw = _grant(captured, ready, batch)
        directory = reserve_unit_effect_phase(
            GPU_BATCH_LIFETIME_ROOT, _unit(captured), original.invocation_id, "ack"
        )
        try:
            write_unit_effect_record(directory, "intent.json", embedding_gpu_control_bytes(grant))
            bind_embedding_gpu_batch_handoff(captured.prepared, grant, batch)
            channel.send_grant(grant)
            channel.bind_batch(batch, input_raw_sha256=sha256_bytes(raw), input_byte_count=len(raw))
            write_unit_effect_record(
                directory,
                "result.json",
                canonical_json_bytes(
                    {
                        "event": "EMBEDDING_GPU_BATCH_GRANT_SENT_NOT_COMPLETED",
                        "grant_message_sha256": grant.message_sha256,
                    }
                ),
            )
        finally:
            os.close(directory)

        def authorize_check(check: EmbeddingGpuCheckChild) -> None:
            authorize(check.child_request_sha256)

        while (claim := channel.authorize_next(authorize_check)) is None:
            pass
        result, ranges = _materialize_result(captured, batch, claim)

        def verify(original_claim: EmbeddingGpuResultReady) -> None:
            _require(original_claim == claim)
            for child in children:
                authorize(child)
            captured.assert_current()
            # Worker may exit as soon as ACK arrives, including before send() returns.
            fence.phase = "TERMINATING"

        channel.acknowledge_result(verify)
        channel.close()
        _wait_terminal(captured, original)
        terminal = observe_embedding_gpu_batch_terminal(ready, captured)
        retirement_started = True
        retirement = retire_embedding_gpu_batch(terminal, captured)
        _socket_effect("stop", _unit(captured))
        _require(terminal.original_outcome == "SUCCEEDED")
        for child in children:
            authorize(child)
        return CompletedEmbeddingGpuBatch(batch, grant, result, ranges, retirement)
    except BaseException as error:
        # Closing the original channel makes the worker leave its finite scope. Never
        # resubmit work. A verified READY permits the existing exact-unit cleanup only.
        if channel is not None:
            channel.close()
        if ready is not None and not retirement_started:
            try:
                _wait_terminal(captured, ready.unit)
                terminal = observe_embedding_gpu_batch_terminal(ready, captured)
                retire_embedding_gpu_batch(terminal, captured)
                _socket_effect("stop", _unit(captured))
            except (ValueError, OSError, subprocess.SubprocessError):
                error.add_note("EMBEDDING_GPU_BATCH_RETIREMENT_RECONCILIATION_REQUIRED")
        elif retirement_started and retirement is None:
            error.add_note("EMBEDDING_GPU_BATCH_RETIREMENT_RECONCILIATION_REQUIRED")
        elif ready is None and original is not None:
            try:
                _wait_terminal(captured, original)
                retire_failed_ungranted_embedding_gpu_batch(captured, original=original)
                _socket_effect("stop", _unit(captured))
            except (ValueError, OSError, subprocess.SubprocessError):
                error.add_note("EMBEDDING_GPU_BATCH_RETIREMENT_RECONCILIATION_REQUIRED")
        raise
    finally:
        if channel is not None:
            channel.close()
        connection.close()
