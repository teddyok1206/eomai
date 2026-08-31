"""Read-only SQLAlchemy adapter for stable API projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Never

from eom_api_contracts.common import ArtifactPointer
from eom_api_contracts.content_intakes import (
    ContentIntakeSummary,
    IntakeDetail,
    SourceFileView,
)
from eom_api_contracts.content_packs import (
    ContentPackActivationView,
    ContentPackReleaseView,
)
from eom_api_contracts.curriculum import CurriculumGraphCapabilityView
from eom_api_contracts.deliverables import DeliverableView
from eom_api_contracts.events import EventView
from eom_api_contracts.hwpx import HwpxBuildView
from eom_api_contracts.items import (
    ItemComponentView,
    ItemRelationshipView,
    ItemRevisionView,
    ItemView,
)
from eom_api_contracts.knowledge_analysis import (
    KnowledgeAnalysisBatchRangeView,
    KnowledgeAnalysisBatchView,
    KnowledgeAnalysisCountsView,
    KnowledgeAnalysisRunView,
)
from eom_api_contracts.knowledge_retrieval import (
    EvidenceBundleBudgetView,
    EvidenceBundleView,
)
from eom_api_contracts.usage import UsagePlanView, UsageRecordView
from eom_api_contracts.workflows import (
    WorkflowKnowledgeProvenanceView,
    WorkflowStepView,
    WorkflowView,
)
from eom_catalog_contracts import INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256
from eom_catalog_service.curriculum_graph_structure import (
    integrated_science_curriculum_units,
)
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_graph_models import (
    CurriculumUnitClosureRecord,
    CurriculumUnitRecord,
    EducationRetrievalRequestRecord,
    EvidenceBundleRecord,
    EvidenceBundleRevisionRecord,
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeEventRecord,
    ContentIntakeSourceFileRecord,
    ContentPackActivationRecord,
    ContentPackEventRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
    DeliverableEventRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemComponentRecord,
    ItemEventRecord,
    ItemRecord,
    ItemRelationshipRecord,
    ItemRevisionRecord,
    UsagePlanRecord,
    UsageRecord,
)
from eom_hwpx_manager.models import HwpxApplicationBuildRecord
from eom_identity_service.models import OperatorEventRecord
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisEventRecord,
    KnowledgeAnalysisRunRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow import ResolvedExecutionPlanV3
from eom_workflow_runner.models import (
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.services.hwpx_projection import project_hwpx_build


@dataclass(frozen=True)
class PageResult[ViewT]:
    data: tuple[ViewT, ...]
    next_cursor: str | None
    has_more: bool


class CursorCodec:
    def __init__(self, key: bytes) -> None:
        self._key = key

    def encode(self, resource: str, created_at: datetime, resource_id: str) -> str:
        payload = json.dumps(
            {"r": resource, "t": created_at.isoformat(), "i": resource_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return self._b64(payload + signature)

    def decode(self, cursor: str, resource: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if value["r"] != resource or not isinstance(value["i"], str):
                raise ValueError
            timestamp = datetime.fromisoformat(value["t"])
            if timestamp.tzinfo is None:
                raise ValueError
            return timestamp, value["i"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The pagination cursor is invalid for this resource.",
            ) from exc

    def encode_ordinal(self, resource: str, aggregate_id: str, ordinal: int) -> str:
        payload = json.dumps(
            {"r": resource, "a": aggregate_id, "o": ordinal},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return self._b64(payload + signature)

    def decode_ordinal(self, cursor: str, resource: str, aggregate_id: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            ordinal = value["o"]
            if (
                value["r"] != resource
                or value["a"] != aggregate_id
                or not isinstance(ordinal, int)
                or isinstance(ordinal, bool)
                or ordinal < 0
            ):
                raise ValueError
            return ordinal
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The pagination cursor is invalid for this resource.",
            ) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class QueryAdapter:
    def __init__(self, engine: Engine, cursor_key: bytes) -> None:
        self.sessions = build_session_factory(engine)
        self.cursors = CursorCodec(cursor_key)

    def integrated_science_graph_capability(self) -> CurriculumGraphCapabilityView:
        """Verify the current Graph contains the exact reviewed curriculum hierarchy."""

        expected_units = integrated_science_curriculum_units()
        expected_framework = expected_units[0].framework_revision_id
        expected_unit_rows = {
            (
                unit.curriculum_unit_id,
                unit.node_stable_key,
                unit.framework_revision_id,
                unit.parent_unit_id,
                unit.unit_level,
                unit.ordinal,
            )
            for unit in expected_units
        }
        expected_by_id = {unit.curriculum_unit_id: unit for unit in expected_units}
        expected_closure: set[tuple[str, str, str, int]] = set()
        for unit in expected_units:
            expected_closure.add(
                (
                    unit.framework_revision_id,
                    unit.curriculum_unit_id,
                    unit.curriculum_unit_id,
                    0,
                )
            )
            current = unit
            depth = 0
            while current.parent_unit_id is not None:
                depth += 1
                parent = expected_by_id[current.parent_unit_id]
                expected_closure.add(
                    (
                        unit.framework_revision_id,
                        parent.curriculum_unit_id,
                        unit.curriculum_unit_id,
                        depth,
                    )
                )
                current = parent

        with self.sessions() as session:
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.corpus_key == "integrated-science-textbooks"
                )
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.current_graph_snapshot_revision_id is None
            ):
                return self._unavailable_curriculum_graph("CORPUS_UNAVAILABLE")
            snapshot_id = corpus.current_graph_snapshot_revision_id
            snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
            if (
                snapshot is None
                or snapshot.state != "PUBLISHED"
                or snapshot.graph_id != corpus.graph_id
            ):
                return self._unavailable_curriculum_graph("SNAPSHOT_UNAVAILABLE")
            manifest_artifact = session.get(ArtifactRecord, snapshot.manifest_artifact_id)
            manifest_revision = session.get(
                ArtifactRevisionRecord, snapshot.manifest_artifact_revision_id
            )
            projection_artifact = session.get(ArtifactRecord, snapshot.projection_artifact_id)
            projection_revision = session.get(
                ArtifactRevisionRecord, snapshot.projection_artifact_revision_id
            )
            if (
                manifest_artifact is None
                or manifest_revision is None
                or not manifest_artifact.approved
                or not manifest_revision.approved
                or manifest_revision.logical_artifact_id != snapshot.manifest_artifact_id
                or manifest_revision.content_hash != snapshot.manifest_sha256
                or projection_artifact is None
                or projection_revision is None
                or not projection_artifact.approved
                or not projection_revision.approved
                or projection_revision.logical_artifact_id != snapshot.projection_artifact_id
            ):
                return self._unavailable_curriculum_graph("SNAPSHOT_UNAVAILABLE")
            unit_rows = tuple(
                session.execute(
                    select(CurriculumUnitRecord, KnowledgeNodeRecord)
                    .join(
                        KnowledgeNodeRecord,
                        and_(
                            KnowledgeNodeRecord.graph_snapshot_revision_id
                            == CurriculumUnitRecord.graph_snapshot_revision_id,
                            KnowledgeNodeRecord.node_id == CurriculumUnitRecord.node_id,
                        ),
                    )
                    .where(
                        CurriculumUnitRecord.graph_snapshot_revision_id == snapshot_id,
                        CurriculumUnitRecord.framework_revision_id == expected_framework,
                    )
                ).all()
            )
            closure_rows = tuple(
                session.scalars(
                    select(CurriculumUnitClosureRecord).where(
                        CurriculumUnitClosureRecord.graph_snapshot_revision_id == snapshot_id,
                        CurriculumUnitClosureRecord.framework_revision_id == expected_framework,
                    )
                )
            )
            observed_unit_rows = {
                (
                    unit.curriculum_unit_id,
                    node.stable_key,
                    unit.framework_revision_id,
                    unit.parent_unit_id,
                    unit.unit_level,
                    unit.ordinal,
                )
                for unit, node in unit_rows
            }
            observed_closure = {
                (
                    row.framework_revision_id,
                    row.ancestor_unit_id,
                    row.descendant_unit_id,
                    row.depth,
                )
                for row in closure_rows
            }
            current_snapshot_id = session.scalar(
                select(KnowledgeCorpusRecord.current_graph_snapshot_revision_id).where(
                    KnowledgeCorpusRecord.corpus_id == corpus.corpus_id
                )
            )
            if current_snapshot_id != snapshot_id:
                return self._unavailable_curriculum_graph("CURRENT_POINTER_CHANGED")
            if observed_unit_rows != expected_unit_rows or observed_closure != expected_closure:
                return self._unavailable_curriculum_graph(
                    "CURRICULUM_MAPPING_INCOMPLETE",
                    unit_count=len(unit_rows),
                    closure_count=len(closure_rows),
                )
            return CurriculumGraphCapabilityView(
                outline_sha256=INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
                capability_state="READY",
                graph_grounding_available=True,
                reason="READY",
                graph_snapshot_revision_id=snapshot_id,
                snapshot_sha256=snapshot.snapshot_sha256,
                framework_revision_id=expected_framework,
                unit_count=len(unit_rows),
                closure_count=len(closure_rows),
            )

    @staticmethod
    def _unavailable_curriculum_graph(
        reason: Literal[
            "CORPUS_UNAVAILABLE",
            "SNAPSHOT_UNAVAILABLE",
            "CURRICULUM_MAPPING_INCOMPLETE",
            "CURRENT_POINTER_CHANGED",
        ],
        *,
        unit_count: int = 0,
        closure_count: int = 0,
    ) -> CurriculumGraphCapabilityView:
        return CurriculumGraphCapabilityView(
            outline_sha256=INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
            capability_state="UNAVAILABLE",
            graph_grounding_available=False,
            reason=reason,
            graph_snapshot_revision_id=None,
            snapshot_sha256=None,
            framework_revision_id=None,
            unit_count=unit_count,
            closure_count=closure_count,
        )

    def list_hwpx_builds(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[HwpxBuildView]:
        with self.sessions() as session:
            statement = select(HwpxApplicationBuildRecord)
            if state:
                statement = statement.where(HwpxApplicationBuildRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                HwpxApplicationBuildRecord.created_at,
                HwpxApplicationBuildRecord.build_id,
                "hwpx-build",
                limit,
                cursor,
            )
            return PageResult(
                tuple(project_hwpx_build(row) for row in rows),
                next_cursor,
                more,
            )

    def list_knowledge_analyses(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[KnowledgeAnalysisRunView]:
        with self.sessions() as session:
            statement = select(KnowledgeAnalysisRunRecord)
            if state:
                statement = statement.where(KnowledgeAnalysisRunRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                KnowledgeAnalysisRunRecord.created_at,
                KnowledgeAnalysisRunRecord.analysis_run_id,
                "knowledge-analysis",
                limit,
                cursor,
            )
            return PageResult(
                tuple(self._knowledge_analysis(row) for row in rows), next_cursor, more
            )

    def knowledge_analysis(self, analysis_run_id: str) -> KnowledgeAnalysisRunView:
        with self.sessions() as session:
            row = session.get(KnowledgeAnalysisRunRecord, analysis_run_id)
            if row is None:
                self._not_found("KNOWLEDGE_ANALYSIS_RUN_NOT_FOUND")
            return self._knowledge_analysis(row)

    def knowledge_analysis_events(self, analysis_run_id: str) -> tuple[EventView, ...]:
        with self.sessions() as session:
            if session.get(KnowledgeAnalysisRunRecord, analysis_run_id) is None:
                self._not_found("KNOWLEDGE_ANALYSIS_RUN_NOT_FOUND")
            rows = session.scalars(
                select(KnowledgeAnalysisEventRecord)
                .where(KnowledgeAnalysisEventRecord.analysis_run_id == analysis_run_id)
                .order_by(KnowledgeAnalysisEventRecord.sequence)
            )
            return tuple(
                self._event(
                    "knowledge_analysis",
                    row.analysis_run_id,
                    str(row.event_id),
                    row.event_type,
                    row.prior_state,
                    row.new_state,
                    row.actor_id,
                    row.created_at,
                )
                for row in rows
            )

    def list_knowledge_analysis_batches(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[KnowledgeAnalysisBatchView]:
        with self.sessions() as session:
            statement = select(KnowledgeAnalysisBatchRecord)
            if state:
                statement = statement.where(KnowledgeAnalysisBatchRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                KnowledgeAnalysisBatchRecord.created_at,
                KnowledgeAnalysisBatchRecord.batch_id,
                "knowledge-analysis-batch",
                limit,
                cursor,
            )
            counts = self._knowledge_analysis_batch_counts(
                session, tuple(row.batch_id for row in rows)
            )
            return PageResult(
                tuple(
                    self._knowledge_analysis_batch(
                        row,
                        counts.get(row.batch_id, (0, 0)),
                    )
                    for row in rows
                ),
                next_cursor,
                more,
            )

    def knowledge_analysis_batch(self, batch_id: str) -> KnowledgeAnalysisBatchView:
        with self.sessions() as session:
            row = session.get(KnowledgeAnalysisBatchRecord, batch_id)
            if row is None:
                self._not_found("KNOWLEDGE_ANALYSIS_BATCH_NOT_FOUND")
            counts = self._knowledge_analysis_batch_counts(session, (batch_id,))
            return self._knowledge_analysis_batch(row, counts.get(batch_id, (0, 0)))

    def knowledge_analysis_batch_ranges(
        self,
        batch_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> PageResult[KnowledgeAnalysisBatchRangeView]:
        with self.sessions() as session:
            if session.get(KnowledgeAnalysisBatchRecord, batch_id) is None:
                self._not_found("KNOWLEDGE_ANALYSIS_BATCH_NOT_FOUND")
            statement = select(KnowledgeAnalysisBatchRangeRecord).where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == batch_id
            )
            if cursor:
                ordinal = self.cursors.decode_ordinal(
                    cursor,
                    "knowledge-analysis-batch-range",
                    batch_id,
                )
                statement = statement.where(KnowledgeAnalysisBatchRangeRecord.ordinal > ordinal)
            rows = list(
                session.scalars(
                    statement.order_by(KnowledgeAnalysisBatchRangeRecord.ordinal).limit(limit + 1)
                )
            )
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = (
                self.cursors.encode_ordinal(
                    "knowledge-analysis-batch-range",
                    batch_id,
                    rows[-1].ordinal,
                )
                if more and rows
                else None
            )
            return PageResult(
                tuple(self._knowledge_analysis_batch_range(row) for row in rows),
                next_cursor,
                more,
            )

    def evidence_bundle(self, evidence_bundle_id: str) -> EvidenceBundleView:
        with self.sessions() as session:
            bundle = session.get(EvidenceBundleRecord, evidence_bundle_id)
            if bundle is None or bundle.current_revision_id is None:
                self._not_found("EVIDENCE_BUNDLE_NOT_FOUND")
            revision = session.get(EvidenceBundleRevisionRecord, bundle.current_revision_id)
            request = (
                session.get(EducationRetrievalRequestRecord, revision.retrieval_request_id)
                if revision is not None
                else None
            )
            manifest_artifact = (
                session.get(ArtifactRevisionRecord, revision.manifest_artifact_revision_id)
                if revision is not None
                else None
            )
            context_artifact = (
                session.get(ArtifactRevisionRecord, revision.context_artifact_revision_id)
                if revision is not None
                else None
            )
            if (
                revision is None
                or request is None
                or manifest_artifact is None
                or context_artifact is None
                or revision.evidence_bundle_id != bundle.evidence_bundle_id
                or revision.retrieval_request_id != bundle.retrieval_request_id
                or request.retrieval_request_id != bundle.retrieval_request_id
                or not manifest_artifact.approved
                or manifest_artifact.logical_artifact_id != revision.manifest_artifact_id
                or not context_artifact.approved
                or context_artifact.logical_artifact_id != revision.context_artifact_id
                or context_artifact.content_hash != revision.context_sha256
            ):
                self._not_found("EVIDENCE_BUNDLE_POINTER_INVALID")
            return EvidenceBundleView(
                evidence_bundle_id=bundle.evidence_bundle_id,
                evidence_bundle_revision_id=revision.evidence_bundle_revision_id,
                revision_number=revision.revision_number,
                state=revision.state,  # type: ignore[arg-type]
                retrieval_request_id=request.retrieval_request_id,
                retrieval_request_sha256=request.request_sha256,
                graph_snapshot_revision_id=revision.graph_snapshot_revision_id,
                access_policy_revision_id=revision.access_policy_revision_id,
                requester_permissions_sha256=revision.requester_permissions_sha256,
                context_artifact_id=revision.context_artifact_id,
                context_artifact_revision_id=revision.context_artifact_revision_id,
                context_sha256=revision.context_sha256,
                manifest_artifact_id=revision.manifest_artifact_id,
                manifest_artifact_revision_id=revision.manifest_artifact_revision_id,
                manifest_artifact_sha256=manifest_artifact.content_hash,
                manifest_sha256=revision.manifest_sha256,
                budget=EvidenceBundleBudgetView(
                    document_count=revision.document_count,
                    item_revision_count=revision.item_revision_count,
                    graph_node_count=revision.graph_node_count,
                    claim_count=revision.claim_count,
                    estimated_context_tokens=revision.estimated_context_tokens,
                ),
                created_by_operator_id=revision.created_by_operator_id,
                created_at=revision.created_at,
            )

    def list_intakes(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[ContentIntakeSummary]:
        with self.sessions() as session:
            statement = select(ContentIntakeBatchRecord)
            if state:
                statement = statement.where(ContentIntakeBatchRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                ContentIntakeBatchRecord.created_at,
                ContentIntakeBatchRecord.intake_batch_id,
                "content-intake",
                limit,
                cursor,
            )
            return PageResult(tuple(self._intake(row) for row in rows), next_cursor, more)

    def intake(self, intake_id: str) -> IntakeDetail:
        with self.sessions() as session:
            row = session.get(ContentIntakeBatchRecord, intake_id)
            if row is None:
                self._not_found("CONTENT_INTAKE_NOT_FOUND")
            sources = session.scalars(
                select(ContentIntakeSourceFileRecord)
                .where(ContentIntakeSourceFileRecord.intake_batch_id == intake_id)
                .order_by(ContentIntakeSourceFileRecord.relative_path)
            )
            return IntakeDetail(
                intake=self._intake(row),
                source_files=tuple(self._source(source) for source in sources),
            )

    def intake_events(self, intake_id: str) -> tuple[EventView, ...]:
        with self.sessions() as session:
            rows = session.scalars(
                select(ContentIntakeEventRecord)
                .where(ContentIntakeEventRecord.intake_batch_id == intake_id)
                .order_by(ContentIntakeEventRecord.sequence)
            )
            return tuple(
                self._event(
                    "content_intake",
                    row.intake_batch_id,
                    row.event_id,
                    row.event_type,
                    row.prior_state,
                    row.new_state,
                    row.actor_id,
                    row.created_at,
                )
                for row in rows
            )

    def list_pack_releases(
        self, *, limit: int, cursor: str | None, pack_key: str | None = None
    ) -> PageResult[ContentPackReleaseView]:
        with self.sessions() as session:
            statement = select(ContentPackReleaseRecord, ContentPackRecord).join(
                ContentPackRecord,
                ContentPackRecord.content_pack_id == ContentPackReleaseRecord.content_pack_id,
            )
            if pack_key:
                statement = statement.where(ContentPackRecord.pack_key == pack_key)
            rows, next_cursor, more = self._page_joined(
                session,
                statement,
                ContentPackReleaseRecord.created_at,
                ContentPackReleaseRecord.content_pack_release_id,
                "content-pack-release",
                limit,
                cursor,
            )
            return PageResult(
                tuple(self._pack_release(release, pack) for release, pack in rows),
                next_cursor,
                more,
            )

    def pack_release(self, release_id: str) -> ContentPackReleaseView:
        with self.sessions() as session:
            row = session.execute(
                select(ContentPackReleaseRecord, ContentPackRecord)
                .join(ContentPackRecord)
                .where(ContentPackReleaseRecord.content_pack_release_id == release_id)
            ).one_or_none()
            if row is None:
                self._not_found("CONTENT_PACK_NOT_FOUND")
            return self._pack_release(row[0], row[1])

    def list_activations(
        self, *, active_only: bool = False
    ) -> tuple[ContentPackActivationView, ...]:
        with self.sessions() as session:
            statement = select(ContentPackActivationRecord).order_by(
                ContentPackActivationRecord.activated_at.desc(),
                ContentPackActivationRecord.activation_id,
            )
            if active_only:
                statement = statement.where(ContentPackActivationRecord.active.is_(True))
            return tuple(self._activation(row) for row in session.scalars(statement).all())

    def list_workflows(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[WorkflowView]:
        with self.sessions() as session:
            statement = select(WorkflowInstanceRecord, ResolvedExecutionPlanRecord).outerjoin(
                ResolvedExecutionPlanRecord,
                ResolvedExecutionPlanRecord.workflow_id == WorkflowInstanceRecord.workflow_id,
            )
            if state:
                statement = statement.where(WorkflowInstanceRecord.state == state)
            if cursor:
                timestamp, resource_id = self.cursors.decode(cursor, "workflow")
                statement = statement.where(
                    or_(
                        WorkflowInstanceRecord.created_at < timestamp,
                        and_(
                            WorkflowInstanceRecord.created_at == timestamp,
                            WorkflowInstanceRecord.workflow_id < resource_id,
                        ),
                    )
                )
            rows = list(
                session.execute(
                    statement.order_by(
                        WorkflowInstanceRecord.created_at.desc(),
                        WorkflowInstanceRecord.workflow_id.desc(),
                    ).limit(limit + 1)
                )
            )
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = (
                self.cursors.encode("workflow", rows[-1][0].created_at, rows[-1][0].workflow_id)
                if more and rows
                else None
            )
            return PageResult(
                tuple(self._workflow(workflow, plan) for workflow, plan in rows),
                next_cursor,
                more,
            )

    def workflow(self, workflow_id: str) -> WorkflowView:
        with self.sessions() as session:
            row = session.execute(
                select(WorkflowInstanceRecord, ResolvedExecutionPlanRecord)
                .outerjoin(
                    ResolvedExecutionPlanRecord,
                    ResolvedExecutionPlanRecord.workflow_id == WorkflowInstanceRecord.workflow_id,
                )
                .where(WorkflowInstanceRecord.workflow_id == workflow_id)
            ).one_or_none()
            if row is None:
                self._not_found("WORKFLOW_NOT_FOUND")
            return self._workflow(row[0], row[1])

    def workflow_steps(self, workflow_id: str) -> tuple[WorkflowStepView, ...]:
        with self.sessions() as session:
            self._require(session, WorkflowInstanceRecord, workflow_id, "WORKFLOW_NOT_FOUND")
            rows = session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow_id)
                .order_by(WorkflowStepRunRecord.attempt, WorkflowStepRunRecord.step_run_id)
            )
            return tuple(self._workflow_step(row) for row in rows)

    def workflow_events(self, workflow_id: str) -> tuple[EventView, ...]:
        with self.sessions() as session:
            self._require(session, WorkflowInstanceRecord, workflow_id, "WORKFLOW_NOT_FOUND")
            rows = session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence)
            )
            return tuple(
                self._event(
                    "workflow",
                    row.workflow_id,
                    row.event_id,
                    row.event_type,
                    row.prior_state,
                    row.new_state,
                    row.actor_id,
                    row.created_at,
                )
                for row in rows
            )

    def list_items(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[ItemView]:
        with self.sessions() as session:
            statement = select(ItemRecord)
            if state:
                statement = statement.where(ItemRecord.lifecycle_state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                ItemRecord.created_at,
                ItemRecord.item_id,
                "item",
                limit,
                cursor,
            )
            return PageResult(tuple(self._item(row) for row in rows), next_cursor, more)

    def item(self, item_id: str) -> ItemView:
        with self.sessions() as session:
            row = self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            return self._item(row)

    def item_revisions(self, item_id: str) -> tuple[ItemRevisionView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            rows = session.scalars(
                select(ItemRevisionRecord)
                .where(ItemRevisionRecord.item_id == item_id)
                .order_by(ItemRevisionRecord.revision_number)
            )
            return tuple(self._revision(row) for row in rows)

    def revision(self, revision_id: str) -> ItemRevisionView:
        with self.sessions() as session:
            row = self._require(session, ItemRevisionRecord, revision_id, "ITEM_REVISION_NOT_FOUND")
            return self._revision(row)

    def components(self, revision_id: str) -> tuple[ItemComponentView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRevisionRecord, revision_id, "ITEM_REVISION_NOT_FOUND")
            rows = session.scalars(
                select(ItemComponentRecord)
                .where(ItemComponentRecord.item_revision_id == revision_id)
                .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
            )
            return tuple(self._component(row) for row in rows)

    def relationships(self, item_id: str) -> tuple[ItemRelationshipView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            rows = session.scalars(
                select(ItemRelationshipRecord)
                .where(
                    or_(
                        ItemRelationshipRecord.source_item_id == item_id,
                        ItemRelationshipRecord.target_item_id == item_id,
                    )
                )
                .order_by(ItemRelationshipRecord.created_at)
            )
            return tuple(
                ItemRelationshipView.model_validate(row, from_attributes=True) for row in rows
            )

    def list_deliverables(self) -> tuple[DeliverableView, ...]:
        with self.sessions() as session:
            rows = session.execute(
                select(DeliverableRecord, DeliverableRevisionRecord)
                .outerjoin(
                    DeliverableRevisionRecord,
                    and_(
                        DeliverableRevisionRecord.deliverable_id
                        == DeliverableRecord.deliverable_id,
                        DeliverableRevisionRecord.revision_number == 1,
                    ),
                )
                .order_by(DeliverableRecord.created_at.desc())
                .limit(200)
            )
            return tuple(self._deliverable(row, revision) for row, revision in rows)

    def deliverable(self, deliverable_id: str) -> DeliverableView:
        with self.sessions() as session:
            row = session.execute(
                select(DeliverableRecord, DeliverableRevisionRecord)
                .outerjoin(
                    DeliverableRevisionRecord,
                    DeliverableRevisionRecord.deliverable_id == DeliverableRecord.deliverable_id,
                )
                .where(DeliverableRecord.deliverable_id == deliverable_id)
                .order_by(DeliverableRevisionRecord.revision_number.desc())
                .limit(1)
            ).one_or_none()
            if row is None:
                self._not_found("DELIVERABLE_NOT_FOUND")
            return self._deliverable(row[0], row[1])

    def list_usage_plans(self) -> tuple[UsagePlanView, ...]:
        with self.sessions() as session:
            return tuple(
                self._usage_plan(row)
                for row in session.scalars(
                    select(UsagePlanRecord).order_by(UsagePlanRecord.created_at.desc()).limit(200)
                )
            )

    def usage_plan(self, plan_id: str) -> UsagePlanView:
        with self.sessions() as session:
            return self._usage_plan(
                self._require(session, UsagePlanRecord, plan_id, "USAGE_PLAN_NOT_FOUND")
            )

    def list_usage_records(self, *, item_id: str | None = None) -> tuple[UsageRecordView, ...]:
        with self.sessions() as session:
            statement = select(UsageRecord).order_by(UsageRecord.recorded_at.desc()).limit(200)
            if item_id:
                statement = statement.where(UsageRecord.item_id == item_id)
            return tuple(self._usage_record(row) for row in session.scalars(statement))

    def usage_record(self, record_id: str) -> UsageRecordView:
        with self.sessions() as session:
            return self._usage_record(
                self._require(session, UsageRecord, record_id, "USAGE_RECORD_NOT_FOUND")
            )

    def events(self, *, limit: int) -> tuple[EventView, ...]:
        projected: list[tuple[int, EventView]] = []
        with self.sessions() as session:
            sources: tuple[tuple[int, str, Any, Any, Any], ...] = (
                (0, "workflow", WorkflowEventRecord, WorkflowEventRecord.workflow_id, None),
                (1, "item", ItemEventRecord, ItemEventRecord.item_id, None),
                (
                    2,
                    "content_intake",
                    ContentIntakeEventRecord,
                    ContentIntakeEventRecord.intake_batch_id,
                    None,
                ),
                (
                    3,
                    "content_pack",
                    ContentPackEventRecord,
                    ContentPackEventRecord.content_pack_release_id,
                    None,
                ),
                (4, "operator", OperatorEventRecord, OperatorEventRecord.operator_id, None),
                (
                    5,
                    "deliverable",
                    DeliverableEventRecord,
                    DeliverableEventRecord.deliverable_id,
                    None,
                ),
            )
            for priority, aggregate_type, model, aggregate_column, _ in sources:
                rows = session.scalars(select(model).order_by(model.created_at.desc()).limit(limit))
                for row in rows:
                    projected.append(
                        (
                            priority,
                            self._event(
                                aggregate_type,
                                getattr(row, aggregate_column.key),
                                getattr(row, "event_id", getattr(row, "operator_event_id", "")),
                                row.event_type,
                                getattr(row, "prior_state", None),
                                getattr(row, "new_state", None),
                                row.actor_id,
                                row.created_at,
                            ),
                        )
                    )
        projected.sort(key=lambda pair: (pair[1].created_at, pair[0], pair[1].event_id))
        return tuple(view for _, view in projected[-limit:])

    def _page(
        self,
        session: Session,
        statement: Select[tuple[Any]],
        time_column: Any,
        id_column: Any,
        resource: str,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None, bool]:
        if cursor:
            timestamp, resource_id = self.cursors.decode(cursor, resource)
            statement = statement.where(
                or_(
                    time_column < timestamp, and_(time_column == timestamp, id_column < resource_id)
                )
            )
        rows = list(
            session.scalars(
                statement.order_by(time_column.desc(), id_column.desc()).limit(limit + 1)
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self.cursors.encode(
                resource, getattr(rows[-1], time_column.key), getattr(rows[-1], id_column.key)
            )
            if more and rows
            else None
        )
        return rows, next_cursor, more

    def _page_joined(
        self,
        session: Session,
        statement: Select[Any],
        time_column: Any,
        id_column: Any,
        resource: str,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None, bool]:
        if cursor:
            timestamp, resource_id = self.cursors.decode(cursor, resource)
            statement = statement.where(
                or_(
                    time_column < timestamp, and_(time_column == timestamp, id_column < resource_id)
                )
            )
        rows = list(
            session.execute(
                statement.order_by(time_column.desc(), id_column.desc()).limit(limit + 1)
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self.cursors.encode(
                resource, rows[-1][0].created_at, rows[-1][0].content_pack_release_id
            )
            if more and rows
            else None
        )
        return rows, next_cursor, more

    @staticmethod
    def _pointer(
        artifact_id: str,
        revision_id: str,
        sha256: str,
        schema_ref: str,
        media_type: str,
        artifact_member: str | None = None,
    ) -> ArtifactPointer:
        return ArtifactPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            artifact_member=artifact_member,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            logical_uri=f"nas://artifacts/{artifact_id}/{revision_id}",
        )

    def _intake(self, row: ContentIntakeBatchRecord) -> ContentIntakeSummary:
        pointer = None
        if (
            row.source_manifest_artifact_id
            and row.source_manifest_artifact_revision_id
            and row.source_manifest_sha256
        ):
            pointer = self._pointer(
                row.source_manifest_artifact_id,
                row.source_manifest_artifact_revision_id,
                row.source_manifest_sha256,
                "urn:eom:schema:content-intake-manifest:1.0",
                "application/json",
            )
        return ContentIntakeSummary(
            intake_batch_id=row.intake_batch_id,
            batch_name=row.batch_name,
            state=row.state,
            purpose=row.purpose,
            received_by=row.received_by,
            resource_version=row.lock_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            source_manifest=pointer,
        )

    def _source(self, row: ContentIntakeSourceFileRecord) -> SourceFileView:
        return SourceFileView(
            source_file_id=row.source_file_id,
            filename=row.original_filename,
            media_type=row.media_type,
            size=row.size_bytes,
            sha256=row.sha256,
            artifact=self._pointer(
                row.artifact_id,
                row.artifact_revision_id,
                row.sha256,
                "urn:eom:schema:content-intake-source:1.0",
                row.media_type,
                row.relative_path,
            ),
            declared_role=row.declared_role,
        )

    def _pack_release(
        self, row: ContentPackReleaseRecord, pack: ContentPackRecord
    ) -> ContentPackReleaseView:
        return ContentPackReleaseView(
            content_pack_release_id=row.content_pack_release_id,
            content_pack_id=row.content_pack_id,
            pack_key=pack.pack_key,
            version=row.version,
            schema_version=row.schema_version,
            state=row.state,
            bundle=self._pointer(
                row.bundle_artifact_id,
                row.bundle_artifact_revision_id,
                row.bundle_sha256,
                "urn:eom:schema:content-pack-manifest:" + row.schema_version,
                "application/zip",
            ),
            resource_version=row.lock_version,
            created_at=row.created_at,
            released_at=row.released_at,
        )

    @staticmethod
    def _activation(row: ContentPackActivationRecord) -> ContentPackActivationView:
        return ContentPackActivationView(
            activation_id=row.activation_id,
            environment=row.environment,
            pack_key=row.pack_key,
            content_pack_release_id=row.content_pack_release_id,
            active=row.active,
            activated_by=row.activated_by,
            activated_at=row.activated_at,
            resource_version=row.lock_version,
        )

    @classmethod
    def _workflow(
        cls,
        row: WorkflowInstanceRecord,
        plan: ResolvedExecutionPlanRecord | None = None,
    ) -> WorkflowView:
        return WorkflowView(
            workflow_id=row.workflow_id,
            definition_key=row.definition_key,
            definition_version=row.definition_version,
            state=row.state,
            stage=row.stage,
            current_step_key=row.current_step_key,
            resource_version=row.lock_version,
            rework_cycle_count=row.rework_cycle_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
            failure_code=row.failure_code,
            knowledge_provenance=cls._knowledge_provenance(row, plan),
        )

    @staticmethod
    def _knowledge_provenance(
        workflow: WorkflowInstanceRecord,
        record: ResolvedExecutionPlanRecord | None,
    ) -> WorkflowKnowledgeProvenanceView | None:
        if record is None or record.canonical_document.get("schema_version") != (
            "resolved-execution-plan/3.0"
        ):
            return None
        try:
            plan = ResolvedExecutionPlanV3.model_validate(record.canonical_document)
        except ValueError as exc:
            raise ApiError(
                500,
                "WORKFLOW_KNOWLEDGE_PROVENANCE_INVALID",
                "Workflow provenance invalid",
                "The pinned knowledge execution plan failed contract validation.",
            ) from exc
        if (
            plan.plan_id != record.plan_id
            or plan.workflow_id != workflow.workflow_id
            or plan.workflow_id != record.workflow_id
            or plan.preset_id != record.preset_id
            or plan.preset_revision_id != record.preset_revision_id
            or plan.capacity_policy_revision_id != record.capacity_policy_revision_id
            or plan.graph_snapshot.graph_snapshot_revision_id != record.graph_snapshot_revision_id
            or plan.evidence_bundle_revision_id != record.evidence_bundle_revision_id
            or plan.plan_sha256 != record.plan_sha256
            or plan.resolved_at != record.resolved_at
        ):
            raise ApiError(
                500,
                "WORKFLOW_KNOWLEDGE_PROVENANCE_INVALID",
                "Workflow provenance invalid",
                "The workflow and pinned knowledge execution plan do not agree.",
            )
        requirement = plan.retrieval_requirement
        return WorkflowKnowledgeProvenanceView(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            preset_revision_id=plan.preset_revision_id,
            corpus_key=requirement.corpus_key,
            query_kind=requirement.query_kind,
            curriculum_root_key=requirement.curriculum_root_key,
            required_item_elements=requirement.required_item_elements,
            source_classes=requirement.source_classes,
            graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
            evidence_bundle_revision_id=plan.evidence_bundle_revision_id,
            retrieval_request_id=plan.retrieval_request_id,
            retrieval_request_sha256=plan.retrieval_request_sha256,
            access_policy_revision_id=plan.access_policy_revision_id,
            access_policy_sha256=plan.access_policy_sha256,
            evidence_manifest_sha256=plan.evidence_manifest_sha256,
            resolved_at=plan.resolved_at,
        )

    @staticmethod
    def _knowledge_analysis(row: KnowledgeAnalysisRunRecord) -> KnowledgeAnalysisRunView:
        return KnowledgeAnalysisRunView(
            analysis_run_id=row.analysis_run_id,
            analysis_request_id=row.analysis_request_id,
            request_sha256=row.request_sha256,
            predecessor_analysis_run_id=row.predecessor_analysis_run_id,
            source_kind=row.source_kind,  # type: ignore[arg-type]
            source_revision_id=row.source_revision_id,
            source_artifact_id=row.source_artifact_id,
            source_artifact_revision_id=row.source_artifact_revision_id,
            source_sha256=row.source_sha256,
            workflow_id=row.workflow_id,
            plan_id=row.plan_id,
            platform_job_id=row.platform_job_id,
            preset_id=row.preset_id,
            preset_revision_id=row.preset_revision_id,
            risk_policy_revision_id=row.risk_policy_revision_id,
            risk_policy_sha256=row.risk_policy_sha256,
            state=row.state,  # type: ignore[arg-type]
            proposal_artifact_id=row.proposal_artifact_id,
            proposal_artifact_revision_id=row.proposal_artifact_revision_id,
            proposal_content_set_sha256=row.proposal_content_set_sha256,
            accepted_result_artifact_id=row.accepted_result_artifact_id,
            accepted_result_artifact_revision_id=row.accepted_result_artifact_revision_id,
            accepted_result_sha256=row.accepted_result_sha256,
            counts=KnowledgeAnalysisCountsView(
                anchors=row.anchor_count,
                nodes=row.node_count,
                edges=row.edge_count,
                claims=row.claim_count,
                component_observations=row.component_count,
                ambiguities=row.ambiguity_count,
            ),
            resource_version=row.lock_version,
            created_by_operator_id=row.created_by_operator_id,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_code=row.error_code,
        )

    @staticmethod
    def _knowledge_analysis_batch_counts(
        session: Session,
        batch_ids: tuple[str, ...],
    ) -> dict[str, tuple[int, int]]:
        if not batch_ids:
            return {}
        rows = session.execute(
            select(
                KnowledgeAnalysisBatchRangeRecord.batch_id,
                func.count().filter(KnowledgeAnalysisBatchRangeRecord.state == "ACCEPTED"),
                func.count().filter(KnowledgeAnalysisBatchRangeRecord.state == "FAILED"),
            )
            .where(KnowledgeAnalysisBatchRangeRecord.batch_id.in_(batch_ids))
            .group_by(KnowledgeAnalysisBatchRangeRecord.batch_id)
        )
        return {
            batch_id: (int(accepted_count), int(failed_count))
            for batch_id, accepted_count, failed_count in rows
        }

    @staticmethod
    def _knowledge_analysis_batch(
        row: KnowledgeAnalysisBatchRecord,
        counts: tuple[int, int],
    ) -> KnowledgeAnalysisBatchView:
        return KnowledgeAnalysisBatchView(
            batch_id=row.batch_id,
            request_sha256=row.request_sha256,
            preset_id=row.preset_id,
            preset_revision_id=row.preset_revision_id,
            preset_sha256=row.preset_sha256,
            risk_policy_revision_id=row.risk_policy_revision_id,
            risk_policy_sha256=row.risk_policy_sha256,
            general_knowledge_mode=row.general_knowledge_mode,  # type: ignore[arg-type]
            review_policy=row.review_policy,  # type: ignore[arg-type]
            range_failure_policy=row.range_failure_policy,  # type: ignore[arg-type]
            scheduling_mode=row.scheduling_mode,  # type: ignore[arg-type]
            max_in_flight=row.max_in_flight,  # type: ignore[arg-type]
            authorized_by_operator_id=row.authorized_by_operator_id,
            authorized_at=row.authorized_at,
            state=row.state,  # type: ignore[arg-type]
            total_range_count=row.total_range_count,
            accepted_range_count=counts[0],
            failed_range_count=counts[1],
            failure_code=row.failure_code,
            resource_version=row.resource_version,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _knowledge_analysis_batch_range(
        row: KnowledgeAnalysisBatchRangeRecord,
    ) -> KnowledgeAnalysisBatchRangeView:
        return KnowledgeAnalysisBatchRangeView(
            range_id=row.range_id,
            batch_id=row.batch_id,
            ordinal=row.ordinal,
            document_id=row.document_id,
            document_revision_id=row.document_revision_id,
            first_physical_page=row.first_physical_page,
            last_physical_page=row.last_physical_page,
            curriculum_unit_keys=tuple(row.curriculum_unit_keys),
            source_artifact_id=row.source_artifact_id,
            source_artifact_revision_id=row.source_artifact_revision_id,
            source_sha256=row.source_sha256,
            source_media_type=row.source_media_type,  # type: ignore[arg-type]
            source_schema_ref=row.source_schema_ref,  # type: ignore[arg-type]
            analysis_artifact_id=row.analysis_artifact_id,
            analysis_artifact_revision_id=row.analysis_artifact_revision_id,
            analysis_manifest_sha256=row.analysis_manifest_sha256,
            analysis_media_type=row.analysis_media_type,  # type: ignore[arg-type]
            analysis_schema_ref=row.analysis_schema_ref,  # type: ignore[arg-type]
            rights_artifact_id=row.rights_artifact_id,
            rights_artifact_revision_id=row.rights_artifact_revision_id,
            rights_attestation_sha256=row.rights_attestation_sha256,
            rights_media_type=row.rights_media_type,  # type: ignore[arg-type]
            rights_schema_ref=row.rights_schema_ref,  # type: ignore[arg-type]
            execution_mode=row.execution_mode,  # type: ignore[arg-type]
            predecessor_analysis_run_id=row.predecessor_analysis_run_id,
            reuse_accepted_analysis_run_id=row.reuse_accepted_analysis_run_id,
            analysis_run_id=row.analysis_run_id,
            state=row.state,  # type: ignore[arg-type]
            submission_attempts=row.submission_attempts,
            error_code=row.error_code,
            resource_version=row.resource_version,
            created_at=row.created_at,
            submitted_at=row.submitted_at,
            completed_at=row.completed_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _workflow_step(row: WorkflowStepRunRecord) -> WorkflowStepView:
        return WorkflowStepView.model_validate(row, from_attributes=True)

    @staticmethod
    def _item(row: ItemRecord) -> ItemView:
        return ItemView(
            item_id=row.item_id,
            human_reference_code=row.human_reference_code,
            lifecycle_state=row.lifecycle_state,
            current_revision_id=row.current_revision_id,
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    def _revision(self, row: ItemRevisionRecord) -> ItemRevisionView:
        return ItemRevisionView(
            item_revision_id=row.item_revision_id,
            item_id=row.item_id,
            revision_number=row.revision_number,
            revision_state=row.revision_state,
            content_pack_release_id=row.content_pack_release_id,
            workflow_id=row.workflow_id,
            item_type_key=row.item_type_key,
            manifest=self._pointer(
                row.manifest_artifact_id,
                row.manifest_artifact_revision_id,
                row.manifest_sha256,
                "urn:eom:schema:item-manifest:1.0",
                "application/json",
            ),
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    def _component(self, row: ItemComponentRecord) -> ItemComponentView:
        return ItemComponentView(
            item_component_id=row.item_component_id,
            item_revision_id=row.item_revision_id,
            component_type=row.component_type,
            ordinal=row.ordinal,
            logical_name=row.logical_name,
            required=row.required,
            artifact=self._pointer(
                row.artifact_id,
                row.artifact_revision_id,
                row.sha256,
                row.schema_ref,
                row.media_type,
            ),
        )

    @staticmethod
    def _deliverable(
        row: DeliverableRecord, revision: DeliverableRevisionRecord | None
    ) -> DeliverableView:
        return DeliverableView(
            deliverable_id=row.deliverable_id,
            deliverable_key=row.deliverable_key,
            deliverable_type=row.deliverable_type,
            title=row.title,
            edition=row.edition,
            lifecycle_state=row.lifecycle_state,
            deliverable_revision_id=revision.deliverable_revision_id if revision else None,
            revision_number=revision.revision_number if revision else None,
            created_at=row.created_at,
        )

    @staticmethod
    def _usage_plan(row: UsagePlanRecord) -> UsagePlanView:
        return UsagePlanView(
            usage_plan_id=row.usage_plan_id,
            item_id=row.item_id,
            preferred_item_revision_id=row.preferred_item_revision_id,
            deliverable_id=row.deliverable_id,
            deliverable_revision_id=row.deliverable_revision_id,
            planned_section=row.planned_section,
            planned_sequence=row.planned_sequence,
            planned_points=row.planned_points,
            planned_role=row.planned_role,
            status=row.status,
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    @staticmethod
    def _usage_record(row: UsageRecord) -> UsageRecordView:
        return UsageRecordView.model_validate(row, from_attributes=True)

    @staticmethod
    def _event(
        aggregate_type: str,
        aggregate_id: str,
        event_id: int | str,
        event_type: str,
        prior_state: str | None,
        new_state: str | None,
        actor_id: str,
        created_at: datetime,
    ) -> EventView:
        return EventView(
            event_id=f"{aggregate_type}:{event_id}",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            prior_state=prior_state,
            new_state=new_state,
            actor_id=actor_id,
            created_at=created_at,
            summary=event_type.replace("_", " ").title(),
        )

    @staticmethod
    def _require(session: Session, model: Any, identifier: str, code: str) -> Any:
        row = session.get(model, identifier)
        if row is None:
            QueryAdapter._not_found(code)
        return row

    @staticmethod
    def _not_found(code: str) -> Never:
        raise ApiError(404, code, "Resource not found", "The requested resource does not exist.")
