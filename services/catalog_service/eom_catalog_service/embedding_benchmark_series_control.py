"""One finite root rendezvous for six original launches; no queue, SQL, NAS or login."""

from __future__ import annotations

import re
import selectors
import socket
import struct
import time
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    BenchmarkOwnerRequest,
    benchmark_listener_timeout_seconds,
    embedding_device_benchmark_bytes,
)
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchCompleted

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_benchmark_handoff import (
    benchmark_owner_start_ticks,
    capture_benchmark_runtime_installation,
)
from eom_catalog_service.embedding_benchmark_launch_workspace import read_owner_benchmark_launch
from eom_catalog_service.embedding_benchmark_layout import benchmark_series_socket_name
from eom_catalog_service.embedding_benchmark_root_control import (
    RootBenchmarkCudaRuntime,
    serve_associated_root_benchmark_launch,
)
from eom_catalog_service.embedding_benchmark_root_socket import root_benchmark_listener
from eom_catalog_service.embedding_benchmark_unit_control import require_root_benchmark_control
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins


@dataclass(frozen=True, slots=True)
class BenchmarkRootSeriesSelection:
    """Installed root caller's explicit selection; neither user nor compute authority."""

    request: BenchmarkOwnerRequest
    owner_pid: int
    owner_start_ticks: int
    accept_until_ns: int
    cpu: NativeEmbeddingBackendPins
    cuda: NativeEmbeddingBackendPins
    controller_release: str

    def __post_init__(self) -> None:
        require_root_benchmark_control()
        embedding_device_benchmark_bytes(self.request)
        if (
            type(self.cpu) is not NativeEmbeddingBackendPins
            or type(self.cuda) is not NativeEmbeddingBackendPins
        ):
            raise ValueError("BENCHMARK_SERIES_SELECTION_INVALID")
        self.cpu.__post_init__()
        self.cuda.__post_init__()
        now = time.monotonic_ns()
        accept_seconds = benchmark_listener_timeout_seconds(self.request.execution_policy)
        if (
            type(self.owner_pid) is not int
            or not 1 <= self.owner_pid <= 2**31 - 1
            or type(self.owner_start_ticks) is not int
            or not 1 <= self.owner_start_ticks < 2**63
            or type(self.accept_until_ns) is not int
            or not now < self.accept_until_ns <= now + accept_seconds * 10**9
            or type(self.controller_release) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.controller_release) is None
            or self.cpu.configuration_revision_id == self.cuda.configuration_revision_id
        ):
            raise ValueError("BENCHMARK_SERIES_SELECTION_INVALID")
        _selected_owner(self)


def _selected_owner(selection: BenchmarkRootSeriesSelection) -> BenchmarkUnixPeer:
    require_root_benchmark_control()
    identity = fixed_owner_identity()
    peer = BenchmarkUnixPeer(selection.owner_pid, identity.owner_uid, identity.owner_gid)
    if (
        benchmark_owner_start_ticks(peer.pid, uid=peer.uid, gid=peer.gid)
        != selection.owner_start_ticks
    ):
        raise ValueError("BENCHMARK_SERIES_OWNER_CHANGED")
    return peer


def _accept_owner(
    listener: socket.socket, selection: BenchmarkRootSeriesSelection
) -> socket.socket:
    expected = _selected_owner(selection)
    rejected = 0
    with selectors.DefaultSelector() as selector:
        selector.register(listener, selectors.EVENT_READ)
        while True:
            _selected_owner(selection)
            remaining = (selection.accept_until_ns - time.monotonic_ns()) / 10**9
            if remaining <= 0 or rejected >= 8:
                raise ValueError("BENCHMARK_SERIES_ACCEPT_UNAVAILABLE")
            if not selector.select(min(remaining, 0.25)):
                continue
            try:
                candidate, _ = listener.accept()
            except BlockingIOError:
                continue
            try:
                actual = BenchmarkUnixPeer(
                    *struct.unpack(
                        "=iII", candidate.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    )
                )
                if actual != expected:
                    candidate.close()
                    rejected += 1
                    continue
                candidate.set_inheritable(False)
                candidate.setblocking(False)
                return candidate
            except BaseException:
                candidate.close()
                raise


def serve_root_benchmark_series(
    selection: BenchmarkRootSeriesSelection,
    *,
    cuda: RootBenchmarkCudaRuntime,
) -> tuple[BenchmarkLaunchCompleted, ...]:
    """Already-running root owner handles only this exact selected process/request.

    Each original owner stage supplies the existing association frame. It does
    not grant source/Job permission. Failed/unknown outcomes stop without a retry;
    existing root machine records and original owner reservations remain intact.
    """
    require_root_benchmark_control()
    if (
        type(selection) is not BenchmarkRootSeriesSelection
        or type(cuda) is not RootBenchmarkCudaRuntime
    ):
        raise ValueError("BENCHMARK_SERIES_SELECTION_INVALID")
    selection.__post_init__()
    # Fixed metadata preflight only. Actual model safety/device/lease ownership
    # remain the unchanged per-launch driver and native checkpoint boundaries.
    files = (
        capture_benchmark_runtime_installation(selection.request.cpu, backend=selection.cpu),
        capture_benchmark_runtime_installation(selection.request.cuda, backend=selection.cuda),
    )
    cuda.inventory.assert_unchanged()
    cuda.host.assert_current()
    completed: list[BenchmarkLaunchCompleted] = []
    executions: set[str] = set()
    job_id: str | None = None
    name = benchmark_series_socket_name(selection.request.benchmark_revision_id)
    with root_benchmark_listener(name) as listener:
        for ordinal, device in enumerate(BENCHMARK_DEVICE_SEQUENCE, 1):
            for captured in files:
                captured.assert_unchanged()
            connection = _accept_owner(listener, selection)
            channel = None
            try:
                expected = _selected_owner(selection)

                def fence(
                    actual: BenchmarkUnixPeer, expected: BenchmarkUnixPeer = expected
                ) -> None:
                    if actual != expected or _selected_owner(selection) != expected:
                        raise ValueError("BENCHMARK_SERIES_OWNER_CHANGED")

                channel = BenchmarkLaunchControlChannel.accept_root_association(
                    connection,
                    expected_peer=expected,
                    peer_fence=fence,
                    controller_release=selection.controller_release,
                    accept_until_ns=selection.accept_until_ns,
                    policy=selection.request.execution_policy,
                )
                association = channel.association
                staged = read_owner_benchmark_launch(association.execution_id, expected=association)
                if (
                    staged.request != selection.request
                    or association.owner_request_sha256 != selection.request.request_sha256
                    or association.owner_pid != expected.pid
                    or association.owner_start_ticks != selection.owner_start_ticks
                    or association.launch_ordinal != ordinal
                    or association.device != device
                    or association.execution_id in executions
                    or (job_id is not None and association.job_id != job_id)
                ):
                    raise ValueError("BENCHMARK_SERIES_ORIGINAL_ASSOCIATION_INVALID")
                job_id = association.job_id
                executions.add(association.execution_id)
                result = serve_associated_root_benchmark_launch(
                    channel,
                    staged,
                    selected_request_sha256=selection.request.request_sha256,
                    backend=selection.cpu if device == "CPU" else selection.cuda,
                    controller_release=selection.controller_release,
                    cuda=cuda if device == "CUDA" else None,
                )
                if result.original_outcome != "SUCCEEDED":
                    raise ValueError("BENCHMARK_SERIES_ORIGINAL_FAILED")
                completed.append(result)
            finally:
                if channel is not None:
                    channel.close()
                connection.close()
    return tuple(completed)
