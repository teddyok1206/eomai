"""Fresh batched relational closure for a saved ranking; no file/model materialization."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.native_query_job_allocation import native_query_launch_key
from eom_workflow.reference_query_execution import PublicReferenceQueryWorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_models import EmbeddingIndexRevisionRecord
from eom_catalog_service.inference_transfer_population_read_set import (
    observe_inference_transfer_population,
    observe_population_dependency,
)
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.local_indexing_source_paging import (
    CandidateSourcePage,
    candidate_source_page_statement,
    validate_candidate_source_page,
)
from eom_catalog_service.models import ItemComponentRecord


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
    observations = []

    def observe(
        group: str,
        statement: Select[Any],
        bound: int,
        order: tuple[str, ...],
        retain: tuple[str, ...] = (),
    ) -> tuple[tuple[Any, ...], ...]:
        observation, keys = observe_population_dependency(
            session,
            group,
            statement,
            maximum=bound,
            order=order,
            retain=retain,
        )
        observations.append((observation.group, observation.row_count, observation.sha256))
        return keys

    def artifact_closure(identities: set[tuple[str, str]], producer_ids: set[str]) -> None:
        artifact, revision, job = (
            ArtifactRecord.__table__,
            ArtifactRevisionRecord.__table__,
            JobRecord.__table__,
        )
        logical_ids = tuple(sorted({value[0] for value in identities}))
        bound = max(1, len(identities))
        observe(
            "artifacts",
            select(*artifact.c).where(artifact.c.logical_artifact_id.in_(logical_ids)),
            bound,
            ("logical_artifact_id",),
        )
        rows = observe(
            "artifact_revisions",
            select(*revision.c).where(
                tuple_(revision.c.logical_artifact_id, revision.c.revision_id).in_(
                    tuple(sorted(identities))
                )
            ),
            bound,
            ("logical_artifact_id", "revision_id"),
            ("job_id",),
        )
        producer_ids.update(value[0] for value in rows)
        observe(
            "producers",
            select(*job.c).where(job.c.job_id.in_(tuple(sorted(producer_ids)))),
            max(1, len(producer_ids)),
            ("job_id",),
        )

    workflow, step, plan = (
        WorkflowInstanceRecord.__table__,
        WorkflowStepRunRecord.__table__,
        ResolvedExecutionPlanRecord.__table__,
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

    page_scope = replace(scope, maximum_candidates=min(256, scope.maximum_candidates))
    pages: list[tuple[str | None, CandidateSourcePage]] = []
    after: str | None = None
    total = 0

    def read_page(cursor: str | None) -> CandidateSourcePage:
        return validate_candidate_source_page(
            tuple(
                tuple(row)
                for row in session.execute(
                    candidate_source_page_statement(page_scope, after_source_revision_id=cursor)
                )
            ),
            maximum=page_scope.maximum_candidates,
            after_source_revision_id=cursor,
        )

    while True:
        page = read_page(after)
        total += len(page.members)
        if total > context.maximum_sources:
            raise ValueError("COMPLETED_PUBLIC_RANKING_POPULATION_CHANGED")
        pages.append((after, page))
        selected = tuple(value[0] for value in page.members)
        current_scope = replace(page_scope, source_revision_ids=selected)
        if selected:
            original = observe_inference_transfer_population(
                session, current_scope, artifact_identities=()
            )
            observations.extend(
                (value.group, value.row_count, value.sha256) for value in original.groups
            )
            component = ItemComponentRecord.__table__
            components = observe(
                "all_components",
                select(*component.c).where(component.c.item_revision_id.in_(selected)),
                len(selected) * 128,
                ("item_component_id",),
                ("artifact_id", "artifact_revision_id"),
            )
            run = KnowledgeAnalysisRunRecord.__table__
            reports = observe(
                "registered_reports",
                select(*run.c).where(
                    run.c.predecessor_analysis_run_id.in_(
                        tuple(value[1] for value in page.members)
                    ),
                    run.c.state == "ACCEPTED",
                    run.c.canonical_request["schema_version"].astext
                    == "knowledge-analysis-request/11.0",
                ),
                len(selected),
                ("analysis_run_id",),
                (
                    "accepted_result_artifact_id",
                    "accepted_result_artifact_revision_id",
                    "proposal_artifact_id",
                    "proposal_artifact_revision_id",
                ),
            )
            identities = set(components)
            for row in reports:
                identities.update(
                    (row[index], row[index + 1])
                    for index in (0, 2)
                    if row[index] is not None and row[index + 1] is not None
                )
            artifact_closure(identities, set())
            revision = ArtifactRevisionRecord.__table__
            producer_statement = select(revision.c.job_id).where(
                tuple_(revision.c.logical_artifact_id, revision.c.revision_id).in_(
                    tuple(sorted(identities))
                )
            )
            steps = observe(
                "source_steps",
                select(*step.c).where(step.c.platform_job_id.in_(producer_statement)),
                len(selected) * 128,
                ("step_run_id",),
                ("workflow_id",),
            )
            workflows = tuple(sorted({value[0] for value in steps}))
            observe(
                "source_workflows",
                select(*workflow.c).where(workflow.c.workflow_id.in_(workflows)),
                max(1, len(workflows)),
                ("workflow_id",),
            )
            observe(
                "source_plans",
                select(*plan.c).where(plan.c.workflow_id.in_(workflows)),
                max(1, len(workflows) * 32),
                ("plan_id",),
            )
        if page.complete:
            break
        after = page.next_after_source_revision_id
    if any(read_page(cursor) != page for cursor, page in pages):
        raise ValueError("COMPLETED_PUBLIC_RANKING_POPULATION_CHANGED")
    return content_sha256(
        {"pages": tuple(page.members for _cursor, page in pages), "dependencies": observations}
    )
