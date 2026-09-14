"""Authoritative Graph-authorization supersession rule for mock-exam recovery."""

from __future__ import annotations

from eom_api_contracts.mock_exam_execution import (
    MockExamGraphPublicationAuthorizationPointerV1,
    MockExamProductionExecutionV1,
)

_SAME_BASE_PRECOMMIT_FAILURE_CODES = frozenset(
    {
        # Catalog emits this only while validating candidates, origin scopes, retrieval-derived
        # alignments, or structure inputs before the atomic Graph publication call.
        "APPROVED_ITEM_GRAPH_ANALYSIS_INELIGIBLE",
    }
)


def graph_authorization_supersession_is_valid(
    checkpoint: MockExamProductionExecutionV1,
    authorization: MockExamGraphPublicationAuthorizationPointerV1,
) -> bool:
    """Return whether ``authorization`` may replace the pinned, failed authorization."""

    previous = checkpoint.graph_publication_authorization
    failure = checkpoint.failure
    if (
        previous is None
        or checkpoint.graph_publications
        or failure is None
        or failure.stage != "GRAPH_PUBLICATION"
        or failure.retryable is not True
        or authorization.supersedes_authorization_sha256 != previous.authorization_sha256
        or authorization.authorized_at <= previous.authorized_at
        or authorization.access_policy_revision_id != previous.access_policy_revision_id
        or authorization.access_policy_sha256 != previous.access_policy_sha256
    ):
        return False
    if failure.code == "KNOWLEDGE_GRAPH_STALE_CURRENT":
        return True
    if failure.code not in _SAME_BASE_PRECOMMIT_FAILURE_CODES:
        return False
    return (
        authorization.current_graph_snapshot_revision_id
        == previous.current_graph_snapshot_revision_id
        and authorization.current_graph_snapshot_sha256 == previous.current_graph_snapshot_sha256
    )
