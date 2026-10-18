"""Explicit protected endpoint only; one exchange, no inference/authentication replay."""

from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)

from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, exchange_chat_frame


class PrivateChatQueryPrepareClient:
    """Composition must select an installed trusted owner endpoint, never a worker path."""

    def __init__(self, endpoint: ChatSocketEndpoint) -> None:
        self.endpoint = endpoint

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
