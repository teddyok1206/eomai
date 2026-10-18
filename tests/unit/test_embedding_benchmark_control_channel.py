"""Actual same-process Unix framing/duplicate lifetime; root/source/cleanup are synthetic."""

import os
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel

from tests.unit.embedding_benchmark_control_fixtures import (
    association,
    completed,
    prepared,
    uncertain,
)
from tests.unit.embedding_device_benchmark_fixtures import resources, worker_invocation
from tests.unit.test_embedding_benchmark_channel import local_resources


def test_root_accepts_original_association_once_and_preserves_its_absolute_control_deadline():
    value = association(1)
    left, right = socket.socketpair()
    peer = BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())
    kwargs = dict(expected_peer=peer, peer_fence=lambda _: None, controller_release="a" * 40)
    owner = BenchmarkLaunchControlChannel(left, value, side="OWNER", **kwargs)
    root = None
    try:
        owner.send_association()
        root = BenchmarkLaunchControlChannel.accept_root_association(
            right, accept_until_ns=time.monotonic_ns() + 30 * 10**9, **kwargs
        )
        root.require_root_association(value, expected_peer=peer, controller_release="a" * 40)
        assert root._frames.expires_ns == value.expires_ns + 30 * 10**9
        with pytest.raises(ValueError, match="ORDER_INVALID"):
            root.receive_association()
    finally:
        owner.close()
        if root is not None:
            root.close()
        right.close()


@pytest.mark.parametrize("fault", ["foreign-message", "oversize", "eof", "peer", "timeout"])
def test_initial_receive_refuses_foreign_frames_or_peer_without_reusing_a_stream(fault):
    from eom_workflow.embedding_benchmark_launch_control import benchmark_launch_control_bytes

    value = association(1)
    left, right = socket.socketpair()
    peer = BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())
    deadline = time.monotonic_ns() + (20_000_000 if fault == "timeout" else 10**9)
    try:
        if fault == "foreign-message":
            raw = benchmark_launch_control_bytes(prepared(value))
            left.sendall(struct.pack("!I", len(raw)) + raw)
        elif fault == "oversize":
            left.sendall(struct.pack("!I", 65537))
        elif fault == "eof":
            left.close()
        elif fault == "peer":
            peer = BenchmarkUnixPeer(os.getpid() + 1, os.getuid(), os.getgid())
        with pytest.raises(ValueError):
            BenchmarkLaunchControlChannel.accept_root_association(
                right,
                expected_peer=peer,
                peer_fence=lambda _: None,
                controller_release="a" * 40,
                accept_until_ns=deadline,
            )
        assert right.fileno() == -1
    finally:
        left.close()
        right.close()


def endpoints(ordinal):
    value = association(ordinal)
    left, right = socket.socketpair()
    peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
    kwargs = dict(expected_peer=peer, peer_fence=lambda actual: None, controller_release="a" * 40)
    return (
        value,
        BenchmarkLaunchControlChannel(left, value, side="OWNER", **kwargs),
        BenchmarkLaunchControlChannel(right, value, side="ROOT", **kwargs),
        peer,
    )


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_prepare_resource_duplicate_and_original_completion_share_one_connection(ordinal):
    value, owner, root, peer = endpoints(ordinal)
    before, after = prepared(value), completed(value, prepared(value))
    try:
        owner.send_association()
        assert root.receive_association() == value
        root.send_prepared(before)
        assert owner.receive_prepared() == before
        if value.device == "CUDA":
            with owner.resources() as left, root.resources() as right:
                kwargs = dict(
                    expected_peer=peer, peer_fence=lambda actual: None, expires_ns=value.expires_ns
                )
                caller = BenchmarkResourceChannel(left, worker_invocation(ordinal), **kwargs)
                server = BenchmarkResourceChannel(right, worker_invocation(ordinal), **kwargs)
                caller.send_resources(local_resources(ordinal))
                assert server.receive_resources() == local_resources(ordinal)
                server.send_resources(resources(ordinal))
                assert caller.receive_resources() == resources(ordinal)
                caller.close()
                server.close()
        root.send_completed(after)
        assert owner.receive_completed() == after
        with pytest.raises(ValueError):
            owner.send_association()
    finally:
        owner.close()
        root.close()


def test_uncertainty_before_prepared_is_terminal_and_not_permission_to_retry():
    value, owner, root, _peer = endpoints(1)
    try:
        owner.send_association()
        root.receive_association()
        root.send_uncertain(uncertain(value))
        assert owner.receive_prepared() == uncertain(value)
        with pytest.raises(ValueError):
            owner.send_association()
    finally:
        owner.close()
        root.close()


def test_unclosed_resource_duplicate_and_exception_poison_original_stream():
    value, owner, root, _peer = endpoints(2)
    try:
        owner.send_association()
        root.receive_association()
        root.send_prepared(prepared(value))
        owner.receive_prepared()
        with pytest.raises(ValueError, match="RESOURCE_NOT_CLOSED"), owner.resources():
            pass
        with pytest.raises(ValueError):
            owner.receive_completed()
    finally:
        owner.close()
        root.close()


def test_completion_cannot_skip_cuda_resource_exchange():
    value, owner, root, _peer = endpoints(2)
    try:
        owner.send_association()
        root.receive_association()
        root.send_prepared(prepared(value))
        owner.receive_prepared()
        with pytest.raises(ValueError, match="COMPLETION_ORDER_INVALID"):
            root.send_completed(completed(value, prepared(value)))
    finally:
        owner.close()
        root.close()


def test_root_stays_alive_until_owner_has_consumed_completion_and_closed():
    value, owner, root, _peer = endpoints(4)
    try:
        owner.send_association()
        root.receive_association()
        root.send_prepared(prepared(value))
        owner.receive_prepared()
        root.send_completed(completed(value, prepared(value)))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(root.wait_for_owner_close)
            assert owner.receive_completed() == completed(value, prepared(value))
            assert not future.done()
            owner.close()
            assert future.result(timeout=3) is None
    finally:
        owner.close()
        root.close()


def test_terminal_channel_never_interprets_trailing_bytes_as_another_command():
    value, owner, root, _peer = endpoints(4)
    try:
        owner.send_association()
        root.receive_association()
        root.send_prepared(prepared(value))
        owner.receive_prepared()
        root.send_completed(completed(value, prepared(value)))
        owner.receive_completed()
        owner._transport().send_raw(b"not-a-command")
        with pytest.raises(ValueError, match="TRAILING_INPUT"):
            root.wait_for_owner_close()
    finally:
        owner.close()
        root.close()
