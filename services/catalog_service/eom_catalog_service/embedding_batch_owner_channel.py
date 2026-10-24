"""One bounded exact-peer root/source-owner exchange; no SQL, model, NAS or reconnection."""

from __future__ import annotations

import os
import re
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Literal

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_identifiers import content_sha256
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_workflow.embedding_batch_owner_control import (
    MAX_BATCH_OWNER_CHECKS,
    EmbeddingBatchOwnerAck,
    EmbeddingBatchOwnerBound,
    EmbeddingBatchOwnerChecked,
    EmbeddingBatchOwnerMessage,
    EmbeddingBatchRootBusy,
    EmbeddingBatchRootCheck,
    EmbeddingBatchRootCompleted,
    EmbeddingBatchRootReady,
    embedding_batch_owner_control_bytes,
    parse_embedding_batch_owner_control,
    parse_embedding_batch_owner_control_bytes,
    validate_embedding_batch_owner_completion,
    validate_embedding_batch_owner_context,
)

from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks
from eom_catalog_service.embedding_batch_owner_pidfd import EmbeddingBatchOwnerPidfd
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer, PeerFence, _Frames

type _Side = Literal["ROOT", "OWNER"]


class _Phase(StrEnum):
    NEW = "NEW"
    READY = "READY"
    ACTIVE = "ACTIVE"
    CHECK = "CHECK"
    COMPLETED = "COMPLETED"
    DONE = "DONE"


_TRANSITIONS = {
    ("ROOT", _Phase.NEW, "SEND_READY"): _Phase.READY,
    ("OWNER", _Phase.NEW, "RECEIVE_READY"): _Phase.READY,
    ("ROOT", _Phase.READY, "RECEIVE_BOUND"): _Phase.ACTIVE,
    ("OWNER", _Phase.READY, "SEND_BOUND"): _Phase.ACTIVE,
    ("ROOT", _Phase.ACTIVE, "SEND_CHECK"): _Phase.CHECK,
    ("OWNER", _Phase.ACTIVE, "RECEIVE_CHECK"): _Phase.CHECK,
    ("ROOT", _Phase.CHECK, "RECEIVE_CHECKED"): _Phase.ACTIVE,
    ("OWNER", _Phase.CHECK, "SEND_CHECKED"): _Phase.ACTIVE,
    ("ROOT", _Phase.ACTIVE, "SEND_COMPLETED"): _Phase.COMPLETED,
    ("OWNER", _Phase.ACTIVE, "RECEIVE_COMPLETED"): _Phase.COMPLETED,
    ("ROOT", _Phase.COMPLETED, "RECEIVE_ACK"): _Phase.DONE,
    ("OWNER", _Phase.COMPLETED, "SEND_ACK"): _Phase.DONE,
    ("ROOT", _Phase.NEW, "SEND_BUSY"): _Phase.DONE,
    ("OWNER", _Phase.NEW, "RECEIVE_BUSY"): _Phase.DONE,
}


class EmbeddingBatchOwnerChannelError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_BATCH_OWNER_CHANNEL_INVALID")


def _require(condition: bool) -> None:
    if not condition:
        raise EmbeddingBatchOwnerChannelError()


class EmbeddingBatchOwnerChannel:
    """Small messages only; caller separately owns actual UID/birth/release/source proof.

    The installed adapters supply kernel peer identities and a current birth fence.
    A supplied UID/DTO alone is not authority. All operations use the original
    allocation deadline and invalidate the connection on any incomplete exchange.
    """

    def __init__(
        self,
        connection: socket.socket,
        request: EmbeddingGpuAllocationRequest,
        *,
        controller_release: str,
        side: _Side,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        expected_sender: BenchmarkUnixPeer | None = None,
    ) -> None:
        self._frames: _Frames | None = None
        self._phase = _Phase.NEW
        self._ready: EmbeddingBatchRootReady | None = None
        self._bound: EmbeddingBatchOwnerBound | None = None
        self._completed: EmbeddingBatchRootCompleted | None = None
        self._children: frozenset[str] = frozenset()
        self._sequence = 0
        self._peer_lifetime: EmbeddingBatchOwnerPidfd | None = None
        self.side = side
        self.controller_release = controller_release
        try:
            self.request = EmbeddingGpuAllocationRequest.model_validate(request)
            _require(
                side in ("ROOT", "OWNER")
                and type(controller_release) is str
                and re.fullmatch(r"[0-9a-f]{40}", controller_release) is not None
                and connection.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) == 1
                and callable(peer_fence)
            )
            callback: Callable[[BenchmarkUnixPeer], object] = peer_fence

            def fence(actual: BenchmarkUnixPeer) -> None:
                _require(callback(actual) is None)

            self._frames = _Frames(
                connection,
                expected_peer,
                fence,
                self.request.expires_monotonic_ns,
                expected_sender=expected_peer if expected_sender is None else expected_sender,
            )
        except BaseException:
            connection.close()
            raise EmbeddingBatchOwnerChannelError() from None

    @contextmanager
    def _operation(self) -> Iterator[_Frames]:
        try:
            _require(self._frames is not None)
            assert self._frames is not None
            self._frames.check()
            yield self._frames
            self._frames.check()
        except BaseException:
            self.close()
            raise EmbeddingBatchOwnerChannelError() from None

    def _transition(self, event: str) -> None:
        after = _TRANSITIONS.get((self.side, self._phase, event))
        _require(after is not None)
        assert after is not None
        self._phase = after

    def _send(self, frames: _Frames, value: EmbeddingBatchOwnerMessage) -> None:
        validate_embedding_batch_owner_context(self.request, self.controller_release, value)
        frames.send_raw(embedding_batch_owner_control_bytes(value))

    def _receive(self, frames: _Frames) -> EmbeddingBatchOwnerMessage:
        value = parse_embedding_batch_owner_control_bytes(frames.receive_raw())
        validate_embedding_batch_owner_context(self.request, self.controller_release, value)
        return value

    def _message(self, kind: str, values: dict[str, Any]) -> EmbeddingBatchOwnerMessage:
        body = {
            "schema_version": "embedding-batch-owner-control/1.0",
            "message_type": kind,
            "allocation_attempt_id": self.request.allocation_attempt_id,
            "allocation_request_sha256": self.request.message_sha256,
            "controller_release": self.controller_release,
        } | values
        return parse_embedding_batch_owner_control(body | {"message_sha256": content_sha256(body)})

    def send_ready(self, value: EmbeddingBatchRootReady) -> None:
        with self._operation() as frames:
            _require(type(value) is EmbeddingBatchRootReady)
            self._transition("SEND_READY")
            self._send(frames, value)
            self._ready = value

    def receive_allocation(self) -> EmbeddingBatchRootReady | EmbeddingBatchRootBusy:
        with self._operation() as frames:
            _require(self.side == "OWNER" and self._phase is _Phase.NEW)
            value = self._receive(frames)
            if isinstance(value, EmbeddingBatchRootBusy):
                self._transition("RECEIVE_BUSY")
                return value
            _require(isinstance(value, EmbeddingBatchRootReady))
            assert isinstance(value, EmbeddingBatchRootReady)
            self._transition("RECEIVE_READY")
            self._ready = value
            return value

    def _bind(self, value: EmbeddingBatchOwnerBound) -> None:
        _require(
            self._ready is not None
            and value.ready_message_sha256 == self._ready.message_sha256
            and value.binding.request_sha256 == self.request.parent_request_sha256
        )
        self._bound = value
        self._children = frozenset(child.native_input_sha256 for child in value.binding.children)

    def send_binding(self, value: EmbeddingBatchOwnerBound) -> None:
        with self._operation() as frames:
            value = EmbeddingBatchOwnerBound.model_validate(value)
            self._transition("SEND_BOUND")
            self._bind(value)
            self._send(frames, value)

    def receive_binding(self) -> EmbeddingBatchOwnerBound:
        with self._operation() as frames:
            _require(self.side == "ROOT" and self._phase is _Phase.READY)
            value = self._receive(frames)
            _require(isinstance(value, EmbeddingBatchOwnerBound))
            assert isinstance(value, EmbeddingBatchOwnerBound)
            self._bind(value)
            self._transition("RECEIVE_BOUND")
            return value

    def check_child(self, batch_request_sha256: str, child_request_sha256: str) -> None:
        """Root-side proxy; no successful old check may satisfy another check."""
        with self._operation() as frames:
            _require(
                self.side == "ROOT"
                and self._phase is _Phase.ACTIVE
                and self._bound is not None
                and batch_request_sha256 == self._bound.binding.batch_request_sha256
                and child_request_sha256 in self._children
                and self._sequence < MAX_BATCH_OWNER_CHECKS
            )
            check = self._message(
                "ROOT_CHECK",
                dict(
                    batch_request_sha256=batch_request_sha256,
                    child_request_sha256=child_request_sha256,
                    sequence=self._sequence + 1,
                ),
            )
            assert isinstance(check, EmbeddingBatchRootCheck)
            self._transition("SEND_CHECK")
            self._send(frames, check)
            reply = self._receive(frames)
            _require(
                isinstance(reply, EmbeddingBatchOwnerChecked)
                and reply.batch_request_sha256 == check.batch_request_sha256
                and reply.child_request_sha256 == check.child_request_sha256
                and reply.sequence == check.sequence
                and reply.check_message_sha256 == check.message_sha256
            )
            self._sequence = check.sequence
            self._transition("RECEIVE_CHECKED")

    def _completion(self, value: EmbeddingBatchRootCompleted) -> None:
        _require(self._ready is not None and self._bound is not None)
        assert self._ready is not None and self._bound is not None
        _require(self._sequence > 0)
        validate_embedding_batch_owner_completion(self.request, self._ready, self._bound, value)
        self._completed = value

    def authorize_next(
        self, authorize_child: Callable[[str, str], None]
    ) -> EmbeddingBatchRootCompleted | None:
        """Actual owner must reauthorize each exact original child before the ACK."""
        with self._operation() as frames:
            _require(
                self.side == "OWNER" and self._phase is _Phase.ACTIVE and callable(authorize_child)
            )
            value = self._receive(frames)
            if isinstance(value, EmbeddingBatchRootCompleted):
                self._completion(value)
                self._transition("RECEIVE_COMPLETED")
                return value
            _require(isinstance(value, EmbeddingBatchRootCheck) and self._bound is not None)
            assert isinstance(value, EmbeddingBatchRootCheck) and self._bound is not None
            _require(
                value.sequence == self._sequence + 1
                and value.batch_request_sha256 == self._bound.binding.batch_request_sha256
                and value.child_request_sha256 in self._children
            )
            self._transition("RECEIVE_CHECK")
            callback: Callable[[str, str], object] = authorize_child
            _require(callback(value.batch_request_sha256, value.child_request_sha256) is None)
            reply = self._message(
                "OWNER_CHECKED",
                dict(
                    batch_request_sha256=value.batch_request_sha256,
                    child_request_sha256=value.child_request_sha256,
                    sequence=value.sequence,
                    check_message_sha256=value.message_sha256,
                ),
            )
            self._send(frames, reply)
            self._sequence = value.sequence
            self._transition("SEND_CHECKED")
            return None

    def send_completed(self, value: EmbeddingBatchRootCompleted) -> None:
        with self._operation() as frames:
            value = EmbeddingBatchRootCompleted.model_validate(value)
            self._transition("SEND_COMPLETED")
            self._completion(value)
            self._send(frames, value)
            ack = self._receive(frames)
            _require(
                isinstance(ack, EmbeddingBatchOwnerAck)
                and ack.completion_message_sha256 == value.message_sha256
            )
            self._transition("RECEIVE_ACK")

    def acknowledge_completion(self, verify: Callable[[EmbeddingBatchRootCompleted], None]) -> None:
        """Required local-output/source verifier; receipt ACK does not mean publication."""
        with self._operation() as frames:
            _require(
                self.side == "OWNER"
                and self._phase is _Phase.COMPLETED
                and self._completed is not None
                and callable(verify)
            )
            assert self._completed is not None
            callback: Callable[[EmbeddingBatchRootCompleted], object] = verify
            _require(callback(self._completed) is None)
            ack = self._message(
                "OWNER_ACK",
                dict(
                    completion_message_sha256=self._completed.message_sha256,
                    evidence_state="RECEIVED_NOT_CANONICAL_PUBLICATION",
                ),
            )
            self._send(frames, ack)
            self._transition("SEND_ACK")

    def send_busy(self, value: EmbeddingBatchRootBusy) -> None:
        with self._operation() as frames:
            _require(type(value) is EmbeddingBatchRootBusy)
            self._transition("SEND_BUSY")
            self._send(frames, value)

    def close(self) -> None:
        try:
            if self._frames is not None:
                self._frames.close()
        finally:
            if self._peer_lifetime is not None:
                self._peer_lifetime.close()

    def require_direct_peer(self) -> BenchmarkUnixPeer:
        """For installed owner/root adapters, not PID1's separate native activation channel."""
        with self._operation() as frames:
            peer = frames.observe_peer()
            _require(frames.expected_sender == peer)
            return peer

    @property
    def terminal_peer_exit_allowed(self) -> bool:
        """No new source/compute exchanges after this original terminal exchange starts."""
        return self._phase in {_Phase.COMPLETED, _Phase.DONE}

    @property
    def received_completion(self) -> EmbeddingBatchRootCompleted:
        """Only a validated original OWNER-side terminal exchange, not arbitrary JSON."""
        with self._operation():
            _require(
                self.side == "OWNER"
                and self._phase in {_Phase.COMPLETED, _Phase.DONE}
                and self._completed is not None
            )
            assert self._completed is not None
            return self._completed

    @property
    def acknowledged_completion(self) -> EmbeddingBatchRootCompleted:
        """Immutable verified terminal metadata, not a live peer/source capability.

        Successful output verification and ACK close the physical exchange.
        Canonical publication must retain fresh source/lease authority, but must
        not require this completed socket/PID or compute deadline to stay alive.
        """
        _require(
            self.side == "OWNER" and self._phase is _Phase.DONE and self._completed is not None
        )
        assert self._completed is not None
        return self._completed


def bind_original_embedding_batch_owner_channel(
    connection: socket.socket,
    request: EmbeddingGpuAllocationRequest,
    *,
    controller_release: str,
    side: _Side,
    expected_peer: BenchmarkUnixPeer,
    peer_start_ticks: int,
) -> EmbeddingBatchOwnerChannel:
    """Installed-role entry: original root↔runner only, actual birth on every frame.

    The caller supplies an already connected original socket, never a socket path
    from a model. This is OS peer authentication, not user/source authorization.
    Only terminal receipt processing may outlive that same peer. A reused PID,
    permission/proc error or disappearance during active checks still fails closed.
    """
    channel: EmbeddingBatchOwnerChannel | None = None
    lifetime: EmbeddingBatchOwnerPidfd | None = None
    try:
        owner = fixed_owner_identity()
        _require(side in ("ROOT", "OWNER") and type(expected_peer) is BenchmarkUnixPeer)
        local = (0, 0) if side == "ROOT" else (owner.owner_uid, owner.owner_gid)
        remote = (owner.owner_uid, owner.owner_gid) if side == "ROOT" else (0, 0)
        _require(
            (expected_peer.uid, expected_peer.gid) == remote
            and type(peer_start_ticks) is int
            and 0 < peer_start_ticks < 2**63
        )
        _require(
            embedding_batch_owner_start_ticks(
                expected_peer.pid, uid=expected_peer.uid, gid=expected_peer.gid
            )
            == peer_start_ticks
        )
        lifetime = EmbeddingBatchOwnerPidfd(expected_peer.pid)
        _require(
            embedding_batch_owner_start_ticks(
                expected_peer.pid, uid=expected_peer.uid, gid=expected_peer.gid
            )
            == peer_start_ticks
        )

        def fence(actual: BenchmarkUnixPeer) -> None:
            _require(
                actual == expected_peer
                and os.getresuid() == (local[0],) * 3
                and os.getresgid() == (local[1],) * 3
            )
            assert lifetime is not None
            terminal = channel is not None and channel.terminal_peer_exit_allowed
            if lifetime.wait_exited(until_ns=time.monotonic_ns()):
                _require(terminal)
                return
            try:
                observed = embedding_batch_owner_start_ticks(
                    actual.pid, uid=actual.uid, gid=actual.gid
                )
            except (ValueError, OSError):
                # /proc can become root-owned while the original process is
                # exiting, even before its State becomes Z. Only the original
                # kernel pidfd proves exit; no active-process parser is relaxed.
                if not terminal:
                    raise
                assert lifetime is not None
                if lifetime.wait_exited(until_ns=request.expires_monotonic_ns):
                    return
                raise
            _require(observed == peer_start_ticks)
            if lifetime.wait_exited(until_ns=time.monotonic_ns()):
                _require(terminal)

        channel = EmbeddingBatchOwnerChannel(
            connection,
            request,
            controller_release=controller_release,
            side=side,
            expected_peer=expected_peer,
            peer_fence=fence,
        )
        channel._peer_lifetime = lifetime
        return channel
    except BaseException:
        if lifetime is not None:
            lifetime.close()
        connection.close()
        raise EmbeddingBatchOwnerChannelError() from None
