"""Explicit protected endpoint only; one exchange, no inference/authentication replay."""

import grp
import pwd
from pathlib import Path
from typing import Self, overload

from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PRIVATE_CHAT_PREPARE_SOCKET,
    PrivateChatQueryPrepareProtocolError,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
)
from eom_catalog_contracts.private_chat_query_prepare_v2 import (
    PrivateChatQueryPrepareReplyV2,
    PrivateChatQueryPrepareRequestV2,
    SupportedPrivateChatQueryPrepareReply,
    SupportedPrivateChatQueryPrepareRequest,
    parse_supported_private_chat_query_prepare_request,
    validate_supported_private_chat_query_prepare_reply,
)
from eom_identifiers import content_sha256

from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)

PRIVATE_CHAT_QUERY_RPC_TIMEOUT = 20.0


def fixed_private_chat_query_prepare_endpoint() -> ChatSocketEndpoint:
    """One trusted layout for host and client; never selected by worker/request fields."""
    try:
        owner = pwd.getpwnam("eom-workflow-runner").pw_uid
        group = grp.getgrnam("eom-general-chat").gr_gid
    except (KeyError, OSError):
        raise ChatTransportError("UNAVAILABLE") from None
    if type(owner) is not int or type(group) is not int or owner <= 0 or group <= 0:
        raise ChatTransportError("INVALID")
    return ChatSocketEndpoint(Path(PRIVATE_CHAT_PREPARE_SOCKET), owner, group, parent_mode=0o2750)


class PrivateChatQueryPrepareClient:
    """Composition must select an installed trusted owner endpoint, never a worker path."""

    def __init__(self, endpoint: ChatSocketEndpoint) -> None:
        self.endpoint = endpoint

    @classmethod
    def for_installed_owner(cls) -> Self:
        """Select only fixed OS identities/layout; each exchange still validates DAC/peer."""
        return cls(fixed_private_chat_query_prepare_endpoint())

    @overload
    def execute(self, request: PrivateChatQueryPrepareRequest) -> PrivateChatQueryPrepareReply: ...

    @overload
    def execute(
        self, request: PrivateChatQueryPrepareRequestV2
    ) -> PrivateChatQueryPrepareReplyV2: ...

    def execute(
        self, request: SupportedPrivateChatQueryPrepareRequest
    ) -> SupportedPrivateChatQueryPrepareReply:
        request = parse_supported_private_chat_query_prepare_request(request)
        # A timeout/disconnect is an unknown outcome. Let the existing transport
        # error propagate; no new key, fallback prepare or authentication occurs.
        value = exchange_chat_frame(
            self.endpoint,
            request.model_dump(mode="json"),
            request_limit=PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
            reply_limit=PRIVATE_CHAT_PREPARE_REPLY_BYTES,
            timeout=PRIVATE_CHAT_QUERY_RPC_TIMEOUT,
        )
        return validate_supported_private_chat_query_prepare_reply(request, value)

    @overload
    def continue_pending_original(
        self, request: PrivateChatQueryPrepareRequest, acknowledged: PrivateChatQueryPrepareReply
    ) -> PrivateChatQueryPrepareReply: ...

    @overload
    def continue_pending_original(
        self,
        request: PrivateChatQueryPrepareRequestV2,
        acknowledged: PrivateChatQueryPrepareReplyV2,
    ) -> PrivateChatQueryPrepareReplyV2: ...

    def continue_pending_original(
        self,
        request: SupportedPrivateChatQueryPrepareRequest,
        acknowledged: SupportedPrivateChatQueryPrepareReply,
    ) -> SupportedPrivateChatQueryPrepareReply:
        """One explicit progress action after known PENDING; never a transport retry or read."""
        request, acknowledged = _original_acknowledgement(request, acknowledged)
        if acknowledged.status != "PENDING":
            raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
        reply = self.execute(request)
        _same_original(acknowledged, reply)
        return reply

    @overload
    def read_original(
        self, request: PrivateChatQueryPrepareRequest, acknowledged: PrivateChatQueryPrepareReply
    ) -> PrivateChatQueryPrepareReply: ...

    @overload
    def read_original(
        self,
        request: PrivateChatQueryPrepareRequestV2,
        acknowledged: PrivateChatQueryPrepareReplyV2,
    ) -> PrivateChatQueryPrepareReplyV2: ...

    def read_original(
        self,
        request: SupportedPrivateChatQueryPrepareRequest,
        acknowledged: SupportedPrivateChatQueryPrepareReply,
    ) -> SupportedPrivateChatQueryPrepareReply:
        """One READ of an acknowledged original; absent/failed/unknown never causes PREPARE."""
        request, acknowledged = _original_acknowledgement(request, acknowledged)
        document = request.model_dump(mode="json", exclude={"request_sha256"})
        document["action"] = "READ_PRIVATE_CHAT_QUERY"
        document["request_sha256"] = content_sha256(document)
        reply = self.execute(parse_supported_private_chat_query_prepare_request(document))
        _same_original(acknowledged, reply)
        return reply


def _original_acknowledgement(
    request: SupportedPrivateChatQueryPrepareRequest, reply: SupportedPrivateChatQueryPrepareReply
) -> tuple[SupportedPrivateChatQueryPrepareRequest, SupportedPrivateChatQueryPrepareReply]:
    request = parse_supported_private_chat_query_prepare_request(request)
    reply = validate_supported_private_chat_query_prepare_reply(request, reply)
    if request.action != "PREPARE_PRIVATE_CHAT_QUERY" or reply.status not in {"PENDING", "READY"}:
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
    return request, reply


def _same_original(
    acknowledged: SupportedPrivateChatQueryPrepareReply,
    reply: SupportedPrivateChatQueryPrepareReply,
) -> None:
    if reply.workflow_id is not None and reply.workflow_id != acknowledged.workflow_id:
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REPLY_INVALID")
