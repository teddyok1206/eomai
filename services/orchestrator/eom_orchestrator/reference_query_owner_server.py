"""Bounded current-capture QUERY socket host; handlers never run as root."""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import BoundedSemaphore, Event
from typing import Self

from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)

from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, bind_chat_listener
from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort
from eom_orchestrator.reference_query_prepare_transport import (
    handle_reference_query_prepare_connection,
)


class ReferenceQueryOwnerServer:
    """Finite accepted requests, no memory task backlog and no model/auth cache."""

    def __init__(
        self,
        *,
        endpoint: ChatSocketEndpoint,
        api_uid: int,
        admission: ProtectedInstalledIdentityProviderAdmission,
        application: Callable[[AuthenticatedOperatorSession], ReferenceQueryPreparationPort],
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
        self.endpoint, self.api_uid = endpoint, api_uid
        self.admission, self.application = admission, application
        self.stopped = Event()
        self.capacity = BoundedSemaphore(4)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reference-query-owner")
        try:
            self.listener = bind_chat_listener(endpoint, backlog=4)
            node = endpoint.path.lstat()
            self._socket_identity = (node.st_dev, node.st_ino)
        except BaseException:
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

    def serve(self) -> None:
        while not self.stopped.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self.stopped.is_set():
                    return
                raise
            if not self.capacity.acquire(blocking=False):
                connection.close()
                continue
            try:
                self.pool.submit(self._handle, connection)
            except RuntimeError:
                self.capacity.release()
                connection.close()
                raise

    def stop(self) -> None:
        self.stopped.set()
        self.listener.close()

    def close(self) -> None:
        self.stop()
        self.pool.shutdown(wait=True)
        with suppress(FileNotFoundError):
            node = self.endpoint.path.lstat()
            if (node.st_dev, node.st_ino) == self._socket_identity:
                self.endpoint.require_socket()
                self.endpoint.path.unlink()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
