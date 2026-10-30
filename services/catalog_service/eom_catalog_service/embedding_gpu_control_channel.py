"""Finite metadata control over existing exact-peer Unix framing; no launch or grant creation."""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from eom_catalog_contracts.embedding_gpu_control import (
    MAX_EMBEDDING_GPU_CONTROL_BYTES,
    MAX_EMBEDDING_GPU_FENCES,
    EmbeddingGpuAllocationBusy,
    EmbeddingGpuAllocationReady,
    EmbeddingGpuAllocationRequest,
    EmbeddingGpuCheckChild,
    EmbeddingGpuComputeGrant,
    EmbeddingGpuControlMessage,
    EmbeddingGpuFenceAck,
    EmbeddingGpuResultAck,
    EmbeddingGpuResultReady,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
    parse_embedding_gpu_control_bytes,
    validate_embedding_gpu_allocation_link,
    validate_embedding_gpu_batch_grant,
    validate_embedding_gpu_fence_ack,
    validate_embedding_gpu_grant,
    validate_embedding_gpu_result_ack,
)
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchChild,
    EmbeddingWorkBatchInput,
    SupportedEmbeddingWorkBatchChild,
    SupportedEmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.embedding_work_batch_result import (
    EmbeddingWorkBatchResult,
    embedding_work_batch_result_bytes,
    validate_embedding_work_batch_result,
)
from eom_identifiers import content_sha256, sha256_bytes

from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkUnixPeer,
    FrameLifetimeProfile,
    PeerFence,
    _Frames,
)

type Side = Literal["ROOT", "WORKER"]


class _Phase(StrEnum):
    NEW = "NEW"
    REQUESTED = "REQUESTED"
    READY = "READY"
    GRANTED = "GRANTED"
    RESULT = "RESULT"
    TERMINAL = "TERMINAL"


_TRANSITIONS = MappingProxyType(
    {
        ("ROOT", _Phase.NEW, "REQUEST"): _Phase.REQUESTED,
        ("WORKER", _Phase.NEW, "REQUEST"): _Phase.REQUESTED,
        ("ROOT", _Phase.REQUESTED, "READY"): _Phase.READY,
        ("WORKER", _Phase.REQUESTED, "READY"): _Phase.READY,
        ("ROOT", _Phase.REQUESTED, "BUSY"): _Phase.TERMINAL,
        ("WORKER", _Phase.REQUESTED, "BUSY"): _Phase.TERMINAL,
        ("ROOT", _Phase.READY, "GRANT"): _Phase.GRANTED,
        ("WORKER", _Phase.READY, "GRANT"): _Phase.GRANTED,
        ("ROOT", _Phase.GRANTED, "RESULT"): _Phase.RESULT,
        ("WORKER", _Phase.GRANTED, "RESULT"): _Phase.RESULT,
        ("ROOT", _Phase.RESULT, "RESULT_ACK"): _Phase.TERMINAL,
        ("WORKER", _Phase.RESULT, "RESULT_ACK"): _Phase.TERMINAL,
    }
)


class EmbeddingGpuChannelError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_GPU_CHANNEL_INVALID")


class EmbeddingGpuControlChannel:
    """One owned socket and deadline; role labels do not authenticate or authorize work.

    Trusted installed composition supplies kernel peer/sender and a mandatory live
    identity/lease fence. For an activated socket peer and actual sender can differ.
    No worker-supplied role, source authority, interpreter or path is accepted here.
    """

    def __init__(
        self,
        connection: socket.socket,
        request: EmbeddingGpuAllocationRequest,
        *,
        side: Side,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expected_sender: BenchmarkUnixPeer | None = None,
    ) -> None:
        self._frames: _Frames | None = None
        self._phase = _Phase.NEW
        self._side = side
        self._ready: EmbeddingGpuAllocationReady | None = None
        self._grant: EmbeddingGpuComputeGrant | None = None
        self._result: EmbeddingGpuResultReady | None = None
        self._batch: EmbeddingWorkBatchInput | None = None
        self._children: dict[str, EmbeddingWorkBatchChild] = {}
        self._checked: set[str] = set()
        self._sequence = 0
        try:
            checked = parse_embedding_gpu_control(request)
            if (
                not isinstance(checked, EmbeddingGpuAllocationRequest)
                or side not in ("ROOT", "WORKER")
                or connection.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) != 1
                or not callable(peer_fence)
            ):
                raise EmbeddingGpuChannelError()
            self.request = checked
            assert_peer: Callable[[BenchmarkUnixPeer], object] = peer_fence

            def fenced(peer: BenchmarkUnixPeer) -> None:
                if assert_peer(peer) is not None:
                    raise EmbeddingGpuChannelError()

            self._frames = _Frames(
                connection,
                expected_peer,
                fenced,
                checked.expires_monotonic_ns,
                lifetime_profile=FrameLifetimeProfile.EMBEDDING_ALLOCATION,
                expected_sender=expected_peer if expected_sender is None else expected_sender,
            )
        except BaseException:
            connection.close()
            raise EmbeddingGpuChannelError() from None

    @contextmanager
    def _operation(self) -> Iterator[None]:
        try:
            if self._frames is None:
                raise EmbeddingGpuChannelError()
            self._frames.check()
            yield
            self._frames.check()
        except BaseException:
            self.close()
            raise EmbeddingGpuChannelError() from None

    def _transition(self, side: Side, event: str) -> None:
        if self._side != side:
            raise EmbeddingGpuChannelError()
        after = _TRANSITIONS.get((side, self._phase, event))
        if after is None:
            raise EmbeddingGpuChannelError()
        self._phase = after

    def _send(self, value: EmbeddingGpuControlMessage) -> None:
        assert self._frames is not None
        self._frames.send_raw(embedding_gpu_control_bytes(value))

    def _receive(self) -> EmbeddingGpuControlMessage:
        assert self._frames is not None
        count = struct.unpack("!I", self._frames.read(4))[0]
        if not 0 < count <= MAX_EMBEDDING_GPU_CONTROL_BYTES:
            raise EmbeddingGpuChannelError()
        return parse_embedding_gpu_control_bytes(self._frames.read(count))

    def _message(self, kind: str, values: dict[str, Any]) -> EmbeddingGpuControlMessage:
        body = {
            "schema_version": "embedding-gpu-allocation-control/1.0",
            "message_type": kind,
            "allocation_attempt_id": self.request.allocation_attempt_id,
            "allocation_request_sha256": self.request.message_sha256,
        } | values
        return parse_embedding_gpu_control(body | {"message_sha256": content_sha256(body)})

    def send_request(self) -> None:
        with self._operation():
            self._transition("ROOT", "REQUEST")
            self._send(self.request)

    def receive_request(self) -> None:
        with self._operation():
            self._transition("WORKER", "REQUEST")
            if self._receive() != self.request:
                raise EmbeddingGpuChannelError()

    def send_allocation(
        self, outcome: EmbeddingGpuAllocationReady | EmbeddingGpuAllocationBusy
    ) -> None:
        with self._operation():
            value = parse_embedding_gpu_control(outcome)
            if not isinstance(value, EmbeddingGpuAllocationReady | EmbeddingGpuAllocationBusy):
                raise EmbeddingGpuChannelError()
            validate_embedding_gpu_allocation_link(self.request, value)
            self._transition(
                "WORKER", "READY" if isinstance(value, EmbeddingGpuAllocationReady) else "BUSY"
            )
            self._ready = value if isinstance(value, EmbeddingGpuAllocationReady) else None
            self._send(value)

    def receive_allocation(self) -> EmbeddingGpuAllocationReady | EmbeddingGpuAllocationBusy:
        with self._operation():
            value = self._receive()
            if not isinstance(value, EmbeddingGpuAllocationReady | EmbeddingGpuAllocationBusy):
                raise EmbeddingGpuChannelError()
            validate_embedding_gpu_allocation_link(self.request, value)
            self._transition(
                "ROOT", "READY" if isinstance(value, EmbeddingGpuAllocationReady) else "BUSY"
            )
            self._ready = value if isinstance(value, EmbeddingGpuAllocationReady) else None
            return value

    def send_grant(self, grant: EmbeddingGpuComputeGrant) -> None:
        with self._operation():
            self._transition("ROOT", "GRANT")
            if self._ready is None:
                raise EmbeddingGpuChannelError()
            value = EmbeddingGpuComputeGrant.model_validate(grant)
            validate_embedding_gpu_grant(self.request, self._ready, value)
            self._grant = value
            self._send(value)

    def receive_grant(self) -> EmbeddingGpuComputeGrant:
        with self._operation():
            self._transition("WORKER", "GRANT")
            value = self._receive()
            if self._ready is None or not isinstance(value, EmbeddingGpuComputeGrant):
                raise EmbeddingGpuChannelError()
            validate_embedding_gpu_grant(self.request, self._ready, value)
            self._grant = value
            return value

    def bind_batch(
        self, batch: EmbeddingWorkBatchInput, *, input_raw_sha256: str, input_byte_count: int
    ) -> None:
        with self._operation():
            if self._phase != _Phase.GRANTED or self._grant is None or self._batch is not None:
                raise EmbeddingGpuChannelError()
            checked = parse_embedding_work_batch_input(batch)
            validate_embedding_gpu_batch_grant(
                self.request,
                self._grant,
                checked,
                input_raw_sha256=input_raw_sha256,
                input_byte_count=input_byte_count,
            )
            self._batch = checked
            self._children = {child.request.request_sha256: child for child in checked.children}

    def assert_compute_granted(self) -> None:
        """Worker checks the original root grant before touching the late-bound input FD."""
        with self._operation():
            if self._side != "WORKER" or self._phase != _Phase.GRANTED or self._grant is None:
                raise EmbeddingGpuChannelError()

    def assert_batch_current(self, batch: SupportedEmbeddingWorkBatchInput) -> None:
        with self._operation():
            if (
                not isinstance(batch, EmbeddingWorkBatchInput)
                or self._side != "WORKER"
                or self._phase != _Phase.GRANTED
                or self._batch is None
                or batch.request_sha256 != self._batch.request_sha256
                or batch.routing_decision_sha256 != self._batch.routing_decision_sha256
                or batch.scope != self._batch.scope
            ):
                raise EmbeddingGpuChannelError()

    def assert_child_current(
        self, batch: SupportedEmbeddingWorkBatchInput, child: SupportedEmbeddingWorkBatchChild
    ) -> None:
        with self._operation():
            self.assert_batch_current(batch)
            if (
                not isinstance(child, EmbeddingWorkBatchChild)
                or self._grant is None
                or self._children.get(child.request.request_sha256) != child
            ):
                raise EmbeddingGpuChannelError()
            self._sequence += 1
            check = self._message(
                "CHECK_CHILD",
                {
                    "grant_message_sha256": self._grant.message_sha256,
                    "batch_request_sha256": batch.request_sha256,
                    "child_request_sha256": child.request.request_sha256,
                    "sequence": self._sequence,
                },
            )
            assert isinstance(check, EmbeddingGpuCheckChild)
            self._send(check)
            ack = self._receive()
            if not isinstance(ack, EmbeddingGpuFenceAck):
                raise EmbeddingGpuChannelError()
            validate_embedding_gpu_fence_ack(self._grant, check, ack)
            self._checked.add(child.request.request_sha256)

    def authorize_next(
        self, authorizer: Callable[[EmbeddingGpuCheckChild], None]
    ) -> EmbeddingGpuResultReady | None:
        """Root invokes the real actual-actor/source fence before writing any child ACK."""
        with self._operation():
            if (
                self._side != "ROOT"
                or self._phase != _Phase.GRANTED
                or self._grant is None
                or self._batch is None
                or not callable(authorizer)
            ):
                raise EmbeddingGpuChannelError()
            value = self._receive()
            if isinstance(value, EmbeddingGpuResultReady):
                if (
                    self._checked != set(self._children)
                    or value.allocation_attempt_id != self.request.allocation_attempt_id
                    or value.allocation_request_sha256 != self.request.message_sha256
                    or value.grant_message_sha256 != self._grant.message_sha256
                    or value.batch_request_sha256 != self._batch.request_sha256
                    or value.vectors_byte_count != self._batch.expected_vector_bytes
                ):
                    raise EmbeddingGpuChannelError()
                self._transition("ROOT", "RESULT")
                self._result = value
                return value
            if (
                not isinstance(value, EmbeddingGpuCheckChild)
                or value.allocation_attempt_id != self.request.allocation_attempt_id
                or value.allocation_request_sha256 != self.request.message_sha256
                or value.grant_message_sha256 != self._grant.message_sha256
                or value.batch_request_sha256 != self._batch.request_sha256
                or value.child_request_sha256 not in self._children
                or value.sequence != self._sequence + 1
                or value.sequence > MAX_EMBEDDING_GPU_FENCES
            ):
                raise EmbeddingGpuChannelError()
            authorize: Callable[[EmbeddingGpuCheckChild], object] = authorizer
            if authorize(value) is not None:
                raise EmbeddingGpuChannelError()
            ack = self._message(
                "FENCE_ACK",
                value.model_dump(
                    mode="json",
                    exclude={
                        "schema_version",
                        "message_type",
                        "allocation_attempt_id",
                        "allocation_request_sha256",
                        "message_sha256",
                    },
                )
                | {"check_message_sha256": value.message_sha256},
            )
            self._send(ack)
            self._sequence = value.sequence
            self._checked.add(value.child_request_sha256)
            return None

    def announce_result(self, result: EmbeddingWorkBatchResult) -> None:
        with self._operation():
            if (
                self._side != "WORKER"
                or self._batch is None
                or self._grant is None
                or self._checked != set(self._children)
            ):
                raise EmbeddingGpuChannelError()
            self._transition("WORKER", "RESULT")
            validate_embedding_work_batch_result(self._batch, result)
            raw = embedding_work_batch_result_bytes(result)
            value = self._message(
                "RESULT_READY",
                {
                    "grant_message_sha256": self._grant.message_sha256,
                    "batch_request_sha256": self._batch.request_sha256,
                    "result_raw_sha256": sha256_bytes(raw),
                    "result_sha256": result.result_sha256,
                    "vectors_sha256": result.vectors.sha256,
                    "result_byte_count": len(raw),
                    "vectors_byte_count": result.vectors.byte_count,
                },
            )
            assert isinstance(value, EmbeddingGpuResultReady)
            self._send(value)
            ack = self._receive()
            if not isinstance(ack, EmbeddingGpuResultAck):
                raise EmbeddingGpuChannelError()
            validate_embedding_gpu_result_ack(self._grant, value, ack)
            self._transition("WORKER", "RESULT_ACK")

    def acknowledge_result(self, verifier: Callable[[EmbeddingGpuResultReady], None]) -> None:
        """Root verifies actual output bytes/FD epochs/sources before the worker may exit."""
        with self._operation():
            if (
                self._side != "ROOT"
                or self._phase != _Phase.RESULT
                or self._result is None
                or self._grant is None
                or not callable(verifier)
            ):
                raise EmbeddingGpuChannelError()
            verify: Callable[[EmbeddingGpuResultReady], object] = verifier
            if verify(self._result) is not None:
                raise EmbeddingGpuChannelError()
            self._send(
                self._message(
                    "RESULT_ACK",
                    {
                        "grant_message_sha256": self._grant.message_sha256,
                        "batch_request_sha256": self._grant.batch_request_sha256,
                        "result_message_sha256": self._result.message_sha256,
                    },
                )
            )
            self._transition("ROOT", "RESULT_ACK")

    def close(self) -> None:
        if self._frames is not None:
            self._frames.invalidate()
            self._frames = None
