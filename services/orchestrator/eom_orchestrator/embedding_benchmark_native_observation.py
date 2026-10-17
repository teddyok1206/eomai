"""Observe one fixed native program through actual owner authorization and local vectors."""

from __future__ import annotations

import os
import pwd
import time
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkCheckpoint,
    BenchmarkLocalVector,
    BenchmarkQueryTiming,
    BenchmarkResourceEvidence,
    BenchmarkSession,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    benchmark_checkpoint_count,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_service.embedding_benchmark_channel import BenchmarkOwnerChannel
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_ranking import rank_benchmark_rows
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

from eom_orchestrator.embedding_benchmark_gpu_resource_client import OwnerBenchmarkGpuResourceClient
from eom_orchestrator.embedding_benchmark_native_connection import CapturedBenchmarkNativeConnection
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)


@dataclass(frozen=True, slots=True)
class ObservedBenchmarkNativeSession:
    session: BenchmarkSession
    resources: BenchmarkResourceEvidence
    cold_completed_ns: int
    queries: tuple[BenchmarkQueryTiming, ...]


def read_benchmark_ready_vectors(
    invocation: BenchmarkWorkerInvocation,
    vector: BenchmarkLocalVector,
) -> tuple[tuple[float, ...], ...]:
    """Explicit small native-result validation boundary; no source/launch/publication grant."""
    owner = fixed_owner_identity()
    if os.getresuid() != (owner.owner_uid,) * 3 or os.getresgid() != (owner.owner_gid,) * 3:
        raise ValueError("BENCHMARK_NATIVE_OWNER_REQUIRED")
    # No caller-supplied path: all names/purpose/space/size are closed typed values.
    embedding_device_benchmark_bytes(invocation)
    vector = BenchmarkLocalVector.model_validate(vector)
    expected_space = (
        invocation.runtime.spaces.document
        if vector.purpose == "DOCUMENT"
        else invocation.runtime.spaces.query
    )
    if vector.space_sha256 != expected_space.space_sha256:
        raise ValueError("BENCHMARK_NATIVE_VECTOR_SPACE_INVALID")
    native = pwd.getpwnam(fixed_native_embedding_profile(invocation.runtime.profile).worker_user)
    with protected_cpu_handoff_directory(
        BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "outputs",
        owner=owner,
        uid=0,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        raw = read_protected_cpu_handoff_member(
            directory,
            vector.member_name,
            uid=native.pw_uid,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=vector.byte_count,
        )
    return read_unit_vectors(
        raw, dimension=1024, row_count=vector.row_count, expected_sha256=vector.sha256
    )


def observe_benchmark_native_session(
    transport: CapturedBenchmarkNativeConnection,
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
    *,
    authorization: BenchmarkLaunchAuthorization,
    expires_ns: int,
    gpu_resources: OwnerBenchmarkGpuResourceClient | None = None,
) -> ObservedBenchmarkNativeSession:
    """One sequence, actual short Source/Job roots and actual query clocks; never model replay.

    The installed caller owns actual unit/listener/PID-birth capture and the root
    resource context. Data ranked here is validated local f32, not invented scores.
    The cold matrix is materialized once and reused for ten bounded exact queries.
    """
    channel = None
    try:
        owner = fixed_owner_identity()
        if (
            os.getresuid() != (owner.owner_uid,) * 3
            or os.getresgid() != (owner.owner_gid,) * 3
            or type(authorization) is not BenchmarkLaunchAuthorization
            or type(transport) is not CapturedBenchmarkNativeConnection
        ):
            raise ValueError("BENCHMARK_NATIVE_OWNER_REQUIRED")
        if (
            invocation.device == "CUDA"
            and type(gpu_resources) is not OwnerBenchmarkGpuResourceClient
        ) or (invocation.device == "CPU" and gpu_resources is not None):
            raise ValueError("BENCHMARK_NATIVE_RESOURCE_CAPTURE_REQUIRED")
        authorization.assert_invocation(invocation)
        authorization_ns: dict[tuple[int, int], int] = {}

        def continuation(checkpoint: BenchmarkCheckpoint) -> None:
            started = time.monotonic_ns()
            authorization.authorize_checkpoint(checkpoint)
            elapsed = time.monotonic_ns() - started
            if checkpoint.query_ordinal is not None and checkpoint.query_repetition is not None:
                key = checkpoint.query_ordinal, checkpoint.query_repetition
                authorization_ns[key] = authorization_ns.get(key, 0) + elapsed

        channel = BenchmarkOwnerChannel.from_activated_listener(
            transport.connection,
            invocation,
            expected_listener=transport.listener,
            expected_sender=transport.sender,
            peer_fence=transport.peer_fence,
            continuation_fence=continuation,
            expires_ns=expires_ns,
        )
        cold = None
        cold_completed_ns = 0
        query_started: dict[tuple[int, int], int] = {}
        timings = []
        for _ in range(benchmark_checkpoint_count(invocation)):
            checkpoint = channel.receive_checkpoint()
            if checkpoint.phase == "QUERY_PREPARED":
                assert (
                    checkpoint.query_ordinal is not None and checkpoint.query_repetition is not None
                )
                query_started[(checkpoint.query_ordinal, checkpoint.query_repetition)] = (
                    time.monotonic_ns()
                )
            else:
                assert checkpoint.vector is not None
                rows = read_benchmark_ready_vectors(invocation, checkpoint.vector)
                if checkpoint.phase == "COLD_READY":
                    if len(rows) != len(inputs.documents):
                        raise ValueError("BENCHMARK_NATIVE_DOCUMENT_ROWS_INVALID")
                    cold = tuple(
                        (row.row, vector)
                        for row, vector in zip(inputs.documents, rows, strict=True)
                    )
                else:
                    assert (
                        checkpoint.query_ordinal is not None
                        and checkpoint.query_repetition is not None
                    )
                    if cold is None or len(rows) != 1:
                        raise ValueError("BENCHMARK_NATIVE_QUERY_ROWS_INVALID")
                    rank_benchmark_rows(
                        inputs.queries[checkpoint.query_ordinal - 1].row, rows[0], cold
                    )
            channel.acknowledge()
            if checkpoint.phase == "COLD_READY":
                cold_completed_ns = time.monotonic_ns()
            elif checkpoint.phase == "QUERY_READY":
                assert (
                    checkpoint.query_ordinal is not None and checkpoint.query_repetition is not None
                )
                key = checkpoint.query_ordinal, checkpoint.query_repetition
                if key not in query_started or checkpoint.encode_duration_ns is None:
                    raise ValueError("BENCHMARK_NATIVE_QUERY_TIMING_INVALID")
                timings.append(
                    BenchmarkQueryTiming(
                        query_ordinal=key[0],
                        repetition=key[1],
                        authorization_ns=authorization_ns[key],
                        encode_ns=checkpoint.encode_duration_ns,
                        end_to_end_ns=time.monotonic_ns() - query_started[key],
                    )
                )
        authorization.assert_invocation(invocation)

        def finalize(local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
            authorization.assert_invocation(invocation)
            result = local if gpu_resources is None else gpu_resources.finalize(local)
            authorization.assert_invocation(invocation)
            transport.allow_writer_exit_after_resources()
            return result

        resources = channel.finalize_resources(finalizer=finalize)
        return ObservedBenchmarkNativeSession(
            channel.transcript(), resources, cold_completed_ns, tuple(timings)
        )
    finally:
        if channel is not None:
            channel.close()
        else:
            transport.close()
        if gpu_resources is not None:
            gpu_resources.close()
