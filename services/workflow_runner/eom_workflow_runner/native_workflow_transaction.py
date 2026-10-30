"""Short current-owner/command-fenced roots shared by the fixed INDEX/QUERY use cases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from eom_orchestrator.database import transaction
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequestV3,
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import CommandLeaseIdentity, require_command_lease
from eom_workflow_runner.state_machine import CommandState

type NativeWorkflowRequest = (
    SupportedLocalEmbeddingRequest
    | SupportedReferenceQueryWorkflowRequest
    | PrivateChatQueryWorkflowRequest
)


class NativeWorkflowMutationOwner[Request: NativeWorkflowRequest](Protocol):
    """Mechanical shared port only; each concrete owner supplies current authority."""

    def fence_mutation(
        self, session: Session, request: Request, lease: CommandLeaseIdentity
    ) -> None: ...


@contextmanager
def native_fenced_runner_transaction[Request: NativeWorkflowRequest](
    factory: sessionmaker[Session],
    *,
    owner: NativeWorkflowMutationOwner[Request],
    workflow_id: str,
    request: Request,
    lease: CommandLeaseIdentity,
) -> Iterator[Session]:
    """Workflow→command locks, fresh authority, late expiry; never inference scope."""
    with transaction(factory) as session:
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if workflow is None:
            raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "native workflow disappeared")
        command = require_command_lease(session, lease, for_update=True)
        initial_command_state = command.state
        if isinstance(request, PrivateChatQueryWorkflowRequest):
            try:
                original: NativeWorkflowRequest = PrivateChatQueryWorkflowRequest.model_validate(
                    workflow.initial_request
                )
            except (ValueError, TypeError, SchemaError):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "private native mutation original request is invalid",
                ) from None
            protocol = "private-chat-query/1.0"
        elif isinstance(request, SupportedReferenceQueryWorkflowRequest):
            original = parse_supported_reference_query_workflow_request(workflow.initial_request)
            protocol = (
                "reference-query/2.0"
                if isinstance(request, ReferenceQueryWorkflowRequestV3)
                else "reference-query/1.0"
            )
        else:
            original = parse_supported_local_embedding_request(workflow.initial_request)
            protocol = "local-embedding/1.0"
        if (
            command.workflow_id != workflow_id
            or workflow.definition_key != request.workflow_definition_key
            or workflow.definition_version != request.workflow_definition_version
            or workflow.definition_hash != request.workflow_definition_sha256
            or workflow.role_schema_version != protocol
            or workflow.protocol_version != "1.0.1"
            or original != request
            or workflow.request_payload != workflow.initial_request
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "native mutation request or command differs",
            )
        owner.fence_mutation(session, request, lease)
        yield session
        session.flush()
        final_command_state = command.state
        owner.fence_mutation(session, request, lease)
        # Current authority resolution consumes time. Wall-clock expiry is LAST.
        if final_command_state in {CommandState.SUCCEEDED.value, CommandState.FAILED.value}:
            current = session.scalar(
                select(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.command_id == lease.command_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                initial_command_state != CommandState.PROCESSING.value
                or current is None
                or current.state != final_command_state
                or current.lease_owner != lease.runner_id
                or current.lease_token != lease.lease_token
                or current.lease_generation != lease.lease_generation
                or current.lease_expires_at is None
                or current.lease_expires_at <= datetime.now(UTC)
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "native terminal command lost its acquired lease",
                )
        else:
            require_command_lease(session, lease, for_update=True)
