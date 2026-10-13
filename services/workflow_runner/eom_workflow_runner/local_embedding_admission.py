"""Fixed native purpose guards and a required current-owner boundary, never a grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition_data
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
from eom_workflow.local_embedding_request import (
    LocalEmbeddingWorkflowRequestV11,
    parse_local_embedding_workflow_request_v11,
    require_local_embedding_operator_seed,
    validate_local_embedding_request_references,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LOCAL_EMBEDDING_WORKFLOW_KEY,
    LOCAL_EMBEDDING_WORKFLOW_VERSION,
    LocalEmbeddingWorkflowDefinition,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)

if TYPE_CHECKING:
    from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
    from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class ResolvedLocalEmbeddingAdmission:
    """Validated immutable controls only; no caller/session/source authority is carried."""

    request: LocalEmbeddingWorkflowRequestV11
    plan: LocalEmbeddingSourcePlan
    policy: LocalEmbeddingExecutionPolicy

    def __post_init__(self) -> None:
        request = LocalEmbeddingWorkflowRequestV11.model_validate(self.request)
        request = parse_local_embedding_workflow_request_v11(request.model_dump(mode="json"))
        plan = LocalEmbeddingSourcePlan.model_validate(self.plan)
        policy = LocalEmbeddingExecutionPolicy.model_validate(self.policy)
        require_local_embedding_operator_seed(request)
        validate_local_embedding_request_references(request, plan, policy)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "policy", policy)


class LocalEmbeddingOwnerAdmission(Protocol):
    """Actual fresh owner composition is REQUIRED; no production default is supplied.

    Bind each exact active root Session to an independently authenticated current
    operator/session, current workflow:start, configured released native-purpose
    policy, official source/read eligibility and eventual Catalog publish guard.
    Saved request actor/hash or an old resolved scope is audit, never continuation.
    Acquire the Identity/session/source fences before savepoints or lease assignment;
    refresh current rows and retain fences through root commit/rollback. Mutation
    repeats current command owner/token/generation/expiry and wall-clock expiry late
    before commit. Missing owner/fence/continuation is unavailable, never fallback.
    """

    def resolve_submission(
        self, session: Session, request: LocalEmbeddingWorkflowRequestV11
    ) -> ResolvedLocalEmbeddingAdmission: ...

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingWorkflowRequestV11,
    ) -> ResolvedLocalEmbeddingAdmission:
        """Fence exact freshly locked candidate rows BEFORE assigning a new lease.

        Repository owns the immutable peek header and compares it with these
        refreshed root-session rows. They are not detached audit/grant DTOs.
        This owner independently reauthorizes the same actual context and pins.
        """
        ...

    def fence_mutation(
        self,
        session: Session,
        request: LocalEmbeddingWorkflowRequestV11,
        lease: CommandLeaseIdentity,
    ) -> None:
        """Retain fresh authority and actual live command fence; return no boolean grant."""
        ...


def validate_local_embedding_submission_controls(
    scope: ResolvedLocalEmbeddingAdmission,
    definition: CompiledWorkflowDefinition,
    *,
    actor_type: str,
    actor_id: str,
) -> ResolvedLocalEmbeddingAdmission:
    """Pure purpose/control/audit closure, not actual authenticated admission.

    An application still requires the owner port in the same root transaction.
    No call here reads a permission, session, source, runtime or database state.
    """
    scope = ResolvedLocalEmbeddingAdmission(scope.request, scope.plan, scope.policy)
    if not isinstance(definition.definition, LocalEmbeddingWorkflowDefinition):
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    checked = compile_definition_data(definition.as_dict(), definition.source_path, set())
    audit = require_local_embedding_operator_seed(scope.request)
    if (
        checked.sha256 != definition.sha256
        or checked.canonical_bytes != definition.canonical_bytes
        or checked.definition != definition.definition
        or checked.definition.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        or checked.definition.definition_version != LOCAL_EMBEDDING_WORKFLOW_VERSION
        or definition_execution_protocol(checked.definition) != LOCAL_EMBEDDING_EXECUTION_PROTOCOL
        or scope.request.workflow_definition_sha256 != checked.sha256
    ):
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    if actor_type != "human" or actor_id != audit.operator_id:
        raise ValueError("LOCAL_EMBEDDING_OPERATOR_UNAVAILABLE")
    return scope


def validate_local_embedding_runner_admission(
    scope: ResolvedLocalEmbeddingAdmission,
    definition: CompiledWorkflowDefinition,
    *,
    actor_type: str,
    actor_id: str,
) -> ResolvedLocalEmbeddingAdmission:
    """Preserve the compute-start guard: coverage-only controls are not a Workflow."""
    scope = validate_local_embedding_submission_controls(
        scope, definition, actor_type=actor_type, actor_id=actor_id
    )
    if not scope.plan.demands:
        raise ValueError("LOCAL_EMBEDDING_COVERAGE_ONLY")
    return scope


def resolve_local_embedding_submission_controls(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: LocalEmbeddingWorkflowRequestV11,
    actor_type: str,
    actor_id: str,
    owner: LocalEmbeddingOwnerAdmission | None,
    executor: LocalEmbeddingNativeExecutor | None,
) -> ResolvedLocalEmbeddingAdmission:
    """Require the actual owner before lookup; immutable metadata is never a grant.

    The owner acquires root authority fences before the application's savepoint.
    Repeated calls inside that savepoint must retain/recheck those same root fences,
    not establish authorization from a nested transaction or a saved audit value.
    The caller commits the root promptly; this function does not own its commit.
    """
    if owner is None or executor is None:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "local embedding requires an actual owner and native executor",
        )
    transaction = session.get_transaction()
    if not session.is_active or transaction is None or not transaction.is_active:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "local embedding requires an active caller-owned root transaction",
        )
    checked = LocalEmbeddingWorkflowRequestV11.model_validate(request)
    checked = parse_local_embedding_workflow_request_v11(checked.model_dump(mode="json"))
    scope = owner.resolve_submission(session, checked)
    scope = ResolvedLocalEmbeddingAdmission(scope.request, scope.plan, scope.policy)
    if scope.request != checked:
        raise ValueError("LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID")
    current = session.scalar(
        select(WorkflowDefinitionRecord)
        .where(WorkflowDefinitionRecord.definition_id == definition.definition_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if current is None or (
        current.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        or current.definition_version != LOCAL_EMBEDDING_WORKFLOW_VERSION
        or current.active is not True
        or not workflow_definition_is_admitted(current.definition_key, current.definition_version)
    ):
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    compiled = compile_definition_data(current.canonical_definition, current.source_path, set())
    if (
        current.schema_version != compiled.definition.schema_version
        or current.definition_key != compiled.definition.definition_key
        or current.definition_version != compiled.definition.definition_version
        or current.definition_hash != compiled.sha256
        or definition.definition_hash != current.definition_hash
    ):
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    return validate_local_embedding_submission_controls(
        scope, compiled, actor_type=actor_type, actor_id=actor_id
    )
