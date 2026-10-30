"""Required QUERY-purpose owner and exact immutable control checks, never a grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition_data
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_request_references,
)
from eom_workflow.reference_query_workflow import SupportedReferenceQueryWorkflowDefinition
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)

if TYPE_CHECKING:
    from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
    from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class ResolvedReferenceQueryAdmission:
    """Exact immutable controls only, not a retained source/session capability."""

    request: SupportedReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle

    def __post_init__(self) -> None:
        request = parse_supported_reference_query_workflow_request(self.request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        validate_reference_query_request_references(request, policy, bundle)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "bundle", bundle)


class ReferenceQueryOwnerAdmission(Protocol):
    """Independent current Identity/source/index owner in every actual SQL root.

    Source preparation/physical purpose/claim are distinct. Saved actor/pins,
    publication receipts and expired leases do not grant a new execution.
    """

    def resolve_submission(
        self, session: Session, request: SupportedReferenceQueryWorkflowRequest
    ) -> ResolvedReferenceQueryAdmission: ...

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: SupportedReferenceQueryWorkflowRequest,
    ) -> ResolvedReferenceQueryAdmission: ...

    def fence_mutation(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> None: ...


def validate_reference_query_runner_admission(
    scope: ResolvedReferenceQueryAdmission,
    definition: CompiledWorkflowDefinition,
    *,
    actor_type: str,
    actor_id: str,
) -> ResolvedReferenceQueryAdmission:
    """Pure purpose/definition/audit closure; actual authority remains the owner."""
    scope = ResolvedReferenceQueryAdmission(scope.request, scope.policy, scope.bundle)
    checked = compile_definition_data(definition.as_dict(), definition.source_path, set())
    if (
        not isinstance(checked.definition, SupportedReferenceQueryWorkflowDefinition)
        or checked.sha256 != definition.sha256
        or checked.canonical_bytes != definition.canonical_bytes
        or checked.definition != definition.definition
        or scope.request.workflow_definition_sha256 != checked.sha256
    ):
        raise ValueError("REFERENCE_QUERY_PURPOSE_INVALID")
    if actor_type != "human" or actor_id != scope.request.operator_audit.operator_id:
        raise ValueError("REFERENCE_QUERY_OPERATOR_UNAVAILABLE")
    return scope


def resolve_reference_query_submission_controls(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: SupportedReferenceQueryWorkflowRequest,
    actor_type: str,
    actor_id: str,
    owner: ReferenceQueryOwnerAdmission | None,
    executor: ReferenceQueryNativeExecutor | None,
) -> ResolvedReferenceQueryAdmission:
    """Fence before savepoints; an unoffered definition stays unavailable even with ports."""
    if (
        owner is None
        or executor is None
        or not workflow_definition_is_admitted(
            request.workflow_definition_key, request.workflow_definition_version
        )
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "reference query requires an admitted definition and actual QUERY owner/executor",
        )
    root = session.get_transaction()
    if not session.is_active or root is None or not root.is_active:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "reference query requires an active caller-owned root transaction",
        )
    request = parse_supported_reference_query_workflow_request(request)
    scope = owner.resolve_submission(session, request)
    scope = ResolvedReferenceQueryAdmission(scope.request, scope.policy, scope.bundle)
    if scope.request != request:
        raise ValueError("REFERENCE_QUERY_SUBMISSION_CONTEXT_INVALID")
    current = session.scalar(
        select(WorkflowDefinitionRecord)
        .where(WorkflowDefinitionRecord.definition_id == definition.definition_id)
        # The immutable-definition trigger covers active as well as its snapshot.
        .execution_options(populate_existing=True)
    )
    if current is None or current.active is not True:
        raise ValueError("REFERENCE_QUERY_PURPOSE_INVALID")
    compiled = compile_definition_data(current.canonical_definition, current.source_path, set())
    if (
        current.schema_version != compiled.definition.schema_version
        or current.definition_key != compiled.definition.definition_key
        or current.definition_version != compiled.definition.definition_version
        or current.definition_hash != compiled.sha256
        or definition.definition_hash != current.definition_hash
    ):
        raise ValueError("REFERENCE_QUERY_PURPOSE_INVALID")
    return validate_reference_query_runner_admission(
        scope, compiled, actor_type=actor_type, actor_id=actor_id
    )
