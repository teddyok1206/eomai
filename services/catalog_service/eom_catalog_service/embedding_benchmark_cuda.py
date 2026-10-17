"""Fixed CUDA benchmark leaf; root ACK and genuine ownership precede every model scope."""

from __future__ import annotations

import os
import pwd
import signal
import sys
import time
from typing import TYPE_CHECKING

from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_socket_activation,
    parse_benchmark_launch_pins,
)
from eom_catalog_service.embedding_native_entrypoint import (
    discard_native_embedding_diagnostics,
    require_native_embedding_identity,
)

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
    from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture


def _wait_root_ack(expires_ns: int) -> None:
    now = time.monotonic_ns()
    deadline = min(expires_ns, now + 30 * 10**9)
    if now >= deadline:
        raise ValueError("BENCHMARK_CUDA_ACK_EXPIRED")
    if signal.SIGUSR1 not in signal.pthread_sigmask(signal.SIG_BLOCK, set()):
        raise ValueError("BENCHMARK_CUDA_ACK_NOT_RESERVED")
    received = None
    # Blocking sigtimedwait hides the reserved SigBlk bit from the root observer.
    # Match the existing retained GPU lease boundary: consume without kernel sleep.
    while time.monotonic_ns() < deadline:
        received = signal.sigtimedwait({signal.SIGUSR1}, 0)
        if received is not None:
            break
        time.sleep(min(0.05, max(0.0, (deadline - time.monotonic_ns()) / 10**9)))
    if (
        received is None
        or received.si_signo != signal.SIGUSR1
        or type(received.si_uid) is not int
        or received.si_uid != 0
        or type(received.si_pid) is not int
        or received.si_pid <= 0
        or time.monotonic_ns() >= deadline
    ):
        raise ValueError("BENCHMARK_CUDA_ROOT_ACK_REQUIRED")


def _expected_device(invocation: BenchmarkWorkerInvocation) -> CudaRuntimeDeviceCapture:
    """Read pinned proof metadata only; this is not whole installation/device admission."""
    from pathlib import Path

    from eom_catalog_contracts.embedding_installed_runtime_proof import (
        MAX_INSTALLED_RUNTIME_PROOF_BYTES,
        CudaRuntimeDeviceCapture,
        parse_installed_runtime_proof,
        validate_installed_runtime_proof_pointer,
    )
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        parse_rootlocal_evidence_document,
    )

    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    pointer = invocation.runtime.installed_proof
    files = NumericalRuntimeFileSnapshots(0)
    raw = files.read(
        Path("/opt/eom/embedding-runtime-proofs")
        / pointer.proof_id
        / pointer.proof_revision_id
        / "proof.json",
        sha256=pointer.proof_raw_sha256,
        maximum=MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    )
    document = parse_rootlocal_evidence_document(raw, MAX_INSTALLED_RUNTIME_PROOF_BYTES)
    if not isinstance(document, dict):
        raise ValueError("BENCHMARK_CUDA_PROOF_INVALID")
    proof = parse_installed_runtime_proof(document)
    validate_installed_runtime_proof_pointer(proof, pointer, raw)
    if (
        proof.profile != "CUDA_INDEX_FP32"
        or not isinstance(proof.device_capture, CudaRuntimeDeviceCapture)
        or proof.device_capture.numeric_device != invocation.runtime.numerical_runtime.device
    ):
        raise ValueError("BENCHMARK_CUDA_DEVICE_INVALID")
    files.assert_unchanged()
    return proof.device_capture


def _run(pins: BenchmarkLaunchPins, started_ns: int) -> int:
    from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
        BenchmarkCudaReady,
        validate_benchmark_cuda_ready,
    )
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeConfigurationPin,
    )
    from eom_gpu_lease import acquire_shared_gpu_lease, request_unit_gpu_lease_retention
    from eom_identifiers import content_sha256

    from eom_catalog_service.embedding_benchmark_activation import capture_benchmark_worker_channel
    from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
    from eom_catalog_service.embedding_benchmark_entrypoint import run_native_embedding_benchmark
    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        capture_cuda_probe_resource_files,
        open_cuda_probe_device_access,
    )
    from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
    from eom_catalog_service.embedding_native_cuda_backend import native_cuda_backend_scope

    owner = pwd.getpwnam("eom-workflow-runner")
    if owner.pw_uid <= 0 or owner.pw_gid <= 0:
        raise ValueError("BENCHMARK_CUDA_OWNER_INVALID")
    peer = BenchmarkUnixPeer(pins.owner_pid, owner.pw_uid, owner.pw_gid)
    configuration = RootLocalNativeConfigurationPin(
        configuration_id=pins.backend.configuration_id,
        configuration_revision_id=pins.backend.configuration_revision_id,
        configuration_sha256=pins.backend.configuration_sha256,
        configuration_raw_sha256=pins.backend.configuration_raw_sha256,
    )
    with BenchmarkWorkerLocalFiles(
        0,
        profile="CUDA_INDEX_FP32",
        execution_id=pins.execution_id,
        invocation_raw_sha256=pins.invocation_raw_sha256,
    ) as files:
        invocation = files.read_invocation()
        device = _expected_device(invocation)
        # No CUDA/model/tokenizer import may precede retained physical ownership + root ACK.
        lease = acquire_shared_gpu_lease()
        try:
            with capture_cuda_probe_resource_files(device, lease) as resources:
                request_unit_gpu_lease_retention(lease)
                resources.assert_current()
                metadata = resources.shared_gpu_lease
                body = {
                    "schema_version": "embedding-benchmark-cuda-ready/1.0",
                    "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
                    "execution_id": invocation.execution_id,
                    "job_id": invocation.job_id,
                    "invocation_raw_sha256": pins.invocation_raw_sha256,
                    "configuration": configuration.model_dump(mode="json"),
                    "receipt_raw_sha256": pins.backend.receipt_raw_sha256,
                    "fdstore_name": "eom-gpu0-lease",
                    "pid": metadata.holder_pid,
                    "start_time_ticks": metadata.holder_start_time_ticks,
                    "worker_uid": os.geteuid(),
                    "worker_gid": os.getegid(),
                    "supplementary_gids": sorted(set(os.getgroups()) - {os.getegid()}),
                    "resource_fds": resources.resource_descriptors.model_dump(mode="json"),
                    "expected_device_capture": device.model_dump(mode="json"),
                    "cuda_initialization_calls": 0,
                    "cuda_synchronize_calls": 0,
                    "model_constructor_calls": 0,
                    "tokenizer_constructor_calls": 0,
                    "forward_calls": 0,
                }
                ready = BenchmarkCudaReady.model_validate(
                    body | {"ready_sha256": content_sha256(body)}
                )
                validate_benchmark_cuda_ready(
                    invocation,
                    ready,
                    configuration=configuration,
                    receipt_raw_sha256=pins.backend.receipt_raw_sha256,
                    expected_device=device,
                )
                files.write_cuda_ready(ready)
                _wait_root_ack(pins.expires_ns)
                resources.assert_current()
                files.assert_current()
                with open_cuda_probe_device_access(resources) as ownership:

                    def peer_fence(actual: BenchmarkUnixPeer) -> None:
                        if actual != peer:
                            raise ValueError("BENCHMARK_CUDA_PEER_CHANGED")
                        resources.assert_current()
                        ownership.assert_owned()

                    channel = capture_benchmark_worker_channel(
                        invocation,
                        activation_fd=3,
                        expected_peer=peer,
                        peer_fence=peer_fence,
                        expires_ns=pins.expires_ns,
                    )
                    try:
                        completed = run_native_embedding_benchmark(
                            files,
                            lambda: native_cuda_backend_scope(
                                configuration,
                                receipt_raw_sha256=pins.backend.receipt_raw_sha256,
                                ownership=ownership,
                            ),
                            channel,
                            profile="CUDA_INDEX_FP32",
                            entry_started_ns=started_ns,
                            expires_ns=pins.expires_ns,
                        )
                        return 0 if completed.status == "COMPLETED" else 1
                    finally:
                        channel.close()
        finally:
            # PID1's retained copy survives exit; never unlock/release it from this worker.
            lease.close()


def _execute(pins: BenchmarkLaunchPins, started_ns: int) -> int:
    with benchmark_socket_activation(pins):
        return _run(pins, started_ns)


def main() -> int:
    started = time.perf_counter_ns()
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
        if signal.SIGUSR1 in signal.sigpending():
            raise ValueError("BENCHMARK_CUDA_PREEXISTING_ACK")
        pins = parse_benchmark_launch_pins(tuple(sys.argv[1:]))
        with discard_native_embedding_diagnostics():
            require_native_embedding_identity("CUDA_INDEX_FP32")
            return _execute(pins, started)
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
