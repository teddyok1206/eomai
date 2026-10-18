"""Actual caller and original private turn → pinned Workflow/START, never model execution."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_workflow.private_chat_query_execution import (
    parse_private_chat_query_workflow_request,
    validate_private_chat_query_request_references,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    parse_private_chat_query_submission_context,
    private_chat_query_origin_key,
    validate_private_chat_query_submission_context,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import (
    read_pinned_private_chat_query_controls,
    require_private_chat_query_source_root,
)
from eom_workflow_runner.private_chat_query_submission import (
    PrivateChatQueryWorkflowSubmitted,
    start_private_chat_query_in_session,
)


def prepare_and_start_private_chat_query_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    origin: ChatPrivateQueryOrigin,
    context: PrivateChatSimilarityRequest,
    owner: CatalogPrivateChatQueryOwnerAdmission,
    executor: PrivateChatQueryNativeExecutor,
) -> PrivateChatQueryWorkflowSubmitted:
    """Build first-use pins only; replay preserves the exact original audit and request.

    The actual owner must still reauthorize Chat/Catalog sources during atomic
    submission. No question text, caller-chosen key, default admission, commit,
    physical execution, saved session or cached authorization is introduced.
    """
    root = require_private_chat_query_source_root(session)
    if (
        type(caller) is not EmbeddingRegistryCaller
        or session.get_bind() is not owner.catalog.engine
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    validate_embedding_registry_actor(caller)
    try:
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        context = PrivateChatSimilarityRequest.model_validate(
            raw_similarity_contract_value(context)
        )
        if origin.actor_id != caller.operator_id or origin.basis != context.query_basis:
            raise ValueError()
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_CONTEXT_INVALID") from None

    owner.sources.identity.fence_current_operator(session, caller.operator_id)
    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    existing = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.idempotency_key == private_chat_query_origin_key(origin))
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        request = parse_private_chat_query_workflow_request(existing.initial_request)
        original_context = validate_private_chat_query_submission_context(
            request, parse_private_chat_query_submission_context(existing.runtime_context)
        )
        if (
            existing.created_actor_type != "human"
            or existing.created_actor_id != caller.operator_id
            or original_context.origin != origin
            or request.context_request != context
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_REPLAY_MISMATCH")
    else:
        config = owner.configuration
        policy, bundle = read_pinned_private_chat_query_controls(
            PinnedArtifactReadContext(session, owner.settings), config
        )
        body = {
            "schema_version": "private-chat-query-workflow-request/1.0",
            "request_name": "PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST",
            "purpose": "PRIVATE_CHAT_QUERY",
            "workflow_definition_key": "local-embedding-private-chat-query",
            "workflow_definition_version": "1.0.0",
            "workflow_definition_sha256": policy.workflow_definition_sha256,
            "operator_audit": {
                "kind": "OPERATOR",
                "operator_id": caller.operator_id,
                "requester_permissions_sha256": content_sha256(
                    sorted(key.value for key in effective_permissions(session, caller.operator_id))
                ),
            },
            "context_request": context.model_dump(mode="json"),
            "runtime_bundle": config.runtime_bundle.model_dump(mode="json"),
            "resource_profile": policy.resource_profile.model_dump(mode="json"),
            "native_execution_policy": config.native_execution_policy.model_dump(mode="json"),
            "native_execution_policy_sha256": config.native_execution_policy_sha256,
        }
        request = parse_private_chat_query_workflow_request(
            body | {"request_sha256": content_sha256(body)}
        )
        validate_private_chat_query_request_references(request, policy, bundle)
        original_context = build_private_chat_query_submission_context(request, origin)

    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    definition = session.scalar(
        select(WorkflowDefinitionRecord)
        .where(
            WorkflowDefinitionRecord.definition_key == request.workflow_definition_key,
            WorkflowDefinitionRecord.definition_version == request.workflow_definition_version,
        )
        .execution_options(populate_existing=True)
    )
    if definition is None or definition.definition_hash != request.workflow_definition_sha256:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_DEFINITION_UNAVAILABLE")
    return start_private_chat_query_in_session(
        session,
        definition=definition,
        request=request,
        context=original_context,
        actor_type="human",
        actor_id=caller.operator_id,
        owner=owner,
        executor=executor,
    )
