"""Catalog-owned current reads for a stored active role; never runner SQL impersonation."""

from __future__ import annotations

import json

from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_materials import parse_similarity_materials
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.workflow_similarity_read import (
    WorkflowSimilarityReadErrorCode,
    WorkflowSimilarityReadReply,
    WorkflowSimilarityReadRequest,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.similarity_materialization import resolve_similarity_materials
from eom_workflow.models import WorkerRequest
from eom_workflow.similarity_control import parse_supported_similarity_execution_plan
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner
from eom_workflow_runner.repository import load_persisted_workflow_request
from eom_workflow_runner.similarity_role_preparation import (
    SIMILARITY_QUERY_CONTEXT_KEY,
    CatalogWorkflowSimilarityRoleContextProvider,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.exc import SQLAlchemyError


class WorkflowSimilarityReadServiceError(ValueError):
    def __init__(self, code: WorkflowSimilarityReadErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogWorkflowSimilarityReadService:
    """One current Catalog root through stored-role and canonical-source/material IO."""

    def __init__(self, owner: ReferenceQuerySourceOwner) -> None:
        self.owner = owner
        self.sessions = build_session_factory(owner.catalog.engine)
        self.provider = CatalogWorkflowSimilarityRoleContextProvider(owner)

    def read(self, request: WorkflowSimilarityReadRequest) -> WorkflowSimilarityReadReply:
        request = WorkflowSimilarityReadRequest.model_validate(request)
        selected = request.selection
        try:
            with self.sessions.begin() as session:
                workflow = session.get(WorkflowInstanceRecord, selected.workflow_id)
                step = session.get(WorkflowStepRunRecord, selected.step_run_id)
                if workflow is None or step is None or step.workflow_id != workflow.workflow_id:
                    raise ValueError("stored role missing")
                initial = load_persisted_workflow_request(workflow.initial_request)
                worker_request = initial.worker_request()
                if not isinstance(worker_request, WorkerRequest):
                    raise ValueError("stored request is not an Item request")
                context = self.provider.prepare(
                    session, workflow=workflow, step=step, request=worker_request
                )
                if context is None:
                    raise ValueError("stored role has no similarity contract")
                raw_pin = workflow.runtime_context["execution_plan"]
                query = CompletedSimilarityQuerySelection.model_validate(
                    workflow.runtime_context[SIMILARITY_QUERY_CONTEXT_KEY]
                )
                record = session.get(ResolvedExecutionPlanRecord, selected.plan_id)
                if (
                    raw_pin["plan_id"] != selected.plan_id
                    or raw_pin["plan_sha256"] != selected.plan_sha256
                    or query != selected.query
                    or record is None
                    or record.workflow_id != workflow.workflow_id
                    or record.plan_sha256 != selected.plan_sha256
                ):
                    raise ValueError("stored role selection changed")
                plan = parse_supported_similarity_execution_plan(record.canonical_document)
                pin = plan.similarity_delivery.context_member
                materialized = resolve_similarity_materials(
                    session,
                    plan=plan,
                    step_key=step.step_key,
                    context=context,
                    original_source=context.request.anchor.source,
                    canonical_artifact_root=self.owner.settings.nas_artifact_root,
                    # This allowlist is the exact stored plan member, not source authority.
                    # The reader above still fences the actual creator and original QUERY.
                    authorized_artifact_revision_ids=frozenset({pin.artifact_revision_id}),
                )
                late = self.provider.prepare(
                    session, workflow=workflow, step=step, request=worker_request
                )
                if (
                    late is None
                    or late.operator_id != context.operator_id
                    or late.request != context.request
                    or workflow.runtime_context["execution_plan"] != raw_pin
                    or CompletedSimilarityQuerySelection.model_validate(
                        workflow.runtime_context[SIMILARITY_QUERY_CONTEXT_KEY]
                    )
                    != query
                ):
                    raise ValueError("stored role changed during materialization")
                return WorkflowSimilarityReadReply(
                    schema_version="system-rag-workflow-similarity-read-reply/1.0",
                    operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
                    status="SUCCESS",
                    request_sha256=content_sha256(request.model_dump(mode="json")),
                    operator_id=context.operator_id,
                    context=parse_similarity_context(json.loads(materialized.context_payload)),
                    materials=parse_similarity_materials(
                        json.loads(materialized.references_payload)
                    ),
                    error_code=None,
                )
        except ControlPlaneError as error:
            raise WorkflowSimilarityReadServiceError(
                "SOURCE_ACCESS_DENIED"
                if error.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                else "AUTHORITY_UNAVAILABLE"
                if error.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
                else "WORKFLOW_SIMILARITY_BINDING_INVALID"
            ) from None
        except SQLAlchemyError:
            raise WorkflowSimilarityReadServiceError("WORKFLOW_SIMILARITY_UNAVAILABLE") from None
        except (ValueError, TypeError, KeyError, SchemaError, RecursionError, WorkflowError):
            raise WorkflowSimilarityReadServiceError(
                "WORKFLOW_SIMILARITY_BINDING_INVALID"
            ) from None
