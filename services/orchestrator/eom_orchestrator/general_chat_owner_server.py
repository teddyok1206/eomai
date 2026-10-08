"""Finite-concurrency private owner RPC; dispatch delegates to the existing use cases."""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import BoundedSemaphore, Event
from time import monotonic
from typing import Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.general_chat_grounding import ChatGroundingQuery
from eom_protocol.general_chat_owner_messages import (
    ChatCreateCommand,
    ChatListQuery,
    ChatOwnerErrorCode,
    ChatOwnerPort,
    ChatOwnerReply,
    ChatOwnerRequest,
    ChatOwnerValue,
    ChatReadQuery,
    ChatSlotQuery,
    ChatSubmitCommand,
    read_chat_owner_reply,
    read_chat_owner_request,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import (
    OWNER_REPLY_LIMIT,
    OWNER_REQUEST_LIMIT,
    OWNER_RPC_TIMEOUT,
    ChatSocketEndpoint,
    ChatTransportError,
    bind_chat_listener,
    chat_peer_uid,
    decode_chat_frame,
    receive_chat_frame,
    send_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError


class GeneralChatOwnerRpcServer:
    def __init__(
        self,
        owner: ChatOwnerPort,
        *,
        endpoint: ChatSocketEndpoint,
        allowed_uids: frozenset[int],
        maximum_requests: int = 8,
    ) -> None:
        if not allowed_uids or not 1 <= maximum_requests <= 16:
            raise ValueError("private owner admission requires bounded trusted peers")
        self.owner = owner
        self.endpoint = endpoint
        self.allowed_uids = allowed_uids
        self.stopped = Event()
        self.capacity = BoundedSemaphore(maximum_requests)
        self.pool = ThreadPoolExecutor(
            max_workers=maximum_requests, thread_name_prefix="chat-owner"
        )
        self.listener = bind_chat_listener(endpoint, backlog=maximum_requests)
        node = endpoint.path.lstat()
        self._socket_identity = (node.st_dev, node.st_ino)

    def execute(self, request: ChatOwnerRequest) -> ChatOwnerReply:
        try:
            value = self._execute(request)
            reply = ChatOwnerReply(
                schema_version="general-chat-owner-reply/2.0"
                if request.schema_version.endswith("/2.0")
                else "general-chat-owner-reply/1.0",
                request_id=request.request_id,
                action=request.command.action,
                status="SUCCEEDED",
                value=value,
                error_code=None,
            )
        except ChatError as exc:
            try:
                code = ChatOwnerErrorCode(exc.code)
            except ValueError:
                code = ChatOwnerErrorCode.UNAVAILABLE
            reply = ChatOwnerReply(
                schema_version="general-chat-owner-reply/2.0"
                if request.schema_version.endswith("/2.0")
                else "general-chat-owner-reply/1.0",
                request_id=request.request_id,
                action=request.command.action,
                status="FAILED",
                value=None,
                error_code=code,
            )
        read_chat_owner_reply(reply.model_dump(mode="json"), request=request)
        return reply

    def _execute(self, request: ChatOwnerRequest) -> ChatOwnerValue:
        command = request.command
        if isinstance(command, ChatGroundingQuery):
            return self.owner.grounding(
                actor_id=command.actor_id,
                conversation_id=command.conversation_id,
                turn_ids=command.turn_ids,
            )
        if isinstance(command, ChatSlotQuery):
            return self.owner.slot()
        if isinstance(command, ChatListQuery):
            return self.owner.conversations(actor_id=command.actor_id, cursor=command.cursor)
        if isinstance(command, ChatCreateCommand):
            return self.owner.create(
                actor_id=command.actor_id,
                request=command.request,
                idempotency_key=command.idempotency_key,
            )
        if isinstance(command, ChatReadQuery):
            return self.owner.conversation(
                actor_id=command.actor_id,
                conversation_id=command.conversation_id,
                cursor=command.cursor,
            )
        assert isinstance(command, ChatSubmitCommand)
        return self.owner.submit(
            actor_id=command.actor_id,
            conversation_id=command.conversation_id,
            request=command.request,
            idempotency_key=command.idempotency_key,
        )

    def _handle(self, connection: socket.socket) -> None:
        with connection:
            try:
                if chat_peer_uid(connection) not in self.allowed_uids:
                    return
                deadline = monotonic() + OWNER_RPC_TIMEOUT
                payload = receive_chat_frame(
                    connection, limit=OWNER_REQUEST_LIMIT, deadline=deadline
                )
                request = read_chat_owner_request(decode_chat_frame(payload))
                try:
                    reply = self.execute(request)
                except Exception:
                    # No raw SQL, filesystem, native output or user content in the
                    # wire error. The unknown outcome may already be committed.
                    reply = ChatOwnerReply(
                        schema_version="general-chat-owner-reply/2.0"
                        if request.schema_version.endswith("/2.0")
                        else "general-chat-owner-reply/1.0",
                        request_id=request.request_id,
                        action=request.command.action,
                        status="FAILED",
                        value=None,
                        error_code=ChatOwnerErrorCode.UNAVAILABLE,
                    )
                send_chat_frame(
                    connection,
                    canonical_json_bytes(reply.model_dump(mode="json")),
                    limit=OWNER_REPLY_LIMIT,
                    deadline=deadline,
                )
            except (OSError, ValueError, SchemaError, ChatTransportError):
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
