"""One owner-local benchmark materialization; no Job allocation, unit or NAS effects.

Concrete owner adapter; state/Artifact commit remain Orchestrator responsibilities.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    MAX_BENCHMARK_STAGED_BYTES,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import (
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)
from eom_workflow.embedding_benchmark_launch_control import (
    MAX_LAUNCH_CONTROL_BYTES,
    BenchmarkLaunchAssociation,
    benchmark_launch_control_bytes,
    parse_benchmark_launch_control_bytes,
    validate_benchmark_launch_association,
)

from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks

BENCHMARK_OWNER_ROOT = Path("/var/lib/eom-workflow-runner/embedding-benchmarks")


@dataclass(frozen=True, slots=True)
class StagedOwnerBenchmarkLaunch:
    association: BenchmarkLaunchAssociation
    request: BenchmarkOwnerRequest
    invocation: BenchmarkWorkerInvocation
    inputs: BenchmarkStagedInputs


def stage_owner_benchmark_launch(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
    *,
    authorization: BenchmarkLaunchAuthorization,
    expires_ns: int,
) -> StagedOwnerBenchmarkLaunch:
    owner = fixed_owner_identity()
    if (
        os.getresuid() != (owner.owner_uid,) * 3
        or os.getresgid() != (owner.owner_gid,) * 3
        or type(authorization) is not BenchmarkLaunchAuthorization
    ):
        raise ValueError("BENCHMARK_OWNER_STAGE_IDENTITY_INVALID")
    authorization.assert_invocation(invocation)
    now = time.monotonic_ns()
    if type(expires_ns) is not int or not now < expires_ns <= now + 180 * 10**9:
        raise ValueError("BENCHMARK_OWNER_STAGE_DEADLINE_INVALID")
    owner_start_ticks = benchmark_owner_start_ticks(
        os.getpid(), uid=owner.owner_uid, gid=owner.owner_gid
    )
    validate_benchmark_invocation(request, invocation, inputs)
    raw_request, raw_invocation, raw_inputs = (
        embedding_device_benchmark_bytes(value) for value in (request, invocation, inputs)
    )
    body = {
        "schema_version": "embedding-benchmark-launch-control/1.0",
        "record_type": "ASSOCIATION",
        "job_id": invocation.job_id,
        "execution_id": invocation.execution_id,
        "device": invocation.device,
        "launch_ordinal": invocation.launch_ordinal,
        "invocation_sha256": invocation.invocation_sha256,
        "owner_request_sha256": request.request_sha256,
        "request": {
            "member_name": "owner-request.json",
            "sha256": sha256_bytes(raw_request),
            "byte_count": len(raw_request),
        },
        "invocation": {
            "member_name": "invocation.json",
            "sha256": sha256_bytes(raw_invocation),
            "byte_count": len(raw_invocation),
        },
        "inputs": {
            "member_name": "benchmark-inputs.json",
            "sha256": sha256_bytes(raw_inputs),
            "byte_count": len(raw_inputs),
        },
        "owner_pid": os.getpid(),
        "owner_start_ticks": owner_start_ticks,
        "expires_ns": expires_ns,
    }
    association = BenchmarkLaunchAssociation.model_validate(
        body | {"association_sha256": content_sha256(body)}
    )
    raw_association = benchmark_launch_control_bytes(association)
    workspace = ensure_protected_cpu_owner_workspace(
        BENCHMARK_OWNER_ROOT, invocation.execution_id, owner=owner
    )
    with protected_cpu_handoff_directory(
        workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        try:
            os.mkdir("inputs", 0o700, dir_fd=directory)
            os.fsync(directory)
        except FileExistsError:
            pass
    with protected_cpu_handoff_directory(
        workspace / "inputs", owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        for name, payload in (
            ("owner-request.json", raw_request),
            ("invocation.json", raw_invocation),
            ("benchmark-inputs.json", raw_inputs),
            ("association.json", raw_association),
        ):
            write_protected_cpu_owner_member(directory, name, payload, owner=owner)
        authorization.assert_invocation(invocation)
    return StagedOwnerBenchmarkLaunch(association, request, invocation, inputs)


def read_owner_benchmark_launch(
    execution_id: str,
    *,
    expected: BenchmarkLaunchAssociation | None = None,
) -> StagedOwnerBenchmarkLaunch:
    """Root/actual owner read exact staged bytes, never model-supplied filesystem paths."""
    owner = fixed_owner_identity()
    if os.geteuid() not in (0, owner.owner_uid):
        raise ValueError("BENCHMARK_OWNER_STAGE_IDENTITY_INVALID")
    # The existing validator checks this exact instance before constructing a path.
    if (
        type(execution_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", execution_id, re.ASCII) is None
    ):
        raise ValueError("BENCHMARK_OWNER_STAGE_IDENTITY_INVALID")
    with protected_cpu_handoff_directory(
        BENCHMARK_OWNER_ROOT / execution_id / "inputs",
        owner=owner,
        uid=owner.owner_uid,
        gid=owner.owner_gid,
        mode=0o700,
    ) as directory:
        if set(os.listdir(directory)) != {
            "association.json",
            "owner-request.json",
            "invocation.json",
            "benchmark-inputs.json",
        }:
            raise ValueError("BENCHMARK_OWNER_STAGE_MEMBERS_INVALID")

        def read(name: str, maximum: int) -> bytes:
            return read_protected_cpu_handoff_member(
                directory,
                name,
                uid=owner.owner_uid,
                gid=owner.owner_gid,
                mode=0o600,
                maximum_bytes=maximum,
            )

        association = parse_benchmark_launch_control_bytes(
            read("association.json", MAX_LAUNCH_CONTROL_BYTES)
        )
        if (
            not isinstance(association, BenchmarkLaunchAssociation)
            or association.execution_id != execution_id
            or (expected is not None and association != expected)
        ):
            raise ValueError("BENCHMARK_OWNER_STAGE_ASSOCIATION_INVALID")
        values = []
        for descriptor in (association.request, association.invocation, association.inputs):
            raw = read(descriptor.member_name, descriptor.byte_count)
            if len(raw) != descriptor.byte_count or sha256_bytes(raw) != descriptor.sha256:
                raise ValueError("BENCHMARK_OWNER_STAGE_HASH_INVALID")
            # The descriptor pins the exact size, but cannot select a parser budget.
            # Existing parsers accept only their released fixed caller budgets.
            maximum = (
                MAX_BENCHMARK_STAGED_BYTES
                if descriptor.member_name == "benchmark-inputs.json"
                else MAX_BENCHMARK_ENVELOPE_BYTES
            )
            value = parse_embedding_device_benchmark_bytes(raw, maximum_bytes=maximum)
            if embedding_device_benchmark_bytes(value) != raw:
                raise ValueError("BENCHMARK_OWNER_STAGE_CANONICAL_INVALID")
            values.append(value)
    request, invocation, inputs = values
    if (
        not isinstance(request, BenchmarkOwnerRequest)
        or not isinstance(invocation, BenchmarkWorkerInvocation)
        or not isinstance(inputs, BenchmarkStagedInputs)
    ):
        raise ValueError("BENCHMARK_OWNER_STAGE_TYPE_INVALID")
    validate_benchmark_launch_association(association, request, invocation, inputs)
    return StagedOwnerBenchmarkLaunch(association, request, invocation, inputs)
