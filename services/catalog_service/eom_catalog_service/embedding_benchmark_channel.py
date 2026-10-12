"""Fixed local checkpoint/ACK and terminal resources; no launch/grant/inference/cleanup.

Endpoints take ownership of one already-admitted Unix socket. Required peer and
continuation fences come from installed owners, never worker input or default callbacks.
"""

from __future__ import annotations

import os
import selectors
import socket
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    BenchmarkAck,
    BenchmarkCheckpoint,
    BenchmarkResourceEvidence,
    BenchmarkSession,
    BenchmarkWorkerInvocation,
    benchmark_ack_for_checkpoint,
    benchmark_checkpoint_count,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_ack,
    validate_benchmark_checkpoint,
    validate_benchmark_local_resources,
    validate_benchmark_resource_finalization,
)
from eom_identifiers import content_sha256

_LENGTH = struct.Struct("!I")
_CREDENTIALS = struct.Struct("=iII")


class BenchmarkChannelError(ValueError):
    """Content-free failure; it cannot establish nonexecution or release capacity."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BenchmarkUnixPeer:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if (
            type(self.pid) is not int
            or not 1 <= self.pid <= 2**31 - 1
            or any(
                type(value) is not int or not 0 <= value <= 2**32 - 1
                for value in (self.uid, self.gid)
            )
        ):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_PEER_INVALID")


PeerFence = Callable[[BenchmarkUnixPeer], None]
ContinuationFence = Callable[[BenchmarkCheckpoint], None]
ResourceFinalizer = Callable[[BenchmarkResourceEvidence], BenchmarkResourceEvidence]


class _Frames:
    def __init__(
        self,
        connection: socket.socket,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expires_ns: int,
    ) -> None:
        self.connection = connection
        self.peer = expected_peer
        self.peer_fence = peer_fence
        self.expires_ns = expires_ns
        self.failed = False
        self.closed = False
        try:
            now = time.monotonic_ns()
            if (
                not isinstance(connection, socket.socket)
                or type(expected_peer) is not BenchmarkUnixPeer
                or not callable(peer_fence)
                or type(expires_ns) is not int
                or not now < expires_ns <= now + 180 * 10**9
            ):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID")
            expected_peer.__post_init__()
            descriptor = connection.fileno()
            value = os.fstat(descriptor)
            if (
                not stat.S_ISSOCK(value.st_mode)
                or connection.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN) != socket.AF_UNIX
                or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                or connection.get_inheritable()
            ):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID")
            self.identity = (descriptor, value.st_dev, value.st_ino, value.st_mode)
            self.check()
        except Exception:
            self.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID") from None

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            if isinstance(self.connection, socket.socket):
                self.connection.close()

    def invalidate(self) -> None:
        self.failed = True
        self.close()

    def check(self) -> None:
        if self.closed or time.monotonic_ns() >= self.expires_ns:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EXPIRED")

        actual = self.observe_peer()
        self.peer_fence(actual)
        if self.observe_peer() != actual:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_PEER_CHANGED")
        if time.monotonic_ns() >= self.expires_ns:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EXPIRED")

    def observe_peer(self) -> BenchmarkUnixPeer:
        # Positive CPython socket timeouts perform an implicit select before even
        # MSG_DONTWAIT calls and can overrun the channel's absolute deadline.
        if self.connection.gettimeout() not in (None, 0.0):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_CHANGED")
        descriptor = self.connection.fileno()
        value = os.fstat(descriptor)
        if self.identity != (descriptor, value.st_dev, value.st_ino, value.st_mode):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_CHANGED")
        actual = BenchmarkUnixPeer(
            *_CREDENTIALS.unpack(
                self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _CREDENTIALS.size)
            )
        )
        if actual != self.peer:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_PEER_CHANGED")
        return actual

    def wait(self, event: int) -> None:
        self.check()
        with selectors.DefaultSelector() as selector:
            selector.register(self.connection, event)
            remaining = (self.expires_ns - time.monotonic_ns()) / 10**9
            if remaining <= 0 or not selector.select(remaining):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EXPIRED")
        self.check()

    def read(self, count: int) -> bytes:
        parts: list[bytes] = []
        remaining = count
        while remaining:
            self.check()
            try:
                part = self.connection.recv(remaining, socket.MSG_DONTWAIT)
            except BlockingIOError:
                self.wait(selectors.EVENT_READ)
                continue
            if not part:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EOF")
            parts.append(part)
            remaining -= len(part)
        self.check()
        return b"".join(parts)

    def _receive_message(self) -> BenchmarkCheckpoint | BenchmarkAck | BenchmarkResourceEvidence:
        count = _LENGTH.unpack(self.read(_LENGTH.size))[0]
        if not 1 <= count <= MAX_BENCHMARK_ENVELOPE_BYTES:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_SIZE_INVALID")
        raw = self.read(count)
        message = parse_embedding_device_benchmark_bytes(raw)
        if not isinstance(
            message, (BenchmarkCheckpoint, BenchmarkAck, BenchmarkResourceEvidence)
        ) or raw != embedding_device_benchmark_bytes(message):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_INVALID")
        return message

    def receive(self) -> BenchmarkCheckpoint | BenchmarkAck:
        message = self._receive_message()
        if not isinstance(message, (BenchmarkCheckpoint, BenchmarkAck)):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_INVALID")
        return message

    def receive_resources(self) -> BenchmarkResourceEvidence:
        message = self._receive_message()
        if not isinstance(message, BenchmarkResourceEvidence):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_INVALID")
        return message

    def send(self, message: BenchmarkCheckpoint | BenchmarkAck | BenchmarkResourceEvidence) -> None:
        raw = embedding_device_benchmark_bytes(message)
        if not 1 <= len(raw) <= MAX_BENCHMARK_ENVELOPE_BYTES:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_SIZE_INVALID")
        pending = memoryview(_LENGTH.pack(len(raw)) + raw)
        while pending:
            self.check()
            try:
                count = self.connection.send(pending, socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL)
            except BlockingIOError:
                self.wait(selectors.EVENT_WRITE)
                continue
            if count == 0:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EOF")
            pending = pending[count:]
        self.check()


class _Exchange:
    def __init__(self, frames: _Frames, invocation: BenchmarkWorkerInvocation) -> None:
        self.frames = frames
        try:
            self.invocation = BenchmarkWorkerInvocation.model_validate(invocation)
            self.count = benchmark_checkpoint_count(self.invocation)
        except Exception:
            frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_INVOCATION_INVALID") from None
        self.sequence = 1
        self.pending: BenchmarkCheckpoint | None = None
        self.checkpoints: list[BenchmarkCheckpoint] = []
        self.acks: list[BenchmarkAck] = []
        self.completed_session: BenchmarkSession | None = None
        self.resources_started = False

    def fail(self) -> None:
        self.frames.invalidate()

    def begin(self) -> None:
        if self.frames.failed or self.pending is not None or self.sequence > self.count:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")

    def checkpoint(self, value: BenchmarkCheckpoint) -> None:
        validate_benchmark_checkpoint(self.invocation, value, self.sequence)
        self.pending = BenchmarkCheckpoint.model_validate(value)

    def finish(self, ack: BenchmarkAck) -> None:
        if self.pending is None:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")
        validate_benchmark_ack(self.pending, ack)
        self.checkpoints.append(self.pending)
        self.acks.append(BenchmarkAck.model_validate(ack))
        self.pending = None
        self.sequence += 1
        if self.sequence == self.count + 1:
            self.completed_session = self.transcript()

    def begin_resources(self) -> None:
        if (
            self.frames.failed
            or self.completed_session is None
            or self.resources_started
            or self.pending is not None
        ):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_ORDER_INVALID")
        self.frames.check()
        self.resources_started = True

    def transcript(self) -> BenchmarkSession:
        if self.completed_session is not None:
            # Historical CP evidence survives a later terminal-resource failure, never a grant.
            return self.completed_session
        if self.frames.failed or self.pending is not None or self.sequence != self.count + 1:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_SESSION_INCOMPLETE")
        body = {
            "schema_version": "embedding-device-benchmark-session/1.0",
            "execution_id": self.invocation.execution_id,
            "invocation_sha256": self.invocation.invocation_sha256,
            "launch_ordinal": self.invocation.launch_ordinal,
            "checkpoints": [value.model_dump(mode="json") for value in self.checkpoints],
            "acks": [value.model_dump(mode="json") for value in self.acks],
        }
        return BenchmarkSession.model_validate(body | {"session_sha256": content_sha256(body)})


class BenchmarkWorkerChannel:
    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        *,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expires_ns: int,
    ) -> None:
        self._exchange = _Exchange(
            _Frames(connection, expected_peer, peer_fence, expires_ns), invocation
        )

    def send_checkpoint(self, value: BenchmarkCheckpoint) -> None:
        try:
            self._exchange.begin()
            self._exchange.checkpoint(value)
            assert self._exchange.pending is not None
            self._exchange.frames.send(self._exchange.pending)
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHECKPOINT_SEND_FAILED") from None

    def receive_ack(self) -> BenchmarkAck:
        try:
            if self._exchange.pending is None:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")
            value = self._exchange.frames.receive()
            if not isinstance(value, BenchmarkAck):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_INVALID")
            self._exchange.finish(value)
            return value
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_ACK_RECEIVE_FAILED") from None

    def transcript(self) -> BenchmarkSession:
        return self._exchange.transcript()

    def exchange_resources(self, local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
        """One terminal roundtrip; independent owner claims cannot alter local measurements."""
        try:
            self._exchange.begin_resources()
            validate_benchmark_local_resources(self._exchange.invocation, local)
            raw_local = embedding_device_benchmark_bytes(local)
            self._exchange.frames.send(local)
            finalized = self._exchange.frames.receive_resources()
            baseline = parse_embedding_device_benchmark_bytes(raw_local)
            assert isinstance(baseline, BenchmarkResourceEvidence)
            validate_benchmark_resource_finalization(self._exchange.invocation, baseline, finalized)
            self._exchange.frames.check()
            return finalized
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_EXCHANGE_FAILED") from None

    def close(self) -> None:
        self._exchange.frames.close()


class BenchmarkOwnerChannel:
    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        *,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        continuation_fence: ContinuationFence,
        expires_ns: int,
    ) -> None:
        frames = _Frames(connection, expected_peer, peer_fence, expires_ns)
        if not callable(continuation_fence):
            frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CONTINUATION_REQUIRED")
        self._continuation = continuation_fence
        self._exchange = _Exchange(frames, invocation)

    def receive_checkpoint(self) -> BenchmarkCheckpoint:
        try:
            self._exchange.begin()
            value = self._exchange.frames.receive()
            if not isinstance(value, BenchmarkCheckpoint):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_INVALID")
            self._exchange.checkpoint(value)
            return value
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHECKPOINT_RECEIVE_FAILED") from None

    def acknowledge(self) -> BenchmarkAck:
        try:
            value = self._exchange.pending
            if value is None:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")
            self._exchange.frames.check()
            self._continuation(value)
            self._exchange.frames.check()
            ack = benchmark_ack_for_checkpoint(value)
            self._exchange.frames.send(ack)
            self._exchange.finish(ack)
            return ack
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CONTINUATION_FAILED") from None

    def transcript(self) -> BenchmarkSession:
        return self._exchange.transcript()

    def finalize_resources(self, *, finalizer: ResourceFinalizer) -> BenchmarkResourceEvidence:
        """Require the installed owner's late observation/fence adapter; no default provider."""
        try:
            self._exchange.begin_resources()
            if not callable(finalizer):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_FINALIZER_REQUIRED")
            local = self._exchange.frames.receive_resources()
            validate_benchmark_local_resources(self._exchange.invocation, local)
            raw_local = embedding_device_benchmark_bytes(local)
            self._exchange.frames.check()
            finalized = finalizer(local)
            self._exchange.frames.check()
            if not isinstance(finalized, BenchmarkResourceEvidence):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_FINALIZER_INVALID")
            baseline = parse_embedding_device_benchmark_bytes(raw_local)
            assert isinstance(baseline, BenchmarkResourceEvidence)
            validate_benchmark_resource_finalization(self._exchange.invocation, baseline, finalized)
            self._exchange.frames.send(finalized)
            return finalized
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError(
                "EMBEDDING_BENCHMARK_RESOURCE_FINALIZATION_FAILED"
            ) from None

    def close(self) -> None:
        self._exchange.frames.close()
