"""Workflow-owner resource client; independent GPU fields come only from its root peer."""

from __future__ import annotations

import os
import socket

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_local_resources,
    validate_benchmark_resource_finalization,
)
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)

from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity


class OwnerBenchmarkGpuResourceClient:
    """Installed composition supplies an already-connected socket and exact root PID.

    No socket discovery, source grant, process launch, GPU fallback, counter synthesis
    or publication is performed. The caller retains actual launch/capacity ownership.
    """

    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        *,
        root_peer: BenchmarkUnixPeer,
        authorization: BenchmarkLaunchAuthorization,
        expires_ns: int,
    ) -> None:
        try:
            owner = fixed_owner_identity()
            if os.getresuid() != (owner.owner_uid,) * 3 or os.getresgid() != (owner.owner_gid,) * 3:
                raise ValueError("BENCHMARK_RESOURCE_CLIENT_OWNER_REQUIRED")
            embedding_device_benchmark_bytes(invocation)
            if (
                invocation.device != "CUDA"
                or type(root_peer) is not BenchmarkUnixPeer
                or root_peer.uid != 0
                or root_peer.gid != 0
                or type(authorization) is not BenchmarkLaunchAuthorization
            ):
                raise ValueError("BENCHMARK_RESOURCE_CLIENT_CONFIGURATION_INVALID")
            self._invocation = BenchmarkWorkerInvocation.model_validate(invocation)
            self._owner = owner
            self._authorization, self._root = authorization, root_peer
            self._channel = BenchmarkResourceChannel(
                connection,
                invocation,
                expected_peer=root_peer,
                peer_fence=self._fence_root,
                expires_ns=expires_ns,
            )
            self._used = False
        except BaseException:
            if isinstance(connection, socket.socket):
                connection.close()
            raise

    def _fence_root(self, actual: BenchmarkUnixPeer) -> None:
        if (
            actual != self._root
            or os.getresuid() != (self._owner.owner_uid,) * 3
            or os.getresgid() != (self._owner.owner_gid,) * 3
        ):
            raise ValueError("BENCHMARK_RESOURCE_CLIENT_ROOT_CHANGED")

    def finalize(self, local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
        """Use as the native owner channel's finalizer; never copy model GPU fields in."""
        if self._used:
            raise ValueError("BENCHMARK_RESOURCE_CLIENT_ALREADY_USED")
        self._used = True
        try:
            validate_benchmark_local_resources(self._invocation, local)
            raw_local = embedding_device_benchmark_bytes(local)
            snapshot = parse_embedding_device_benchmark_bytes(raw_local)
            assert isinstance(snapshot, BenchmarkResourceEvidence)
            self._authorization.assert_invocation(self._invocation)
            self._channel.send_resources(snapshot)
            finalized = self._channel.receive_resources()
            baseline = parse_embedding_device_benchmark_bytes(raw_local)
            assert isinstance(baseline, BenchmarkResourceEvidence)
            validate_benchmark_resource_finalization(self._invocation, baseline, finalized)
            self._authorization.assert_invocation(self._invocation)
            return finalized
        finally:
            self._channel.close()

    def close(self) -> None:
        self._channel.close()
