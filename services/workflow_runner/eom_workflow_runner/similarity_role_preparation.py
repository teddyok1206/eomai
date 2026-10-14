"""Bind current Catalog reads to the exact stored authoring/review step and QUERY."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_prompt_context import read_similarity_prompt_context
from eom_identity_service import OperatorAuthorizationFenceError
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.similarity_materialization import SimilarityMaterializationContext
from eom_workflow.models import WorkerRequest
from eom_workflow.schemas import result_schema_protocol
from eom_workflow.similarity_control import (
    ResolvedExecutionPlanV23,
    parse_similarity_execution_plan,
    validate_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.reference_query_consumer_read import (
    CatalogCompletedReferenceQueryRead,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_business_fingerprint,
)
from eom_workflow_runner.similarity_context_session_reader import (
    CatalogSimilaritySessionContextReader,
)
from eom_workflow_runner.similarity_materialization_adapter import (
    CatalogSimilarityMaterializationReader,
)
from eom_workflow_runner.state_machine import StepState, WorkflowState

SIMILARITY_QUERY_CONTEXT_KEY = "similarity_query"


@dataclass(frozen=True, slots=True)
class _SimilarityRoleBinding:
    """Attached root-local records/values only, not stored authority or a grant."""

    workflow: WorkflowInstanceRecord
    plan: ResolvedExecutionPlanV23


def _bind_role(
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: WorkerRequest,
) -> _SimilarityRoleBinding | None:
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise ControlPlaneError("CONTROL_SIMILARITY_CONTEXT_INVALID", "role root is invalid")
    actual = session.get(WorkflowInstanceRecord, workflow.workflow_id, populate_existing=True)
    current = session.get(WorkflowStepRunRecord, step.step_run_id, populate_existing=True)
    if (
        actual is None
        or current is None
        or (
            object_session(actual) is not session
            or object_session(current) is not session
            or current.workflow_id != actual.workflow_id
            or current.step_key != step.step_key
            or current.worker_role != step.worker_role
            or current.attempt != step.attempt
            or current.result_schema != step.result_schema
            or current.result_schema is None
            or current.step_type != "agent"
            or actual.current_step_key != current.step_key
            or current.state != StepState.RUNNING.value
            or actual.state != WorkflowState.RUNNING.value
        )
    ):
        raise ControlPlaneError("CONTROL_SIMILARITY_CONTEXT_INVALID", "stored role differs")
    raw_pin = actual.runtime_context.get("execution_plan")
    if not isinstance(raw_pin, dict) or not isinstance(raw_pin.get("plan_id"), str):
        return None  # Legacy/no-plan retains its original Orchestrator guards.
    record = session.get(ResolvedExecutionPlanRecord, raw_pin["plan_id"])
    if record is None:
        raise ControlPlaneError("CONTROL_PLAN_MISSING", "stored execution plan is missing")
    if not isinstance(record.canonical_document, dict):
        raise ControlPlaneError("CONTROL_SIMILARITY_CONTEXT_INVALID", "stored plan is invalid")
    if record.canonical_document.get("schema_version") != "resolved-execution-plan/23.0":
        return None
    try:
        declaration = read_similarity_prompt_context(
            session,
            workflow=actual,
            step=current,
            pack_release_id=record.canonical_document["content_pack_release_id"],
        )
        plan = parse_similarity_execution_plan(record.canonical_document)
        stored_request = load_persisted_workflow_request(actual.initial_request)
        definition = session.get(WorkflowDefinitionRecord, actual.definition_id)
        if (
            declaration.reference_mode != "PINNED_REFERENCE_CONTEXT"
            or definition is None
            or definition.definition_key != actual.definition_key
            or definition.definition_version != actual.definition_version
            or definition.definition_hash != actual.definition_hash
            or workflow_business_fingerprint(definition, stored_request) != actual.request_hash
            or plan.workflow_definition_sha256 != actual.definition_hash
            or actual.role_schema_version != "workflow-role/1.24.0"
            or result_schema_protocol(current.result_schema) != actual.role_schema_version
            or plan.content_pack_sha256 != SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.17"]
            or stored_request.content_pack is None
            or stored_request.content_pack.pack_key != "generated-knowledge-item"
            or stored_request.worker_request() != request
            or stored_request != load_persisted_workflow_request(actual.request_payload)
            or stored_request.educational_retrieval != plan.retrieval_requirement
            or actual.created_actor_type != "human"
        ):
            raise ValueError("SIMILARITY_ROLE_REQUEST_MISMATCH")
        return _SimilarityRoleBinding(actual, plan)
    except (ValueError, TypeError, KeyError, SchemaError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "stored similarity role binding differs"
        ) from None


def _materialization_context(
    binding: _SimilarityRoleBinding, query: CatalogCompletedReferenceQueryRead
) -> SimilarityMaterializationContext:
    try:
        if binding.workflow.created_actor_id != query.request.operator_audit.operator_id:
            raise ValueError("SIMILARITY_ROLE_CREATOR_MISMATCH")
        validate_similarity_plan_request(binding.plan, query.request.context_request)
    except (ValueError, TypeError, KeyError, SchemaError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "stored similarity query binding differs"
        ) from None
    caller = EmbeddingRegistryCaller(binding.workflow.created_actor_id)
    common = CatalogSimilaritySessionContextReader(query)
    return SimilarityMaterializationContext(
        workflow_id=binding.workflow.workflow_id,
        operator_id=caller.operator_id,
        request=query.request.context_request,
        reader=CatalogSimilarityMaterializationReader(caller, common, query.owner.catalog),
    )


class CatalogSimilarityRoleContextProvider:
    """Existing bounded exact-reader path; never a process-wide operator fallback."""

    def __init__(self, query: CatalogCompletedReferenceQueryRead) -> None:
        if not isinstance(query, CatalogCompletedReferenceQueryRead):
            raise ValueError("SIMILARITY_ROLE_READER_INVALID")
        self.query = query

    def prepare(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
    ) -> SimilarityMaterializationContext | None:
        binding = _bind_role(session, workflow, step, request)
        if binding is None:
            return None
        result = _materialization_context(binding, self.query)
        try:
            self.query.owner.identity.fence_current_operator(session, result.operator_id)
        except OperatorAuthorizationFenceError as error:
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                "current role operator unavailable",
            ) from None
        return result


class CatalogWorkflowSimilarityRoleContextProvider:
    """Shared provider with an exact selection per stored Workflow and caller root.

    Retain only trusted read-owner configuration, never the last user/query, a
    capture cache, native executor, current index or latest-query fallback.
    """

    def __init__(self, owner: ReferenceQuerySourceOwner) -> None:
        self.owner = owner

    def prepare(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
    ) -> SimilarityMaterializationContext | None:
        binding = _bind_role(session, workflow, step, request)
        if binding is None:
            return None
        try:
            selection = CompletedSimilarityQuerySelection.model_validate(
                binding.workflow.runtime_context.get(SIMILARITY_QUERY_CONTEXT_KEY)
            )
            if selection.context_request_sha256 != binding.plan.similarity_delivery.request_sha256:
                raise ValueError("SIMILARITY_ROLE_CONTEXT_SELECTION_MISMATCH")
            original = select_completed_reference_query_request(
                session,
                self.owner,
                EmbeddingRegistryCaller(binding.workflow.created_actor_id),
                selection,
            )
            query = CatalogCompletedReferenceQueryRead(
                self.owner, workflow_id=selection.workflow_id, request=original
            )
            return _materialization_context(binding, query)
        except SimilarityContextReadError as error:
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                if error.code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
                if error.code == "AUTHORITY_UNAVAILABLE"
                else "CONTROL_SIMILARITY_CONTEXT_INVALID",
                "current workflow query unavailable",
            ) from None
        except (ValueError, TypeError, KeyError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "stored workflow query selection differs"
            ) from None
