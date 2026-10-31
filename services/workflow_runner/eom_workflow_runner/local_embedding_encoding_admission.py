"""Current actor/command/source admission for the same existing encoding owner."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationError,
)
from eom_orchestrator.embedding_encoding_reservations import (
    EncodingReadTarget,
    ObservedEncodingReads,
    ResolvedEncodingCompletion,
    ResolvedEncodingLaunch,
    ResolvedEncodingScope,
)
from eom_orchestrator.native_embedding_launch_identity import require_native_embedding_launch
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    SupportedEmbeddingCompletedEvent,
    SupportedEmbeddingIntent,
    validate_supported_embedding_association,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    parse_local_embedding_launch_intent_for_request,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.local_embedding_source_plan_dispatch import SupportedLocalEmbeddingSourcePlan
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingExecution,
    DocumentExecutionState,
)
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandLeaseIdentity, require_command_lease


@dataclass(frozen=True, slots=True)
class CurrentEncodingExecution:
    """Trusted composition values; intent is audit, not current lease/authentication."""

    request: SupportedLocalEmbeddingRequest
    intent: SupportedEmbeddingIntent
    command_lease: CommandLeaseIdentity

    def __post_init__(self) -> None:
        request = parse_supported_local_embedding_request(self.request)
        intent = parse_local_embedding_launch_intent_for_request(self.intent, request)
        if (
            intent.workflow_request_sha256 != request.request_sha256
            or intent.source_plan != request.source_plan
            or intent.source_plan_sha256 != request.source_plan_sha256
            or intent.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
        ):
            raise ValueError("EMBEDDING_ENCODING_CURRENT_CONTEXT_INVALID")
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "intent", intent)


def _scope(value: ResolvedLocalEmbeddingSources) -> ResolvedEncodingScope:
    return ResolvedEncodingScope(
        value.admission.request, value.admission.plan, value.admission.policy
    )


def _keys(
    plan: SupportedLocalEmbeddingSourcePlan,
) -> dict[str, EmbeddingEncodingJobRequest]:
    # Derive the exact small request identities, not source data or permission.
    from eom_identifiers import content_sha256

    values = {}
    for demand in plan.demands:
        key = demand.encoding.encoding_sha256
        if key in values:
            continue
        body = {
            "schema_version": "embedding-encoding-job/1.0",
            "record_type": "REQUEST",
            "purpose": "LOCAL_EMBEDDING",
            "space": plan.space.model_dump(mode="json"),
            "encoding": demand.encoding.model_dump(mode="json"),
        }
        values[key] = EmbeddingEncodingJobRequest.model_validate(
            body | {"request_sha256": content_sha256(body)}
        )
    return values


class CatalogEncodingOwnerAdmission:
    """Current source/Identity owner is mandatory; no persisted actor grants authority."""

    def __init__(
        self,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        execution: CurrentEncodingExecution,
        execution_backend: DocumentEmbeddingExecution,
    ) -> None:
        self.owner, self.execution, self.execution_backend = owner, execution, execution_backend

    def _current_mutation(
        self, session: Session, intent: SupportedEmbeddingIntent
    ) -> ResolvedLocalEmbeddingSources:
        context = self.execution
        # Fence actual caller before even revealing Workflow/launch existence.
        self.owner.fence_current_actor(session, context.request)
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == context.intent.workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            workflow is None
            or workflow.state != "RUNNING"
            or workflow.current_step_key != "encode_batch"
        ):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_CURRENT_STEP_INVALID")
        sources = self.owner.resolve_mutation_sources(
            session, context.request, context.command_lease
        )
        step = session.scalar(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.step_run_id == context.intent.step_run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            intent != context.intent
            or step is None
            or step.workflow_id != workflow.workflow_id
            or step.step_key != "encode_batch"
            or step.attempt != 1
            or step.state != "RUNNING"
            or step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != "incremental-embedding-result@1.0"
            or step.input_pointer_manifest
            != {
                "source_plan": context.request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": context.request.source_plan_sha256,
            }
        ):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_CURRENT_STEP_INVALID")
        observation = require_native_embedding_launch(session, intent, context.request)
        if observation.state in {"FAILED", "CANCELLED", "SUCCEEDED"}:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN")
        return sources

    def resolve_reservation(
        self,
        session: Session,
        requests: tuple[EmbeddingEncodingJobRequest, ...],
        intent: SupportedEmbeddingIntent,
    ) -> ResolvedEncodingScope:
        current = self._current_mutation(session, intent)
        allowed = _keys(current.admission.plan)
        if any(allowed.get(row.encoding.encoding_sha256) != row for row in requests):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_SCOPE_MISMATCH")
        return _scope(current)

    def resolve_launch(
        self, session: Session, association: SupportedEmbeddingAssociation
    ) -> ResolvedEncodingLaunch:
        current = self._current_mutation(session, association.intent)
        request = CatalogLocalEmbeddingEncodingArtifacts(
            session, self.owner.settings
        ).resolve_input(association)
        scope = _scope(current)
        validate_supported_embedding_association(
            association,
            scope.plan,
            request,
            scope.workflow_request.resource_profile,
            scope.workflow_request.request_sha256,
        )
        return ResolvedEncodingLaunch(scope, request)

    def resolve_completion(
        self,
        session: Session,
        association: SupportedEmbeddingAssociation,
        events: tuple[SupportedEmbeddingCompletedEvent, ...],
    ) -> ResolvedEncodingCompletion:
        current = self._current_mutation(session, association.intent)
        resolved = CatalogLocalEmbeddingEncodingArtifacts(
            session, self.owner.settings
        ).resolve_result(association, events)
        validate_supported_embedding_association(
            association,
            current.admission.plan,
            resolved.request,
            current.admission.request.resource_profile,
            current.admission.request.request_sha256,
        )
        return ResolvedEncodingCompletion(resolved.request, resolved.result)

    def fence_mutation(self, session: Session, intent: SupportedEmbeddingIntent) -> None:
        self._current_mutation(session, intent)

    def fence_read_scope(
        self, session: Session, references: tuple[EmbeddingEncodingJobReference, ...]
    ) -> None:
        current = self.owner.resolve_sources(session, self.execution.request)
        allowed = {row.request_sha256 for row in _keys(current.admission.plan).values()}
        if any(ref.request_sha256 not in allowed for ref in references):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_READ_SCOPE_INVALID")

    def reauthorize_read(
        self, session: Session, targets: tuple[EncodingReadTarget, ...]
    ) -> ObservedEncodingReads:
        current = self.owner.resolve_sources(session, self.execution.request)
        allowed = _keys(current.admission.plan)
        if any(
            allowed.get(t.owned_job.request.encoding.encoding_sha256) != t.owned_job.request
            for t in targets
        ):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_READ_SCOPE_INVALID")
        completed = tuple((t.owned_job, t.completion) for t in targets if t.completion is not None)
        if completed:
            CatalogLocalEmbeddingEncodingArtifacts(session, self.owner.settings).verify_shared_rows(
                completed
            )
        owned_pending = tuple(
            t for t in targets if t.completion is None and t.owner_intent == self.execution.intent
        )
        uncertain = set()
        if owned_pending:
            try:
                require_command_lease(session, self.execution.command_lease)
                observation = require_native_embedding_launch(
                    session, self.execution.intent, self.execution.request
                )
                if observation.state in {"FAILED", "CANCELLED", "SUCCEEDED"}:
                    raise ValueError("terminal native coordinator")
                state = self.execution_backend.observe(self.execution.intent)
                if (
                    state is not DocumentExecutionState.NOT_STARTED
                    and state is not DocumentExecutionState.SUCCEEDED
                ):
                    uncertain.add(self.execution.intent.native_launch_job_id)
            except WorkflowError:
                uncertain.add(self.execution.intent.native_launch_job_id)
        # Late current authorization also catches expiry consumed by Artifact/OS reads.
        self.owner.fence_current_actor(session, self.execution.request)
        return ObservedEncodingReads(self.execution.intent, frozenset(uncertain))
