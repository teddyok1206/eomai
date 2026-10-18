"""One closed original-launch root control exchange; no source or compute authorization."""

from __future__ import annotations

import re
import selectors
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Literal

from eom_workflow.embedding_benchmark_launch_control import (
    BENCHMARK_CONTROL_SECONDS,
    BenchmarkLaunchAssociation,
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    BenchmarkLaunchUncertain,
    benchmark_launch_control_bytes,
    parse_benchmark_launch_control,
    parse_benchmark_launch_control_bytes,
    validate_benchmark_control_reply,
)

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer, PeerFence, _Frames


class _Phase(StrEnum):
    NEW = "NEW"
    ASSOCIATED = "ASSOCIATED"
    PREPARED = "PREPARED"
    RESOURCE_BORROWED = "RESOURCE_BORROWED"
    RESOURCE_COMPLETE = "RESOURCE_COMPLETE"
    TERMINAL = "TERMINAL"


_TRANSITIONS = {
    ("OWNER", _Phase.NEW, "SEND_ASSOCIATION"): _Phase.ASSOCIATED,
    ("ROOT", _Phase.NEW, "READ_ASSOCIATION"): _Phase.ASSOCIATED,
    ("ROOT", _Phase.ASSOCIATED, "SEND_PREPARED"): _Phase.PREPARED,
    ("OWNER", _Phase.ASSOCIATED, "READ_PREPARED"): _Phase.PREPARED,
}


class BenchmarkLaunchControlChannel:
    """Trusted composition supplies the actual exact peer and installed root release.

    For CUDA, the resource context transfers a duplicate only; the unchanged resource
    endpoints consume exact frames and close that duplicate before control resumes.
    Any exception poisons the original connection; no ambiguous stream resynchronization.
    """

    def __init__(
        self,
        connection: socket.socket,
        association: BenchmarkLaunchAssociation,
        *,
        side: Literal["OWNER", "ROOT"],
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        controller_release: str,
    ) -> None:
        self._frames: _Frames | None = None
        try:
            checked = parse_benchmark_launch_control(association)
            if not isinstance(checked, BenchmarkLaunchAssociation) or side not in {"OWNER", "ROOT"}:
                raise ValueError("BENCHMARK_CONTROL_ASSOCIATION_INVALID")
            # The release pin is configuration, not a model-selected role/identity.

            if (
                type(controller_release) is not str
                or re.fullmatch(r"[0-9a-f]{40}", controller_release, re.ASCII) is None
            ):
                raise ValueError("BENCHMARK_CONTROL_RELEASE_INVALID")
            self.association, self._side, self._release = checked, side, controller_release
            self._phase = _Phase.NEW
            self._prepared: BenchmarkLaunchPrepared | None = None
            self._frames = _Frames(
                connection,
                expected_peer,
                peer_fence,
                checked.expires_ns + 30 * 10**9,
                maximum_lifetime_seconds=BENCHMARK_CONTROL_SECONDS,
            )
        except BaseException:
            connection.close()
            raise

    def _transport(self) -> _Frames:
        if self._frames is None:
            raise ValueError("BENCHMARK_CONTROL_CLOSED")
        self._frames.check()
        return self._frames

    @classmethod
    def accept_root_association(
        cls,
        connection: socket.socket,
        *,
        expected_peer: BenchmarkUnixPeer,
        peer_fence: PeerFence,
        controller_release: str,
        accept_until_ns: int,
    ) -> BenchmarkLaunchControlChannel:
        """Consume one existing association from the exact selected owner, once.

        The short receive bound is not a compute deadline or authentication
        grant. After it, retain only the original association's absolute control
        deadline. No bytes are peeked/replayed and no second socket is created.
        """
        bootstrap = None
        try:
            now = time.monotonic_ns()
            if type(accept_until_ns) is not int or not now < accept_until_ns <= now + 900 * 10**9:
                raise ValueError("BENCHMARK_CONTROL_ACCEPT_DEADLINE_INVALID")
            bootstrap = _Frames(
                connection,
                expected_peer,
                peer_fence,
                min(accept_until_ns, now + 10 * 10**9),
            )
            value = parse_benchmark_launch_control_bytes(bootstrap.receive_raw())
            now = time.monotonic_ns()
            if not isinstance(value, BenchmarkLaunchAssociation) or not (
                now < value.expires_ns <= now + 180 * 10**9
            ):
                raise ValueError("BENCHMARK_CONTROL_ASSOCIATION_INVALID")
            bootstrap.check()
            channel = cls(
                connection,
                value,
                side="ROOT",
                expected_peer=expected_peer,
                peer_fence=peer_fence,
                controller_release=controller_release,
            )
            channel._phase = _Phase.ASSOCIATED
            # Transfer the same owned socket; an inactive bootstrap must no
            # longer be able to close the new original-deadline transport.
            bootstrap.closed = True
            return channel
        except BaseException:
            if bootstrap is not None:
                bootstrap.invalidate()
            connection.close()
            raise

    def require_root_association(
        self,
        association: BenchmarkLaunchAssociation,
        *,
        expected_peer: BenchmarkUnixPeer,
        controller_release: str,
    ) -> None:
        """The exact already-received root phase, not a caller-supplied grant."""
        try:
            if (
                self._side != "ROOT"
                or self._phase != _Phase.ASSOCIATED
                or self.association != association
                or self._release != controller_release
            ):
                raise ValueError("BENCHMARK_CONTROL_ASSOCIATION_INVALID")
            if self._transport().peer != expected_peer:
                raise ValueError("BENCHMARK_CONTROL_ASSOCIATION_INVALID")
        except BaseException:
            self.close()
            raise

    def _transition(self, event: str) -> None:
        after = _TRANSITIONS.get((self._side, self._phase, event))
        if after is None:
            self.close()
            raise ValueError("BENCHMARK_CONTROL_ORDER_INVALID")
        self._phase = after

    def send_association(self) -> None:
        try:
            self._transition("SEND_ASSOCIATION")
            self._transport().send_raw(benchmark_launch_control_bytes(self.association))
        except BaseException:
            self.close()
            raise

    def receive_association(self) -> BenchmarkLaunchAssociation:
        try:
            self._transition("READ_ASSOCIATION")
            value = parse_benchmark_launch_control_bytes(self._transport().receive_raw())
            if value != self.association:
                raise ValueError("BENCHMARK_CONTROL_ASSOCIATION_INVALID")
            return self.association
        except BaseException:
            self.close()
            raise

    def send_prepared(self, prepared: BenchmarkLaunchPrepared) -> None:
        try:
            self._transition("SEND_PREPARED")
            value = parse_benchmark_launch_control(prepared)
            if (
                not isinstance(value, BenchmarkLaunchPrepared)
                or value.controller_release != self._release
            ):
                raise ValueError("BENCHMARK_CONTROL_RELEASE_INVALID")
            validate_benchmark_control_reply(self.association, value)
            self._transport().send_raw(benchmark_launch_control_bytes(value))
            self._prepared = value
        except BaseException:
            self.close()
            raise

    def receive_prepared(self) -> BenchmarkLaunchPrepared | BenchmarkLaunchUncertain:
        try:
            self._transition("READ_PREPARED")
            value = parse_benchmark_launch_control_bytes(self._transport().receive_raw())
            if not isinstance(value, BenchmarkLaunchPrepared | BenchmarkLaunchUncertain):
                raise ValueError("BENCHMARK_CONTROL_REPLY_INVALID")
            validate_benchmark_control_reply(self.association, value)
            if isinstance(value, BenchmarkLaunchUncertain):
                self._phase = _Phase.TERMINAL
            else:
                if value.controller_release != self._release:
                    raise ValueError("BENCHMARK_CONTROL_RELEASE_INVALID")
                self._prepared = value
            return value
        except BaseException:
            self.close()
            raise

    @contextmanager
    def resources(self) -> Iterator[socket.socket]:
        duplicate = None
        try:
            if self.association.device != "CUDA" or self._phase != _Phase.PREPARED:
                raise ValueError("BENCHMARK_CONTROL_RESOURCE_ORDER_INVALID")
            self._phase = _Phase.RESOURCE_BORROWED
            duplicate = self._transport().connection.dup()
            duplicate.set_inheritable(False)
            yield duplicate
            if duplicate.fileno() != -1:
                raise ValueError("BENCHMARK_CONTROL_RESOURCE_NOT_CLOSED")
            self._transport()
            self._phase = _Phase.RESOURCE_COMPLETE
        except BaseException:
            self.close()
            raise
        finally:
            if duplicate is not None:
                duplicate.close()

    def _completion(self) -> None:
        if (self.association.device, self._phase) not in {
            ("CPU", _Phase.PREPARED),
            ("CUDA", _Phase.RESOURCE_COMPLETE),
        } or self._prepared is None:
            raise ValueError("BENCHMARK_CONTROL_COMPLETION_ORDER_INVALID")

    def send_completed(self, value: BenchmarkLaunchCompleted) -> None:
        try:
            if self._side != "ROOT":
                raise ValueError("BENCHMARK_CONTROL_ORDER_INVALID")
            self._completion()
            validate_benchmark_control_reply(self.association, value, prepared=self._prepared)
            self._transport().send_raw(benchmark_launch_control_bytes(value))
            self._phase = _Phase.TERMINAL
        except BaseException:
            self.close()
            raise

    def wait_for_owner_close(self) -> None:
        """Keep the root peer alive until its queued completion is actually consumed.

        No new command or implicit acknowledgement is accepted. Publication is not
        attested by EOF; root's machine completion has already been persisted.
        The original absolute control deadline bounds a disconnected/stuck owner.
        """
        try:
            if self._side != "ROOT" or self._phase != _Phase.TERMINAL:
                raise ValueError("BENCHMARK_CONTROL_ORDER_INVALID")
            frames = self._transport()
            while True:
                frames.check()
                try:
                    raw = frames.connection.recv(1, socket.MSG_DONTWAIT | socket.MSG_PEEK)
                except BlockingIOError:
                    frames.wait(selectors.EVENT_READ)
                    continue
                if raw:
                    raise ValueError("BENCHMARK_CONTROL_UNEXPECTED_TRAILING_INPUT")
                return
        except BaseException:
            self.close()
            raise

    def receive_completed(self) -> BenchmarkLaunchCompleted:
        try:
            if self._side != "OWNER":
                raise ValueError("BENCHMARK_CONTROL_ORDER_INVALID")
            self._completion()
            value = parse_benchmark_launch_control_bytes(self._transport().receive_raw())
            if not isinstance(value, BenchmarkLaunchCompleted):
                raise ValueError("BENCHMARK_CONTROL_REPLY_INVALID")
            validate_benchmark_control_reply(self.association, value, prepared=self._prepared)
            self._phase = _Phase.TERMINAL
            return value
        except BaseException:
            self.close()
            raise

    def send_uncertain(self, value: BenchmarkLaunchUncertain) -> None:
        try:
            if self._side != "ROOT" or self._phase != _Phase.ASSOCIATED:
                raise ValueError("BENCHMARK_CONTROL_ORDER_INVALID")
            validate_benchmark_control_reply(self.association, value)
            self._transport().send_raw(benchmark_launch_control_bytes(value))
            self._phase = _Phase.TERMINAL
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._frames is not None:
            self._frames.invalidate()
            self._frames = None
