"""Finite-concurrency private owner RPC; dispatch delegates to the existing use cases."""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from threading import BoundedSemaphore, Event
from time import monotonic
from typing import Self

from eom_catalog_contracts.private_chat_query_read import (
    PRIVATE_CHAT_SOURCE_REPLY_BYTES,
    PRIVATE_CHAT_SOURCE_REQUEST_BYTES,
    parse_private_chat_query_read_reply,
    parse_private_chat_query_read_request,
)
from eom_identifiers import canonical_json_bytes
from eom_protocol.general_chat_grounding import ChatGroundingQuery, ChatGroundingViews
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
from eom_protocol.general_chat_rag_turn import ChatGroundingViewsV2
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_private_query_source import (
    ChatPrivateQueryReadPort,
    failed_private_chat_query_read,
)
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


@dataclass(frozen=True, slots=True)
class PrivateChatQueryRpcAccess:
    """Separate source-only endpoint profile; never an extra peer on the API endpoint."""

    reader: ChatPrivateQueryReadPort
    peer_uid: int

    def __post_init__(self) -> None:
        if type(self.peer_uid) is not int or not 0 < self.peer_uid <= 2**31 - 1:
            raise ValueError("private query source requires an explicit non-root controller peer")


class GeneralChatOwnerRpcServer:
    def __init__(
        self,
        owner: ChatOwnerPort | None,
        *,
        endpoint: ChatSocketEndpoint,
        allowed_uids: frozenset[int],
        maximum_requests: int = 8,
        private_queries: PrivateChatQueryRpcAccess | None = None,
    ) -> None:
        api_profile = owner is not None and bool(allowed_uids) and private_queries is None
        private_profile = owner is None and not allowed_uids and private_queries is not None
        if not (api_profile or private_profile) or not 1 <= maximum_requests <= 16:
            raise ValueError("private owner admission requires bounded trusted peers")
        self.owner = owner
        self.private_queries = private_queries
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
            if request.schema_version.endswith("/4.0") and isinstance(value, ChatGroundingViews):
                value = ChatGroundingViewsV2.model_validate(value.model_dump(mode="json"))
            elif not request.schema_version.endswith("/4.0") and isinstance(
                value, ChatGroundingViewsV2
            ):
                raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
            reply = ChatOwnerReply(
                schema_version=request.reply_version,
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
                schema_version=request.reply_version,
                request_id=request.request_id,
                action=request.command.action,
                status="FAILED",
                value=None,
                error_code=code,
            )
        read_chat_owner_reply(reply.model_dump(mode="json"), request=request)
        return reply

    def _execute(self, request: ChatOwnerRequest) -> ChatOwnerValue:
        if self.owner is None:
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
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
                peer = chat_peer_uid(connection)
                private = self.private_queries
                if (private is None and peer not in self.allowed_uids) or (
                    private is not None and peer != private.peer_uid
                ):
                    return
                deadline = monotonic() + OWNER_RPC_TIMEOUT
                payload = receive_chat_frame(
                    connection,
                    limit=OWNER_REQUEST_LIMIT
                    if private is None
                    else PRIVATE_CHAT_SOURCE_REQUEST_BYTES,
                    deadline=deadline,
                )
                if private is not None:
                    source_request = parse_private_chat_query_read_request(
                        decode_chat_frame(payload)
                    )
                    try:
                        source_reply = parse_private_chat_query_read_reply(
                            private.reader.read(source_request), request=source_request
                        )
                    except Exception:
                        source_reply = failed_private_chat_query_read(
                            source_request, "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
                        )
                    send_chat_frame(
                        connection,
                        canonical_json_bytes(source_reply),
                        limit=PRIVATE_CHAT_SOURCE_REPLY_BYTES,
                        deadline=deadline,
                    )
                    return
                request = read_chat_owner_request(decode_chat_frame(payload))
                try:
                    reply = self.execute(request)
                except Exception:
                    # No raw SQL, filesystem, native output or user content in the
                    # wire error. The unknown outcome may already be committed.
                    reply = ChatOwnerReply(
                        schema_version=request.reply_version,
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
