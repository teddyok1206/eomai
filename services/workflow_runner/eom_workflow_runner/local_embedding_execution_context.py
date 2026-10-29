"""Current native Workflow/command/step source fence, shared by compute and completion."""

from __future__ import annotations

from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryLookup
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandLeaseIdentity, require_command_lease


def native_embedding_registry_scope(
    request: SupportedLocalEmbeddingRequest,
) -> EmbeddingRegistryLookup:
    """Small exact request selection, never source or publisher authority."""
    return EmbeddingRegistryLookup(
        request.corpus_id,
        request.namespace,
        request.graph_snapshot,
        request.access_policy_revision_id,
        request.access_policy_sha256,
        MAX_PUBLIC_SOLUTION_SOURCES
        if isinstance(request.namespace, PublicSolutionIndexNamespace)
        else 1024,
    )


def resolve_native_execution_sources(
    owner: CatalogLocalEmbeddingOwnerAdmission,
    session: Session,
    *,
    workflow_id: str,
    step_run_id: str,
    request: SupportedLocalEmbeddingRequest,
    lease: CommandLeaseIdentity,
) -> ResolvedLocalEmbeddingSources:
    sources = owner.resolve_mutation_sources(session, request, lease)
    command = require_command_lease(session, lease)
    workflow = session.get(WorkflowInstanceRecord, workflow_id)
    step = session.get(WorkflowStepRunRecord, step_run_id)
    if (
        workflow is None
        or step is None
        or workflow.state not in {"RUNNING", "COMPLETED"}
        or command.workflow_id != workflow_id
        or step.workflow_id != workflow_id
        or step.step_key != "encode_batch"
        or step.attempt != 1
        or step.state not in {"RUNNING", "SUCCEEDED"}
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != "incremental-embedding-result@1.0"
        or step.input_pointer_manifest
        != {
            "source_plan": request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": request.source_plan_sha256,
        }
    ):
        raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CURRENT_STEP_INVALID")
    return sources
