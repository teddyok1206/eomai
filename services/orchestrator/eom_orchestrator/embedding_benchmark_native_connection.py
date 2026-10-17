"""Actual PID1 listener and native writer capture for one original benchmark execution."""

from __future__ import annotations

import errno
import os
import pwd
import selectors
import socket
import stat
import struct
import time
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_unit_control import (
    CPU_BENCHMARK_TEMPLATE,
    CUDA_BENCHMARK_TEMPLATE,
)
from eom_catalog_service.embedding_runtime_files import (
    fixed_native_embedding_profile,
    read_live_runtime_os_file,
)

from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import inspect_cpu_unit


class CapturedBenchmarkNativeConnection:
    """Own just this connection, not a unit, model, source grant or physical lease.

    Capture is performed by ``connect``. PID1 creates the inherited listener;
    native credentials on every received fragment identify the different writer.
    Only after the last native resource record has been validated may that writer
    exit. Its cleanup remains the separate root controller's responsibility.
    """

    connection: socket.socket
    listener: BenchmarkUnixPeer
    sender: BenchmarkUnixPeer
    _path: Path
    _epoch: tuple[int, ...]
    _birth: int
    _unit: str
    _writer_may_exit: bool

    def __init__(self) -> None:
        raise TypeError("use the actual original-execution connection capture")

    @classmethod
    def connect(
        cls,
        invocation: BenchmarkWorkerInvocation,
        *,
        authorization: BenchmarkLaunchAuthorization,
        expires_ns: int,
    ) -> CapturedBenchmarkNativeConnection:
        owner = fixed_owner_identity()
        if (
            os.getresuid() != (owner.owner_uid,) * 3
            or os.getresgid() != (owner.owner_gid,) * 3
            or type(authorization) is not BenchmarkLaunchAuthorization
        ):
            raise ValueError("BENCHMARK_NATIVE_OWNER_REQUIRED")
        authorization.assert_invocation(invocation)
        template = CPU_BENCHMARK_TEMPLATE if invocation.device == "CPU" else CUDA_BENCHMARK_TEMPLATE
        unit_name = template.replace("@.service", f"@{invocation.execution_id}.service")
        account = pwd.getpwnam(
            fixed_native_embedding_profile(invocation.runtime.profile).worker_user
        )
        parent = BENCHMARK_HANDOFF_ROOT / invocation.execution_id
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.setblocking(False)
        connection.set_inheritable(False)
        # Set before connect: queued bytes must already carry their actual writer.
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        try:
            with protected_cpu_handoff_directory(
                parent, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
            ) as directory:
                while True:
                    if time.monotonic_ns() >= expires_ns:
                        raise ValueError("BENCHMARK_NATIVE_CONNECTION_EXPIRED")
                    try:
                        value = os.stat("control.sock", dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        time.sleep(0.05)
                        continue
                    if (
                        not stat.S_ISSOCK(value.st_mode)
                        or value.st_uid != owner.owner_uid
                        or value.st_gid != owner.owner_gid
                        or stat.S_IMODE(value.st_mode) != 0o600
                        or value.st_nlink != 1
                    ):
                        raise ValueError("BENCHMARK_NATIVE_SOCKET_INVALID")
                    break
                path = parent / "control.sock"
                status = connection.connect_ex(str(path))
                if status in {errno.EINPROGRESS, errno.EALREADY}:
                    with selectors.DefaultSelector() as selector:
                        selector.register(connection, selectors.EVENT_WRITE)
                        remaining = (expires_ns - time.monotonic_ns()) / 10**9
                        if remaining <= 0 or not selector.select(remaining):
                            raise ValueError("BENCHMARK_NATIVE_CONNECTION_UNCERTAIN")
                        status = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if status != 0:
                    raise ValueError("BENCHMARK_NATIVE_CONNECTION_UNCERTAIN")
                listener = BenchmarkUnixPeer(
                    *struct.unpack(
                        "=iII", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    )
                )
                if listener != BenchmarkUnixPeer(1, 0, 0):
                    raise ValueError("BENCHMARK_NATIVE_LISTENER_INVALID")
                # The service may still be starting after the socket is listening.
                while True:
                    if time.monotonic_ns() >= expires_ns:
                        raise ValueError("BENCHMARK_NATIVE_CONNECTION_EXPIRED")
                    current = inspect_cpu_unit(unit_name, template=template)
                    if current.main_pid > 0 and current.invocation_id:
                        break
                    if current.status.active_state == "failed":
                        raise ValueError("BENCHMARK_NATIVE_UNIT_FAILED")
                    time.sleep(0.05)
                if (
                    current.fragment_path != "/etc/systemd/system/" + template
                    or current.drop_in_paths
                    or current.status.exec_main_started_monotonic <= 0
                ):
                    raise ValueError("BENCHMARK_NATIVE_UNIT_INVALID")
                sender = BenchmarkUnixPeer(current.main_pid, account.pw_uid, account.pw_gid)
                birth = benchmark_owner_start_ticks(sender.pid, uid=sender.uid, gid=sender.gid)
                endpoint = cls.__new__(cls)
                endpoint.connection, endpoint.listener, endpoint.sender = (
                    connection,
                    listener,
                    sender,
                )
                endpoint._path, endpoint._epoch = path, cls._socket_epoch(value)
                endpoint._birth, endpoint._unit = birth, unit_name
                endpoint._writer_may_exit = False
                endpoint.peer_fence(listener)
                authorization.assert_invocation(invocation)
                return endpoint
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _socket_epoch(value: os.stat_result) -> tuple[int, ...]:
        return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink

    def peer_fence(self, actual: BenchmarkUnixPeer) -> None:
        if actual != self.listener:
            raise ValueError("BENCHMARK_NATIVE_LISTENER_CHANGED")
        if not self._writer_may_exit:
            if self._socket_epoch(self._path.lstat()) != self._epoch:
                raise ValueError("BENCHMARK_NATIVE_LISTENER_CHANGED")
            sender = self.sender
            if (
                benchmark_owner_start_ticks(sender.pid, uid=sender.uid, gid=sender.gid)
                != self._birth
            ):
                raise ValueError("BENCHMARK_NATIVE_WRITER_CHANGED")
            raw = read_live_runtime_os_file(
                Path("/proc") / str(sender.pid) / "cgroup", maximum=16384, owner_uid=sender.uid
            )
            if raw != ("0::/system.slice/" + self._unit + "\n").encode("ascii"):
                raise ValueError("BENCHMARK_NATIVE_CGROUP_CHANGED")

    def allow_writer_exit_after_resources(self) -> None:
        """No more native input follows; root may unlink its socket after our final send.

        The owned connected FD and its PID1 peer remain checked by the channel.
        Native process/path lifetime may then end; cleanup is still not attested here.
        """
        self.peer_fence(self.listener)
        self._writer_may_exit = True

    def close(self) -> None:
        self.connection.close()
