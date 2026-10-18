"""Actual fixed-owner connection to a protected original-execution root controller.

Concrete owner adapter; state/Artifact commit remain Orchestrator responsibilities.
"""

from __future__ import annotations

import errno
import os
import selectors
import socket
import stat
import struct
import time

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    embedding_device_benchmark_bytes,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchAssociation,
    parse_benchmark_launch_control,
)

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_catalog_service.embedding_benchmark_layout import (
    BENCHMARK_CONTROL_ROOT,
    benchmark_series_socket_name,
)


def require_benchmark_series_listener(request: BenchmarkOwnerRequest) -> None:
    """Read-only absence/metadata preflight, not root liveness or execution admission."""
    owner = fixed_owner_identity()
    if os.getresuid() != (owner.owner_uid,) * 3 or os.getresgid() != (owner.owner_gid,) * 3:
        raise ValueError("BENCHMARK_ROOT_CONNECTION_OWNER_REQUIRED")
    embedding_device_benchmark_bytes(request)
    name = benchmark_series_socket_name(request.benchmark_revision_id)
    try:
        with protected_cpu_handoff_directory(
            BENCHMARK_CONTROL_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ) as parent:
            _socket_metadata(parent, name, owner.owner_gid)
    except (OSError, CpuHandoffError):
        raise ValueError("BENCHMARK_SERIES_CONTROLLER_UNAVAILABLE") from None


def _socket_metadata(parent: int, name: str, owner_gid: int) -> os.stat_result:
    metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != owner_gid
        or stat.S_IMODE(metadata.st_mode) != 0o660
        or metadata.st_nlink != 1
    ):
        raise ValueError("BENCHMARK_ROOT_CONNECTION_PATH_INVALID")
    return metadata


def connect_benchmark_root(
    association: BenchmarkLaunchAssociation,
    *,
    authorization: BenchmarkLaunchAuthorization,
    controller_release: str,
) -> tuple[BenchmarkLaunchControlChannel, BenchmarkUnixPeer]:
    """One connect after the exact protected socket appears; never a new Job or model retry."""
    return _connect_benchmark_control(
        association,
        request=None,
        authorization=authorization,
        controller_release=controller_release,
    )


def connect_benchmark_series_root(
    request: BenchmarkOwnerRequest,
    association: BenchmarkLaunchAssociation,
    *,
    authorization: BenchmarkLaunchAuthorization,
    controller_release: str,
) -> tuple[BenchmarkLaunchControlChannel, BenchmarkUnixPeer]:
    """The original request's preselected finite listener; existing control frames only."""
    return _connect_benchmark_control(
        association,
        request=request,
        authorization=authorization,
        controller_release=controller_release,
    )


def _connect_benchmark_control(
    association: BenchmarkLaunchAssociation,
    *,
    request: BenchmarkOwnerRequest | None,
    authorization: BenchmarkLaunchAuthorization,
    controller_release: str,
) -> tuple[BenchmarkLaunchControlChannel, BenchmarkUnixPeer]:
    owner = fixed_owner_identity()
    if (
        os.getresuid() != (owner.owner_uid,) * 3
        or os.getresgid() != (owner.owner_gid,) * 3
        or type(authorization) is not BenchmarkLaunchAuthorization
    ):
        raise ValueError("BENCHMARK_ROOT_CONNECTION_OWNER_REQUIRED")
    checked = parse_benchmark_launch_control(association)
    if not isinstance(checked, BenchmarkLaunchAssociation):
        raise ValueError("BENCHMARK_ROOT_CONNECTION_ASSOCIATION_INVALID")
    association = checked
    name = association.execution_id + ".sock"
    if request is not None:
        embedding_device_benchmark_bytes(request)
        if association.owner_request_sha256 != request.request_sha256:
            raise ValueError("BENCHMARK_ROOT_CONNECTION_SELECTION_INVALID")
        name = benchmark_series_socket_name(request.benchmark_revision_id)
    # Full invocation authorization belongs to its caller; this exact association
    # is read from that invocation's already authorized protected stage.
    authorization.assert_current()
    if (
        association.owner_pid != os.getpid()
        or benchmark_owner_start_ticks(os.getpid(), uid=owner.owner_uid, gid=owner.owner_gid)
        != association.owner_start_ticks
    ):
        raise ValueError("BENCHMARK_ROOT_CONNECTION_OWNER_CHANGED")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.setblocking(False)
    connection.set_inheritable(False)
    try:
        with protected_cpu_handoff_directory(
            BENCHMARK_CONTROL_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ) as parent:
            while True:
                if time.monotonic_ns() >= association.expires_ns:
                    raise ValueError("BENCHMARK_ROOT_CONNECTION_EXPIRED")
                try:
                    before = _socket_metadata(parent, name, owner.owner_gid)
                    break
                except FileNotFoundError:
                    time.sleep(0.1)
            status = connection.connect_ex(str(BENCHMARK_CONTROL_ROOT / name))
            if status in {errno.EINPROGRESS, errno.EALREADY}:
                with selectors.DefaultSelector() as selector:
                    selector.register(connection, selectors.EVENT_WRITE)
                    remaining = (association.expires_ns - time.monotonic_ns()) / 10**9
                    if (
                        remaining <= 0
                        or not selector.select(remaining)
                        or connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    ):
                        raise ValueError("BENCHMARK_ROOT_CONNECTION_UNCERTAIN")
            elif status != 0:
                raise ValueError("BENCHMARK_ROOT_CONNECTION_UNCERTAIN")
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode) != (
                after.st_dev,
                after.st_ino,
                after.st_uid,
                after.st_gid,
                after.st_mode,
            ):
                raise ValueError("BENCHMARK_ROOT_CONNECTION_PATH_CHANGED")
            peer = BenchmarkUnixPeer(
                *struct.unpack(
                    "=iII", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
            )
            if peer.uid != 0 or peer.gid != 0:
                raise ValueError("BENCHMARK_ROOT_CONNECTION_PEER_INVALID")
            birth = benchmark_owner_start_ticks(peer.pid, uid=0, gid=0)

            def fence(actual: BenchmarkUnixPeer) -> None:
                if actual != peer or benchmark_owner_start_ticks(peer.pid, uid=0, gid=0) != birth:
                    raise ValueError("BENCHMARK_ROOT_CONNECTION_PEER_CHANGED")

            channel = BenchmarkLaunchControlChannel(
                connection,
                association,
                side="OWNER",
                expected_peer=peer,
                peer_fence=fence,
                controller_release=controller_release,
            )
            authorization.assert_current()
            channel.send_association()
            return channel, peer
    except BaseException:
        connection.close()
        raise
