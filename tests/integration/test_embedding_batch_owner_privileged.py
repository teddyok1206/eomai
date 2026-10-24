"""Opt-in real root/runner UID Unix credentials and local DAC; no GPU, SQL, NAS or units."""

from __future__ import annotations

import ctypes
import os
import pwd
import socket
import struct
import tempfile
import time
from pathlib import Path

import pytest
from eom_catalog_service import embedding_batch_owner_workspace as workspace
from eom_catalog_service.embedding_batch_owner_channel import (
    EmbeddingBatchOwnerChannel,
    EmbeddingBatchOwnerChannelError,
    bind_original_embedding_batch_owner_channel,
)
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_workflow.embedding_batch_owner_control import (
    EmbeddingBatchRootCompleted,
    embedding_batch_owner_control_bytes,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import RELEASE, control_frames

pytestmark = pytest.mark.privileged


@pytest.fixture
def owned(monkeypatch):
    if os.environ.get("EOM_RUN_GPU_BATCH_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit root test-only filesystem/peer gate required")
    assert os.getresuid() == (0, 0, 0)
    account = pwd.getpwnam("eom-workflow-runner")
    # Warm pure schema/model caches before dropping UID. Test children do not
    # gain repository reads, auth, a DB connection, source grants or worker work.
    case = control_frames(expires_ns=time.monotonic_ns() + 30 * 10**9)
    with tempfile.TemporaryDirectory(prefix="eom-batch-owner-os-", dir="/run") as directory:
        parent = Path(directory)
        parent.chmod(0o755)
        root = parent / "owner"
        root.mkdir(mode=0o700)
        os.chown(root, account.pw_uid, account.pw_gid)
        monkeypatch.setattr(workspace, "BATCH_OWNER_ROOT", root)
        yield case, account, parent, root


def _drop(account):
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    # Only this secret-free fork fixture: make /proc owner/birth readable under
    # its real UID, as it is after a normal service exec. No host policy changes.
    assert ctypes.CDLL(None, use_errno=True).prctl(4, 1, 0, 0, 0) == 0


def _wait(child):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        pid, status = os.waitpid(child, os.WNOHANG)
        if pid:
            assert os.waitstatus_to_exitcode(status) == 0
            return
        time.sleep(0.02)
    os.kill(child, 9)
    os.waitpid(child, 0)
    pytest.fail("test-only child failed to terminate within its original deadline")


@pytest.mark.parametrize("wait_after_ack", [False, True])
def test_actual_source_owner_pid_uid_sender_and_root_read_only_input_round_trip(
    owned, wait_after_ack
):
    case, account, parent, _root = owned
    address = str(parent / "root.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    listener.bind(address)
    os.chown(address, 0, account.pw_gid)
    os.chmod(address, 0o660)
    listener.listen(1)
    listener.settimeout(10)
    release_read, release_write = os.pipe2(os.O_CLOEXEC)
    root_peer = BenchmarkUnixPeer(os.getpid(), 0, 0)
    root_birth = benchmark_owner_start_ticks(root_peer.pid, uid=0, gid=0)
    child = os.fork()
    if child == 0:
        try:
            listener.close()
            os.close(release_write)
            _drop(account)
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            connection.connect(address)
            owner = bind_original_embedding_batch_owner_channel(
                connection,
                case.request,
                controller_release=RELEASE,
                side="OWNER",
                expected_peer=root_peer,
                peer_start_ticks=root_birth,
            )
            ready = owner.receive_allocation()
            assert ready == case.ready
            staged = workspace.stage_owner_embedding_batch(
                case.request, ready, case.binding, case.batch
            )
            assert staged.notice.owner_pid == os.getpid()
            owner.send_binding(staged.notice)
            assert owner.authorize_next(lambda *_: None) is None  # synthetic source seam
            completed = owner.authorize_next(lambda *_: None)
            assert completed.grant.batch_request_sha256 == case.batch.request_sha256
            owner.acknowledge_completion(lambda _: staged.assert_current())
            if wait_after_ack:
                assert os.read(release_read, 1) == b"1"
            owner.close()
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(release_read)
    root = None
    try:
        connection, _address = listener.accept()
        connection.settimeout(None)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        source_peer = BenchmarkUnixPeer(child, account.pw_uid, account.pw_gid)
        source_birth = benchmark_owner_start_ticks(child, uid=account.pw_uid, gid=account.pw_gid)
        root = bind_original_embedding_batch_owner_channel(
            connection,
            case.request,
            controller_release=RELEASE,
            side="ROOT",
            expected_peer=source_peer,
            peer_start_ticks=source_birth,
        )
        assert root.require_direct_peer() == source_peer
        root.send_ready(case.ready)
        bound = root.receive_binding()
        assert bound.owner_pid == child
        staged = workspace.read_owner_embedding_batch(case.request, bound)
        assert staged.batch == case.batch
        root.check_child(case.batch.request_sha256, case.batch.children[0].request.request_sha256)
        completion = EmbeddingBatchRootCompleted.model_validate(
            seal(
                case.completed.model_dump(mode="json")
                | {"bound_message_sha256": bound.message_sha256},
                "message_sha256",
            )
        )
        root.send_completed(completion)
    finally:
        if root is not None:
            root.close()
        listener.close()
        try:
            os.write(release_write, b"1")
        except BrokenPipeError:
            assert not wait_after_ack
        os.close(release_write)
        _wait(child)


def test_actual_native_gpu_identity_cannot_read_source_owner_input(owned):
    _case, account, _parent, root = owned
    path = root / "private-input.json"
    path.write_bytes(b"test-owned source input, not production content")
    path.chmod(0o600)
    os.chown(path, account.pw_uid, account.pw_gid)
    native = pwd.getpwnam("eom-embedding-cuda")
    child = os.fork()
    if child == 0:
        try:
            _drop(native)
            with pytest.raises(PermissionError):
                path.read_bytes()
            os._exit(0)
        except BaseException:
            os._exit(1)
    _wait(child)


def test_inherited_socket_sender_does_not_impersonate_original_root(owned):
    case, account, _parent, _root = owned
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    right.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    original = BenchmarkUnixPeer(os.getpid(), 0, 0)
    owner = EmbeddingBatchOwnerChannel(
        right,
        case.request,
        controller_release=RELEASE,
        side="OWNER",
        expected_peer=original,
        peer_fence=lambda _: None,
    )
    child = os.fork()
    if child == 0:
        try:
            right.close()
            _drop(account)
            raw = embedding_batch_owner_control_bytes(case.ready)
            left.sendall(struct.pack("!I", len(raw)) + raw)
            left.close()
            os._exit(0)
        except BaseException:
            os._exit(1)
    left.close()
    try:
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.receive_allocation()
    finally:
        owner.close()
        _wait(child)
