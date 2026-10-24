"""One original owner↔fixed root-controller connection; no source grant or numerical launch."""

from __future__ import annotations

import os
import re
import selectors
import socket
import stat
import struct
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import (
    inspect_cpu_unit,
    require_fixed_cpu_unit_template,
)

from eom_catalog_service.embedding_batch_control_workspace import (
    BATCH_CONTROL_TEMPLATE,
    StagedEmbeddingBatchControl,
    claim_embedding_batch_control_dispatch,
    embedding_batch_control_unit,
)
from eom_catalog_service.embedding_batch_owner_channel import (
    EmbeddingBatchOwnerChannel,
    bind_original_embedding_batch_owner_channel,
)
from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer

BATCH_CONTROL_TEMPLATE_SHA256 = "a1d7f9a228d865e98d57306dd127f8beb98576481a393f0990e2ed514e6a824c"
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_CONTROL_CONNECTION_INVALID")


def _owner() -> None:
    value = fixed_owner_identity()
    _require(os.getresuid() == (value.owner_uid,) * 3 and os.getresgid() == (value.owner_gid,) * 3)


def _peer(connection: socket.socket) -> BenchmarkUnixPeer:
    return BenchmarkUnixPeer(
        *struct.unpack("=iII", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    )


def _socket_epoch(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink)


def _socket_metadata(staged: StagedEmbeddingBatchControl, directory: int) -> tuple[int, ...]:
    owner = fixed_owner_identity()
    value = os.stat("control.sock", dir_fd=directory, follow_symlinks=False)
    _require(
        stat.S_ISSOCK(value.st_mode)
        and value.st_uid == owner.owner_uid
        and value.st_gid == owner.owner_gid
        and stat.S_IMODE(value.st_mode) == 0o660
        and value.st_nlink == 1
        and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(staged.path / "control.sock", follow_symlinks=False)
        )
    )
    return _socket_epoch(value)


@dataclass(frozen=True, slots=True)
class OwnerEmbeddingBatchListener:
    staged: StagedEmbeddingBatchControl
    socket: socket.socket
    socket_epoch: tuple[int, ...]

    def assert_current(self) -> None:
        _owner()
        self.staged.assert_current()
        _require(
            self.socket.fileno() >= 0
            and self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
        )
        owner = fixed_owner_identity()
        with protected_cpu_handoff_directory(
            self.staged.path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            _require(_socket_metadata(self.staged, directory) == self.socket_epoch)

    def accept_root(self, *, controller_release: str) -> EmbeddingBatchOwnerChannel:
        """Match actual root MainPID and original birth, never a model-supplied identity."""
        _owner()
        self.assert_current()
        _require(re.fullmatch(r"[0-9a-f]{40}", controller_release, re.ASCII) is not None)
        require_fixed_cpu_unit_template(BATCH_CONTROL_TEMPLATE, BATCH_CONTROL_TEMPLATE_SHA256)
        with selectors.DefaultSelector() as selector:
            selector.register(self.socket, selectors.EVENT_READ)
            rejected = 0
            while rejected < 8:
                remaining = (self.staged.request.expires_monotonic_ns - time.monotonic_ns()) / 10**9
                _require(remaining > 0)
                if not selector.select(min(remaining, 0.25)):
                    continue
                connection, _ = self.socket.accept()
                channel = None
                try:
                    connection.set_inheritable(False)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                    connection.setblocking(False)
                    peer = _peer(connection)
                    if (peer.uid, peer.gid) != (0, 0):
                        rejected += 1
                        connection.close()
                        continue
                    unit = inspect_cpu_unit(
                        embedding_batch_control_unit(self.staged.attempt_hex),
                        template=BATCH_CONTROL_TEMPLATE,
                    )
                    _require(
                        unit.main_pid == peer.pid
                        and unit.status.process_started
                        and unit.status.active_state in {"activating", "active"}
                        and unit.fragment_path == "/etc/systemd/system/" + BATCH_CONTROL_TEMPLATE
                        and not unit.drop_in_paths
                        and not unit.status.need_daemon_reload
                        and re.fullmatch(r"[0-9a-f]{32}", unit.invocation_id, re.ASCII) is not None
                    )
                    birth = embedding_batch_owner_start_ticks(peer.pid, uid=0, gid=0)
                    self.assert_current()
                    channel = bind_original_embedding_batch_owner_channel(
                        connection,
                        self.staged.request,
                        controller_release=controller_release,
                        side="OWNER",
                        expected_peer=peer,
                        peer_start_ticks=birth,
                    )
                    current = inspect_cpu_unit(
                        embedding_batch_control_unit(self.staged.attempt_hex),
                        template=BATCH_CONTROL_TEMPLATE,
                    )
                    _require(current == unit)
                    return channel
                except BaseException:
                    if channel is not None:
                        channel.close()
                    else:
                        connection.close()
                    raise
        raise ValueError("EMBEDDING_BATCH_CONTROL_CONNECTION_INVALID")


@contextmanager
def owner_embedding_batch_listener(
    staged: StagedEmbeddingBatchControl,
) -> Iterator[OwnerEmbeddingBatchListener]:
    """Remove only the socket inode created here; preserve allocation/dispatch history."""
    _owner()
    staged.assert_current()
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        staged.path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        created = None
        try:
            connection.set_inheritable(False)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            connection.bind(str(staged.path / "control.sock"))
            # Save identity before chmod so a failure never deletes a pre-existing socket.
            created = _socket_epoch(
                os.stat("control.sock", dir_fd=directory, follow_symlinks=False)
            )
            os.chmod("control.sock", 0o660, dir_fd=directory, follow_symlinks=False)
            created = _socket_metadata(staged, directory)
            connection.listen(1)
            connection.setblocking(False)
            yield OwnerEmbeddingBatchListener(staged, connection, created)
        finally:
            connection.close()
            if created is not None:
                _require(
                    _socket_epoch(os.stat("control.sock", dir_fd=directory, follow_symlinks=False))
                    == created
                )
                os.unlink("control.sock", dir_fd=directory)


def dispatch_embedding_batch_control(listener: OwnerEmbeddingBatchListener) -> None:
    """One Polkit-authorized fixed unit start; unknown/failed dispatch is never replayed."""
    _owner()
    listener.assert_current()
    staged = listener.staged
    require_fixed_cpu_unit_template(BATCH_CONTROL_TEMPLATE, BATCH_CONTROL_TEMPLATE_SHA256)
    unit = embedding_batch_control_unit(staged.attempt_hex)
    before = inspect_cpu_unit(unit, template=BATCH_CONTROL_TEMPLATE)
    _require(
        before.fresh
        and before.fragment_path == "/etc/systemd/system/" + BATCH_CONTROL_TEMPLATE
        and not before.drop_in_paths
        and not before.status.need_daemon_reload
    )
    claim_embedding_batch_control_dispatch(staged)
    result = subprocess.run(
        ("/usr/bin/systemctl", "--no-ask-password", "--no-block", "start", unit),
        check=False,
        capture_output=True,
        timeout=10,
        env=_ENV,
    )
    _require(result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384)


def connect_embedding_batch_source_owner(
    staged: StagedEmbeddingBatchControl, *, controller_release: str
) -> EmbeddingBatchOwnerChannel:
    """Actual fixed root connects once to the owner which staged this original allocation."""
    _require(os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0))
    staged.assert_current()
    owner = fixed_owner_identity()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.set_inheritable(False)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        remaining = (staged.request.expires_monotonic_ns - time.monotonic_ns()) / 10**9
        _require(remaining > 0)
        connection.settimeout(remaining)
        with protected_cpu_handoff_directory(
            staged.path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            before = _socket_metadata(staged, directory)
            connection.connect(str(staged.path / "control.sock"))
            # Framing owns one absolute deadline. A positive CPython timeout
            # would add hidden select waits even to MSG_DONTWAIT operations.
            connection.setblocking(False)
            peer = _peer(connection)
            _require((peer.uid, peer.gid) == (owner.owner_uid, owner.owner_gid))
            birth = embedding_batch_owner_start_ticks(peer.pid, uid=peer.uid, gid=peer.gid)
            _require(_socket_metadata(staged, directory) == before)
            staged.assert_current()
            return bind_original_embedding_batch_owner_channel(
                connection,
                staged.request,
                controller_release=controller_release,
                side="ROOT",
                expected_peer=peer,
                peer_start_ticks=birth,
            )
    except BaseException:
        connection.close()
        raise
