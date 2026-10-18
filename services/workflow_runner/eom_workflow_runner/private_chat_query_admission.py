"""Required private-purpose owner interface; no retained source or native capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition_data
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    parse_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
    private_chat_query_submission_key,
    validate_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import (
    PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL,
    PrivateChatQueryWorkflowDefinition,
    validate_private_chat_query_definition,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatQuerySources,
    require_private_chat_query_source_root,
)

if TYPE_CHECKING:
    from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
    from eom_workflow_runner.repository import CommandLeaseIdentity


class PrivateChatQueryOwnerAdmission(Protocol):
    def resolve_submission(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        context: PrivateChatQuerySubmissionContext,
    ) -> ResolvedPrivateChatQuerySources: ...

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: PrivateChatQueryWorkflowRequest,
    ) -> ResolvedPrivateChatQuerySources: ...

    def fence_mutation(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> None: ...


def resolve_private_chat_query_submission_controls(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: PrivateChatQueryWorkflowRequest,
    context: PrivateChatQuerySubmissionContext,
    actor_type: str,
    actor_id: str,
    owner: PrivateChatQueryOwnerAdmission | None,
    executor: PrivateChatQueryNativeExecutor | None,
) -> ResolvedPrivateChatQuerySources:
    """Current clean-root authority, not retained submission/physical permission."""
    request = parse_private_chat_query_workflow_request(request)
    context = validate_private_chat_query_submission_context(request, context)
    if (
        owner is None
        or executor is None
        or not workflow_definition_is_admitted(
            request.workflow_definition_key, request.workflow_definition_version
        )
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "private QUERY requires an admitted definition and actual paired owner/executor",
        )
    require_private_chat_query_source_root(session)
    if actor_type != "human" or actor_id != context.origin.actor_id:
        raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_ACTOR_INVALID")
    current = session.get(
        WorkflowDefinitionRecord, definition.definition_id, populate_existing=True
    )
    if current is None or current.active is not True:
        raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_DEFINITION_INVALID")
    compiled = compile_definition_data(current.canonical_definition, current.source_path, set())
    if not isinstance(compiled.definition, PrivateChatQueryWorkflowDefinition) or (
        current.definition_key != compiled.definition.definition_key
        or current.definition_version != compiled.definition.definition_version
        or current.schema_version != compiled.definition.schema_version
        or current.definition_hash != compiled.sha256
        or definition.definition_hash != current.definition_hash
        or definition.definition_key != current.definition_key
        or definition.definition_version != current.definition_version
        or definition.schema_version != current.schema_version
        or definition.canonical_definition != compiled.as_dict()
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_DEFINITION_INVALID")
    validate_private_chat_query_definition(compiled.definition, request)
    scope = owner.resolve_submission(session, request, context)
    if type(scope) is not ResolvedPrivateChatQuerySources:
        raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID")
    scope.__post_init__()
    if scope.request != request or scope.projection.origin != context.origin:
        raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID")
    return scope


def validate_private_chat_query_workflow_submission(
    session: Session,
    workflow: WorkflowInstanceRecord,
    request: PrivateChatQueryWorkflowRequest,
) -> PrivateChatQuerySubmissionContext:
    """Attached immutable row closure only; live source/claim permission is separate."""
    require_private_chat_query_source_root(session)
    try:
        request = PrivateChatQueryWorkflowRequest.model_validate(
            raw_similarity_contract_value(request)
        )
        if object_session(workflow) is not session:
            raise ValueError()
        definition = session.get(
            WorkflowDefinitionRecord, workflow.definition_id, populate_existing=True
        )
        if definition is None or definition.active is not True:
            raise ValueError()
        fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition.canonical_definition)
        validate_private_chat_query_definition(fixed, request)
        context = validate_private_chat_query_submission_context(
            request, parse_private_chat_query_submission_context(workflow.runtime_context)
        )
        expected_definition = (
            fixed.definition_key,
            fixed.definition_version,
            request.workflow_definition_sha256,
        )
        if (
            (definition.definition_key, definition.definition_version, definition.definition_hash)
            != expected_definition
            or (workflow.definition_key, workflow.definition_version, workflow.definition_hash)
            != expected_definition
            or definition.schema_version != fixed.schema_version
            or sha256_bytes(canonical_json_bytes(fixed)) != definition.definition_hash
            or workflow.role_schema_version != PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL
            or workflow.protocol_version != "1.0.1"
            or workflow.created_actor_type != "human"
            or workflow.created_actor_id != context.origin.actor_id
            or workflow.initial_request != request.model_dump(mode="json")
            or workflow.request_payload != workflow.initial_request
            or workflow.idempotency_key != private_chat_query_submission_key(context)
            or workflow.request_hash
            != private_chat_query_submission_fingerprint(
                request,
                context,
                definition_sha256=definition.definition_hash,
                actor_type=workflow.created_actor_type,
                actor_id=workflow.created_actor_id,
            )
        ):
            raise ValueError()
        return context
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_WORKFLOW_CONTEXT_INVALID") from None
