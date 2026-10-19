"""Atomic bounded native submission; no claim, runtime launch or authority default."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_workflow.local_embedding_index_refresh import LocalEmbeddingIndexRefreshRequest
from eom_workflow.local_embedding_request_v2 import SupportedLocalEmbeddingRequest
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    resolve_local_embedding_submission_controls,
)
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.native_start_command import (
    LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.repository import create_workflow_instance


@dataclass(frozen=True, slots=True)
class LocalEmbeddingCoverageOnly:
    """Reuse the verified immutable plan, without inventing a zero-output Artifact."""

    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2

    def __post_init__(self) -> None:
        plan = (
            parse_local_embedding_source_plan_v2(self.plan)
            if isinstance(self.plan, LocalEmbeddingSourcePlanV2)
            else parse_local_embedding_source_plan(raw_similarity_contract_value(self.plan))
        )
        if plan.demands:
            raise ValueError("LOCAL_EMBEDDING_COVERAGE_ONLY_INVALID")
        object.__setattr__(self, "plan", plan)


@dataclass(frozen=True, slots=True)
class LocalEmbeddingWorkflowSubmitted:
    """In-session records and creation observations, not a wire receipt or grant."""

    workflow: WorkflowInstanceRecord
    command: WorkflowCommandRecord
    workflow_created: bool
    command_created: bool


type LocalEmbeddingSubmissionResult = LocalEmbeddingCoverageOnly | LocalEmbeddingWorkflowSubmitted


def start_local_embedding_in_session(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: SupportedLocalEmbeddingRequest,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    owner: LocalEmbeddingOwnerAdmission,
    executor: LocalEmbeddingNativeExecutor,
) -> LocalEmbeddingSubmissionResult:
    """Resolve current owner before savepoints; caller owns the root commit/rollback.

    No readiness/inference runs here. The real owner retains root authorization
    fences and rechecks current source/session and wall-clock expiry late. The
    caller must promptly commit/rollback this same root transaction; neither the
    returned plan nor an old request/actor can authorize a later operation.
    """
    if session.in_nested_transaction():
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "local embedding submission must enter in the root transaction",
        )
    scope = resolve_local_embedding_submission_controls(
        session,
        definition=definition,
        request=request,
        actor_type=actor_type,
        actor_id=actor_id,
        owner=owner,
        executor=executor,
    )
    if not scope.plan.demands:
        if isinstance(scope.request, LocalEmbeddingIndexRefreshRequest):
            raise ValueError("LOCAL_EMBEDDING_REFRESH_AVAILABLE_WITNESS_REQUIRED")
        late = resolve_local_embedding_submission_controls(
            session,
            definition=definition,
            request=scope.request,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=owner,
            executor=executor,
        )
        if late != scope:
            raise ValueError("LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID")
        return LocalEmbeddingCoverageOnly(scope.plan)
    with session.begin_nested():
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=scope.request,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_id=actor_id,
            local_embedding_owner=owner,
            local_embedding_executor=executor,
        )
        command, command_created = resolve_native_start_command(
            session,
            workflow=workflow,
            workflow_created=created,
            actor_type=actor_type,
            actor_id=actor_id,
            source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
        )
        late = resolve_local_embedding_submission_controls(
            session,
            definition=definition,
            request=scope.request,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=owner,
            executor=executor,
        )
        if late != scope:
            raise ValueError("LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID")
        return LocalEmbeddingWorkflowSubmitted(workflow, command, created, command_created)
