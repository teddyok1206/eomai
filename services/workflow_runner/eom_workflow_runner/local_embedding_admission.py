"""Fixed native purpose guards and a required current-owner boundary, never a grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition_data
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingExecutablePolicy,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_executable_policy,
)
from eom_workflow.local_embedding_request import (
    validate_local_embedding_request_references,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
    validate_local_embedding_request_references_v2,
)
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LOCAL_EMBEDDING_WORKFLOW_KEY,
    LocalEmbeddingWorkflowDefinition,
)
from eom_workflow.local_embedding_workflow_v2 import LocalEmbeddingWorkflowDefinitionV2
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

type SupportedLocalEmbeddingOwnerRequest = SupportedLocalEmbeddingRequest

# Public compatibility names delegate to the authoritative lower-layer contract.
parse_supported_local_embedding_owner_request = parse_supported_local_embedding_request
local_embedding_owner_request_actor = supported_local_embedding_request_actor


@dataclass(frozen=True, slots=True)
class ResolvedLocalEmbeddingAdmission:
    """Validated immutable controls only; no caller/session/source authority is carried."""

    request: SupportedLocalEmbeddingOwnerRequest
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2
    policy: LocalEmbeddingExecutablePolicy

    def __post_init__(self) -> None:
        request = parse_supported_local_embedding_owner_request(self.request)
        policy = parse_local_embedding_executable_policy(raw_similarity_contract_value(self.policy))
        plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2
        if isinstance(request, LocalEmbeddingWorkflowRequestV2):
            plan = parse_local_embedding_source_plan_v2(self.plan)
            if not isinstance(policy, LocalEmbeddingServiceExecutionPolicy):
                raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
            validate_local_embedding_request_references_v2(request, plan, policy)
        else:
            plan = parse_local_embedding_source_plan(raw_similarity_contract_value(self.plan))
            validate_local_embedding_request_references(request, plan, policy)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "policy", policy)


class LocalEmbeddingOwnerAdmission(Protocol):
    """Actual fresh owner composition is REQUIRED; no production default is supplied.

    Bind each exact active root Session to an independently authenticated current
    operator/session+workflow:start OR installed purpose-specific service authority,
    configured released native policy, official source/read eligibility and eventual
    Catalog derived-index publication guard. These are separate checked actors.
    Saved request actor/hash or an old resolved scope is audit, never continuation.
    Acquire the Identity/session/source fences before savepoints or lease assignment;
    refresh current rows and retain fences through root commit/rollback. Mutation
    repeats current command owner/token/generation/expiry and wall-clock expiry late
    before commit. Missing owner/fence/continuation is unavailable, never fallback.
    """

    def resolve_submission(
        self, session: Session, request: SupportedLocalEmbeddingOwnerRequest
    ) -> ResolvedLocalEmbeddingAdmission: ...

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: SupportedLocalEmbeddingOwnerRequest,
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
        request: SupportedLocalEmbeddingOwnerRequest,
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
    expected_definition = (
        LocalEmbeddingWorkflowDefinitionV2
        if isinstance(scope.request, LocalEmbeddingWorkflowRequestV2)
        else LocalEmbeddingWorkflowDefinition
    )
    if type(definition.definition) is not expected_definition:
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    checked = compile_definition_data(definition.as_dict(), definition.source_path, set())
    expected_actor_type, expected_actor_id = local_embedding_owner_request_actor(scope.request)
    if (
        checked.sha256 != definition.sha256
        or checked.canonical_bytes != definition.canonical_bytes
        or checked.definition != definition.definition
        or checked.definition.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        or checked.definition.definition_version != scope.request.workflow_definition_version
        or definition_execution_protocol(checked.definition) != LOCAL_EMBEDDING_EXECUTION_PROTOCOL
        or scope.request.workflow_definition_sha256 != checked.sha256
    ):
        raise ValueError("LOCAL_EMBEDDING_PURPOSE_INVALID")
    if actor_type != expected_actor_type or actor_id != expected_actor_id:
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
    request: SupportedLocalEmbeddingOwnerRequest,
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
    checked = parse_supported_local_embedding_owner_request(request)
    scope = owner.resolve_submission(session, checked)
    scope = ResolvedLocalEmbeddingAdmission(scope.request, scope.plan, scope.policy)
    if scope.request != checked:
        raise ValueError("LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID")
    current = session.scalar(
        select(WorkflowDefinitionRecord)
        .where(WorkflowDefinitionRecord.definition_id == definition.definition_id)
        # Definitions (including active) are DB-enforced immutable revisions.
        # A row lock requires UPDATE privilege without adding protection here.
        .execution_options(populate_existing=True)
    )
    if current is None or (
        current.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        or current.definition_version != checked.workflow_definition_version
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
