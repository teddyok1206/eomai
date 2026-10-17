"""Actual inherited-listener peers and SCM writers; synthetic checkpoints, no model/IAM."""

import os
import signal
import socket
import struct
import time
from contextlib import contextmanager

import pytest
from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkOwnerChannel,
    BenchmarkUnixPeer,
    BenchmarkWorkerChannel,
)

from tests.unit.embedding_device_benchmark_fixtures import resources, session, worker_invocation
from tests.unit.test_embedding_benchmark_channel import local_resources


def peer(pid=None):
    return BenchmarkUnixPeer(os.getpid() if pid is None else pid, os.geteuid(), os.getegid())


@contextmanager
def inherited(tmp_path, ordinal=3, *, fault=None, expected_sender_offset=0, passcred=True):
    invocation, program = worker_invocation(ordinal), session(ordinal)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = str(tmp_path / "control.sock")
    listener.bind(path)
    listener.listen(1)
    creator = peer()
    expires = time.monotonic_ns() + 10 * 10**9
    child = os.fork()
    if child == 0:
        try:
            connection, _ = listener.accept()
            listener.close()
            if fault in {"fragmented", "foreign_writer", "foreign_body"}:
                raw = embedding_device_benchmark_bytes(program.checkpoints[0])
                raw = struct.pack("!I", len(raw)) + raw
                if fault in {"foreign_writer", "foreign_body"}:
                    if fault == "foreign_body":
                        connection.sendall(raw[:4])
                        raw = raw[4:]
                    writer = os.fork()
                    if writer == 0:
                        try:
                            connection.sendall(raw)
                            os._exit(0)
                        except BaseException:
                            os._exit(6)
                    os.waitpid(writer, 0)
                else:
                    for index in range(0, len(raw), 7):
                        connection.sendall(raw[index : index + 7])
                connection.close()
                os._exit(0)
            worker = BenchmarkWorkerChannel(
                connection,
                invocation,
                expected_peer=creator,
                peer_fence=lambda actual: None,
                expires_ns=expires,
            )
            for checkpoint in program.checkpoints:
                worker.send_checkpoint(checkpoint)
                worker.receive_ack()
            worker.exchange_resources(local_resources(ordinal))
            worker.close()
            os._exit(0)
        except BaseException:
            os._exit(5)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if passcred:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    client.connect(path)
    fences, authorizations = [], []
    owner = None
    try:
        actual_creator = BenchmarkUnixPeer(
            *struct.unpack("=iII", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        )
        assert actual_creator == creator and creator.pid != child
        owner = BenchmarkOwnerChannel.from_activated_listener(
            client,
            invocation,
            expected_listener=creator,
            expected_sender=peer(child + expected_sender_offset),
            peer_fence=lambda value: fences.append(value),
            continuation_fence=lambda value: authorizations.append(value),
            expires_ns=expires,
        )
        yield owner, program, fences, authorizations, client
    finally:
        if owner is not None:
            owner.close()
        client.close()
        listener.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            finished, status = os.waitpid(child, os.WNOHANG)
            if finished:
                if fault is None and not expected_sender_offset and passcred:
                    assert os.waitstatus_to_exitcode(status) == 0
                break
            time.sleep(0.01)
        else:
            # This exact unreaped child cannot be PID-reused; never touch another process.
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
            pytest.fail("private inherited-listener child did not exit")


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_real_creator_and_writer_remain_distinct_through_full_program(tmp_path, ordinal):
    with inherited(tmp_path, ordinal) as (owner, program, fences, auth, client):
        for checkpoint in program.checkpoints:
            assert owner.receive_checkpoint() == checkpoint
            owner.acknowledge()
        assert owner.transcript() == program
        assert owner.finalize_resources(finalizer=lambda value: resources(ordinal)) == resources(
            ordinal
        )
        assert auth == list(program.checkpoints) and fences and set(fences) == {peer()}
        # Never substitute the writer for the actual connect-level creator PID.
        assert (
            BenchmarkUnixPeer(
                *struct.unpack("=iII", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            )
            == peer()
        )


def test_another_process_writing_inherited_connection_is_rejected_before_authorization(tmp_path):
    with inherited(tmp_path, fault="foreign_writer") as (owner, _program, _fences, auth, client):
        with pytest.raises(ValueError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert not auth and client.fileno() == -1


def test_writer_cannot_change_between_valid_header_and_body(tmp_path):
    with inherited(tmp_path, fault="foreign_body") as (owner, _program, _fences, auth, client):
        with pytest.raises(ValueError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert not auth and client.fileno() == -1


def test_wrong_native_sender_does_not_borrow_valid_listener_identity(tmp_path):
    with inherited(tmp_path, expected_sender_offset=1) as (owner, _program, _fences, auth, client):
        with pytest.raises(ValueError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert not auth and client.fileno() == -1


def test_fragmented_header_and_body_recheck_real_sender_on_each_read(tmp_path):
    with inherited(tmp_path, fault="fragmented") as (owner, program, fences, auth, _client):
        assert owner.receive_checkpoint() == program.checkpoints[0]
        assert not auth and fences


def test_disabled_passcred_is_refused_before_any_checkpoint(tmp_path):
    with pytest.raises(ValueError, match="CHANNEL_INVALID"), inherited(tmp_path, passcred=False):
        pytest.fail("disabled credentials accepted")


@pytest.mark.parametrize("count", (1, 16, 64))
def test_unexpected_fd_ancillary_is_refused_without_leaking_or_closing_original(count):
    sender, receiver = socket.socketpair()
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    descriptor = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
    owner = BenchmarkOwnerChannel.from_activated_listener(
        receiver,
        worker_invocation(3),
        expected_listener=peer(),
        expected_sender=peer(),
        peer_fence=lambda value: None,
        continuation_fence=lambda value: pytest.fail("unexpected auth"),
        expires_ns=time.monotonic_ns() + 3 * 10**9,
    )
    before = len(os.listdir("/proc/self/fd"))
    try:
        sender.sendmsg(
            [b"x"],
            [
                (
                    socket.SOL_SOCKET,
                    socket.SCM_RIGHTS,
                    struct.pack("=" + "i" * count, *([descriptor] * count)),
                )
            ],
        )
        with pytest.raises(ValueError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert receiver.fileno() == -1
        assert len(os.listdir("/proc/self/fd")) == before - 1
        os.fstat(descriptor)  # Receiver may close only newly kernel-delivered duplicates.
    finally:
        owner.close()
        sender.close()
        receiver.close()
        os.close(descriptor)
