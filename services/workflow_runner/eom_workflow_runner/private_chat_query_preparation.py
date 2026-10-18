"""Actual caller and original private turn → pinned Workflow/START, never model execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_basis import PrivateChatQueryBasis
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    PrivateChatContextPreparation,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_context_preparation import (
    validate_private_chat_context_preparation,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_orchestrator.general_chat_state import ChatError
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
    validate_private_chat_query_request_references,
)
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    build_private_chat_query_submission_context,
    private_chat_query_origin_key,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_admission import (
    validate_private_chat_query_workflow_submission,
)
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


@dataclass(frozen=True, slots=True)
class SelectedPrivateChatQueryWorkflow:
    """Original immutable selection and observed state, never retained authority."""

    workflow_id: str
    state: str
    request: PrivateChatQueryWorkflowRequest
    context: PrivateChatQuerySubmissionContext


class PrivateChatQueryPreparationUnavailable(ValueError):
    """Known initial absence, never permission to relabel another numerical space."""

    code: Literal["INDEX_NOT_PREPARED"] = "INDEX_NOT_PREPARED"

    def __init__(self) -> None:
        super().__init__(self.code)


def _preparation_root(
    session: Session, caller: EmbeddingRegistryCaller, owner: CatalogPrivateChatQueryOwnerAdmission
) -> object:
    root = require_private_chat_query_source_root(session)
    if (
        type(caller) is not EmbeddingRegistryCaller
        or session.get_bind() is not owner.catalog.engine
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    validate_embedding_registry_actor(caller)
    return root


def _original_origin(
    origin: ChatPrivateQueryOrigin, caller: EmbeddingRegistryCaller, basis: PrivateChatQueryBasis
) -> ChatPrivateQueryOrigin:
    try:
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        if origin.actor_id != caller.operator_id or origin.basis != basis:
            raise ValueError()
        return origin
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_CONTEXT_INVALID") from None


def _original_request(
    session: Session,
    caller: EmbeddingRegistryCaller,
    owner: CatalogPrivateChatQueryOwnerAdmission,
    origin: ChatPrivateQueryOrigin,
    root: object,
) -> SelectedPrivateChatQueryWorkflow | None:
    owner.sources.identity.fence_current_operator(session, caller.operator_id)
    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    existing = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.idempotency_key == private_chat_query_origin_key(origin))
        .execution_options(populate_existing=True)
    )
    if existing is None:
        return None
    request = parse_private_chat_query_workflow_request(existing.initial_request)
    context = validate_private_chat_query_workflow_submission(session, existing, request)
    if (
        existing.created_actor_type != "human"
        or existing.created_actor_id != caller.operator_id
        or context.origin != origin
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_REPLAY_MISMATCH")
    return SelectedPrivateChatQueryWorkflow(existing.workflow_id, existing.state, request, context)


def read_private_chat_query_selection_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    origin: ChatPrivateQueryOrigin,
    preparation: PrivateChatContextPreparation,
    owner: CatalogPrivateChatQueryOwnerAdmission,
) -> SelectedPrivateChatQueryWorkflow | None:
    """Observe the original only; no head selection, submission, renewal or drive."""
    root = _preparation_root(session, caller, owner)
    validate_private_chat_context_preparation(preparation, owner.configuration.registry)
    origin = _original_origin(origin, caller, preparation.query_basis)
    original = _original_request(session, caller, owner, origin, root)
    try:
        current = ChatPrivateQueryOrigin.model_validate(
            raw_similarity_contract_value(owner.sources.chat.authorize(origin))
        )
    except ChatError as error:
        raise SimilarityContextReadError(
            "SOURCE_ACCESS_DENIED"
            if error.code == "GENERAL_CHAT_FORBIDDEN"
            else "AUTHORITY_UNAVAILABLE"
        ) from None
    if current != origin:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_REPLAY_MISMATCH")
    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    owner.sources.identity.fence_current_operator(session, caller.operator_id)
    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    if original is not None:
        validate_private_chat_context_preparation(
            preparation, owner.configuration.registry, original.request.context_request
        )
    return original


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
    root = _preparation_root(session, caller, owner)
    try:
        context = PrivateChatSimilarityRequest.model_validate(
            raw_similarity_contract_value(context)
        )
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_CONTEXT_INVALID") from None
    origin = _original_origin(origin, caller, context.query_basis)
    original = _original_request(session, caller, owner, origin, root)
    return _start_with_pinned_context(
        session,
        caller=caller,
        origin=origin,
        context=context,
        original=original,
        root=root,
        owner=owner,
        executor=executor,
    )


def prepare_and_start_private_chat_query_selection_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    origin: ChatPrivateQueryOrigin,
    preparation: PrivateChatContextPreparation,
    owner: CatalogPrivateChatQueryOwnerAdmission,
    executor: PrivateChatQueryNativeExecutor,
) -> PrivateChatQueryWorkflowSubmitted:
    """Initial official context capture only; exact replay never selects a newer head."""
    root = _preparation_root(session, caller, owner)
    validate_private_chat_context_preparation(preparation, owner.configuration.registry)
    origin = _original_origin(origin, caller, preparation.query_basis)
    original = _original_request(session, caller, owner, origin, root)
    context = (
        owner.catalog.prepare_private_chat_context_in_session(session, caller, preparation)
        if original is None
        else original.request.context_request
    )
    validate_private_chat_context_preparation(preparation, owner.configuration.registry, context)
    if require_private_chat_query_source_root(session) is not root:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARATION_ROOT_INVALID")
    if original is None and context.views[0].index is None:
        raise PrivateChatQueryPreparationUnavailable()
    return _start_with_pinned_context(
        session,
        caller=caller,
        origin=origin,
        context=context,
        original=original,
        root=root,
        owner=owner,
        executor=executor,
    )


def _start_with_pinned_context(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    origin: ChatPrivateQueryOrigin,
    context: PrivateChatSimilarityRequest,
    original: SelectedPrivateChatQueryWorkflow | None,
    root: object,
    owner: CatalogPrivateChatQueryOwnerAdmission,
    executor: PrivateChatQueryNativeExecutor,
) -> PrivateChatQueryWorkflowSubmitted:
    if original is not None:
        request, original_context = original.request, original.context
        if request.context_request != context:
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
