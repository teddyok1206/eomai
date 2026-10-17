"""Concrete root-only GPU observation relay; no compute ACK, launch, grant or retirement."""

from __future__ import annotations

import os
import pwd
import socket
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    validate_benchmark_local_resources,
)

from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)
from eom_catalog_service.embedding_benchmark_cuda_observation import observe_benchmark_cuda_ready
from eom_catalog_service.embedding_benchmark_gpu_observation import (
    BenchmarkGpuMemoryObserver,
    BenchmarkGpuObservedPeaks,
)
from eom_catalog_service.embedding_benchmark_handoff import (
    PreparedBenchmarkEnvironment,
    benchmark_owner_start_ticks,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory


class RootBenchmarkGpuResourceRelay:
    """Root lifecycle composition constructs this before ACK, then serves on this thread.

    The caller must continue actual sampling if intervening readiness/ACK work blocks;
    this relay never resets a baseline or relaxes the existing maximum-gap policy.
    Parsed invocation/readiness/peer data is not source/compute/cleanup authority.
    """

    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        environment: PreparedBenchmarkEnvironment,
        *,
        backend: NativeEmbeddingBackendPins,
        inventory: PrefixRuntimeInventory,
        host: ProtectedCudaEmbeddingHostClosure,
    ) -> None:
        try:
            if os.getresuid() != (0, 0, 0):
                raise ValueError("BENCHMARK_RESOURCE_RELAY_ROOT_REQUIRED")
            embedding_device_benchmark_bytes(invocation)
            owner = pwd.getpwnam("eom-workflow-runner")
            if (
                invocation.device != "CUDA"
                or type(environment) is not PreparedBenchmarkEnvironment
                or environment.execution_id != invocation.execution_id
                or environment.job_id != invocation.job_id
                or owner.pw_uid <= 0
                or owner.pw_gid <= 0
            ):
                raise ValueError("BENCHMARK_RESOURCE_RELAY_IDENTITY_INVALID")
            self._peer = BenchmarkUnixPeer(environment.owner_pid, owner.pw_uid, owner.pw_gid)
            self._environment = environment
            self._invocation = BenchmarkWorkerInvocation.model_validate(invocation)
            ready = observe_benchmark_cuda_ready(
                invocation, environment, backend=backend, inventory=inventory, host=host
            )
            self._observer = BenchmarkGpuMemoryObserver(
                ready, invocation, environment, backend=backend, inventory=inventory, host=host
            )
            self._channel = BenchmarkResourceChannel(
                connection,
                invocation,
                expected_peer=self._peer,
                peer_fence=self._fence_owner,
                expires_ns=environment.expires_ns,
                wait_observer=self._observe_wait,
            )
            self._used = False
        except BaseException:
            if isinstance(connection, socket.socket):
                connection.close()
            raise

    def _fence_owner(self, actual: BenchmarkUnixPeer) -> None:
        if (
            os.getresuid() != (0, 0, 0)
            or actual != self._peer
            or benchmark_owner_start_ticks(actual.pid, uid=actual.uid, gid=actual.gid)
            != self._environment.owner_start_ticks
        ):
            raise ValueError("BENCHMARK_RESOURCE_RELAY_OWNER_CHANGED")

    def sample(self) -> None:
        """Allow the real lifecycle control thread to sample during its other bounded work."""
        self._observer.sample()

    def observed_peaks(self) -> BenchmarkGpuObservedPeaks:
        return self._observer.observed_peaks()

    def _observe_wait(self) -> None:
        # A finalized reply can encounter socket backpressure after the model scope
        # ended. Keep peer/deadline checks, never mutate the frozen original metrics.
        state = self._observer.observed_peaks().state
        if state == "OPEN":
            self._observer.sample()
        elif state != "FROZEN":
            raise ValueError("BENCHMARK_RESOURCE_RELAY_OBSERVATION_INVALID")

    def serve(self) -> BenchmarkResourceEvidence:
        """Receive once, observe/finalize once and reply once; failure never permits retry."""
        if self._used:
            raise ValueError("BENCHMARK_RESOURCE_RELAY_ALREADY_USED")
        self._used = True
        try:
            local = self._channel.receive_resources()
            validate_benchmark_local_resources(self._invocation, local)
            finalized = self._observer.finalize(local)
            self._channel.send_resources(finalized)
            return finalized
        finally:
            self._channel.close()

    def close(self) -> None:
        """Close only this socket; physical GPU ownership is retained by its real owner."""
        self._channel.close()
