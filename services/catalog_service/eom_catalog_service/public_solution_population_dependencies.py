"""Current public-solution source closure, shared by saved reads and INDEX roots."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.inference_transfer_population_read_set import (
    observe_indexing_population_in_transaction,
    observe_inference_transfer_population,
    observe_population_dependency,
)
from eom_catalog_service.inference_transfer_read_timing import (
    InferenceTransferReadStage,
    observe_read_stage,
)
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.local_indexing_source_paging import (
    CandidateSourcePage,
    candidate_source_page_statement,
    validate_candidate_source_page,
)
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.models import ItemComponentRecord


class PublicSolutionDependencyObserver:
    """Stream bounded SQL digests, never canonical reports or a permission grant."""

    def __init__(
        self, session: Session, *, index_transaction: SessionTransaction | None = None
    ) -> None:
        self.session = session
        self.index_transaction = index_transaction
        self.observations: list[tuple[str, int, str]] = []

    def observe(
        self,
        group: str,
        statement: Select[Any],
        bound: int,
        order: tuple[str, ...],
        retain: tuple[str, ...] = (),
    ) -> tuple[tuple[Any, ...], ...]:
        observation, keys = observe_population_dependency(
            self.session,
            group,
            statement,
            maximum=bound,
            order=order,
            retain=retain,
        )
        self.observations.append((observation.group, observation.row_count, observation.sha256))
        return keys

    def artifact_closure(self, identities: set[tuple[str, str]], producer_ids: set[str]) -> None:
        artifact, revision, job = (
            ArtifactRecord.__table__,
            ArtifactRevisionRecord.__table__,
            JobRecord.__table__,
        )
        logical_ids = tuple(sorted({value[0] for value in identities}))
        bound = max(1, len(identities))
        self.observe(
            "artifacts",
            select(*artifact.c).where(artifact.c.logical_artifact_id.in_(logical_ids)),
            bound,
            ("logical_artifact_id",),
        )
        rows = self.observe(
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
        self.observe(
            "producers",
            select(*job.c).where(job.c.job_id.in_(tuple(sorted(producer_ids)))),
            max(1, len(producer_ids)),
            ("job_id",),
        )

    def population(
        self,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        maximum_sources: int,
    ) -> tuple[tuple[tuple[str, str], ...], ...]:
        session = self.session
        workflow, step, plan = (
            WorkflowInstanceRecord.__table__,
            WorkflowStepRunRecord.__table__,
            ResolvedExecutionPlanRecord.__table__,
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
            if total > maximum_sources:
                raise ValueError("COMPLETED_PUBLIC_RANKING_POPULATION_CHANGED")
            pages.append((after, page))
            selected = tuple(value[0] for value in page.members)
            current_scope = replace(page_scope, source_revision_ids=selected)
            if selected:
                if self.index_transaction is None:
                    original = observe_inference_transfer_population(
                        session, current_scope, artifact_identities=()
                    )
                else:
                    if not isinstance(current_scope, LocalIndexingSourceReadIntent):
                        raise ValueError("PUBLIC_SOLUTION_INDEX_TRANSACTION_INVALID")
                    original = observe_indexing_population_in_transaction(
                        session,
                        current_scope,
                        transaction=self.index_transaction,
                        artifact_identities=(),
                    )
                self.observations.extend(
                    (value.group, value.row_count, value.sha256) for value in original.groups
                )
                component = ItemComponentRecord.__table__
                components = self.observe(
                    "all_components",
                    select(*component.c).where(component.c.item_revision_id.in_(selected)),
                    len(selected) * 128,
                    ("item_component_id",),
                    ("artifact_id", "artifact_revision_id"),
                )
                run = KnowledgeAnalysisRunRecord.__table__
                reports = self.observe(
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
                self.artifact_closure(identities, set())
                revision = ArtifactRevisionRecord.__table__
                producer_statement = select(revision.c.job_id).where(
                    tuple_(revision.c.logical_artifact_id, revision.c.revision_id).in_(
                        tuple(sorted(identities))
                    )
                )
                steps = self.observe(
                    "source_steps",
                    select(*step.c).where(step.c.platform_job_id.in_(producer_statement)),
                    len(selected) * 128,
                    ("step_run_id",),
                    ("workflow_id",),
                )
                workflows = tuple(sorted({value[0] for value in steps}))
                self.observe(
                    "source_workflows",
                    select(*workflow.c).where(workflow.c.workflow_id.in_(workflows)),
                    max(1, len(workflows)),
                    ("workflow_id",),
                )
                self.observe(
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

        return tuple(page.members for _cursor, page in pages)


@observe_read_stage(InferenceTransferReadStage.PUBLIC_POPULATION_REVALIDATION)
def observe_public_solution_population_dependencies(
    session: Session,
    scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
    maximum_sources: int,
) -> str:
    observer = PublicSolutionDependencyObserver(session)
    pages = observer.population(scope, maximum_sources)
    return content_sha256({"pages": pages, "dependencies": observer.observations})


@observe_read_stage(InferenceTransferReadStage.PUBLIC_POPULATION_REVALIDATION)
def observe_public_solution_index_dependencies(
    session: Session,
    scope: LocalIndexingSourceReadIntent,
    maximum_sources: int,
    *,
    transaction: SessionTransaction,
) -> str:
    """Same source closure for INDEX, pinned to the caller's exact clean frame."""
    root = session.get_transaction()

    def require_frame() -> None:
        if (
            not isinstance(scope, LocalIndexingSourceReadIntent)
            or root is None
            or session.get_transaction() is not root
            or not root.is_active
            or not transaction.is_active
            or (session.get_nested_transaction() or root) is not transaction
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise ValueError("PUBLIC_SOLUTION_INDEX_TRANSACTION_INVALID")

    require_frame()
    observer = PublicSolutionDependencyObserver(session, index_transaction=transaction)
    pages = observer.population(scope, maximum_sources)
    require_frame()
    return content_sha256({"pages": pages, "dependencies": observer.observations})
