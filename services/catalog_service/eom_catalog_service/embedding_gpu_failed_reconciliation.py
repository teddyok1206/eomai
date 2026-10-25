"""Recover one actual FAILED batch without fabricating lost historical READY evidence."""

from __future__ import annotations

import grp
import os
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationRequest,
    EmbeddingGpuComputeGrant,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
)
from eom_catalog_contracts.embedding_gpu_failed_retirement import FailedEmbeddingGpuRetirement
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    UngrantedEmbeddingGpuBatchResources,
    hold_released_terminal_embedding_gpu_batch_resources,
    observe_terminal_embedding_gpu_batch_resources,
)
from eom_catalog_service.embedding_gpu_batch_handoff import (
    validate_embedding_gpu_batch_reconciliation_pins,
)
from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_RUNTIME_ROOT,
    GPU_BATCH_SERVICE_SHA256,
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
    parse_native_embedding_gpu_batch_environment,
)
from eom_catalog_service.embedding_gpu_batch_lifetime import (
    GPU_BATCH_LIFETIME_ROOT,
    apply_embedding_gpu_batch_effect,
    require_embedding_gpu_batch_cgroup_empty,
)
from eom_catalog_service.embedding_gpu_batch_unit_descriptor import (
    embedding_gpu_batch_descriptor_bytes,
    embedding_gpu_batch_descriptor_path,
    inspect_embedding_gpu_batch_unit,
    require_embedding_gpu_batch_descriptor,
)
from eom_catalog_service.embedding_native_installation_admission import (
    read_pinned_cuda_admission_receipt,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.gpu_unit_policy_observation import observe_embedding_gpu_batch_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_embedding_gpu_batch_terminal_metadata,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    reserve_unit_effect_phase,
    write_unit_effect_record,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_FAILED_RECONCILIATION_INVALID")


@dataclass(frozen=True, slots=True)
class FailedEmbeddingGpuWitness:
    """Real current terminal facts, never reconstructed process birth/READY."""

    allocation: EmbeddingGpuAllocationRequest
    allocation_raw_sha256: str
    grant: EmbeddingGpuComputeGrant
    original_terminal: CpuUnitObservation
    terminal_pid: int
    stored_descriptors: Literal[0, 1]
    resources: UngrantedEmbeddingGpuBatchResources | None
    device: CudaRuntimeDeviceCapture
    effective_policy_sha256: str


def validate_failed_embedding_gpu_witness(
    witness: FailedEmbeddingGpuWitness, result: FailedEmbeddingGpuRetirement
) -> None:
    """Closed metadata linkage only; concrete reader separately checks protected OS bytes."""
    _require(type(witness) is FailedEmbeddingGpuWitness)
    allocation, terminal, grant = witness.allocation, witness.original_terminal, witness.grant
    _require(
        result.allocation_attempt_id == allocation.allocation_attempt_id
        and result.allocation_raw_sha256 == witness.allocation_raw_sha256
        and result.allocation_request_sha256 == allocation.message_sha256
        and result.invocation_id == terminal.invocation_id
        and result.original_outcome == gpu_unit_terminal_outcome(terminal) == "FAILED"
        and terminal.main_pid == 0
        and terminal.fragment_path == "/etc/systemd/system/" + GPU_BATCH_TEMPLATE
        and not terminal.status.need_daemon_reload
        and type(witness.terminal_pid) is int
        and 0 < witness.terminal_pid <= 2147483647
        and type(witness.stored_descriptors) is int
        and witness.stored_descriptors in (0, 1)
        and (witness.resources is not None) == (witness.stored_descriptors == 1)
        and grant.allocation_attempt_id == allocation.allocation_attempt_id
        and grant.allocation_request_sha256 == allocation.message_sha256
        and sha256_bytes(embedding_gpu_control_bytes(allocation)) == witness.allocation_raw_sha256
    )
    require_embedding_gpu_batch_descriptor(
        allocation.allocation_attempt_id.removeprefix("embeddingallocation_"),
        terminal.drop_in_paths,
    )
    if witness.resources is not None:
        _require(witness.resources.shared_gpu_lease.holder_pid == witness.terminal_pid)


def retire_failed_granted_embedding_gpu_batch(
    allocation: EmbeddingGpuAllocationRequest, *, invocation_id: str
) -> FailedEmbeddingGpuRetirement:
    """One root-only terminal cleanup, no numeric replay or CPU-fallback authorization.

    If an intent already exists, effects are never repeated. A completed result is
    consumed by the existing root reader; an incomplete phase requires diagnosis.
    Unrelated image/training work is neither stopped nor inspected for zero-store failures.
    """
    _require(os.getresuid() == (0, 0, 0))
    allocation = EmbeddingGpuAllocationRequest.model_validate(allocation)
    _require(
        type(invocation_id) is str
        and re.fullmatch(r"[0-9a-f]{32}", invocation_id, re.ASCII) is not None
    )
    _require(time.monotonic_ns() > allocation.expires_monotonic_ns)
    attempt = allocation.allocation_attempt_id.removeprefix("embeddingallocation_")
    unit = native_embedding_gpu_batch_unit(attempt)
    execution = GPU_BATCH_RUNTIME_ROOT / attempt
    files = NumericalRuntimeFileSnapshots()
    raw = embedding_gpu_control_bytes(allocation)
    files.read(execution / "allocation.json", sha256=sha256_bytes(raw), maximum=32768)
    launch = parse_native_embedding_gpu_batch_environment(
        files.observe_protected_member_bytes(execution / "launch.env", maximum=4096).raw,
        attempt_hex=attempt,
    )
    _require(validate_embedding_gpu_batch_reconciliation_pins(launch, allocation) == raw)
    files.read(
        Path("/etc/systemd/system") / GPU_BATCH_TEMPLATE,
        sha256=GPU_BATCH_SERVICE_SHA256,
        maximum=65536,
    )
    descriptor = embedding_gpu_batch_descriptor_bytes(attempt)
    files.read(
        embedding_gpu_batch_descriptor_path(attempt), sha256=sha256_bytes(descriptor), maximum=4096
    )
    lifetime = GPU_BATCH_LIFETIME_ROOT / unit / invocation_id
    grant_raw = files.observe_protected_member_bytes(
        lifetime / "ack/intent.json", maximum=32768
    ).raw
    grant = parse_embedding_gpu_control(parse_rootlocal_evidence_document(grant_raw, 32768))
    _require(type(grant) is EmbeddingGpuComputeGrant)
    assert isinstance(grant, EmbeddingGpuComputeGrant)
    _require(grant_raw == embedding_gpu_control_bytes(grant))
    files.read(execution / "input-grant.json", sha256=sha256_bytes(grant_raw), maximum=32768)
    sent = files.observe_protected_member_bytes(lifetime / "ack/result.json", maximum=4096).raw
    _require(
        sent
        == canonical_json_bytes(
            dict(
                event="EMBEDDING_GPU_BATCH_GRANT_SENT_NOT_COMPLETED",
                grant_message_sha256=grant.message_sha256,
            )
        )
    )
    receipt, _raw = read_pinned_cuda_admission_receipt(
        files, allocation.configuration, receipt_raw_sha256=allocation.receipt_raw_sha256
    )
    device = receipt.device_capture
    terminal = inspect_embedding_gpu_batch_unit(unit, template=GPU_BATCH_TEMPLATE)
    _require(
        terminal.invocation_id == invocation_id and gpu_unit_terminal_outcome(terminal) == "FAILED"
    )
    require_embedding_gpu_batch_descriptor(attempt, terminal.drop_in_paths)
    pid, store = observe_embedding_gpu_batch_terminal_metadata(unit, expected=terminal)
    policy = observe_embedding_gpu_batch_unit_policy(unit)
    lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
    resources = (
        None
        if store == 0
        else observe_terminal_embedding_gpu_batch_resources(
            unit=unit, terminal_pid=pid, lease_gid=lease_gid
        )
    )
    witness = FailedEmbeddingGpuWitness(
        allocation, sha256_bytes(raw), grant, terminal, pid, store, resources, device, policy
    )

    def physical() -> None:
        files.assert_unchanged()
        require_embedding_gpu_batch_cgroup_empty(unit)
        _require(observe_embedding_gpu_batch_unit_policy(unit) == policy)
        if resources is not None:
            observe_runtime_device(device)
            _require(observe_cuda_probe_gpu_clients(device) == ())

    def original() -> None:
        physical()
        _require(inspect_embedding_gpu_batch_unit(unit, template=GPU_BATCH_TEMPLATE) == terminal)
        _require(
            observe_embedding_gpu_batch_terminal_metadata(unit, expected=terminal) == (pid, store)
        )
        if resources is not None:
            _require(
                observe_terminal_embedding_gpu_batch_resources(
                    unit=unit, terminal_pid=pid, lease_gid=lease_gid
                )
                == resources
            )

    intent = canonical_json_bytes(
        dict(
            event="EMBEDDING_GPU_BATCH_FAILED_RECOVERY_INTENT",
            observation=TypeAdapter(FailedEmbeddingGpuWitness).dump_python(witness, mode="json"),
        )
    )
    draft = FailedEmbeddingGpuRetirement.model_validate(
        dict(
            schema_version="embedding-gpu-failed-retirement/1.0",
            event="EMBEDDING_GPU_BATCH_FAILED_RETIRED_NOT_PUBLISHED",
            allocation_attempt_id=allocation.allocation_attempt_id,
            allocation_raw_sha256=witness.allocation_raw_sha256,
            allocation_request_sha256=allocation.message_sha256,
            invocation_id=invocation_id,
            intent_sha256=sha256_bytes(intent),
            original_outcome="FAILED",
            stored_descriptors=0,
            observed_at=datetime.now(UTC).isoformat(),
        )
    )
    validate_failed_embedding_gpu_witness(witness, draft)
    original()
    directory = reserve_unit_effect_phase(
        GPU_BATCH_LIFETIME_ROOT, unit, invocation_id, "retirement"
    )
    try:
        write_unit_effect_record(directory, "intent.json", intent)
        original()
        apply_embedding_gpu_batch_effect("RESET_FAILED", unit)

        def stopped() -> StoppedGpuUnit:
            physical()
            return observe_stopped_gpu_unit(
                unit, template=GPU_BATCH_TEMPLATE, invocation=invocation_id
            )

        after = stopped()
        _require(store == 1 or after.stored_descriptors == 0)
        if after.stored_descriptors == 1:
            _require(resources is not None)
            _require(
                observe_terminal_embedding_gpu_batch_resources(
                    unit=unit, terminal_pid=pid, lease_gid=lease_gid
                )
                == resources
            )
            _require(stopped() == after)
            apply_embedding_gpu_batch_effect("CLEAN_FDSTORE", unit)
        scope = (
            nullcontext()
            if resources is None
            else hold_released_terminal_embedding_gpu_batch_resources(resources, unit=unit)
        )
        with scope:
            final = stopped()
            _require(final.stored_descriptors == 0 and stopped() == final)
            result = FailedEmbeddingGpuRetirement.model_validate(
                draft.model_dump(mode="json") | {"observed_at": datetime.now(UTC).isoformat()}
            )
            write_unit_effect_record(directory, "result.json", canonical_json_bytes(result))
        return result
    finally:
        os.close(directory)
