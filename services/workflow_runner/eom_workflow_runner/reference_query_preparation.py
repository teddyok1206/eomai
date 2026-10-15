"""Current operator/pinned reference → existing canonical QUERY Workflow/START."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context import (
    SimilarityContextRequest,
    parse_similarity_context_request,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_workflow.reference_query_execution import (
    parse_reference_query_workflow_request,
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


def prepare_and_start_reference_query_in_session(
    session: Session,
    *,
    caller: EmbeddingRegistryCaller,
    context: SimilarityContextRequest,
    idempotency_key: str,
    owner: CatalogReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
) -> ReferenceQueryWorkflowSubmitted:
    """Own request construction, not another queue or a substitute for current admission.

    A repeated key reuses its exact stored request/audit. Existing atomic admission
    still checks the current authority and original START in this caller-owned root.
    No model, index selection, implicit latest, commit or automatic retry occurs.
    """
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
    context = parse_similarity_context_request(context)
    owner.identity.fence_current_operator(session, caller.operator_id)
    existing = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.idempotency_key == idempotency_key)
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        request = parse_reference_query_workflow_request(existing.initial_request)
        if (
            existing.created_actor_type != "human"
            or existing.created_actor_id != caller.operator_id
            or request.operator_audit.operator_id != caller.operator_id
            or request.context_request != context
        ):
            raise ValueError("REFERENCE_QUERY_PREPARATION_REPLAY_MISMATCH")
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
        policy, bundle = read_pinned_reference_query_controls(
            PinnedArtifactReadContext(session, owner.settings), config
        )
        body = {
            "schema_version": "reference-query-workflow-request/1.0",
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
        request = parse_reference_query_workflow_request(
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
