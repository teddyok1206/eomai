"""Current operator/source/control preparation; no QUERY launch or implicit admission."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
    reference_query_result_schema,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
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
from eom_workflow_runner.native_step_completion import (
    native_application_step,
)
from eom_workflow_runner.reference_query_admission import ResolvedReferenceQueryAdmission
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQueryOwnerConfiguration as ReferenceQueryOwnerConfiguration,
)
from eom_workflow_runner.reference_query_source_read import (
    ResolvedCompletedReferenceQuerySources as ResolvedCompletedReferenceQuerySources,
)
from eom_workflow_runner.reference_query_source_read import (
    ResolvedReferenceQuerySources as ResolvedReferenceQuerySources,
)
from eom_workflow_runner.reference_query_source_read import (
    SupportedResolvedReferenceQuerySources,
    resolve_completed_reference_query_sources,
    resolve_reference_query_sources,
)
from eom_workflow_runner.reference_query_source_read import (
    build_reference_query_native_input as build_reference_query_native_input,
)
from eom_workflow_runner.reference_query_source_read import (
    validate_current_reference_query_input as validate_current_reference_query_input,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    require_command_lease,
    validate_reference_query_workflow_submission,
)
from eom_workflow_runner.state_machine import CommandState


class CatalogReferenceQueryOwnerAdmission:
    """Actual Identity and official Catalog scope, before any QUERY side effect.

    Claim/mutation independently resolve the actual source/session in their own
    root. Installed physical QUERY-purpose admission remains the executor's duty.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: ReferenceQueryOwnerConfiguration,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        configuration.__post_init__()
        self.configuration = configuration
        self.settings = settings or CatalogSettings.from_environment()
        self.identity = CapturedOperatorAuthorizationFence(
            capture, session_fence, PermissionKey.WORKFLOW_START
        )
        self.catalog = CatalogEmbeddingRegistryVerifier(
            engine, configuration.registry, identity_fence=self.identity, settings=self.settings
        )
        self._command_fence = NativeCommandMutationFence()

    def resolve_submission(
        self, session: Session, request: SupportedReferenceQueryWorkflowRequest
    ) -> ResolvedReferenceQueryAdmission:
        sources = self.resolve_sources(session, request)
        return ResolvedReferenceQueryAdmission(sources.request, sources.policy, sources.bundle)

    @staticmethod
    def _require_rows(
        session: Session,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: SupportedReferenceQueryWorkflowRequest,
    ) -> None:
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        if (
            object_session(command) is not session
            or object_session(workflow) is not session
            or command.workflow_id != workflow.workflow_id
            or definition is None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "QUERY current owner requires attached exact Workflow/command rows",
            )
        validate_reference_query_workflow_submission(
            session,
            workflow,
            definition=definition,
            request=request,
            actor_type="human",
            actor_id=request.operator_audit.operator_id,
        )

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: SupportedReferenceQueryWorkflowRequest,
    ) -> ResolvedReferenceQueryAdmission:
        request = parse_supported_reference_query_workflow_request(request)
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        self._require_rows(session, command, workflow, request)
        fresh = (
            command.state == CommandState.PENDING.value
            and command.attempts == 0
            and command.lease_generation == 0
            and command.lease_owner is None
            and command.lease_token is None
            and command.lease_expires_at is None
        )
        expired = (
            command.state in {CommandState.LEASED.value, CommandState.PROCESSING.value}
            and command.attempts >= 1
            and command.lease_generation >= 1
            and command.lease_expires_at is not None
            and command.lease_expires_at <= datetime.now(UTC)
        )
        if not fresh and not expired:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY acquisition requires supported original-execution reconciliation",
            )
        scope = self.resolve_submission(session, request)
        step = native_application_step(session, workflow.workflow_id, "encode_reference_query")
        if fresh and step is None:
            return scope
        if step is None or (
            step.workflow_id != workflow.workflow_id
            or step.step_key != "encode_reference_query"
            or step.attempt != 1
            or step.state not in {"RUNNING", "SUCCEEDED"}
            or step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != reference_query_result_schema(request)
            or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
        ):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY original-execution reconciliation lacks its exact prior attempt",
            )
        launch = read_native_reference_query_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        if launch is None:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY recovery cannot replace a vanished original execution",
            )
        history = NativeReferenceQueryCoordinator(request, launch).read(session)
        if not history.records or history.state in {"FAILED", "CANCELLED"}:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY recovery requires allocated nonfailed original history",
            )
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        return scope

    def fence_mutation(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> None:
        self.resolve_mutation_sources(session, request, lease)

    def resolve_mutation_sources(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> SupportedResolvedReferenceQuerySources:
        request = parse_supported_reference_query_workflow_request(request)
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        command = self._command_fence.acquire(session, request.request_sha256, lease)
        workflow = session.get(WorkflowInstanceRecord, command.workflow_id)
        if workflow is None:
            raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "QUERY Workflow disappeared")
        self._require_rows(session, command, workflow, request)
        sources = self.resolve_sources(session, request)
        require_unexpired_native_command(command, lease)
        return sources

    def resolve_execution_sources(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        *,
        workflow_id: str,
        step_run_id: str,
    ) -> SupportedResolvedReferenceQuerySources:
        """Current attached Workflow/command/step closure for computation and completion."""
        sources = self.resolve_mutation_sources(session, request, lease)
        command = require_command_lease(session, lease)
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        step = session.get(WorkflowStepRunRecord, step_run_id)
        if (
            workflow is None
            or step is None
            or workflow.state not in {"RUNNING", "COMPLETED"}
            or command.workflow_id != workflow_id
            or step.workflow_id != workflow_id
            or step.step_key != "encode_reference_query"
            or step.attempt != 1
            or step.state not in {"RUNNING", "SUCCEEDED"}
            or step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != reference_query_result_schema(request)
            or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
        ):
            raise ValueError("REFERENCE_QUERY_EXECUTOR_CURRENT_STEP_INVALID")
        return sources

    def resolve_sources(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> SupportedResolvedReferenceQuerySources:
        return resolve_reference_query_sources(
            self, session, request, artifact_reader=artifact_reader
        )

    def resolve_completed_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        workflow_id: str,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedCompletedReferenceQuerySources:
        return resolve_completed_reference_query_sources(
            self, session, caller, request, workflow_id=workflow_id, artifact_reader=artifact_reader
        )
