"""Bounded current-capture QUERY socket host; handlers never run as root."""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from select import select
from threading import BoundedSemaphore, Event
from typing import Self

from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)

from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    bind_chat_listener,
    chat_peer_uid,
)
from eom_orchestrator.private_chat_query_prepare_transport import (
    PrivateChatQueryPreparationFactory,
    handle_private_chat_query_prepare_connection,
)
from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort
from eom_orchestrator.reference_query_prepare_transport import (
    handle_reference_query_prepare_connection,
)


@dataclass(frozen=True, slots=True)
class PrivateChatQueryListener:
    endpoint: ChatSocketEndpoint
    chat_uid: int
    factory: PrivateChatQueryPreparationFactory


class ReferenceQueryOwnerServer:
    """Finite accepted requests, no memory task backlog and no model/auth cache."""

    def __init__(
        self,
        *,
        endpoint: ChatSocketEndpoint,
        api_uid: int,
        admission: ProtectedInstalledIdentityProviderAdmission,
        application: Callable[[AuthenticatedOperatorSession], ReferenceQueryPreparationPort],
        private_queries: PrivateChatQueryListener | None = None,
    ) -> None:
        if (
            type(admission) is not ProtectedInstalledIdentityProviderAdmission
            or type(api_uid) is not int
            or api_uid <= 0
            or os.geteuid() <= 0
            or os.geteuid() != endpoint.owner_uid
            or endpoint.parent_mode != 0o2750
        ):
            raise ValueError("REFERENCE_QUERY_OWNER_SERVER_UNAVAILABLE")
        if private_queries is not None and (
            type(private_queries) is not PrivateChatQueryListener
            or type(private_queries.endpoint) is not ChatSocketEndpoint
            or type(private_queries.chat_uid) is not int
            or private_queries.chat_uid <= 0
            or private_queries.chat_uid == api_uid
            or private_queries.endpoint.owner_uid != endpoint.owner_uid
            or private_queries.endpoint.parent_mode != 0o2750
            or private_queries.endpoint.path == endpoint.path
            or private_queries.endpoint.path.parent == endpoint.path.parent
            or not callable(getattr(private_queries.factory, "application", None))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_LISTENER_UNAVAILABLE")
        self.endpoint, self.api_uid = endpoint, api_uid
        self.admission, self.application = admission, application
        self.private_queries = private_queries
        self.private_listener: socket.socket | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._private_socket_identity: tuple[int, int] | None = None
        self.stopped = Event()
        self.capacity = BoundedSemaphore(4)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reference-query-owner")
        try:
            self.listener = bind_chat_listener(endpoint, backlog=4)
            node = endpoint.path.lstat()
            self._socket_identity = (node.st_dev, node.st_ino)
            if private_queries is not None:
                self.private_listener = bind_chat_listener(private_queries.endpoint, backlog=4)
                private_node = private_queries.endpoint.path.lstat()
                self._private_socket_identity = (private_node.st_dev, private_node.st_ino)
        except BaseException:
            try:
                if self.private_listener is not None:
                    self.private_listener.close()
                    if self._private_socket_identity is not None and private_queries is not None:
                        self._unlink_owned(private_queries.endpoint, self._private_socket_identity)
                if hasattr(self, "listener"):
                    self.listener.close()
                    if self._socket_identity is not None:
                        self._unlink_owned(self.endpoint, self._socket_identity)
            finally:
                self.pool.shutdown(wait=True)
            raise

    def _handle(self, connection: socket.socket) -> None:
        try:
            with connection:
                handle_reference_query_prepare_connection(
                    connection,
                    admission=self.admission,
                    api_uid=self.api_uid,
                    application=self.application,
                )
        finally:
            self.capacity.release()

    def _handle_private(self, connection: socket.socket) -> None:
        try:
            with connection:
                private = self.private_queries
                if private is None:
                    return
                try:
                    if chat_peer_uid(connection) != private.chat_uid:
                        return
                    pin = self.admission.observation.pin
                    self.admission.assert_current(
                        source_commit=pin.source_commit,
                        wheel_sha256=pin.wheel_sha256,
                        configuration_sha256=pin.configuration_sha256,
                    )
                    handle_private_chat_query_prepare_connection(
                        connection, chat_uid=private.chat_uid, factory=private.factory
                    )
                except Exception:
                    # No provider observation/input/exception representation is
                    # disclosed, and no alternate capture/application is tried.
                    return
        finally:
            self.capacity.release()

    def serve(self, *, stop_requested: Callable[[], bool] = lambda: False) -> None:
        listeners = (
            (self.listener,)
            if self.private_listener is None
            else (self.listener, self.private_listener)
        )
        while not self.stopped.is_set() and not stop_requested():
            try:
                ready, _, _ = select(listeners, (), (), 0.25)
            except (OSError, ValueError):
                if self.stopped.is_set():
                    return
                raise
            for listener in ready:
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self.stopped.is_set():
                        return
                    raise
                if not self.capacity.acquire(blocking=False):
                    connection.close()
                    continue
                handler = (
                    self._handle_private if listener is self.private_listener else self._handle
                )
                try:
                    self.pool.submit(handler, connection)
                except RuntimeError:
                    self.capacity.release()
                    connection.close()
                    if self.stopped.is_set():
                        return
                    raise

    def stop(self) -> None:
        self.stopped.set()
        self.listener.close()
        if self.private_listener is not None:
            self.private_listener.close()

    def close(self) -> None:
        self.stop()
        self.pool.shutdown(wait=True)
        if self._socket_identity is not None:
            self._unlink_owned(self.endpoint, self._socket_identity)
        if self.private_queries is not None and self._private_socket_identity is not None:
            self._unlink_owned(self.private_queries.endpoint, self._private_socket_identity)

    @staticmethod
    def _unlink_owned(endpoint: ChatSocketEndpoint, identity: tuple[int, int]) -> None:
        with suppress(FileNotFoundError):
            node = endpoint.path.lstat()
            if (node.st_dev, node.st_ino) == identity:
                endpoint.require_socket()
                endpoint.path.unlink()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
