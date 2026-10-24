"""Real Unix framing with synthetic work; not root admission or physical GPU evidence."""

from __future__ import annotations

import os
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from eom_catalog_contracts.embedding_gpu_control import (
    MAX_EMBEDDING_GPU_CONTROL_BYTES,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
)
from eom_catalog_contracts.embedding_work_batch_result import (
    build_embedding_work_batch_result,
    embedding_work_batch_result_bytes,
)
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_gpu_control_channel import (
    EmbeddingGpuChannelError,
    EmbeddingGpuControlChannel,
)
from eom_catalog_service.embedding_work_batch_execution import execute_embedding_work_batch
from eom_identifiers import sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_gpu_control import control_case
from tests.unit.test_embedding_work_batch import Fence
from tests.unit.test_embedding_work_batch_result import local_case


def send_raw(connection, value):
    raw = embedding_gpu_control_bytes(value)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


@contextmanager
def endpoints(
    *, requested=True, ready=True, granted=True, bound=True, sender=None, peer_fence=None
):
    case = control_case(expires_ns=time.monotonic_ns() + 15 * 10**9)
    request, allocation, _, grant, _, _, batch, raw = case
    left, right = socket.socketpair()
    for connection in (left, right):
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
    observations = []

    def fence(actual):
        assert actual == peer
        observations.append(actual)
        if peer_fence is not None:
            peer_fence(actual)

    root = EmbeddingGpuControlChannel(
        left,
        request,
        side="ROOT",
        expected_peer=peer,
        peer_fence=fence,
        expected_sender=sender,
    )
    worker = EmbeddingGpuControlChannel(
        right, request, side="WORKER", expected_peer=peer, peer_fence=fence
    )
    try:
        if requested:
            root.send_request()
            worker.receive_request()
        if ready:
            worker.send_allocation(allocation)
            assert root.receive_allocation() == allocation
        if granted:
            root.send_grant(grant)
            assert worker.receive_grant() == grant
        if bound:
            for channel in (root, worker):
                channel.bind_batch(
                    batch, input_raw_sha256=sha256_bytes(raw), input_byte_count=len(raw)
                )
        yield root, worker, case, observations, left, right
    finally:
        root.close()
        worker.close()


def synthetic_result():
    batch, _, scope, resources, _ = local_case(device="CUDA")
    encoded = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=Fence()
    )
    vectors = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        batch, tuple(child.result for child in encoded.children), sha256_bytes(vectors)
    )
    return result, vectors


def test_real_unix_round_trip_source_fences_before_each_encode_and_output_ack():
    with endpoints() as (root, worker, case, observations, _, _):
        batch, backend, scope, resources, life = local_case(device="CUDA")
        assert batch == case[6]
        authorized, outputs, verified = [], [], []

        def run():
            encoded = execute_embedding_work_batch(
                batch, resources=resources, backend_scope=scope, fence=worker
            )
            vectors = b"".join(child.vectors for child in encoded.children)
            result = build_embedding_work_batch_result(
                batch, tuple(child.result for child in encoded.children), sha256_bytes(vectors)
            )
            outputs.append((result, vectors))
            worker.announce_result(result)

        def verify(claim):
            result, vectors = outputs[0]
            raw = embedding_work_batch_result_bytes(result)
            assert claim.result_raw_sha256 == sha256_bytes(raw)
            assert claim.result_sha256 == result.result_sha256
            assert claim.result_byte_count == len(raw)
            assert claim.vectors_sha256 == sha256_bytes(vectors)
            assert claim.vectors_byte_count == len(vectors)
            verified.append(claim)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            while root.authorize_next(lambda check: authorized.append(check)) is None:
                pass
            root.acknowledge_result(verify)
            future.result(timeout=2)
        assert len(authorized) == 8  # before model load, before/after each child, after cleanup
        assert [check.sequence for check in authorized] == list(range(1, 9))
        assert {check.child_request_sha256 for check in authorized} == {
            child.request.request_sha256 for child in batch.children
        }
        assert life == ["open", "closed"] and len(backend.calls) == 2
        assert len(verified) == 1 and observations
        with pytest.raises(EmbeddingGpuChannelError):
            worker.assert_batch_current(batch)


def test_busy_is_terminal_and_cannot_receive_compute_grant():
    with endpoints(ready=False, granted=False, bound=False) as (root, worker, case, *_):
        worker.send_allocation(case[2])
        assert root.receive_allocation() == case[2]
        with pytest.raises(EmbeddingGpuChannelError):
            root.send_grant(case[3])
        with pytest.raises(EmbeddingGpuChannelError):
            root.send_request()


@pytest.mark.parametrize("side", ["ROOT", "WORKER"])
def test_missing_passcred_is_rejected_before_any_frame(side):
    left, right = socket.socketpair()
    request = control_case(expires_ns=time.monotonic_ns() + 10**9)[0]
    try:
        with pytest.raises(EmbeddingGpuChannelError):
            EmbeddingGpuControlChannel(
                left,
                request,
                side=side,
                expected_peer=BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid()),
                peer_fence=lambda _: None,
            )
        assert left.fileno() == -1
    finally:
        left.close()
        right.close()


def test_grant_before_ready_poisons_connection():
    with endpoints(ready=False, granted=False, bound=False) as (root, _, case, *_):
        with pytest.raises(EmbeddingGpuChannelError):
            root.send_grant(case[3])
        with pytest.raises(EmbeddingGpuChannelError):
            root.receive_allocation()


@pytest.mark.parametrize(
    "field", ["allocation_attempt_id", "batch_request_sha256", "child_request_sha256", "sequence"]
)
def test_root_rejects_foreign_or_skipped_child_before_authorizer(field):
    with endpoints() as (root, _, case, _, _, right):
        body = case[4].model_dump(mode="json")
        body[field] = (
            2
            if field == "sequence"
            else "embeddingallocation_" + "b" * 32
            if field == "allocation_attempt_id"
            else "sha256:" + "b" * 64
        )
        send_raw(right, parse_embedding_gpu_control(seal(body, "message_sha256")))
        called = []
        with pytest.raises(EmbeddingGpuChannelError):
            root.authorize_next(lambda check: called.append(check))
        assert not called


@pytest.mark.parametrize("fault", ["denied", "false"])
def test_source_denial_or_invalid_fence_return_does_not_ack(fault):
    with endpoints() as (root, worker, case, *_):

        def authorize(_):
            if fault == "denied":
                raise PermissionError("revoked")
            return False

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.assert_child_current, case[6], case[6].children[0])
            with pytest.raises(EmbeddingGpuChannelError):
                root.authorize_next(authorize)
            with pytest.raises(EmbeddingGpuChannelError):
                future.result(timeout=2)


def test_repeated_sequence_is_not_reauthorized():
    with endpoints() as (root, _, case, _, _, right):
        send_raw(right, case[4])
        called = []
        assert root.authorize_next(lambda check: called.append(check)) is None
        send_raw(right, case[4])
        with pytest.raises(EmbeddingGpuChannelError):
            root.authorize_next(lambda check: called.append(check))
        assert len(called) == 1


def test_forged_result_before_all_child_fences_is_rejected():
    with endpoints() as (root, _, case, _, _, right):
        result, _ = synthetic_result()
        body = {
            "schema_version": "embedding-gpu-allocation-control/1.0",
            "message_type": "RESULT_READY",
            "allocation_attempt_id": case[0].allocation_attempt_id,
            "allocation_request_sha256": case[0].message_sha256,
            "grant_message_sha256": case[3].message_sha256,
            "batch_request_sha256": case[6].request_sha256,
            "result_raw_sha256": sha256_bytes(embedding_work_batch_result_bytes(result)),
            "result_sha256": result.result_sha256,
            "vectors_sha256": result.vectors.sha256,
            "result_byte_count": len(embedding_work_batch_result_bytes(result)),
            "vectors_byte_count": result.vectors.byte_count,
        }
        send_raw(right, parse_embedding_gpu_control(seal(body, "message_sha256")))
        with pytest.raises(EmbeddingGpuChannelError):
            root.authorize_next(lambda _: None)


@pytest.mark.parametrize("fault", ["raw_hash", "count", "double_bind"])
def test_binding_requires_actual_input_hash_count_and_single_assignment(fault):
    with endpoints(bound=False) as (root, _, case, *_):
        batch, raw = case[6:]
        digest, count = sha256_bytes(raw), len(raw)
        if fault == "double_bind":
            root.bind_batch(batch, input_raw_sha256=digest, input_byte_count=count)
        elif fault == "count":
            count += 1
        else:
            digest = "sha256:" + "e" * 64
        with pytest.raises(EmbeddingGpuChannelError):
            root.bind_batch(batch, input_raw_sha256=digest, input_byte_count=count)


def test_oversized_header_is_rejected_without_waiting_for_body():
    with endpoints(ready=False, granted=False, bound=False) as (root, _, _, _, _, right):
        right.sendall(struct.pack("!I", MAX_EMBEDDING_GPU_CONTROL_BYTES + 1))
        with pytest.raises(EmbeddingGpuChannelError):
            root.receive_allocation()


def test_kernel_sender_mismatch_is_not_hidden_by_matching_socket_peer():
    peer = BenchmarkUnixPeer(os.getpid() + 1, os.geteuid(), os.getegid())
    with endpoints(ready=False, granted=False, bound=False, sender=peer) as (
        root,
        worker,
        case,
        *_,
    ):
        worker.send_allocation(case[1])
        with pytest.raises(EmbeddingGpuChannelError):
            root.receive_allocation()


def test_expired_channel_is_not_reopened(monkeypatch):
    with endpoints() as (root, _, case, *_):
        monkeypatch.setattr(time, "monotonic_ns", lambda: case[0].expires_monotonic_ns)
        with pytest.raises(EmbeddingGpuChannelError):
            root.authorize_next(lambda _: None)
        with pytest.raises(EmbeddingGpuChannelError):
            root.send_request()


@pytest.mark.parametrize("fault", ["denied", "false"])
def test_root_output_verifier_failure_does_not_ack_local_output(fault):
    with endpoints() as (root, worker, case, *_):
        result, _ = synthetic_result()

        def run():
            for child in case[6].children:
                worker.assert_child_current(case[6], child)
            worker.announce_result(result)

        def verify(_):
            if fault == "denied":
                raise PermissionError("hash or source revalidation failed")
            return False

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            while root.authorize_next(lambda _: None) is None:
                pass
            with pytest.raises(EmbeddingGpuChannelError):
                root.acknowledge_result(verify)
            with pytest.raises(EmbeddingGpuChannelError):
                future.result(timeout=2)


def test_live_identity_fence_revocation_closes_channel_before_send():
    state = [True]

    def fence(_):
        if not state[0]:
            raise PermissionError("original unit identity changed")

    with endpoints(peer_fence=fence) as (root, _, _, _, left, _):
        state[0] = False
        with pytest.raises(EmbeddingGpuChannelError):
            root.authorize_next(lambda _: None)
        assert left.fileno() == -1
