"""Explicit protected endpoint only; one exchange, no inference/authentication replay."""

import grp
import pwd
from pathlib import Path
from typing import Self

from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PRIVATE_CHAT_PREPARE_SOCKET,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)

from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)


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

    def execute(self, request: PrivateChatQueryPrepareRequest) -> PrivateChatQueryPrepareReply:
        request = parse_private_chat_query_prepare_request(request)
        # A timeout/disconnect is an unknown outcome. Let the existing transport
        # error propagate; no new key, fallback prepare or authentication occurs.
        value = exchange_chat_frame(
            self.endpoint,
            request.model_dump(mode="json"),
            request_limit=PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
            reply_limit=PRIVATE_CHAT_PREPARE_REPLY_BYTES,
            timeout=20,
        )
        return validate_private_chat_query_prepare_reply(request, value)
