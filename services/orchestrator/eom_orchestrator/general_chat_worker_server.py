"""Private isolated-worker RPC; only the trusted Orchestrator owner may invoke."""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import BoundedSemaphore, Event
from time import monotonic
from typing import Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerError,
    ChatWorkerExecute,
    read_chat_worker_reply,
    read_chat_worker_request,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import (
    WORKER_EXECUTE_TIMEOUT,
    WORKER_FRAME_LIMIT,
    WORKER_PROBE_TIMEOUT,
    ChatSocketEndpoint,
    ChatTransportError,
    bind_chat_listener,
    chat_peer_uid,
    decode_chat_frame,
    receive_chat_frame,
    send_chat_frame,
)
from eom_orchestrator.general_chat_worker import ChatWorkerApplication


class ChatWorkerRpcServer:
    def __init__(
        self, worker: ChatWorkerApplication, *, endpoint: ChatSocketEndpoint, owner_uid: int
    ) -> None:
        if owner_uid < 0:
            raise ValueError("worker RPC requires an exact trusted owner")
        self.worker = worker
        self.endpoint = endpoint
        self.owner_uid = owner_uid
        self.stopped = Event()
        # One generation plus two probes/lookups, never an unbounded executor queue.
        self.capacity = BoundedSemaphore(3)
        self.listener = bind_chat_listener(endpoint, backlog=3)
        node = endpoint.path.lstat()
        self._socket_identity = (node.st_dev, node.st_ino)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="chat-worker")

    def _handle(self, connection: socket.socket) -> None:
        with connection:
            try:
                if chat_peer_uid(connection) != self.owner_uid:
                    return
                payload = receive_chat_frame(
                    connection,
                    limit=WORKER_FRAME_LIMIT,
                    deadline=monotonic() + WORKER_PROBE_TIMEOUT,
                )
                request = read_chat_worker_request(decode_chat_frame(payload))
                deadline = monotonic() + (
                    WORKER_EXECUTE_TIMEOUT
                    if isinstance(request.command, ChatWorkerExecute)
                    else WORKER_PROBE_TIMEOUT
                )
                try:
                    reply = self.worker.handle(request)
                except Exception:
                    reply = self.worker.failure(request, ChatWorkerError.RECOVERY)
                read_chat_worker_reply(reply.model_dump(mode="json"), request=request)
                send_chat_frame(
                    connection,
                    canonical_json_bytes(reply.model_dump(mode="json")),
                    limit=WORKER_FRAME_LIMIT,
                    deadline=deadline,
                )
            except (OSError, ValueError, SchemaError, ChatTransportError):
                # A disconnect after execution leaves its exact local result intact.
                # No implicit retry, raw errors, native reasoning or new claim.
                return

    def _serve_connection(self, connection: socket.socket) -> None:
        try:
            self._handle(connection)
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
                self.pool.submit(self._serve_connection, connection)
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
