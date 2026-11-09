"""Fresh batched relational closure for a saved ranking; no file/model materialization."""

from __future__ import annotations

from eom_identifiers import content_sha256
from eom_orchestrator.models import (
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.native_query_job_allocation import native_query_launch_key
from eom_workflow.reference_query_execution import PublicReferenceQueryWorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_models import EmbeddingIndexRevisionRecord
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.public_solution_population_dependencies import (
    PublicSolutionDependencyObserver,
)


def observe_completed_public_ranking_dependencies(
    session: Session,
    scope: ReadOnlyCandidatePoolScope,
    request: PublicReferenceQueryWorkflowRequest,
    workflow_id: str,
) -> str:
    """Reuse exact-source SQL pages/fingerprints, not previous authorization decisions.

    SHA observations cover original producer/Artifact state, source components,
    accepted V10/V11 reports and creative Workflow/step/plan provenance. A new
    mutable index/Graph head is deliberately absent: this read pins the old scope.
    Only small digests/IDs cross SQL; no reports or vectors are decoded in Python.
    """
    context = request.context_request
    if (
        scope.graph_snapshot != context.graph_snapshot
        or scope.access_policy_revision_id != context.policy_revision_id
        or scope.access_policy_sha256 != context.policy_sha256
        or scope.requested_by != request.operator_audit.operator_id
        or scope.source_classes != context.source_classes
        or scope.source_revision_ids
        or scope.analysis_run_ids
        or context.consumer_purpose != "ITEM_DATABASE_SEARCH"
    ):
        raise ValueError("COMPLETED_PUBLIC_RANKING_SCOPE_INVALID")
    observer = PublicSolutionDependencyObserver(session)
    observations = observer.observations
    observe, artifact_closure = observer.observe, observer.artifact_closure

    workflow, step = (
        WorkflowInstanceRecord.__table__,
        WorkflowStepRunRecord.__table__,
    )
    observe(
        "query_workflow",
        select(*workflow.c).where(workflow.c.workflow_id == workflow_id),
        1,
        ("workflow_id",),
    )
    query_steps = observe(
        "query_steps",
        select(*step.c).where(step.c.workflow_id == workflow_id),
        4,
        ("step_run_id",),
        ("step_run_id",),
    )
    keys = tuple(native_query_launch_key(request, workflow_id, value[0]) for value in query_steps)
    job, event = JobRecord.__table__, JobEventRecord.__table__
    native = observe(
        "query_jobs",
        select(*job.c).where(job.c.idempotency_key.in_(keys)),
        4,
        ("job_id",),
        ("job_id",),
    )
    native_ids = tuple(value[0] for value in native)
    producers = observe(
        "query_events",
        select(
            *event.c,
            event.c.data["payload"]["query_owner_job_id"].astext.label("query_producer"),
            event.c.data["payload"]["output"]["receipt_owner_job_id"].astext.label(
                "receipt_producer"
            ),
        ).where(event.c.job_id.in_(native_ids)),
        64,
        ("job_id", "sequence"),
        ("query_producer", "receipt_producer"),
    )
    query_producers = {value for row in producers for value in row if value is not None}
    revisions = observe(
        "query_artifact_revisions",
        select(*ArtifactRevisionRecord.__table__.c).where(
            ArtifactRevisionRecord.job_id.in_(tuple(sorted(query_producers)))
        ),
        16,
        ("logical_artifact_id", "revision_id"),
        ("logical_artifact_id", "revision_id"),
    )
    pointers = (
        request.native_execution_policy,
        request.runtime_bundle.manifest_member,
        context.views[0].index.index_manifest,
        context.anchor.source.artifact_member,
    )
    artifact_closure(
        set(revisions) | {(value.artifact_id, value.artifact_revision_id) for value in pointers},
        query_producers,
    )
    index = EmbeddingIndexRevisionRecord.__table__
    pin = context.views[0].index
    observe(
        "pinned_index",
        select(*index.c).where(
            index.c.index_id == pin.index_id, index.c.index_revision_id == pin.index_revision_id
        ),
        1,
        ("index_revision_id",),
    )

    pages = observer.population(scope, context.maximum_sources)
    return content_sha256({"pages": pages, "dependencies": observations})
