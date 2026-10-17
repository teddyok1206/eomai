"""Original private turn, current source and command fences; no implicit admission."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import NativePrivateQueryAllocation
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    parse_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
    private_chat_query_submission_key,
    validate_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import (
    PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL,
    PRIVATE_CHAT_QUERY_RESULT_SCHEMA,
    PrivateChatQueryWorkflowDefinition,
    validate_private_chat_query_definition,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_command_fence import (
    NativeCommandMutationFence,
    require_unexpired_native_command,
)
from eom_workflow_runner.native_step_completion import native_application_step
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    ResolvedPrivateChatQuerySources,
    require_private_chat_query_source_root,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    CommandType,
    command_business_fingerprint,
    require_command_lease,
)

PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE = "private_chat_query_submission"


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


def _require_command(workflow: WorkflowInstanceRecord, command: WorkflowCommandRecord) -> None:
    key = f"start:{workflow.workflow_id}"
    if (
        command.workflow_id != workflow.workflow_id
        or command.command_type != CommandType.START_WORKFLOW.value
        or command.payload != {}
        or command.actor_type != workflow.created_actor_type
        or command.actor_id != workflow.created_actor_id
        or command.source != PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE
        or command.idempotency_key != key
        or command.request_hash
        != command_business_fingerprint(
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type=workflow.created_actor_type,
            actor_id=workflow.created_actor_id,
            source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
        )
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")


def validate_private_chat_query_execution_step(
    step: WorkflowStepRunRecord,
    workflow: WorkflowInstanceRecord,
    request: PrivateChatQueryWorkflowRequest,
) -> None:
    if (
        step.workflow_id != workflow.workflow_id
        or workflow.state not in {"RUNNING", "COMPLETED"}
        or workflow.current_step_key not in {"encode_private_chat_query", "complete"}
        or (workflow.current_step_key == "complete" and step.state != "SUCCEEDED")
        or (workflow.state == "COMPLETED" and workflow.current_step_key != "complete")
        or step.step_key != "encode_private_chat_query"
        or step.attempt != 1
        or step.state not in {"RUNNING", "SUCCEEDED"}
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != PRIVATE_CHAT_QUERY_RESULT_SCHEMA
        or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CURRENT_STEP_INVALID")


class CatalogPrivateChatQueryOwnerAdmission:
    """No retained grant: source owner and command lease are checked in every root."""

    def __init__(self, sources: CatalogPrivateChatQuerySourceOwner) -> None:
        sources.configuration.__post_init__()
        self.sources = sources
        self.configuration, self.catalog, self.settings = (
            sources.configuration,
            sources.catalog,
            sources.settings,
        )
        self._command_fence = NativeCommandMutationFence()

    def resolve_submission(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        context: PrivateChatQuerySubmissionContext,
    ) -> ResolvedPrivateChatQuerySources:
        context = validate_private_chat_query_submission_context(request, context)
        return self.sources.resolve_sources(session, request, context.origin)

    def _rows(
        self,
        session: Session,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: PrivateChatQueryWorkflowRequest,
    ) -> PrivateChatQuerySubmissionContext:
        if object_session(command) is not session:
            raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")
        context = validate_private_chat_query_workflow_submission(session, workflow, request)
        _require_command(workflow, command)
        return context

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: PrivateChatQueryWorkflowRequest,
    ) -> ResolvedPrivateChatQuerySources:
        context = self._rows(session, command, workflow, request)
        fresh = (
            command.state == "PENDING"
            and command.attempts == 0
            and command.lease_generation == 0
            and command.lease_owner is None
            and command.lease_token is None
            and command.lease_expires_at is None
        )
        expired = (
            command.state in {"LEASED", "PROCESSING"}
            and command.attempts >= 1
            and command.lease_generation >= 1
            and command.lease_expires_at is not None
            and command.lease_expires_at <= datetime.now(UTC)
        )
        if (not fresh and not expired) or workflow.state not in {
            "REQUESTED",
            "RUNNING",
            "COMPLETED",
        }:
            raise ValueError("PRIVATE_CHAT_QUERY_CLAIM_UNAVAILABLE")
        sources = self.resolve_submission(session, request, context)
        step = native_application_step(session, workflow.workflow_id, "encode_private_chat_query")
        if fresh and step is None:
            if (
                workflow.state != "REQUESTED"
                or workflow.current_step_key != "encode_private_chat_query"
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING")
            return sources
        if step is None:
            raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING")
        validate_private_chat_query_execution_step(step, workflow, request)
        launch = read_native_query_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        if not isinstance(launch, PrivateChatQueryLaunchAssociation):
            raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING")
        history = NativePrivateChatQueryCoordinator(request, launch).read(session)
        if not history.records or history.state in {"FAILED", "CANCELLED"}:
            raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_UNAVAILABLE")
        allocation = history.records[0].payload
        if (
            not isinstance(allocation, NativePrivateQueryAllocation)
            or allocation.origin != context.origin
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_ORIGIN_MISMATCH")
        return sources

    def resolve_mutation_sources(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> ResolvedPrivateChatQuerySources:
        require_private_chat_query_source_root(session)
        command = self._command_fence.acquire(session, request.request_sha256, lease)
        workflow = session.get(WorkflowInstanceRecord, command.workflow_id)
        if workflow is None:
            raise ValueError("PRIVATE_CHAT_QUERY_WORKFLOW_UNAVAILABLE")
        context = self._rows(session, command, workflow, request)
        sources = self.resolve_submission(session, request, context)
        require_unexpired_native_command(command, lease)
        return sources

    def fence_mutation(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> None:
        self.resolve_mutation_sources(session, request, lease)

    def resolve_execution_sources(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        *,
        workflow_id: str,
        step_run_id: str,
    ) -> ResolvedPrivateChatQuerySources:
        sources = self.resolve_mutation_sources(session, request, lease)
        command = require_command_lease(session, lease)
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        step = session.get(WorkflowStepRunRecord, step_run_id)
        if (
            workflow is None
            or step is None
            or object_session(step) is not session
            or workflow.state not in {"RUNNING", "COMPLETED"}
            or command.workflow_id != workflow_id
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CURRENT_STEP_INVALID")
        validate_private_chat_query_execution_step(step, workflow, request)
        return sources
