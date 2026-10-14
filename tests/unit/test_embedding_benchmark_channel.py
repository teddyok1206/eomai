"""Real unprivileged Unix sockets with synthetic gates; no source/model/runtime grant."""

from __future__ import annotations

import multiprocessing
import os
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkAck,
    BenchmarkCheckpoint,
    BenchmarkResourceEvidence,
    benchmark_ack_for_checkpoint,
    benchmark_checkpoint_count,
    embedding_device_benchmark_bytes,
    validate_benchmark_ack,
    validate_benchmark_checkpoint,
)
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkOwnerChannel,
    BenchmarkUnixPeer,
    BenchmarkWorkerChannel,
)

from tests.unit.embedding_device_benchmark_fixtures import resources, session, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal


def peer() -> BenchmarkUnixPeer:
    return BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())


def synthetic_peer_fence(value: BenchmarkUnixPeer) -> None:
    assert value == peer()


def synthetic_continuation(value: BenchmarkCheckpoint) -> None:
    assert value.kind == "LOCAL_CHECKPOINT"


def local_resources(ordinal: int) -> BenchmarkResourceEvidence:
    body = resources(ordinal).model_dump(mode="json")
    body.update(
        peak_whole_process_gpu_bytes=None,
        peak_whole_device_gpu_bytes=None,
        owner_observation_count=0,
        other_consumer_overlap_count=0,
    )
    for sample in body["capacity_samples"]:
        sample["peak_whole_process_gpu_bytes"] = None
    return BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))


def complete_checkpoints(
    worker: BenchmarkWorkerChannel, owner: BenchmarkOwnerChannel, ordinal: int
) -> None:
    for checkpoint in session(ordinal).checkpoints:
        worker.send_checkpoint(checkpoint)
        assert owner.receive_checkpoint() == checkpoint
        owner.acknowledge()
        worker.receive_ack()


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_original_invocation_is_peer_checked_before_any_phase_or_model(ordinal: int) -> None:
    with endpoints(ordinal) as (worker, owner):
        worker.assert_initial_invocation(worker_invocation(ordinal))
        # This read-only assertion creates no checkpoint or continuation ACK.
        with pytest.raises(BenchmarkChannelError, match="INCOMPLETE"):
            owner.transcript()


@pytest.mark.parametrize("fault", ("foreign", "pending", "completed", "closed", "revoked"))
def test_foreign_or_consumed_channel_cannot_start_another_invocation(fault: str) -> None:
    with endpoints(3) as (worker, owner):
        expected = worker_invocation(3)
        if fault == "foreign":
            expected = worker_invocation(4)
        elif fault == "pending":
            worker.send_checkpoint(session(3).checkpoints[0])
        elif fault == "completed":
            complete_checkpoints(worker, owner, 3)
        elif fault == "closed":
            worker.close()
        else:

            def revoked(_peer: BenchmarkUnixPeer) -> None:
                raise ValueError("synthetic late peer revocation")

            worker._exchange.frames.peer_fence = revoked
        with pytest.raises(BenchmarkChannelError, match="INITIAL_INVOCATION_INVALID"):
            worker.assert_initial_invocation(expected)
        with pytest.raises(BenchmarkChannelError, match="INITIAL_INVOCATION_INVALID"):
            worker.assert_initial_invocation(worker_invocation(3))


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_one_terminal_resource_roundtrip_preserves_historical_checkpoint_program(
    ordinal: int,
) -> None:
    results: list[BenchmarkResourceEvidence] = []
    calls: list[BenchmarkResourceEvidence] = []
    with endpoints(ordinal) as (worker, owner):
        complete_checkpoints(worker, owner, ordinal)
        before = worker.transcript()
        local, finalized = local_resources(ordinal), resources(ordinal)

        def exchange() -> None:
            results.append(worker.exchange_resources(local))

        def synthetic_finalizer(value: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
            assert value == local
            calls.append(value)
            return finalized

        thread = threading.Thread(target=exchange)
        thread.start()
        try:
            assert owner.finalize_resources(finalizer=synthetic_finalizer) == finalized
        finally:
            thread.join(timeout=2)
        assert not thread.is_alive() and results == [finalized] and calls == [local]
        assert worker.transcript() == owner.transcript() == before == session(ordinal)
        actions: tuple[
            tuple[
                BenchmarkWorkerChannel | BenchmarkOwnerChannel,
                Callable[[], BenchmarkResourceEvidence],
            ],
            ...,
        ] = (
            (worker, lambda: worker.exchange_resources(local)),
            (owner, lambda: owner.finalize_resources(finalizer=synthetic_finalizer)),
        )
        for channel, action in actions:
            with pytest.raises(BenchmarkChannelError, match="RESOURCE"):
                action()
            # History is not evidence that repeated resource finalization was admitted.
            assert channel.transcript() == before
        assert len(calls) == 1


@pytest.mark.parametrize("side", ("worker", "owner"))
def test_terminal_resources_cannot_start_before_exact_checkpoint_completion(side: str) -> None:
    with endpoints(3) as (worker, owner):
        with pytest.raises(BenchmarkChannelError, match="RESOURCE"):
            if side == "worker":
                worker.exchange_resources(local_resources(3))
            else:
                owner.finalize_resources(finalizer=lambda value: value)
        with pytest.raises(BenchmarkChannelError, match="INCOMPLETE"):
            (worker if side == "worker" else owner).transcript()


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "raises",
        "wrong_type",
        "local_rss",
        "mutate_alias",
        "capacity_bound",
        "count",
        "invocation",
        "device",
        "bool",
    ),
)
def test_missing_or_malicious_finalizer_closes_both_sides_without_resource_success(
    case: str,
) -> None:
    errors: list[str] = []
    with endpoints(2) as (worker, owner):
        complete_checkpoints(worker, owner, 2)
        historical = worker.transcript()
        local = local_resources(2)

        def exchange() -> None:
            try:
                worker.exchange_resources(local)
            except BenchmarkChannelError as exc:
                errors.append(exc.code)

        def synthetic(value: BenchmarkResourceEvidence) -> Any:
            if case == "raises":
                raise RuntimeError("synthetic late fence failure")
            if case == "wrong_type":
                return True
            body = resources(2).model_dump(mode="json")
            if case in {"local_rss", "mutate_alias"}:
                body["peak_rss_bytes"] += 1
                if case == "mutate_alias":
                    object.__setattr__(value, "peak_rss_bytes", body["peak_rss_bytes"])
            elif case == "capacity_bound":
                body["capacity_samples"][0]["peak_whole_process_gpu_bytes"] = 1
            elif case == "count":
                body["owner_observation_count"] = 0
            elif case == "invocation":
                body["invocation_sha256"] = "sha256:" + "f" * 64
            elif case == "device":
                return resources(1)
            result = BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
            return (
                result.model_copy(update={"owner_observation_count": True})
                if case == "bool"
                else result
            )

        thread = threading.Thread(target=exchange)
        thread.start()
        try:
            with pytest.raises(BenchmarkChannelError, match="FINALIZATION_FAILED"):
                candidate: Any = None if case == "missing" else synthetic
                owner.finalize_resources(finalizer=candidate)
        finally:
            thread.join(timeout=2)
        assert not thread.is_alive() and errors == ["EMBEDDING_BENCHMARK_RESOURCE_EXCHANGE_FAILED"]
        assert local == local_resources(2)
        assert worker.transcript() == owner.transcript() == historical


@pytest.mark.parametrize("side", ("worker", "owner"))
@pytest.mark.parametrize("case", ("noncanonical", "wrong_kind", "foreign", "copied_bool", "eof"))
def test_untrusted_terminal_resource_frames_are_rejected_on_both_endpoints(
    side: str, case: str
) -> None:
    left, right = socket.socketpair()
    deadline = time.monotonic_ns() + 2 * 10**9
    invocation = worker_invocation(3)
    worker = BenchmarkWorkerChannel(
        left, invocation, expected_peer=peer(), peer_fence=synthetic_peer_fence, expires_ns=deadline
    )
    owner = BenchmarkOwnerChannel(
        right,
        invocation,
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=deadline,
    )
    try:
        complete_checkpoints(worker, owner, 3)
        raw = embedding_device_benchmark_bytes(local_resources(3))
        if case == "noncanonical":
            raw += b"\n"
        elif case == "wrong_kind":
            raw = embedding_device_benchmark_bytes(session(3).acks[0])
        elif case == "foreign":
            body = local_resources(3).model_dump(mode="json")
            body["invocation_sha256"] = "sha256:" + "f" * 64
            raw = embedding_device_benchmark_bytes(
                BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
            )
        elif case == "copied_bool":
            raw = raw.replace(b'"owner_observation_count":0', b'"owner_observation_count":true')
        sender = right if side == "worker" else left
        if case == "eof":
            sender.shutdown(socket.SHUT_WR)
        else:
            sender.sendall(struct.pack("!I", len(raw)) + raw)
        with pytest.raises(BenchmarkChannelError, match="RESOURCE"):
            if side == "worker":
                worker.exchange_resources(local_resources(3))
            else:
                owner.finalize_resources(finalizer=lambda value: value)
        # CP program is complete, not resource success or current authority.
        assert (worker if side == "worker" else owner).transcript() == session(3)
    finally:
        worker.close()
        owner.close()


@pytest.mark.parametrize("case", ("peer", "deadline", "fd"))
def test_late_finalizer_rechecks_same_peer_fd_and_absolute_deadline(case: str) -> None:
    left, right = socket.socketpair()
    other_left, other_right = socket.socketpair()
    revoked = False
    now = time.monotonic_ns()
    clock = [now]

    def synthetic_peer(value: BenchmarkUnixPeer) -> None:
        assert value == peer()
        if revoked:
            raise RuntimeError("synthetic peer revoked")

    worker = BenchmarkWorkerChannel(
        left,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        expires_ns=now + 10**9,
    )
    owner = BenchmarkOwnerChannel(
        right,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer,
        continuation_fence=synthetic_continuation,
        expires_ns=now + 10**9,
    )
    errors: list[str] = []

    def exchange() -> None:
        try:
            worker.exchange_resources(local_resources(3))
        except BenchmarkChannelError as exc:
            errors.append(exc.code)

    def synthetic_finalizer(value: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
        nonlocal revoked
        if case == "peer":
            revoked = True
        elif case == "deadline":
            clock[0] += 10**9
        else:
            os.dup2(other_right.fileno(), right.fileno(), inheritable=False)
        return value

    try:
        complete_checkpoints(worker, owner, 3)
        with pytest.MonkeyPatch.context() as patch:
            if case == "deadline":
                patch.setattr(time, "monotonic_ns", lambda: clock[0])
            thread = threading.Thread(target=exchange)
            thread.start()
            try:
                with pytest.raises(BenchmarkChannelError, match="FINALIZATION_FAILED"):
                    owner.finalize_resources(finalizer=synthetic_finalizer)
            finally:
                thread.join(timeout=2)
            assert not thread.is_alive() and errors
        assert owner.transcript() == session(3)
    finally:
        worker.close()
        owner.close()
        other_left.close()
        other_right.close()


def test_resource_on_ordinary_checkpoint_route_is_not_admitted_early() -> None:
    sender, receiver = socket.socketpair()
    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    try:
        raw = embedding_device_benchmark_bytes(local_resources(3))
        sender.sendall(struct.pack("!I", len(raw)) + raw)
        with pytest.raises(BenchmarkChannelError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert receiver.fileno() == -1
    finally:
        owner.close()
        sender.close()


@pytest.mark.parametrize("size", (0, 65537, 2**32 - 1))
def test_terminal_announcement_is_bounded_before_payload_or_json_allocation(
    size: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eom_catalog_service import embedding_benchmark_channel as module

    left, right = socket.socketpair()
    deadline = time.monotonic_ns() + 10**9
    worker = BenchmarkWorkerChannel(
        left,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        expires_ns=deadline,
    )
    owner = BenchmarkOwnerChannel(
        right,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=deadline,
    )

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("oversized terminal frame must not parse")

    try:
        complete_checkpoints(worker, owner, 3)
        monkeypatch.setattr(module, "parse_embedding_device_benchmark_bytes", forbidden)
        left.sendall(struct.pack("!I", size))
        with pytest.raises(BenchmarkChannelError, match="FINALIZATION_FAILED"):
            owner.finalize_resources(finalizer=lambda value: value)
        assert right.fileno() == -1 and owner.transcript() == session(3)
    finally:
        worker.close()
        owner.close()


def test_terminal_absolute_deadline_is_not_reset_by_partial_progress() -> None:
    left, right = socket.socketpair()
    deadline = time.monotonic_ns() + 2 * 10**9
    clock = [deadline - 40_000_000]
    worker = BenchmarkWorkerChannel(
        left,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        expires_ns=deadline,
    )
    owner = BenchmarkOwnerChannel(
        right,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=deadline,
    )
    try:
        complete_checkpoints(worker, owner, 3)
        left.sendall(b"\x00")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic_ns", lambda: clock[0])
            started = time.perf_counter()
            with pytest.raises(BenchmarkChannelError, match="FINALIZATION_FAILED"):
                owner.finalize_resources(finalizer=lambda value: value)
            elapsed = time.perf_counter() - started
        assert elapsed < 0.5 and right.fileno() == -1
        assert owner.transcript() == session(3)
    finally:
        worker.close()
        owner.close()


def test_worker_resource_wait_uses_immutable_local_snapshot_not_caller_alias() -> None:
    local = local_resources(3)
    original = resources(3)
    results: list[BenchmarkResourceEvidence] = []
    with endpoints(3) as (worker, owner):
        complete_checkpoints(worker, owner, 3)

        def exchange() -> None:
            results.append(worker.exchange_resources(local))

        def synthetic(value: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
            assert value.peak_rss_bytes == 1024
            object.__setattr__(local, "peak_rss_bytes", 2048)
            return original

        thread = threading.Thread(target=exchange)
        thread.start()
        try:
            owner.finalize_resources(finalizer=synthetic)
        finally:
            thread.join(timeout=2)
        assert not thread.is_alive() and results == [original]
        assert local.peak_rss_bytes == 2048 and results[0].peak_rss_bytes == 1024


@contextmanager
def endpoints(
    ordinal: int = 1,
    continuation: Callable[[BenchmarkCheckpoint], None] = synthetic_continuation,
) -> Iterator[tuple[BenchmarkWorkerChannel, BenchmarkOwnerChannel]]:
    left, right = socket.socketpair()
    deadline = time.monotonic_ns() + 10**10
    invocation = worker_invocation(ordinal)
    worker = BenchmarkWorkerChannel(
        left, invocation, expected_peer=peer(), peer_fence=synthetic_peer_fence, expires_ns=deadline
    )
    owner = BenchmarkOwnerChannel(
        right,
        invocation,
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=continuation,
        expires_ns=deadline,
    )
    try:
        yield worker, owner
    finally:
        worker.close()
        owner.close()


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_actual_socket_fixed_program_and_shared_pure_transcript(ordinal: int) -> None:
    expected = session(ordinal)
    observed: list[BenchmarkCheckpoint] = []
    with endpoints(ordinal, observed.append) as (worker, owner):
        for checkpoint, ack in zip(expected.checkpoints, expected.acks, strict=True):
            worker.send_checkpoint(checkpoint)
            assert owner.receive_checkpoint() == checkpoint
            assert owner.acknowledge() == ack
            assert worker.receive_ack() == ack
        assert observed == list(expected.checkpoints)
        assert worker.transcript() == owner.transcript() == expected
        owner.close()
        # Completed metadata remains historical evidence, never live permission/cleanup.
        assert owner.transcript() == expected


@pytest.mark.parametrize("ordinal,count", ((1, 21), (2, 21), (3, 1), (4, 1), (5, 1), (6, 1)))
def test_public_count_and_ack_rules_share_full_session_semantics(ordinal: int, count: int) -> None:
    invocation, expected = worker_invocation(ordinal), session(ordinal)
    assert benchmark_checkpoint_count(invocation) == count
    for checkpoint, ack in zip(expected.checkpoints, expected.acks, strict=True):
        validate_benchmark_checkpoint(invocation, checkpoint, checkpoint.sequence)
        validate_benchmark_ack(checkpoint, ack)
        assert benchmark_ack_for_checkpoint(checkpoint) == ack


@pytest.mark.parametrize("sequence", (0, True, 1.0, "1", 22))
def test_raw_expected_sequence_is_exact_before_sending(sequence: Any) -> None:
    with pytest.raises(ValueError):
        validate_benchmark_checkpoint(worker_invocation(), session().checkpoints[0], sequence)


@pytest.mark.parametrize("field", ("execution_id", "invocation_sha256", "vector"))
def test_wrong_child_or_purpose_space_resealed_checkpoint_denied(field: str) -> None:
    checkpoint = session().checkpoints[0]
    body = checkpoint.model_dump(mode="json")
    if field == "vector":
        body[field]["space_sha256"] = worker_invocation().runtime.spaces.query.space_sha256
    else:
        body[field] = "f" * 32 if field == "execution_id" else "sha256:" + "f" * 64
    value = BenchmarkCheckpoint.model_validate(seal(body, "checkpoint_sha256"))
    with pytest.raises(ValueError):
        validate_benchmark_checkpoint(worker_invocation(), value, 1)


def test_cold_only_child_cannot_add_a_query_phase() -> None:
    value = session().checkpoints[1]
    body = value.model_dump(mode="json")
    invocation = worker_invocation(3)
    body.update(
        execution_id=invocation.execution_id, invocation_sha256=invocation.invocation_sha256
    )
    checkpoint = BenchmarkCheckpoint.model_validate(seal(body, "checkpoint_sha256"))
    with pytest.raises(ValueError):
        validate_benchmark_checkpoint(invocation, checkpoint, 2)


@pytest.mark.parametrize("field", ("execution_id", "invocation_sha256", "checkpoint_sha256"))
def test_foreign_ack_hash_or_child_rejected(field: str) -> None:
    expected = session()
    body = expected.acks[0].model_dump(mode="json")
    body[field] = "f" * 32 if field == "execution_id" else "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        validate_benchmark_ack(expected.checkpoints[0], BenchmarkAck.model_validate(body))


def test_copied_bool_rejected_before_dump_in_direct_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session().checkpoints[0].model_copy(update={"sequence": True})

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("raw copied bool serialized")

    monkeypatch.setattr(BenchmarkCheckpoint, "model_dump", forbidden)
    for function in (
        lambda: benchmark_ack_for_checkpoint(value),
        lambda: validate_benchmark_checkpoint(worker_invocation(), value, 1),
    ):
        with pytest.raises(ValueError):
            function()


@pytest.mark.parametrize(
    "side,operation",
    (("worker", "ack"), ("owner", "ack"), ("worker", "repeat"), ("owner", "repeat")),
)
def test_exchanges_cannot_skip_or_duplicate_pending_ack(side: str, operation: str) -> None:
    with endpoints() as (worker, owner):
        if operation == "ack":
            with pytest.raises(BenchmarkChannelError):
                worker.receive_ack() if side == "worker" else owner.acknowledge()
        else:
            worker.send_checkpoint(session().checkpoints[0])
            owner.receive_checkpoint()
            with pytest.raises(BenchmarkChannelError):
                worker.send_checkpoint(
                    session().checkpoints[1]
                ) if side == "worker" else owner.receive_checkpoint()


def test_revoked_continuation_sends_no_ack_and_peer_observes_failure() -> None:
    def revoked(value: BenchmarkCheckpoint) -> None:
        raise RuntimeError("synthetic private authentication failure")

    with endpoints(continuation=revoked) as (worker, owner):
        worker.send_checkpoint(session().checkpoints[0])
        owner.receive_checkpoint()
        with pytest.raises(BenchmarkChannelError, match="CONTINUATION_FAILED"):
            owner.acknowledge()
        with pytest.raises(BenchmarkChannelError, match="ACK_RECEIVE_FAILED"):
            worker.receive_ack()
        for channel in (worker, owner):
            with pytest.raises(BenchmarkChannelError, match="INCOMPLETE"):
                channel.transcript()


@pytest.mark.parametrize("size", (0, 65537, 2**32 - 1))
def test_announced_overflow_is_rejected_before_payload_or_json_allocation(
    size: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eom_catalog_service import embedding_benchmark_channel as module

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("JSON must not parse oversized announcement")

    monkeypatch.setattr(module, "parse_embedding_device_benchmark_bytes", forbidden)
    sender, receiver = socket.socketpair()
    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    try:
        sender.sendall(struct.pack("!I", size))
        with pytest.raises(BenchmarkChannelError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert receiver.fileno() == -1
    finally:
        sender.close()
        owner.close()


@pytest.mark.parametrize(
    "case", ("noncanonical", "wrong_kind", "truncated", "duplicate", "invalid_json")
)
def test_untrusted_frames_are_closed_without_transcript(case: str) -> None:
    sender, receiver = socket.socketpair()
    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    raw = embedding_device_benchmark_bytes(session().checkpoints[0])
    if case == "noncanonical":
        raw += b"\n"
    elif case == "wrong_kind":
        raw = embedding_device_benchmark_bytes(session().acks[0])
    elif case == "duplicate":
        raw = b'{"a":1,"a":2}'
    elif case == "invalid_json":
        raw = b'{"a":'
    try:
        sender.sendall(struct.pack("!I", len(raw)) + (raw[:10] if case == "truncated" else raw))
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(BenchmarkChannelError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert receiver.fileno() == -1
        with pytest.raises(BenchmarkChannelError, match="INCOMPLETE"):
            owner.transcript()
    finally:
        sender.close()
        owner.close()


def test_absolute_deadline_is_not_reset_by_partial_header_progress() -> None:
    sender, receiver = socket.socketpair()
    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 40_000_000,
    )
    errors: list[str] = []

    def slowly() -> None:
        try:
            for byte in struct.pack("!I", 1000):
                sender.send(bytes((byte,)))
                time.sleep(0.025)
        except OSError:
            errors.append("closed")

    thread = threading.Thread(target=slowly)
    thread.start()
    try:
        with pytest.raises(BenchmarkChannelError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
    finally:
        owner.close()
        sender.close()
        thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "case",
    (
        "peer",
        "missing_fence",
        "missing_continue",
        "expired",
        "too_long",
        "bool_time",
        "inheritable",
        "positive_timeout",
        "datagram",
        "tcp",
    ),
)
def test_unadmitted_endpoint_never_starts_a_session(case: str) -> None:
    kind = socket.SOCK_DGRAM if case == "datagram" else socket.SOCK_STREAM
    sender, receiver = socket.socketpair(type=kind)
    if case == "tcp":
        receiver.close()
        receiver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if case == "inheritable":
        receiver.set_inheritable(True)
    if case == "positive_timeout":
        receiver.settimeout(0.25)
    options: dict[str, Any] = {
        "expected_peer": replace(peer(), pid=peer().pid + 1) if case == "peer" else peer(),
        "peer_fence": None if case == "missing_fence" else synthetic_peer_fence,
        "continuation_fence": None if case == "missing_continue" else synthetic_continuation,
        "expires_ns": time.monotonic_ns() + 10**9,
    }
    if case in {"expired", "too_long", "bool_time"}:
        options["expires_ns"] = {
            "expired": 1,
            "too_long": time.monotonic_ns() + 181 * 10**9,
            "bool_time": True,
        }[case]
    try:
        with pytest.raises(BenchmarkChannelError):
            BenchmarkOwnerChannel(receiver, worker_invocation(), **options)
        assert receiver.fileno() == -1
    finally:
        receiver.close()
        sender.close()


def test_peer_fence_rechecked_before_ack_and_blocking_mode_is_unchanged() -> None:
    sender, receiver = socket.socketpair()
    calls: list[int] = []
    revoked = False

    def checked(value: BenchmarkUnixPeer) -> None:
        if revoked:
            raise ValueError("synthetic revoked process association")
        assert value == peer()
        calls.append(value.pid)

    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=checked,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    try:
        assert sender.getblocking() and receiver.getblocking()
        raw = embedding_device_benchmark_bytes(session(3).checkpoints[0])
        sender.sendall(struct.pack("!I", len(raw)) + raw)
        owner.receive_checkpoint()
        assert receiver.getblocking()
        revoked = True
        with pytest.raises(BenchmarkChannelError, match="CONTINUATION_FAILED"):
            owner.acknowledge()
        assert calls and receiver.fileno() == -1
    finally:
        sender.close()
        owner.close()


def test_timeout_changed_after_capture_is_rejected_before_receiving() -> None:
    sender, receiver = socket.socketpair()
    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(),
        expected_peer=peer(),
        peer_fence=synthetic_peer_fence,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    try:
        receiver.settimeout(0.25)
        with pytest.raises(BenchmarkChannelError, match="CHECKPOINT_RECEIVE_FAILED"):
            owner.receive_checkpoint()
        assert receiver.fileno() == -1
    finally:
        owner.close()
        sender.close()


def test_peer_callback_fd_substitution_is_rejected_before_ack_send() -> None:
    sender, receiver = socket.socketpair()
    other_sender, other_receiver = socket.socketpair()
    replace_fd = False

    def synthetic(value: BenchmarkUnixPeer) -> None:
        assert value == peer()
        if replace_fd:
            os.dup2(other_receiver.fileno(), receiver.fileno(), inheritable=False)

    owner = BenchmarkOwnerChannel(
        receiver,
        worker_invocation(3),
        expected_peer=peer(),
        peer_fence=synthetic,
        continuation_fence=synthetic_continuation,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    try:
        raw = embedding_device_benchmark_bytes(session(3).checkpoints[0])
        sender.sendall(struct.pack("!I", len(raw)) + raw)
        owner.receive_checkpoint()
        replace_fd = True
        with pytest.raises(BenchmarkChannelError, match="CONTINUATION_FAILED"):
            owner.acknowledge()
        other_sender.settimeout(0.01)
        with pytest.raises(TimeoutError):
            other_sender.recv(1)
        assert receiver.fileno() == -1
    finally:
        owner.close()
        sender.close()
        other_sender.close()
        other_receiver.close()


def _independent_worker(path: str) -> None:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(path)
    expected = BenchmarkUnixPeer(os.getppid(), os.geteuid(), os.getegid())

    def synthetic(value: BenchmarkUnixPeer) -> None:
        assert value == expected

    worker = BenchmarkWorkerChannel(
        connection,
        worker_invocation(3),
        expected_peer=expected,
        peer_fence=synthetic,
        expires_ns=time.monotonic_ns() + 5 * 10**9,
    )
    try:
        checkpoint = session(3).checkpoints[0]
        worker.send_checkpoint(checkpoint)
        assert worker.receive_ack() == benchmark_ack_for_checkpoint(checkpoint)
        assert worker.transcript() == session(3)
    finally:
        worker.close()


def test_actual_independent_process_peer_credentials(tmp_path: Path) -> None:
    path = tmp_path / "channel.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    server.settimeout(15)
    process = multiprocessing.get_context("spawn").Process(
        target=_independent_worker, args=(str(path),)
    )
    process.start()
    try:
        connection, _ = server.accept()
        expected = BenchmarkUnixPeer(process.pid or 0, os.geteuid(), os.getegid())

        def synthetic(value: BenchmarkUnixPeer) -> None:
            assert value == expected and value.pid != os.getpid()

        owner = BenchmarkOwnerChannel(
            connection,
            worker_invocation(3),
            expected_peer=expected,
            peer_fence=synthetic,
            continuation_fence=synthetic_continuation,
            expires_ns=time.monotonic_ns() + 5 * 10**9,
        )
        try:
            assert owner.receive_checkpoint() == session(3).checkpoints[0]
            owner.acknowledge()
            assert owner.transcript() == session(3)
        finally:
            owner.close()
        process.join(timeout=10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        server.close()
