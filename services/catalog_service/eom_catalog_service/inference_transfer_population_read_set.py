"""Fresh bounded relational observations for one already materialized Catalog read.

These derived row fingerprints are not Artifact hashes or permission grants. Every
observation reloads the actual source closure through explicit Core projections;
large JSON and Graph pointer populations never become a second ORM/object cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import get_ident
from typing import TYPE_CHECKING, Any

from eom_catalog_contracts import LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy import Select, Text, and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.knowledge_analysis_sources import (
    MAX_ITEM_SOURCE_RELATION_WORK_UNITS,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    MAX_RETRIEVAL_CANDIDATES,
    KnowledgeRetrievalApplicationService,
    ReadOnlyCandidatePoolScope,
)
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext

if TYPE_CHECKING:
    from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
        InferenceTransferSessionCapture,
    )


@dataclass(frozen=True, slots=True)
class InferenceTransferDependencyObservation:
    group: str
    row_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class InferenceTransferPopulationObservation:
    groups: tuple[InferenceTransferDependencyObservation, ...]


def population_membership_statement(
    scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
) -> Select[tuple[KnowledgeSnapshotAnalysisRecord]]:
    """Bound metadata hints by official eligibility; this query grants no access."""
    association = KnowledgeSnapshotAnalysisRecord
    selection = (
        KnowledgeRetrievalApplicationService.candidate_pool_analysis_statement(
            scope, allow_answer_bearing=True
        )
        .cte("eligible_snapshot_analyses")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    return (
        select(association)
        .join(selection, selection.c.analysis_run_id == association.analysis_run_id)
        .where(
            association.graph_snapshot_revision_id
            == scope.graph_snapshot.graph_snapshot_revision_id,
        )
        .order_by(association.analysis_run_id)
        .limit(scope.maximum_candidates + 1)
        .execution_options(populate_existing=True)
    )


def _invalid() -> InferenceTransferServiceError:
    return InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")


def _observe(
    session: Session,
    group: str,
    statement: Select[Any],
    *,
    maximum: int,
    order: tuple[str, ...],
    retain: tuple[str, ...] = (),
) -> tuple[InferenceTransferDependencyObservation, tuple[tuple[Any, ...], ...]]:
    """Stream fixed-width server digests; retain only explicit dependency IDs.

    PostgreSQL's built-in SHA256 covers the complete selected row, including JSON
    values even when a stored content hash was not changed. Unsupported backends
    fail explicitly; no weaker fingerprint or omitted-field fallback is used.
    """
    current = statement.limit(maximum + 1).subquery("population_observed_row")
    fingerprint = func.sha256(
        func.convert_to(func.row_to_json(current.table_valued()).cast(Text), "UTF8")
    ).label("_row_sha256")
    query = select(*(current.c[key] for key in retain), fingerprint).order_by(
        *(current.c[key] for key in order)
    )
    digest = sha256()
    count = 0
    retained: dict[tuple[Any, ...], None] = {}
    result = session.execute(
        query, execution_options={"stream_results": True, "max_row_buffer": 128}
    ).yield_per(128)
    try:
        for row in result.mappings():
            count += 1
            if count > maximum:
                raise _invalid()
            value = row["_row_sha256"]
            if not isinstance(value, bytes) or len(value) != 32:
                raise _invalid()
            digest.update(value)
            if retain:
                retained[tuple(row[key] for key in retain)] = None
                if len(retained) > PinnedArtifactReadContext.MAX_REVISIONS:
                    raise _invalid()
    finally:
        result.close()
    return (
        InferenceTransferDependencyObservation(group, count, "sha256:" + digest.hexdigest()),
        tuple(retained),
    )


def observe_inference_transfer_population(
    session: Session,
    scope: ReadOnlyCandidatePoolScope,
    *,
    artifact_identities: tuple[tuple[str, str], ...],
    layout_observation_ids: tuple[str, ...] = (),
) -> InferenceTransferPopulationObservation:
    """Observe every original source dependency, not merely the previous Item IDs.

    Identity/policy/Graph authorization and physical member validation stay with
    their existing owners. This operation cannot create an admitted capture.
    """
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
        or not 1 <= scope.maximum_candidates <= 1024
    ):
        raise _invalid()
    maximum = scope.maximum_candidates
    groups = []

    def observe(
        group: str,
        statement: Select[Any],
        *,
        bound: int,
        order: tuple[str, ...],
        retain: tuple[str, ...] = (),
    ) -> tuple[tuple[Any, ...], ...]:
        observation, keys = _observe(
            session, group, statement, maximum=bound, order=order, retain=retain
        )
        groups.append(observation)
        return keys

    graph = KnowledgeGraphSnapshotRecord.__table__
    observe(
        "graph_snapshot",
        select(*graph.c).where(
            graph.c.graph_snapshot_revision_id == scope.graph_snapshot.graph_snapshot_revision_id
        ),
        bound=1,
        order=("graph_snapshot_revision_id",),
    )

    association = KnowledgeSnapshotAnalysisRecord.__table__
    memberships = observe(
        "membership",
        population_membership_statement(scope).with_only_columns(
            *association.c, maintain_column_froms=True
        ),
        bound=maximum,
        order=("analysis_run_id",),
        retain=("analysis_run_id", "source_revision_id"),
    )
    base_ids = tuple(row[0] for row in memberships)
    revision_ids = tuple(sorted({row[1] for row in memberships}))
    revision = ItemRevisionRecord.__table__
    revisions = observe(
        "item_revisions",
        select(
            *revision.c,
            revision.c.metadata_json["source_kind"].astext.label("observed_source_kind"),
            revision.c.metadata_json["extraction_acceptance_id"].astext.label(
                "observed_acceptance_id"
            ),
            revision.c.metadata_json["extraction_result_id"].astext.label("observed_result_id"),
            revision.c.metadata_json["item_proposal_id"].astext.label("observed_proposal_id"),
            revision.c.metadata_json["item_number"].label("observed_item_number"),
        ).where(revision.c.item_revision_id.in_(revision_ids)),
        bound=maximum,
        order=("item_revision_id",),
        retain=(
            "item_id",
            "observed_source_kind",
            "observed_acceptance_id",
            "observed_result_id",
            "observed_proposal_id",
            "observed_item_number",
        ),
    )
    item = ItemRecord.__table__
    observe(
        "items",
        select(item.c.item_id, item.c.lifecycle_state).where(
            item.c.item_id.in_(tuple(sorted({row[0] for row in revisions})))
        ),
        bound=maximum,
        order=("item_id",),
    )
    component = ItemComponentRecord.__table__
    components = observe(
        "components",
        select(*component.c).where(
            component.c.item_revision_id.in_(revision_ids),
            or_(
                and_(component.c.component_type == "ITEM_CONTENT", component.c.ordinal == 0),
                and_(
                    component.c.component_type == "OTHER",
                    component.c.schema_ref == LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF,
                ),
            ),
        ),
        bound=4 * maximum,
        order=("item_component_id",),
        retain=("artifact_id", "artifact_revision_id"),
    )
    pointer, node = KnowledgeNodeSourcePointerRecord.__table__, KnowledgeNodeRecord.__table__
    graph_members = observe(
        "graph_pointers",
        select(
            *pointer.c,
            node.c.node_type,
            node.c.stable_key,
            node.c.label,
            node.c.answer_bearing,
        )
        .join(
            node,
            and_(
                node.c.graph_snapshot_revision_id == pointer.c.graph_snapshot_revision_id,
                node.c.node_id == pointer.c.node_id,
            ),
        )
        .where(
            pointer.c.graph_snapshot_revision_id == scope.graph_snapshot.graph_snapshot_revision_id,
            pointer.c.analysis_run_id.in_(base_ids),
            pointer.c.source_class.in_(scope.source_classes),
        ),
        bound=maximum * MAX_RETRIEVAL_CANDIDATES,
        order=("analysis_run_id", "node_id", "anchor_id", "pointer_id"),
        retain=("source_artifact_id", "artifact_revision_id"),
    )
    run = KnowledgeAnalysisRunRecord.__table__
    runs = observe(
        "base_and_solution_runs",
        select(*run.c).where(
            or_(
                run.c.analysis_run_id.in_(base_ids),
                and_(
                    run.c.predecessor_analysis_run_id.in_(base_ids),
                    run.c.state == "ACCEPTED",
                    run.c.canonical_request["schema_version"].astext
                    == "knowledge-analysis-request/10.0",
                ),
            )
        ),
        bound=3 * maximum,
        order=("analysis_run_id",),
        retain=(
            "accepted_result_artifact_id",
            "accepted_result_artifact_revision_id",
            "proposal_artifact_id",
            "proposal_artifact_revision_id",
        ),
    )
    metadata = tuple(row[1:] for row in revisions)
    for row in metadata:
        if row[0] == "PAST_EXAM" and (
            any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in row[1:4])
            or type(row[4]) is not int
            or row[4] <= 0
        ):
            raise _invalid()
    acceptance_ids = tuple(
        sorted({row[1] for row in metadata if row[0] == "PAST_EXAM" and isinstance(row[1], str)})
    )
    acceptance = LegacyItemExtractionAcceptanceRecord.__table__
    acceptances = observe(
        "extraction_acceptances",
        select(*acceptance.c).where(acceptance.c.acceptance_id.in_(acceptance_ids)),
        bound=maximum,
        order=("acceptance_id",),
        retain=(
            "result_artifact_id",
            "result_artifact_revision_id",
            "acceptance_artifact_id",
            "acceptance_artifact_revision_id",
        ),
    )
    decision_keys = tuple(
        sorted(
            {
                (row[1], row[3], row[4])
                for row in metadata
                if row[0] == "PAST_EXAM"
                and isinstance(row[1], str)
                and isinstance(row[3], str)
                and type(row[4]) is int
            }
        )
    )
    decision = LegacyItemExtractionDecisionRecord.__table__
    observe(
        "extraction_decisions",
        select(*decision.c).where(
            tuple_(
                decision.c.acceptance_id,
                decision.c.item_proposal_id,
                decision.c.item_number,
            ).in_(decision_keys)
        ),
        bound=2 * maximum,
        order=("decision_id",),
    )
    unit_keys = tuple(
        sorted(
            {
                (row[1], row[2])
                for row in metadata
                if row[0] == "PAST_EXAM" and isinstance(row[1], str) and isinstance(row[2], str)
            }
        )
    )
    unit = LegacyItemExtractionBatchWorkUnitRecord.__table__
    units = observe(
        "extraction_units",
        select(*unit.c).where(
            tuple_(unit.c.acceptance_id, unit.c.extraction_result_id).in_(unit_keys),
            unit.c.state == "ACCEPTED",
        ),
        bound=MAX_ITEM_SOURCE_RELATION_WORK_UNITS,
        order=("created_at", "extraction_batch_id", "work_unit_id"),
        retain=("extraction_batch_id", "assessment_source_bundle_revision_id"),
    )
    batch = LegacyItemExtractionBatchRecord.__table__
    batches = observe(
        "extraction_batches",
        select(*batch.c).where(
            batch.c.extraction_batch_id.in_(tuple(sorted({row[0] for row in units})))
        ),
        bound=MAX_ITEM_SOURCE_RELATION_WORK_UNITS,
        order=("extraction_batch_id",),
        retain=("manifest_artifact_id", "manifest_artifact_revision_id"),
    )
    bundle_ids = tuple(sorted({row[1] for row in units}))
    bundle = AssessmentSourceBundleRevisionRecord.__table__
    observe(
        "source_bundles",
        select(
            bundle.c.assessment_source_bundle_revision_id,
            bundle.c.assessment_source_bundle_id,
            bundle.c.bundle_manifest_sha256,
            bundle.c.state,
        ).where(bundle.c.assessment_source_bundle_revision_id.in_(bundle_ids)),
        bound=MAX_ITEM_SOURCE_RELATION_WORK_UNITS,
        order=("assessment_source_bundle_revision_id",),
    )
    layout = AssessmentLayoutObservationRecord.__table__
    layouts = observe(
        "layouts",
        select(*layout.c).where(
            layout.c.assessment_layout_observation_id.in_(layout_observation_ids)
        ),
        bound=PinnedArtifactReadContext.MAX_REVISIONS,
        order=("assessment_layout_observation_id",),
        retain=("artifact_id", "artifact_revision_id"),
    )
    identities = (
        set(artifact_identities)
        | set(components)
        | set(batches)
        | set(layouts)
        | set(graph_members)
    )
    for rows in (runs, acceptances):
        for row in rows:
            for index in (0, 2):
                if row[index] is not None and row[index + 1] is not None:
                    identities.add((row[index], row[index + 1]))
    if len(identities) > PinnedArtifactReadContext.MAX_REVISIONS:
        raise _invalid()
    artifact = ArtifactRecord.__table__
    observe(
        "artifacts",
        select(
            artifact.c.logical_artifact_id,
            artifact.c.job_id,
            artifact.c.artifact_type,
            artifact.c.approved,
        ).where(artifact.c.logical_artifact_id.in_(tuple(sorted({key[0] for key in identities})))),
        bound=PinnedArtifactReadContext.MAX_REVISIONS,
        order=("logical_artifact_id",),
    )
    artifact_revision = ArtifactRevisionRecord.__table__
    artifact_rows = observe(
        "artifact_revisions",
        select(
            artifact_revision.c.logical_artifact_id,
            artifact_revision.c.revision_id,
            artifact_revision.c.job_id,
            artifact_revision.c.content_hash,
            artifact_revision.c.manifest_hash,
            artifact_revision.c.content_bytes,
            artifact_revision.c.nas_path,
            artifact_revision.c.approved,
            artifact_revision.c.manifest,
            artifact_revision.c.result,
        ).where(
            tuple_(artifact_revision.c.logical_artifact_id, artifact_revision.c.revision_id).in_(
                tuple(sorted(identities))
            )
        ),
        bound=PinnedArtifactReadContext.MAX_REVISIONS,
        order=("logical_artifact_id", "revision_id"),
        retain=("job_id",),
    )
    job = JobRecord.__table__
    observe(
        "producer_jobs",
        select(
            job.c.job_id,
            job.c.logical_artifact_id,
            job.c.revision_id,
            job.c.task_type,
            job.c.status,
        ).where(job.c.job_id.in_(tuple(sorted({row[0] for row in artifact_rows})))),
        bound=PinnedArtifactReadContext.MAX_REVISIONS,
        order=("job_id",),
    )
    return InferenceTransferPopulationObservation(tuple(groups))


class InferenceTransferPopulationReadSet:
    """One materialization plus fresh current admission validation on every capture.

    Four capture fences produce five closure observations (initial before/after
    plus three later checks). The snapshot owner also refreshes its existing five
    mutable extraction-metadata batches after BEGIN, before first admission. Those
    five queries are not five further population observations or materializations.
    """

    def __init__(
        self,
        session: Session,
        reader: PinnedArtifactReadContext,
        *,
        operator_id: str,
        request_sha256: str,
    ) -> None:
        reader.require_session(session)
        self._session = session
        self._root = session.get_transaction()
        self._thread_id = get_ident()
        self._reader = reader
        self._operator_id = operator_id
        self._request_sha256 = request_sha256
        self._scope: ReadOnlyCandidatePoolScope | None = None
        self._recipe: ExperimentViewRecipe | None = None
        self._before: InferenceTransferPopulationObservation | None = None
        self._identities: tuple[tuple[str, str], ...] = ()
        self._layout_ids: tuple[str, ...] = ()
        self._capture: InferenceTransferSessionCapture | None = None

    def require_request(
        self,
        session: Session,
        operator_id: str,
        request_sha256: str,
        reader: PinnedArtifactReadContext,
    ) -> None:
        if operator_id != self._operator_id or request_sha256 != self._request_sha256:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        self._require(session, self._scope, self._recipe, reader)

    def _require(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | None,
        recipe: ExperimentViewRecipe | None,
        reader: PinnedArtifactReadContext,
    ) -> None:
        reader.require_session(session)
        if (
            session is not self._session
            or session.get_transaction() is not self._root
            or self._root is None
            or not self._root.is_active
            or session.in_nested_transaction()
            or get_ident() != self._thread_id
            or reader is not self._reader
            or session.new
            or session.dirty
            or session.deleted
            or (scope is not None and scope.requested_by != self._operator_id)
            or (self._scope is not None and (scope != self._scope or recipe != self._recipe))
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")

    def reuse(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope,
        recipe: ExperimentViewRecipe,
        reader: PinnedArtifactReadContext,
    ) -> InferenceTransferSessionCapture | None:
        self._require(session, scope, recipe, reader)
        if self._before is None:
            return None
        if self._capture is None:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        self._revalidate(session, scope, reader)
        return self._capture

    def begin(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope,
        recipe: ExperimentViewRecipe,
        reader: PinnedArtifactReadContext,
        *,
        layout_observation_ids: tuple[str, ...] = (),
    ) -> None:
        self._require(session, scope, recipe, reader)
        if self._before is not None:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        self._scope, self._recipe = scope, recipe
        self._identities = reader.provenance_identities()
        self._layout_ids = layout_observation_ids
        self._before = observe_inference_transfer_population(
            session,
            scope,
            artifact_identities=self._identities,
            layout_observation_ids=self._layout_ids,
        )

    def complete(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope,
        recipe: ExperimentViewRecipe,
        reader: PinnedArtifactReadContext,
        capture: InferenceTransferSessionCapture,
    ) -> None:
        self._require(session, scope, recipe, reader)
        if self._before is None or self._capture is not None or capture.scope != scope:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        self._revalidate(session, scope, reader)
        self._capture = capture

    def _revalidate(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope,
        reader: PinnedArtifactReadContext,
    ) -> None:
        current = observe_inference_transfer_population(
            session,
            scope,
            artifact_identities=self._identities,
            layout_observation_ids=self._layout_ids,
        )
        if current != self._before:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        reader.revalidate_provenance()
