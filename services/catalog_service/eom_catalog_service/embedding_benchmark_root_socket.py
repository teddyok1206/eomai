"""One exact original-execution root listener; no queue, source discovery or NAS access."""

from __future__ import annotations

import os
import selectors
import socket
import stat
import struct
import time

from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchCompleted

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_catalog_service.embedding_benchmark_launch_workspace import read_owner_benchmark_launch
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_CONTROL_ROOT
from eom_catalog_service.embedding_benchmark_root_control import (
    RootBenchmarkCudaRuntime,
    serve_root_benchmark_launch,
)
from eom_catalog_service.embedding_benchmark_unit_control import require_root_benchmark_control
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins


def serve_root_benchmark_workspace(
    execution_id: str,
    *,
    selected_request_sha256: str,
    backend: NativeEmbeddingBackendPins,
    controller_release: str,
    cuda: RootBenchmarkCudaRuntime | None = None,
) -> BenchmarkLaunchCompleted:
    """Protected installed operator invokes this for an existing admitted owner stage.

    Reject other peers before processing frames. Root owns the fixed namespace and
    removes only its own ephemeral socket inode; original staging/effect records remain.
    This one-shot entry is not permission to restart an unresolved parent reservation.
    """
    require_root_benchmark_control()
    staged = read_owner_benchmark_launch(execution_id)
    association = staged.association
    owner = fixed_owner_identity()
    expected = BenchmarkUnixPeer(association.owner_pid, owner.owner_uid, owner.owner_gid)
    if (
        staged.request.request_sha256 != selected_request_sha256
        or not time.monotonic_ns() < association.expires_ns
    ):
        raise ValueError("BENCHMARK_ROOT_SELECTION_OR_DEADLINE_INVALID")
    if (
        benchmark_owner_start_ticks(expected.pid, uid=expected.uid, gid=expected.gid)
        != association.owner_start_ticks
    ):
        raise ValueError("BENCHMARK_ROOT_OWNER_CHANGED")
    name = execution_id + ".sock"
    with protected_cpu_handoff_directory(
        BENCHMARK_CONTROL_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as parent:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection = None
        created = None
        try:
            listener.bind(str(BENCHMARK_CONTROL_ROOT / name))
            os.chown(name, 0, owner.owner_gid, dir_fd=parent, follow_symlinks=False)
            os.chmod(name, 0o660, dir_fd=parent, follow_symlinks=False)
            created = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISSOCK(created.st_mode) or created.st_nlink != 1:
                raise ValueError("BENCHMARK_ROOT_CONTROL_SOCKET_INVALID")
            listener.listen(1)
            listener.setblocking(False)
            with selectors.DefaultSelector() as selector:
                selector.register(listener, selectors.EVENT_READ)
                remaining_peers = 8
                while connection is None:
                    remaining = (association.expires_ns - time.monotonic_ns()) / 10**9
                    if remaining <= 0 or remaining_peers <= 0:
                        raise ValueError("BENCHMARK_ROOT_CONTROL_EXPIRED")
                    if not selector.select(min(remaining, 0.25)):
                        continue
                    try:
                        candidate, _ = listener.accept()
                    except BlockingIOError:
                        continue
                    peer = BenchmarkUnixPeer(
                        *struct.unpack(
                            "=iII", candidate.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                        )
                    )
                    if peer != expected:
                        candidate.close()
                        remaining_peers -= 1
                        continue
                    candidate.set_inheritable(False)
                    candidate.setblocking(False)
                    connection = candidate
            return serve_root_benchmark_launch(
                connection,
                staged,
                selected_request_sha256=selected_request_sha256,
                backend=backend,
                controller_release=controller_release,
                cuda=cuda,
            )
        finally:
            if connection is not None:
                connection.close()
            listener.close()
            if created is not None:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_uid,
                    current.st_gid,
                    current.st_mode,
                ) != (
                    created.st_dev,
                    created.st_ino,
                    created.st_uid,
                    created.st_gid,
                    created.st_mode,
                ):
                    raise ValueError("BENCHMARK_ROOT_CONTROL_SOCKET_CHANGED")
                os.unlink(name, dir_fd=parent)
