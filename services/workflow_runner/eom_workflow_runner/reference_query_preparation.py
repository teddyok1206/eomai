"""Current operator/pinned reference → existing canonical QUERY Workflow/START."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityContextRequestV2,
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context_request,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    ReferenceQueryContextPreparation,
    SelectedEmbeddingSources,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.reference_query_context_preparation import (
    validate_reference_query_context_preparation,
)
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_request_references,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_source_read import read_pinned_reference_query_controls
from eom_workflow_runner.reference_query_submission import (
    ReferenceQueryWorkflowSubmitted,
    start_reference_query_in_session,
)


class ReferenceQueryPreparationUnavailable(ValueError):
    """Known absent auxiliary input, not permission to ignore corrupt/revoked pointers."""

    def __init__(self, code: Literal["ANCHOR_REPORT_MISSING", "INDEX_NOT_PREPARED"]) -> None:
        self.code = code
        super().__init__(code)


def _require_preparation_root(
    session: Session,
    owner: CatalogReferenceQueryOwnerAdmission,
    caller: EmbeddingRegistryCaller,
) -> None:
    root = session.get_transaction()
    if (
        not session.is_active
        or type(caller) is not EmbeddingRegistryCaller
        or root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.get_bind() is not owner.catalog.engine
    ):
        raise ValueError("REFERENCE_QUERY_PREPARATION_ROOT_INVALID")
    validate_embedding_registry_actor(caller)


def _current_query_request(
    session: Session,
    owner: CatalogReferenceQueryOwnerAdmission,
    caller: EmbeddingRegistryCaller,
    idempotency_key: str,
) -> SupportedReferenceQueryWorkflowRequest | None:
    owner.identity.fence_current_operator(session, caller.operator_id)
    existing = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.idempotency_key == idempotency_key)
        .execution_options(populate_existing=True)
    )
    if existing is None:
        return None
    request = parse_supported_reference_query_workflow_request(existing.initial_request)
    if (
        existing.created_actor_type != "human"
        or existing.created_actor_id != caller.operator_id
        or request.operator_audit.operator_id != caller.operator_id
    ):
        raise ValueError("REFERENCE_QUERY_PREPARATION_REPLAY_MISMATCH")
    return request


def prepare_and_start_reference_query_selection_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    preparation: ReferenceQueryContextPreparation,
    idempotency_key: str,
    owner: CatalogReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
) -> ReferenceQueryWorkflowSubmitted:
    """Selected reference → initial pins → canonical QUERY/START; replay never reselects.

    The actual native owner runs this use case, not the isolated API. There is no
    commit, encoder operation, new queue or substitute for real current authority.
    """
    _require_preparation_root(session, owner, caller)
    validate_reference_query_context_preparation(preparation, owner.configuration.registry)
    original = _current_query_request(session, owner, caller, idempotency_key)
    replay_preparation = preparation
    registry = owner.configuration.registry
    if original is not None:
        catalog = owner.catalog.for_pinned_similarity_request_in_session(
            session, caller, original.context_request
        )
        registry = catalog.configuration
        # Namespace is internal deployment selection, not an HTTP replay field.
        # Normalize only that proven selection; all original intent still matches.
        replay_preparation = replace(
            preparation,
            selection=SelectedEmbeddingSources(
                replace(preparation.selection.scope, namespace=registry.namespace),
                preparation.selection.source_revision_ids,
            ),
        )
    context = (
        owner.catalog.prepare_reference_query_context_in_session(session, caller, preparation)
        if original is None
        else original.context_request
    )
    validate_reference_query_context_preparation(replay_preparation, registry, context)
    if original is None:
        # Only an initial context captured by the actual Catalog source owner can
        # establish absence. A supplied/replayed context is not an absence grant.
        if context.anchor.profile is None:
            raise ReferenceQueryPreparationUnavailable("ANCHOR_REPORT_MISSING")
        if not any(row.index is not None for row in context.views):
            raise ReferenceQueryPreparationUnavailable("INDEX_NOT_PREPARED")
    return _start_with_pinned_context(
        session,
        caller=caller,
        context=context,
        original=original,
        idempotency_key=idempotency_key,
        owner=owner,
        executor=executor,
    )


def prepare_and_start_reference_query_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    context: SupportedSimilarityContextRequest,
    idempotency_key: str,
    owner: CatalogReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
) -> ReferenceQueryWorkflowSubmitted:
    """Own request construction from existing pins, without index selection or model use.

    Repeated keys retain the original audit/pins and reauthorize through existing
    atomic admission. Both preparation entrypoints share this single start path.
    """
    _require_preparation_root(session, owner, caller)
    context = parse_supported_similarity_context_request(context)
    original = _current_query_request(session, owner, caller, idempotency_key)
    return _start_with_pinned_context(
        session,
        caller=caller,
        context=context,
        original=original,
        idempotency_key=idempotency_key,
        owner=owner,
        executor=executor,
    )


def _start_with_pinned_context(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    context: SupportedSimilarityContextRequest,
    original: SupportedReferenceQueryWorkflowRequest | None,
    idempotency_key: str,
    owner: CatalogReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
) -> ReferenceQueryWorkflowSubmitted:
    if original is not None and original.context_request != context:
        raise ValueError("REFERENCE_QUERY_PREPARATION_REPLAY_MISMATCH")
    if original is not None:
        request = original
    else:
        config = owner.configuration
        owner.catalog.authorize_scope(
            session,
            caller,
            EmbeddingRegistryLookup(
                config.registry.corpus_id,
                config.registry.namespace,
                context.graph_snapshot,
                context.policy_revision_id,
                context.policy_sha256,
                context.maximum_sources,
            ),
        )
        reader = PinnedArtifactReadContext(session, owner.settings)
        selected = owner.catalog.for_pinned_similarity_request_in_session(
            session, caller, context, artifact_reader=reader
        )
        if selected.configuration.namespace != config.registry.namespace:
            raise ValueError("REFERENCE_QUERY_INITIAL_NAMESPACE_MISMATCH")
        policy, bundle = read_pinned_reference_query_controls(reader, config)
        body = {
            "schema_version": "reference-query-workflow-request/2.0"
            if isinstance(context, SimilarityContextRequestV2)
            else (
                "reference-query-workflow-request/1.0"
                if context.consumer_purpose == "PAST_EXAM_VARIATION"
                else "reference-query-workflow-request/1.1"
            ),
            "request_name": "REFERENCE_QUERY_WORKFLOW_REQUEST",
            "purpose": "REFERENCE_QUERY",
            "workflow_definition_key": "local-embedding-reference-query",
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
        request = parse_supported_reference_query_workflow_request(
            body | {"request_sha256": content_sha256(body)}
        )
        validate_reference_query_request_references(request, policy, bundle)
    definition = session.scalar(
        select(WorkflowDefinitionRecord)
        .where(
            WorkflowDefinitionRecord.definition_key == request.workflow_definition_key,
            WorkflowDefinitionRecord.definition_version == request.workflow_definition_version,
        )
        .execution_options(populate_existing=True)
    )
    if definition is None or definition.definition_hash != request.workflow_definition_sha256:
        raise ValueError("REFERENCE_QUERY_PREPARATION_DEFINITION_UNAVAILABLE")
    return start_reference_query_in_session(
        session,
        definition=definition,
        request=request,
        idempotency_key=idempotency_key,
        actor_type="human",
        actor_id=caller.operator_id,
        owner=owner,
        executor=executor,
    )
