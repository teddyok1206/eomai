"""Catalog-owned current reads for a stored active role; never runner SQL impersonation."""

from __future__ import annotations

import json

from eom_catalog_contracts.public_similarity_materials import parse_public_similarity_materials
from eom_catalog_contracts.public_workflow_similarity_read import (
    PublicWorkflowSimilarityReadReply,
    PublicWorkflowSimilarityReadRequest,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
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
from eom_orchestrator.public_similarity_materialization import (
    PublicSimilarityMaterializationContext,
    resolve_public_similarity_materials,
)
from eom_orchestrator.similarity_materialization import resolve_similarity_materials
from eom_workflow.models import WorkerRequest
from eom_workflow.public_similarity_control import SupportedPublicSimilarityExecutionPlan
from eom_workflow.similarity_control import SupportedSimilarityExecutionPlan
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner
from eom_workflow_runner.repository import load_persisted_workflow_request
from eom_workflow_runner.similarity_role_preparation import (
    SIMILARITY_QUERY_CONTEXT_KEY,
    CatalogWorkflowSimilarityRoleContextProvider,
    parse_role_similarity_plan,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.exc import SQLAlchemyError


class WorkflowSimilarityReadServiceError(ValueError):
    def __init__(self, code: WorkflowSimilarityReadErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogWorkflowSimilarityReadService:
    """One current Catalog root through stored-role and canonical-source/material IO."""

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        *,
        public_owner: ReferenceQuerySourceOwner | None = None,
    ) -> None:
        if public_owner is not None and (
            public_owner.catalog.engine is not owner.catalog.engine
            or public_owner.settings != owner.settings
        ):
            raise ValueError("public role read root differs")
        self.owner = owner
        self.public_owner = public_owner
        self.sessions = build_session_factory(owner.catalog.engine)
        self.provider = CatalogWorkflowSimilarityRoleContextProvider(owner)
        self.public_provider = (
            None
            if public_owner is None
            else CatalogWorkflowSimilarityRoleContextProvider(public_owner)
        )

    def read(self, request: WorkflowSimilarityReadRequest) -> WorkflowSimilarityReadReply:
        request = WorkflowSimilarityReadRequest.model_validate(request)
        result = self._read(request)
        assert isinstance(result, WorkflowSimilarityReadReply)
        return result

    def read_public(
        self, request: PublicWorkflowSimilarityReadRequest
    ) -> PublicWorkflowSimilarityReadReply:
        result = self._read(PublicWorkflowSimilarityReadRequest.model_validate(request))
        assert isinstance(result, PublicWorkflowSimilarityReadReply)
        return result

    def _read(
        self, request: WorkflowSimilarityReadRequest | PublicWorkflowSimilarityReadRequest
    ) -> WorkflowSimilarityReadReply | PublicWorkflowSimilarityReadReply:
        public = isinstance(request, PublicWorkflowSimilarityReadRequest)
        owner = self.public_owner if public else self.owner
        provider = self.public_provider if public else self.provider
        if owner is None or provider is None:
            raise WorkflowSimilarityReadServiceError("WORKFLOW_SIMILARITY_UNAVAILABLE")
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
                context = provider.prepare(
                    session, workflow=workflow, step=step, request=worker_request
                )
                if context is None:
                    raise ValueError("stored role has no similarity contract")
                raw_pin = dict(workflow.runtime_context["execution_plan"])
                role_pin = (step.step_key, step.worker_role, step.attempt, step.result_schema)
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
                plan = parse_role_similarity_plan(record.canonical_document)
                pin = plan.similarity_delivery.context_member
                if isinstance(request, PublicWorkflowSimilarityReadRequest):
                    if not isinstance(
                        plan, SupportedPublicSimilarityExecutionPlan
                    ) or not isinstance(context, PublicSimilarityMaterializationContext):
                        raise ValueError("public role family differs")
                    materialized = resolve_public_similarity_materials(
                        session,
                        plan=plan,
                        step_key=step.step_key,
                        context=context,
                        original_source=context.request.anchor.source,
                        canonical_artifact_root=owner.settings.nas_artifact_root,
                        authorized_artifact_revision_ids=frozenset({pin.artifact_revision_id}),
                    )
                else:
                    if not isinstance(plan, SupportedSimilarityExecutionPlan) or isinstance(
                        context, PublicSimilarityMaterializationContext
                    ):
                        raise ValueError("legacy role family differs")
                    materialized = resolve_similarity_materials(
                        session,
                        plan=plan,
                        step_key=step.step_key,
                        context=context,
                        original_source=context.request.anchor.source,
                        canonical_artifact_root=owner.settings.nas_artifact_root,
                        authorized_artifact_revision_ids=frozenset({pin.artifact_revision_id}),
                    )
                late = provider.prepare(
                    session, workflow=workflow, step=step, request=worker_request
                )
                if (
                    late is None
                    or type(late) is not type(context)
                    or (step.step_key, step.worker_role, step.attempt, step.result_schema)
                    != role_pin
                    or late.operator_id != context.operator_id
                    or late.request != context.request
                    or workflow.runtime_context["execution_plan"] != raw_pin
                    or CompletedSimilarityQuerySelection.model_validate(
                        workflow.runtime_context[SIMILARITY_QUERY_CONTEXT_KEY]
                    )
                    != query
                ):
                    raise ValueError("stored role changed during materialization")
                if isinstance(request, PublicWorkflowSimilarityReadRequest):
                    return PublicWorkflowSimilarityReadReply(
                        schema_version="system-rag-workflow-similarity-read-reply/2.0",
                        operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
                        status="SUCCESS",
                        request_sha256=content_sha256(request.model_dump(mode="json")),
                        operator_id=context.operator_id,
                        context=parse_supported_public_solution_similarity_context(
                            json.loads(materialized.context_payload)
                        ),
                        materials=parse_public_similarity_materials(
                            json.loads(materialized.references_payload)
                        ),
                        error_code=None,
                    )
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
