"""Real bounded Unix framing; same-process peers/synthetic sources, not a live root or GPU."""

from __future__ import annotations

import array
import os
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_batch_owner_channel as channel_module
from eom_catalog_service.embedding_batch_owner_channel import (
    EmbeddingBatchOwnerChannel,
    EmbeddingBatchOwnerChannelError,
)
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_workflow.embedding_batch_owner_control import (
    MAX_BATCH_OWNER_CHECKS,
    EmbeddingBatchRootCheck,
    embedding_batch_owner_control_bytes,
    parse_embedding_batch_owner_control,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import RELEASE, control_frames


@contextmanager
def endpoints(*, ready=True, bound=True, peer_fence=None):
    value = control_frames()
    left, right = socket.socketpair()
    for connection in (left, right):
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
    observations = []

    def fence(actual):
        assert actual == peer
        observations.append(actual)
        if peer_fence is not None:
            return peer_fence(actual)

    root = EmbeddingBatchOwnerChannel(
        left,
        value.request,
        controller_release=RELEASE,
        side="ROOT",
        expected_peer=peer,
        peer_fence=fence,
    )
    owner = EmbeddingBatchOwnerChannel(
        right,
        value.request,
        controller_release=RELEASE,
        side="OWNER",
        expected_peer=peer,
        peer_fence=fence,
    )
    try:
        if ready:
            root.send_ready(value.ready)
            assert owner.receive_allocation() == value.ready
        if bound:
            owner.send_binding(value.bound)
            assert root.receive_binding() == value.bound
        yield root, owner, value, observations, left, right
    finally:
        root.close()
        owner.close()


def raw_send(connection, value):
    raw = embedding_batch_owner_control_bytes(value)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def checked_once(root, owner, value, authorizer=lambda *_: None):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner.authorize_next, authorizer)
        root.check_child(value.batch.request_sha256, value.batch.children[0].request.request_sha256)
        assert future.result(timeout=2) is None


def test_ordered_checks_and_completion_require_source_and_output_verifiers():
    with endpoints() as (root, owner, value, observations, *_):
        checks, outputs = [], []
        for _ in range(3):
            checked_once(root, owner, value, lambda batch, child: checks.append((batch, child)))

        def receive():
            completed = owner.authorize_next(lambda *_: pytest.fail("unexpected new check"))
            assert completed == value.completed
            owner.acknowledge_completion(lambda notice: outputs.append(notice))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(receive)
            root.send_completed(value.completed)
            future.result(timeout=2)
        assert len(checks) == 3 and outputs == [value.completed] and observations
        assert root.require_direct_peer().pid == os.getpid()
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.check_child(value.batch.request_sha256, value.check.child_request_sha256)


@pytest.mark.parametrize("result", (False, "denied"))
def test_denied_or_false_source_fence_never_sends_success_ack(result):
    with endpoints() as (root, owner, value, *_):

        def deny(*_):
            if result == "denied":
                raise PermissionError("synthetic source revoked")
            return False

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(owner.authorize_next, deny)
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                root.check_child(value.batch.request_sha256, value.check.child_request_sha256)
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                future.result(timeout=2)


def test_busy_is_terminal_and_cannot_authorize_or_bind_compute():
    with endpoints(ready=False, bound=False) as (root, owner, value, *_):
        root.send_busy(value.busy)
        assert owner.receive_allocation() == value.busy
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.send_binding(value.bound)
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.send_ready(value.ready)


@pytest.mark.parametrize("field", ("batch_request_sha256", "child_request_sha256", "sequence"))
def test_foreign_or_nonmonotonic_check_never_reaches_source_authorizer(field):
    with endpoints() as (_, owner, value, _, left, _right):
        body = value.check.model_dump(mode="json")
        body[field] = 2 if field == "sequence" else "sha256:" + "f" * 64
        invalid = EmbeddingBatchRootCheck.model_validate(seal(body, "message_sha256"))
        raw_send(left, invalid)
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.authorize_next(lambda *_: pytest.fail("foreign check authorized"))


@pytest.mark.parametrize(
    "field", ("ready_message_sha256", "input_raw_sha256", "unit_invocation_id")
)
def test_completion_cannot_close_a_different_original_grant_or_invocation(field):
    with endpoints() as (root, owner, value, *_):
        checked_once(root, owner, value)
        body = value.completed.model_dump(mode="json")
        if field == "unit_invocation_id":
            body[field] = "f" * 32
        else:
            grant_key = (
                "ready_message_sha256"
                if field == "ready_message_sha256"
                else "batch_input_raw_sha256"
            )
            body["grant"] = seal(
                body["grant"] | {grant_key: "sha256:" + "f" * 64}, "message_sha256"
            )
        invalid = parse_embedding_batch_owner_control(seal(body, "message_sha256"))
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.send_completed(invalid)


def test_completion_requires_at_least_one_fresh_source_check():
    with endpoints() as (root, _owner, value, *_), pytest.raises(EmbeddingBatchOwnerChannelError):
        root.send_completed(value.completed)


def test_output_verifier_failure_does_not_confirm_receipt_or_permit_replay():
    with endpoints() as (root, owner, value, *_):
        checked_once(root, owner, value)

        def reject():
            assert owner.authorize_next(lambda *_: None) == value.completed
            owner.acknowledge_completion(lambda _: False)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reject)
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                root.send_completed(value.completed)
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                future.result(timeout=2)
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.acknowledge_completion(lambda _: None)


def test_source_fence_replay_or_wrong_check_ack_is_rejected():
    with endpoints() as (root, _owner, value, _, _left, right):
        invalid = value.checked.model_dump(mode="json") | {"sequence": 2}
        raw_send(right, parse_embedding_batch_owner_control(seal(invalid, "message_sha256")))
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.check_child(value.batch.request_sha256, value.check.child_request_sha256)


def test_wrong_release_is_rejected_before_source_selection():
    with endpoints(ready=False, bound=False) as (_, owner, value, _, left, _right):
        invalid = value.ready.model_dump(mode="json") | {"controller_release": "f" * 40}
        raw_send(left, parse_embedding_batch_owner_control(seal(invalid, "message_sha256")))
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.receive_allocation()


@pytest.mark.parametrize("side", ("ROOT", "OWNER"))
def test_missing_sender_credentials_or_wrong_actual_peer_cannot_create_channel(side):
    value = control_frames()
    peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
    for wrong_peer in (False, True):
        left, right = socket.socketpair()
        try:
            if wrong_peer:
                left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            expected = BenchmarkUnixPeer(peer.pid + 1, peer.uid, peer.gid) if wrong_peer else peer
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                EmbeddingBatchOwnerChannel(
                    left,
                    value.request,
                    controller_release=RELEASE,
                    side=side,
                    expected_peer=expected,
                    peer_fence=lambda _: None,
                )
        finally:
            left.close()
            right.close()


def test_peer_authority_change_closes_the_original_channel():
    allowed = [True]

    def fence(_peer):
        if not allowed[0]:
            raise ValueError("synthetic peer changed")

    with endpoints(peer_fence=fence) as (root, _owner, value, *_):
        allowed[0] = False
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.check_child(value.batch.request_sha256, value.check.child_request_sha256)


def test_unexpected_descriptor_is_closed_and_never_accepted_as_a_lease():
    with endpoints(ready=False, bound=False) as (_, owner, value, _, left, _right):
        raw = embedding_batch_owner_control_bytes(value.ready)
        descriptor = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        try:
            left.sendmsg(
                [struct.pack("!I", len(raw)) + raw],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [descriptor]))],
            )
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                owner.receive_allocation()
        finally:
            os.close(descriptor)


def test_partial_frame_and_deadline_are_not_permission_to_restart():
    with endpoints(ready=False, bound=False) as (_, owner, value, _, left, _right):
        raw = embedding_batch_owner_control_bytes(value.ready)
        left.sendall(struct.pack("!I", len(raw)) + raw[:10])
        left.close()
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            owner.receive_allocation()
    with endpoints() as (root, _, value, *_):
        root._frames.expires_ns = time.monotonic_ns() - 1
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.check_child(value.batch.request_sha256, value.check.child_request_sha256)


def test_original_lifetime_bounds_source_checks():
    with endpoints() as (root, _owner, value, *_):
        root._sequence = MAX_BATCH_OWNER_CHECKS
        with pytest.raises(EmbeddingBatchOwnerChannelError):
            root.check_child(value.batch.request_sha256, value.check.child_request_sha256)


@pytest.mark.parametrize("terminal", (False, True))
@pytest.mark.parametrize("fault", ("gone", "reused", "permission"))
def test_original_peer_guard_only_allows_kernel_confirmed_exit_after_terminal_exchange(
    monkeypatch, terminal, fault
):
    value = control_frames()
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
    birth = benchmark_owner_start_ticks(peer.pid, uid=peer.uid, gid=peer.gid)
    # Explicit local role seam; actual root/runner UID testing is opt-in and separate.
    monkeypatch.setattr(
        channel_module,
        "os",
        SimpleNamespace(getresuid=lambda: (0, 0, 0), getresgid=lambda: (0, 0, 0)),
    )
    monkeypatch.setattr(
        channel_module,
        "fixed_owner_identity",
        lambda: SimpleNamespace(owner_uid=peer.uid, owner_gid=peer.gid),
    )
    channel = channel_module.bind_original_embedding_batch_owner_channel(
        left,
        value.request,
        controller_release=RELEASE,
        side="ROOT",
        expected_peer=peer,
        peer_start_ticks=birth,
    )
    try:
        if terminal:
            channel._phase = channel_module._Phase.COMPLETED

        def observed(*_args, **_kwargs):
            if fault == "reused":
                return birth + 1
            raise ValueError("synthetic proc unavailable")

        monkeypatch.setattr(channel_module, "benchmark_owner_start_ticks", observed)
        # Synthetic exit proof only in this guard unit test. The privileged test
        # exercises the actual pidfd when the real runner exits immediately at ACK.
        monkeypatch.setattr(channel._peer_lifetime, "wait_exited", lambda **_: fault == "gone")
        if terminal and fault == "gone":
            assert channel.require_direct_peer() == peer
        else:
            with pytest.raises(EmbeddingBatchOwnerChannelError):
                channel.require_direct_peer()
    finally:
        channel.close()
        right.close()
