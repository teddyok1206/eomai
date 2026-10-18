"""Bounded original-query progress, never a new queue, SQL root or transport retry."""

from threading import Event
from time import monotonic

from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareProtocolError,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
)

from eom_orchestrator.private_chat_query_prepare_client import (
    PRIVATE_CHAT_QUERY_RPC_TIMEOUT,
    PrivateChatQueryPrepareClient,
)

MAX_PRIVATE_CHAT_QUERY_WAIT_SECONDS = 180.0
MAX_PRIVATE_CHAT_QUERY_PROGRESS_ROUNDS = 12
PRIVATE_CHAT_QUERY_POLL_SECONDS = 5.0


def wait_for_original_private_chat_query(
    client: PrivateChatQueryPrepareClient,
    request: PrivateChatQueryPrepareRequest,
    *,
    stop: Event,
    deadline: float,
) -> PrivateChatQueryPrepareReply:
    """One initial admission, then acknowledged reads/explicit original progress only.

    Caller's live worker deadline may shorten but never extend this owner's bound.
    Errors propagate immediately: a timeout is unknown, not a reason to send again.
    PENDING at the bound is returned honestly; it is neither EMPTY nor completion.
    """
    request = parse_private_chat_query_prepare_request(request)
    now = monotonic()
    if request.action != "PREPARE_PRIVATE_CHAT_QUERY" or type(deadline) not in {int, float}:
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
    # Reject NaN/infinity rather than treating them as an unlimited worker budget.
    if not float("-inf") < deadline < float("inf"):
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
    deadline = min(deadline, now + MAX_PRIVATE_CHAT_QUERY_WAIT_SECONDS)
    if stop.is_set() or deadline - now < PRIVATE_CHAT_QUERY_RPC_TIMEOUT:
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_UNAVAILABLE")
    acknowledged = client.execute(request)
    for _ in range(MAX_PRIVATE_CHAT_QUERY_PROGRESS_ROUNDS):
        if acknowledged.status != "PENDING":
            return acknowledged
        remaining = deadline - monotonic()
        if remaining < PRIVATE_CHAT_QUERY_POLL_SECONDS + PRIVATE_CHAT_QUERY_RPC_TIMEOUT:
            return acknowledged
        if stop.wait(PRIVATE_CHAT_QUERY_POLL_SECONDS):
            return acknowledged
        if deadline - monotonic() < PRIVATE_CHAT_QUERY_RPC_TIMEOUT:
            return acknowledged
        observed = client.read_original(request, acknowledged)
        if observed.status != "PENDING":
            return observed
        if stop.is_set() or deadline - monotonic() < PRIVATE_CHAT_QUERY_RPC_TIMEOUT:
            return observed
        # This explicit admission is not hidden inside READ. The existing Runner
        # decides current original claim/checkpoint eligibility; this loop cannot.
        acknowledged = client.continue_pending_original(request, acknowledged)
    return acknowledged
