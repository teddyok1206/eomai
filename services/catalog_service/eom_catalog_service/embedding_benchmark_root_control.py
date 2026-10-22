"""Concrete original-launch root bridge; local machine effects only, never SQL/NAS."""

from __future__ import annotations

import pwd
import socket
from dataclasses import dataclass

from eom_identifiers import content_sha256
from eom_orchestrator.inference_transfer_cpu_handoff import (
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    BenchmarkLaunchUncertain,
    benchmark_launch_control_bytes,
    validate_benchmark_launch_association,
)

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_benchmark_cpu_driver import FixedRootBenchmarkCpuDriver
from eom_catalog_service.embedding_benchmark_cuda_driver import FixedRootBenchmarkCudaDriver
from eom_catalog_service.embedding_benchmark_handoff import (
    benchmark_owner_start_ticks,
    prepare_benchmark_environment,
    prepare_benchmark_handoff,
)
from eom_catalog_service.embedding_benchmark_launch_workspace import StagedOwnerBenchmarkLaunch
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_unit_control import require_root_benchmark_control
from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory


@dataclass(frozen=True, slots=True)
class RootBenchmarkCudaRuntime:
    """Already captured installed machine resources, neither model nor source permission."""

    inventory: PrefixRuntimeInventory
    host: ProtectedCudaEmbeddingHostClosure


def _persist_root_control(execution_id: str, name: str, raw: bytes) -> None:
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        BENCHMARK_HANDOFF_ROOT / execution_id,
        owner=owner,
        uid=0,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        create_protected_cpu_handoff_member(
            directory, name, raw, owner_gid=owner.owner_gid, mode=0o640
        )


def serve_root_benchmark_launch(
    connection: socket.socket,
    staged: StagedOwnerBenchmarkLaunch,
    *,
    selected_request_sha256: str,
    backend: NativeEmbeddingBackendPins,
    controller_release: str,
    cuda: RootBenchmarkCudaRuntime | None = None,
) -> BenchmarkLaunchCompleted:
    """Existing known-stage entry; receive its association then share one lifecycle."""
    channel = None
    try:
        peer = _validated_launch_peer(
            staged, selected_request_sha256=selected_request_sha256, backend=backend, cuda=cuda
        )
        association = staged.association

        def fence(actual: BenchmarkUnixPeer) -> None:
            require_root_benchmark_control()
            if (
                actual != peer
                or benchmark_owner_start_ticks(actual.pid, uid=actual.uid, gid=actual.gid)
                != association.owner_start_ticks
            ):
                raise ValueError("BENCHMARK_ROOT_OWNER_CHANGED")

        channel = BenchmarkLaunchControlChannel(
            connection,
            association,
            side="ROOT",
            expected_peer=peer,
            peer_fence=fence,
            controller_release=controller_release,
            policy=staged.request.execution_policy,
        )
        channel.receive_association()
        return serve_associated_root_benchmark_launch(
            channel,
            staged,
            selected_request_sha256=selected_request_sha256,
            backend=backend,
            controller_release=controller_release,
            cuda=cuda,
        )
    except BaseException:
        if channel is not None:
            channel.close()
        connection.close()
        raise


def _validated_launch_peer(
    staged: StagedOwnerBenchmarkLaunch,
    *,
    selected_request_sha256: str,
    backend: NativeEmbeddingBackendPins,
    cuda: RootBenchmarkCudaRuntime | None,
) -> BenchmarkUnixPeer:
    require_root_benchmark_control()
    association, invocation = staged.association, staged.invocation
    validate_benchmark_launch_association(association, staged.request, invocation, staged.inputs)
    if type(backend) is not NativeEmbeddingBackendPins:
        raise ValueError("BENCHMARK_ROOT_BACKEND_INVALID")
    backend.__post_init__()
    if (
        selected_request_sha256 != staged.request.request_sha256
        or association.owner_request_sha256 != selected_request_sha256
    ):
        raise ValueError("BENCHMARK_ROOT_SELECTION_MISMATCH")
    if invocation.device == "CUDA" and type(cuda) is not RootBenchmarkCudaRuntime:
        raise ValueError("BENCHMARK_ROOT_CUDA_CAPTURE_REQUIRED")
    account = pwd.getpwnam("eom-workflow-runner")
    return BenchmarkUnixPeer(association.owner_pid, account.pw_uid, account.pw_gid)


def serve_associated_root_benchmark_launch(
    channel: BenchmarkLaunchControlChannel,
    staged: StagedOwnerBenchmarkLaunch,
    *,
    selected_request_sha256: str,
    backend: NativeEmbeddingBackendPins,
    controller_release: str,
    cuda: RootBenchmarkCudaRuntime | None = None,
) -> BenchmarkLaunchCompleted:
    """One validated original association; the sole root prepare/driver/cleanup path.

    Receiving a frame grants no source or compute permission. Actual Orchestrator
    identity/Source/Job admission and publication stay on the owner side.
    """
    if type(channel) is not BenchmarkLaunchControlChannel:
        raise ValueError("BENCHMARK_ROOT_CHANNEL_INVALID")
    before = None
    handoff_created = False
    association = None
    try:
        peer = _validated_launch_peer(
            staged, selected_request_sha256=selected_request_sha256, backend=backend, cuda=cuda
        )
        invocation = staged.invocation
        channel.require_root_association(
            staged.association,
            expected_peer=peer,
            controller_release=controller_release,
        )
        association = staged.association
        local = prepare_benchmark_handoff(staged.request, invocation, staged.inputs)
        handoff_created = True
        environment = prepare_benchmark_environment(
            local,
            invocation,
            backend=backend,
            owner_pid=association.owner_pid,
            expires_ns=association.expires_ns,
        )
        if environment.owner_start_ticks != association.owner_start_ticks:
            raise ValueError("BENCHMARK_ROOT_OWNER_CHANGED")
        body: dict[str, object] = dict(
            schema_version="embedding-benchmark-launch-control/1.0",
            record_type="PREPARED",
            association_sha256=association.association_sha256,
            job_id=invocation.job_id,
            execution_id=invocation.execution_id,
            invocation_sha256=invocation.invocation_sha256,
            environment_raw_sha256=environment.environment_raw_sha256,
            controller_release=controller_release,
            backend=dict(
                configuration_id=backend.configuration_id,
                configuration_revision_id=backend.configuration_revision_id,
                configuration_sha256=backend.configuration_sha256,
                configuration_raw_sha256=backend.configuration_raw_sha256,
                receipt_raw_sha256=backend.receipt_raw_sha256,
            ),
        )
        before = BenchmarkLaunchPrepared.model_validate(
            body | {"prepared_sha256": content_sha256(body)}
        )
        _persist_root_control(
            invocation.execution_id, "root-prepared.json", benchmark_launch_control_bytes(before)
        )
        channel.send_prepared(before)
        resources = None
        if invocation.device == "CPU":
            result = FixedRootBenchmarkCpuDriver(invocation, environment, backend=backend).run()
            observed = (
                result.execution_id,
                result.job_id,
                result.invocation_sha256,
                result.started_ns,
                result.completed_ns,
                result.outcome,
            )
        else:
            assert cuda is not None
            with channel.resources() as duplicate:
                cuda_result = FixedRootBenchmarkCudaDriver(
                    duplicate,
                    invocation,
                    environment,
                    backend=backend,
                    inventory=cuda.inventory,
                    host=cuda.host,
                ).run()
                resources = cuda_result.resources
                observed = (
                    cuda_result.execution_id,
                    cuda_result.job_id,
                    cuda_result.invocation_sha256,
                    cuda_result.started_ns,
                    cuda_result.completed_ns,
                    cuda_result.outcome,
                )
        if observed[:3] != (
            invocation.execution_id,
            invocation.job_id,
            invocation.invocation_sha256,
        ):
            raise ValueError("BENCHMARK_ROOT_ORIGINAL_EXECUTION_MISMATCH")
        body = dict(
            schema_version="embedding-benchmark-launch-control/1.0",
            record_type="COMPLETED",
            association_sha256=association.association_sha256,
            prepared_sha256=before.prepared_sha256,
            job_id=invocation.job_id,
            execution_id=invocation.execution_id,
            invocation_sha256=invocation.invocation_sha256,
            device=invocation.device,
            launch_ordinal=invocation.launch_ordinal,
            original_outcome=observed[5],
            cleanup="CONFIRMED",
            started_ns=observed[3],
            completed_ns=observed[4],
            resources=resources.model_dump(mode="json") if resources is not None else None,
        )
        completed = BenchmarkLaunchCompleted.model_validate(
            body | {"completion_sha256": content_sha256(body)}
        )
        # Preserve actual machine cleanup even if a later peer/session has ended.
        _persist_root_control(
            invocation.execution_id,
            "root-completion.json",
            benchmark_launch_control_bytes(completed),
        )
        channel.send_completed(completed)
        channel.wait_for_owner_close()
        return completed
    except Exception:
        if association is not None:
            body = dict(
                schema_version="embedding-benchmark-launch-control/1.0",
                record_type="UNCERTAIN",
                association_sha256=association.association_sha256,
                job_id=association.job_id,
                execution_id=association.execution_id,
                invocation_sha256=association.invocation_sha256,
                code="BENCHMARK_ROOT_EXECUTION_UNCERTAIN",
            )
            uncertain = BenchmarkLaunchUncertain.model_validate(
                body | {"uncertainty_sha256": content_sha256(body)}
            )
            if handoff_created:
                _persist_root_control(
                    association.execution_id,
                    "root-uncertain.json",
                    benchmark_launch_control_bytes(uncertain),
                )
            if before is None:
                channel.send_uncertain(uncertain)
        raise
    finally:
        channel.close()
