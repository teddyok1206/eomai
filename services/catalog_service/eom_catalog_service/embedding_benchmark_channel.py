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
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Self

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    BenchmarkAck,
    BenchmarkCheckpoint,
    BenchmarkExecutionPolicy,
    BenchmarkResourceEvidence,
    BenchmarkSession,
    BenchmarkWorkerInvocation,
    benchmark_ack_for_checkpoint,
    benchmark_checkpoint_count,
    benchmark_timeout_seconds,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_ack,
    validate_benchmark_checkpoint,
    validate_benchmark_local_resources,
    validate_benchmark_resource_finalization,
)
from eom_catalog_contracts.embedding_gpu_control import MAX_EMBEDDING_GPU_ALLOCATION_SECONDS
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


class FrameLifetimeProfile(Enum):
    """Trusted transport composition, not a model-supplied execution permission."""

    BENCHMARK = "BENCHMARK"
    EMBEDDING_ALLOCATION = "EMBEDDING_ALLOCATION"


class _Frames:
    def __init__(
        self,
        connection: socket.socket,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expires_ns: int,
        *,
        wait_observer: Callable[[], None] | None = None,
        expected_sender: BenchmarkUnixPeer | None = None,
        maximum_lifetime_seconds: int | None = None,
        policy: BenchmarkExecutionPolicy | None = None,
        lifetime_profile: FrameLifetimeProfile = FrameLifetimeProfile.BENCHMARK,
    ) -> None:
        self.connection = connection
        self.peer = expected_peer
        self.peer_fence = peer_fence
        self.expires_ns = expires_ns
        self.wait_observer = wait_observer
        self.expected_sender = expected_sender
        self.failed = False
        self.closed = False
        try:
            allowed_lifetimes: tuple[int, ...]
            if lifetime_profile is FrameLifetimeProfile.EMBEDDING_ALLOCATION:
                if policy is not None or maximum_lifetime_seconds is not None:
                    raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID")
                seconds = MAX_EMBEDDING_GPU_ALLOCATION_SECONDS
                allowed_lifetimes = (seconds,)
            elif lifetime_profile is FrameLifetimeProfile.BENCHMARK:
                seconds = 180 if policy is None else benchmark_timeout_seconds(policy)
                allowed_lifetimes = (seconds, seconds + 30)
            else:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID")
            if maximum_lifetime_seconds is None:
                maximum_lifetime_seconds = seconds
            now = time.monotonic_ns()
            if (
                not isinstance(connection, socket.socket)
                or type(expected_peer) is not BenchmarkUnixPeer
                or not callable(peer_fence)
                or type(expires_ns) is not int
                or type(maximum_lifetime_seconds) is not int
                or maximum_lifetime_seconds not in allowed_lifetimes
                or not now < expires_ns <= now + maximum_lifetime_seconds * 10**9
                or (wait_observer is not None and not callable(wait_observer))
                or (expected_sender is not None and type(expected_sender) is not BenchmarkUnixPeer)
            ):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_INVALID")
            expected_peer.__post_init__()
            if expected_sender is not None:
                expected_sender.__post_init__()
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
        if (
            self.expected_sender is not None
            and self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) != 1
        ):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_SENDER_CREDENTIALS_REQUIRED")
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
            while True:
                if self.wait_observer is not None:
                    self.wait_observer()
                    self.check()
                remaining = (self.expires_ns - time.monotonic_ns()) / 10**9
                if remaining <= 0:
                    raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EXPIRED")
                timeout = remaining if self.wait_observer is None else min(remaining, 0.25)
                if selector.select(timeout):
                    break
                if self.wait_observer is None:
                    raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EXPIRED")
                self.check()
        self.check()

    def read(self, count: int) -> bytes:
        parts: list[bytes] = []
        remaining = count
        while remaining:
            self.check()
            try:
                part = (
                    self.connection.recv(remaining, socket.MSG_DONTWAIT)
                    if self.expected_sender is None
                    else self._read_sender_bytes(remaining)
                )
            except BlockingIOError:
                self.wait(selectors.EVENT_READ)
                continue
            if not part:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EOF")
            parts.append(part)
            remaining -= len(part)
        self.check()
        return b"".join(parts)

    def _read_sender_bytes(self, count: int) -> bytes:
        """SCM credentials attest the writer, independently of an inherited listener.

        Unexpected SCM_RIGHTS already materialize owned duplicate FDs in this
        process. Close every delivered duplicate before refusing ancillary data.
        MSG_CMSG_CLOEXEC prevents a concurrent child from inheriting them.
        """
        part, ancillary, flags, _ = self.connection.recvmsg(
            count,
            socket.CMSG_SPACE(_CREDENTIALS.size) + socket.CMSG_SPACE(16 * 4),
            socket.MSG_DONTWAIT | socket.MSG_CMSG_CLOEXEC,
        )
        unexpected = False
        closed: set[int] = set()
        for level, kind, value in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                unexpected = True
                for (descriptor,) in struct.iter_unpack("=i", value[: len(value) // 4 * 4]):
                    if descriptor not in closed:
                        # Refuse the message after attempting every owned duplicate.
                        with suppress(OSError):
                            os.close(descriptor)
                        closed.add(descriptor)
        if unexpected or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_SENDER_CHANGED")
        if not part:
            # Linux may attach dummy pid=0 credentials to stream EOF. There is
            # no frame to authenticate; do not misreport it as a peer change.
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CHANNEL_EOF")
        if (
            len(ancillary) != 1
            or ancillary[0][:2] != (socket.SOL_SOCKET, socket.SCM_CREDENTIALS)
            or len(ancillary[0][2]) != _CREDENTIALS.size
            or BenchmarkUnixPeer(*_CREDENTIALS.unpack(ancillary[0][2])) != self.expected_sender
        ):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_SENDER_CHANGED")
        return part

    def receive_raw(self) -> bytes:
        count = _LENGTH.unpack(self.read(_LENGTH.size))[0]
        if not 1 <= count <= MAX_BENCHMARK_ENVELOPE_BYTES:
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_FRAME_SIZE_INVALID")
        return self.read(count)

    def _receive_message(self) -> BenchmarkCheckpoint | BenchmarkAck | BenchmarkResourceEvidence:
        raw = self.receive_raw()
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
        self.send_raw(embedding_device_benchmark_bytes(message))

    def send_raw(self, raw: bytes) -> None:
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BENCHMARK_ENVELOPE_BYTES:
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


class BenchmarkResourceChannel:
    """One resource-only exchange; framing/peer validation does not grant authority.

    Each endpoint owns its connection, can send and receive once, and never accepts
    checkpoint/control frames. Root sampling remains the concrete root relay's duty.
    """

    def __init__(
        self,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        *,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expires_ns: int,
        wait_observer: Callable[[], None] | None = None,
    ) -> None:
        self._frames = _Frames(
            connection,
            expected_peer,
            peer_fence,
            expires_ns,
            wait_observer=wait_observer,
            policy=invocation.execution_policy,
        )
        self._sent = self._received = False
        try:
            self._invocation = BenchmarkWorkerInvocation.model_validate(invocation)
        except Exception:
            self._frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_INVOCATION_INVALID") from None

    def _check(self, value: BenchmarkResourceEvidence) -> None:
        if (
            value.invocation_sha256 != self._invocation.invocation_sha256
            or value.launch_ordinal != self._invocation.launch_ordinal
            or value.device != self._invocation.device
        ):
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_ASSOCIATION_INVALID")

    def send_resources(self, value: BenchmarkResourceEvidence) -> None:
        try:
            if self._sent:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")
            value = BenchmarkResourceEvidence.model_validate(value)
            self._check(value)
            self._sent = True
            self._frames.send(value)
        except Exception:
            self._frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_SEND_FAILED") from None

    def receive_resources(self) -> BenchmarkResourceEvidence:
        try:
            if self._received:
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_EXCHANGE_ORDER_INVALID")
            self._received = True
            value = self._frames.receive_resources()
            self._check(value)
            return value
        except Exception:
            self._frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_RESOURCE_RECEIVE_FAILED") from None

    def close(self) -> None:
        self._frames.close()


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
            _Frames(
                connection,
                expected_peer,
                peer_fence,
                expires_ns,
                policy=invocation.execution_policy,
            ),
            invocation,
        )

    @property
    def execution_policy(self) -> BenchmarkExecutionPolicy:
        """Read the validated immutable selection; this grants no continuation authority."""
        return self._exchange.invocation.execution_policy

    def assert_initial_invocation(self, invocation: BenchmarkWorkerInvocation) -> None:
        """Bind the staged invocation before model entry; this is not a source grant."""
        try:
            checked = BenchmarkWorkerInvocation.model_validate(invocation)
            if (
                checked != self._exchange.invocation
                or self._exchange.frames.failed
                or self._exchange.sequence != 1
                or self._exchange.pending is not None
                or self._exchange.checkpoints
                or self._exchange.acks
                or self._exchange.resources_started
            ):
                raise BenchmarkChannelError("EMBEDDING_BENCHMARK_INITIAL_INVOCATION_INVALID")
            self._exchange.frames.check()
        except Exception:
            self._exchange.fail()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_INITIAL_INVOCATION_INVALID") from None

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
        frames = _Frames(
            connection, expected_peer, peer_fence, expires_ns, policy=invocation.execution_policy
        )
        self._initialize(frames, invocation, continuation_fence)

    def _initialize(
        self,
        frames: _Frames,
        invocation: BenchmarkWorkerInvocation,
        continuation_fence: ContinuationFence,
    ) -> None:
        if not callable(continuation_fence):
            frames.invalidate()
            raise BenchmarkChannelError("EMBEDDING_BENCHMARK_CONTINUATION_REQUIRED")
        self._continuation = continuation_fence
        self._exchange = _Exchange(frames, invocation)

    @classmethod
    def from_activated_listener(
        cls,
        connection: socket.socket,
        invocation: BenchmarkWorkerInvocation,
        *,
        expected_listener: BenchmarkUnixPeer,
        expected_sender: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        continuation_fence: ContinuationFence,
        expires_ns: int,
    ) -> Self:
        """Keep actual listener SO_PEERCRED and actual per-message writer separate.

        Trusted composition captures both identities and enables SO_PASSCRED before
        connect. This factory never replaces an observed listener with a native PID,
        derives authority from message claims or attests a live systemd unit itself.
        """
        frames = _Frames(
            connection,
            expected_listener,
            peer_fence,
            expires_ns,
            expected_sender=expected_sender,
            policy=invocation.execution_policy,
        )
        endpoint = cls.__new__(cls)
        endpoint._initialize(frames, invocation, continuation_fence)
        return endpoint

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
