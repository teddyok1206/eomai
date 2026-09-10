"""PostgreSQL and NAS adapter for immutable mock-exam planning candidates."""

from __future__ import annotations

import json
import os
import stat
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Never, cast

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V3_SCHEMA_REF,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    CurriculumUnitBindingV2,
    MockExamAssemblyCohortV1,
    MockExamAssemblyPolicyV1,
    MockExamContentPointerContract,
    MockExamContentPointerV1,
    MockExamContentPointerV2,
    MockExamPlanningCandidateContract,
    MockExamPlanningCandidateV1,
    MockExamPlanningCandidateV2,
    MockExamRatingPolicyV1,
    MockExamReviewPointerV1,
    MockExamUsageSnapshotV1,
    validate_contract,
)
from eom_catalog_contracts.item_review import (
    MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
    MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA_REF,
    MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA_REF,
    MockExamItemReviewDecisionV1,
    MockExamItemReviewDecisionV2,
    MockExamItemReviewDecisionV3,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    classify_content_team_mock_exam_material_profile,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import and_, literal, select
from sqlalchemy.orm import Session

from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord,
    CurriculumUnitRecord,
    KnowledgeEdgeRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.legacy_usage_models import UsageRecordV1Record
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemRecord,
    ItemReviewRecord,
    ItemRevisionRecord,
    UsageRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_PLANNING_CANDIDATES = 5_000
MAX_ITEM_MANIFEST_BYTES = 1_048_576
MAX_ITEM_CONTENT_BYTES = 2_097_152
MAX_EDITORIAL_MARKDOWN_BYTES = 2_097_152
MAX_REVIEW_BYTES = 2_097_152

_CONTENT_TEAM_V2_SCHEMA_REFS = frozenset(
    {
        ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
        "eom://schemas/item-registry/assessment-item-content-v2",
    }
)
_CONTENT_TEAM_V3_SCHEMA_REFS = frozenset(
    {
        ASSESSMENT_ITEM_CONTENT_V3_SCHEMA_REF,
        "eom://schemas/item-registry/assessment-item-content-v3",
    }
)
_CONTENT_TEAM_SCHEMA_REFS = _CONTENT_TEAM_V2_SCHEMA_REFS | _CONTENT_TEAM_V3_SCHEMA_REFS


class MockExamCandidateResolutionError(RuntimeError):
    """Stable pointer-resolution failure at the infrastructure boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MockExamPlanningInputs:
    resolved_candidate_count: int
    candidates: tuple[MockExamPlanningCandidateContract, ...]
    usage_snapshot: MockExamUsageSnapshotV1


@dataclass(frozen=True)
class _StructuralCandidate:
    analysis: KnowledgeSnapshotAnalysisRecord
    node: KnowledgeNodeRecord
    revision: ItemRevisionRecord
    item: ItemRecord
    component: ItemComponentRecord
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    occurrence: AssessmentItemOccurrenceReferenceRecord | None
    curriculum_unit_keys: tuple[str, ...]
    large_unit_key: str


@dataclass(frozen=True)
class _CandidateContent:
    pointer: MockExamContentPointerContract
    value: AssessmentItemContentV2 | AssessmentItemContentV3


class MockExamCandidateRepository:
    """Resolve Graph candidates through bulk key lookups and bounded member reads.

    The dominant operations are snapshot-local key lookup, membership and immutable-history
    aggregation. General SQL queries are bounded to 5,000 revisions; an exact cohort adds an
    indexed 25-ID ``IN`` filter and a 26-row ambiguity bound. Maps and sets keep all in-memory joins
    O(n). Artifact bytes are materialized only at the validation boundary.
    """

    def __init__(self, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()

    def resolve(
        self,
        session: Session,
        *,
        graph_snapshot_revision_id: str,
        policy: MockExamAssemblyPolicyV1,
        rating_policy: MockExamRatingPolicyV1,
        planned_at: datetime,
        cohort: MockExamAssemblyCohortV1 | None = None,
    ) -> MockExamPlanningInputs:
        if planned_at.tzinfo is None or planned_at.utcoffset() is None:
            self._fail("ASSEMBLY_PLANNING_TIME_INVALID", "planning time must be timezone-aware")
        cohort_revision_ids = (
            tuple(member.item_revision_id for member in cohort.members)
            if cohort is not None
            else None
        )
        structural = self._structural_candidates(
            session,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            policy=policy,
            cohort_revision_ids=cohort_revision_ids,
        )
        structural_by_revision = {row.revision.item_revision_id: row for row in structural}
        if cohort_revision_ids is not None and set(structural_by_revision) != set(
            cohort_revision_ids
        ):
            self._fail(
                "ASSEMBLY_COHORT_MEMBER_NOT_FOUND",
                "every cohort Item revision must resolve in the pinned published Graph",
            )
        # Exact cohorts intentionally resolve immutable revisions. ItemRecord.current_revision_id
        # may advance after Graph publication; lifecycle, revision state, Graph, artifacts, and
        # the pinned rating are still validated below before the revision can be assembled.
        latest_reviews = self._latest_reviews(
            session,
            revision_ids=tuple(row.revision.item_revision_id for row in structural),
        )
        if cohort_revision_ids is None:
            rated_rows = tuple(
                (row, review)
                for row in structural
                if (review := latest_reviews.get(row.revision.item_revision_id)) is not None
                and review.decision == rating_policy.review_decision
                and review.severity_summary.get(rating_policy.rating_field)
                in rating_policy.eligible_ratings
            )
        else:
            rated_by_revision = {
                revision_id: review
                for revision_id in cohort_revision_ids
                if (review := latest_reviews.get(revision_id)) is not None
                and review.decision == rating_policy.review_decision
                and review.severity_summary.get(rating_policy.rating_field)
                in rating_policy.eligible_ratings
            }
            if set(rated_by_revision) != set(cohort_revision_ids):
                self._fail(
                    "ASSEMBLY_COHORT_MEMBER_NOT_RATED",
                    "every cohort Item revision must resolve under the pinned rating policy",
                )
            rated_rows = tuple(
                (structural_by_revision[revision_id], rated_by_revision[revision_id])
                for revision_id in cohort_revision_ids
            )
        artifacts, revisions = self._validate_artifact_pointers(session, rated_rows)
        usage_by_revision, usage_snapshot = self._usage_snapshot(
            session,
            revision_ids=tuple(row.revision.item_revision_id for row, _review in rated_rows),
            captured_at=planned_at,
        )
        candidates: list[MockExamPlanningCandidateContract] = []
        for row, review in rated_rows:
            content = self._load_candidate_content(
                row,
                artifacts=artifacts,
                revisions=revisions,
            )
            usage = usage_by_revision[row.revision.item_revision_id]
            final_rating = review.severity_summary[rating_policy.rating_field]
            candidate_values = {
                "item_id": row.item.item_id,
                "item_revision_id": row.revision.item_revision_id,
                "item_manifest_sha256": row.revision.manifest_sha256,
                "item_current_revision": (
                    row.item.current_revision_id == row.revision.item_revision_id
                ),
                "graph_item_node_id": row.node.node_id,
                "graph_analysis_run_id": row.analysis.analysis_run_id,
                "graph_source_class": row.source_class,
                "graph_occurrence_placement_node_id": (
                    row.occurrence.placement_node_id if row.occurrence is not None else None
                ),
                "curriculum_unit_keys": row.curriculum_unit_keys,
                "large_unit_key": row.large_unit_key,
                "item_type_key": row.revision.item_type_key,
                "difficulty_band": row.revision.difficulty_band,
                "is_inquiry": content.value.inquiry is not None,
                "material_profile": classify_content_team_mock_exam_material_profile(content.value),
                "source_score_display": content.value.score_display,
                "content": content.pointer.model_dump(mode="json"),
                "review": MockExamReviewPointerV1(
                    item_review_record_id=review.item_review_record_id,
                    review_artifact_id=review.review_artifact_id,
                    review_artifact_revision_id=review.review_artifact_revision_id,
                    review_sha256=review.review_sha256,
                    decision="APPROVE",
                    final_rating=cast(Literal["A", "B", "C"], final_rating),
                ).model_dump(mode="json"),
                "usage_count": usage[0],
                "latest_usage_at": usage[1],
                "usage_fingerprint_sha256": usage[2],
            }
            if isinstance(content.value, AssessmentItemContentV3):
                candidates.append(MockExamPlanningCandidateV2.model_validate(candidate_values))
            else:
                candidates.append(MockExamPlanningCandidateV1.model_validate(candidate_values))
        return MockExamPlanningInputs(
            resolved_candidate_count=len(structural),
            candidates=(
                tuple(candidates)
                if cohort_revision_ids is not None
                else tuple(sorted(candidates, key=lambda row: row.item_revision_id))
            ),
            usage_snapshot=usage_snapshot,
        )

    def _structural_candidates(
        self,
        session: Session,
        *,
        graph_snapshot_revision_id: str,
        policy: MockExamAssemblyPolicyV1,
        cohort_revision_ids: tuple[str, ...] | None = None,
    ) -> tuple[_StructuralCandidate, ...]:
        source_pointer_exists = (
            select(literal(1))
            .select_from(KnowledgeNodeSourcePointerRecord)
            .where(
                KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id
                == graph_snapshot_revision_id,
                KnowledgeNodeSourcePointerRecord.node_id == KnowledgeNodeRecord.node_id,
                KnowledgeNodeSourcePointerRecord.analysis_run_id
                == KnowledgeSnapshotAnalysisRecord.analysis_run_id,
                KnowledgeNodeSourcePointerRecord.source_revision_id
                == KnowledgeSnapshotAnalysisRecord.source_revision_id,
            )
            .exists()
        )
        conditions = [
            KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
            == graph_snapshot_revision_id,
            KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
            source_pointer_exists,
            ItemRecord.lifecycle_state == "ACTIVE",
            ItemRevisionRecord.revision_state.in_(policy.eligible_item_revision_states),
            ItemComponentRecord.media_type == ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            ItemComponentRecord.schema_ref.in_(_CONTENT_TEAM_SCHEMA_REFS),
        ]
        if cohort_revision_ids is not None:
            conditions.append(ItemRevisionRecord.item_revision_id.in_(cohort_revision_ids))
        candidate_limit = (
            len(cohort_revision_ids) + 1
            if cohort_revision_ids is not None
            else MAX_PLANNING_CANDIDATES + 1
        )
        rows = tuple(
            session.execute(
                select(
                    KnowledgeSnapshotAnalysisRecord,
                    KnowledgeNodeRecord,
                    ItemRevisionRecord,
                    ItemRecord,
                    ItemComponentRecord,
                )
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeSnapshotAnalysisRecord.source_revision_id,
                )
                .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
                .join(
                    KnowledgeNodeRecord,
                    and_(
                        KnowledgeNodeRecord.graph_snapshot_revision_id
                        == graph_snapshot_revision_id,
                        KnowledgeNodeRecord.node_type == "ITEM_REVISION",
                        KnowledgeNodeRecord.stable_key
                        == literal("item-revision:") + ItemRevisionRecord.item_revision_id,
                    ),
                )
                .join(
                    ItemComponentRecord,
                    and_(
                        ItemComponentRecord.item_revision_id == ItemRevisionRecord.item_revision_id,
                        ItemComponentRecord.component_type == "ITEM_CONTENT",
                        ItemComponentRecord.ordinal == 0,
                    ),
                )
                .where(*conditions)
                .order_by(
                    ItemRevisionRecord.item_revision_id,
                    KnowledgeSnapshotAnalysisRecord.analysis_run_id,
                    KnowledgeNodeRecord.node_id,
                )
                .limit(candidate_limit)
            ).all()
        )
        revision_ids = [row[2].item_revision_id for row in rows]
        if len(revision_ids) != len(set(revision_ids)):
            self._fail(
                "ASSEMBLY_GRAPH_ITEM_AMBIGUOUS",
                "a Graph snapshot has multiple planning rows for one Item revision",
            )
        if len(rows) >= candidate_limit:
            self._fail(
                "ASSEMBLY_CANDIDATE_LIMIT_EXCEEDED",
                "planning candidate set exceeds its reviewed bound",
            )
        run_ids = {row[0].analysis_run_id for row in rows}
        node_ids = {row[1].node_id for row in rows}
        allowed_pointer_keys = {
            (row[0].analysis_run_id, row[1].node_id, row[2].item_revision_id) for row in rows
        }
        classes_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        if run_ids and node_ids:
            for pointer in session.scalars(
                select(KnowledgeNodeSourcePointerRecord).where(
                    KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id
                    == graph_snapshot_revision_id,
                    KnowledgeNodeSourcePointerRecord.analysis_run_id.in_(run_ids),
                    KnowledgeNodeSourcePointerRecord.node_id.in_(node_ids),
                )
            ):
                key = (
                    pointer.analysis_run_id,
                    pointer.node_id,
                    pointer.source_revision_id,
                )
                if key in allowed_pointer_keys:
                    classes_by_key[key].add(pointer.source_class)

        occurrences_by_run: dict[str, list[AssessmentItemOccurrenceReferenceRecord]] = defaultdict(
            list
        )
        if run_ids:
            for observed_occurrence in session.scalars(
                select(AssessmentItemOccurrenceReferenceRecord).where(
                    AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id
                    == graph_snapshot_revision_id,
                    AssessmentItemOccurrenceReferenceRecord.analysis_run_id.in_(run_ids),
                )
            ):
                occurrences_by_run[observed_occurrence.analysis_run_id].append(observed_occurrence)
        placement_ids = {
            occurrence.placement_node_id
            for occurrences in occurrences_by_run.values()
            for occurrence in occurrences
        }
        unit_ids_by_node = self._unit_ids_by_node(
            session,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            node_ids=node_ids | placement_ids,
        )
        expected_units = integrated_science_curriculum_units()
        expected_by_id = {row.curriculum_unit_id: row for row in expected_units}

        structural: list[_StructuralCandidate] = []
        for analysis, node, revision, item, component in rows:
            key = (analysis.analysis_run_id, node.node_id, revision.item_revision_id)
            classes = classes_by_key.get(key, set())
            if len(classes) != 1 or not classes.issubset({"APPROVED_ITEM", "PAST_EXAM"}):
                self._fail(
                    "ASSEMBLY_GRAPH_SOURCE_POINTER_INVALID",
                    "a planning Item has no unique accepted Graph source class",
                )
            source_class = cast(Literal["APPROVED_ITEM", "PAST_EXAM"], next(iter(classes)))
            occurrences = occurrences_by_run.get(analysis.analysis_run_id, [])
            candidate_occurrence: AssessmentItemOccurrenceReferenceRecord | None
            if source_class == "PAST_EXAM":
                if len(occurrences) != 1:
                    self._fail(
                        "ASSEMBLY_GRAPH_OCCURRENCE_AMBIGUOUS",
                        "a past-exam Item does not have one exact occurrence placement",
                    )
                candidate_occurrence = occurrences[0]
                if candidate_occurrence.subject_key != policy.subject_key:
                    continue
                if (
                    candidate_occurrence.target_school_level == "HIGH_SCHOOL"
                    and candidate_occurrence.target_grade == 1
                    and candidate_occurrence.administration_month == 3
                ):
                    continue
            else:
                if occurrences:
                    self._fail(
                        "ASSEMBLY_GRAPH_SOURCE_CONTEXT_INVALID",
                        "an approved Item unexpectedly owns a past-exam placement",
                    )
                candidate_occurrence = None
            direct_units = unit_ids_by_node.get(node.node_id, set())
            occurrence_units = (
                unit_ids_by_node.get(candidate_occurrence.placement_node_id, set())
                if candidate_occurrence is not None
                else set()
            )
            if direct_units and occurrence_units and direct_units != occurrence_units:
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "canonical Item and occurrence curriculum pointers differ",
                )
            unit_ids = direct_units or occurrence_units
            if not unit_ids:
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "a planning Item has no reviewed curriculum pointer",
                )
            curriculum_unit_keys = tuple(
                sorted(expected_by_id[unit_id].unit_key for unit_id in unit_ids)
            )
            large_unit_keys = {
                self._large_unit_key(expected_by_id[unit_id], expected_by_id)
                for unit_id in unit_ids
            }
            if len(large_unit_keys) != 1:
                self._fail(
                    "ASSEMBLY_LARGE_UNIT_AMBIGUOUS",
                    "a planning Item crosses reviewed large-unit boundaries",
                )
            self.validate_structural_component(component)
            structural.append(
                _StructuralCandidate(
                    analysis=analysis,
                    node=node,
                    revision=revision,
                    item=item,
                    component=component,
                    source_class=source_class,
                    occurrence=candidate_occurrence,
                    curriculum_unit_keys=curriculum_unit_keys,
                    large_unit_key=next(iter(large_unit_keys)),
                )
            )
        return tuple(structural)

    def _unit_ids_by_node(
        self,
        session: Session,
        *,
        graph_snapshot_revision_id: str,
        node_ids: set[str],
    ) -> dict[str, set[str]]:
        if not node_ids:
            return {}
        expected = {row.curriculum_unit_id: row for row in integrated_science_curriculum_units()}
        values: dict[str, set[str]] = defaultdict(set)
        for from_node_id, observed in session.execute(
            select(KnowledgeEdgeRecord.from_node_id, CurriculumUnitRecord)
            .join(
                CurriculumUnitRecord,
                and_(
                    CurriculumUnitRecord.graph_snapshot_revision_id
                    == KnowledgeEdgeRecord.graph_snapshot_revision_id,
                    CurriculumUnitRecord.node_id == KnowledgeEdgeRecord.to_node_id,
                ),
            )
            .where(
                KnowledgeEdgeRecord.graph_snapshot_revision_id == graph_snapshot_revision_id,
                KnowledgeEdgeRecord.from_node_id.in_(node_ids),
                KnowledgeEdgeRecord.edge_type == "ALIGNS_WITH_CURRICULUM",
            )
        ):
            canonical = expected.get(observed.curriculum_unit_id)
            if (
                canonical is None
                or observed.framework_revision_id != canonical.framework_revision_id
                or observed.parent_unit_id != canonical.parent_unit_id
                or observed.unit_level != canonical.unit_level
                or observed.ordinal != canonical.ordinal
            ):
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "Graph curriculum pointer differs from the reviewed outline",
                )
            values[from_node_id].add(observed.curriculum_unit_id)
        return dict(values)

    @staticmethod
    def _large_unit_key(
        unit: CurriculumUnitBindingV2,
        unit_by_id: dict[str, CurriculumUnitBindingV2],
    ) -> str:
        current = unit
        while current.unit_level != "MIDDLE":
            if current.parent_unit_id is None:
                raise MockExamCandidateResolutionError(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "curriculum pointer has no reviewed large-unit ancestor",
                )
            parent = unit_by_id.get(current.parent_unit_id)
            if parent is None:
                raise MockExamCandidateResolutionError(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "curriculum pointer targets an unknown reviewed ancestor",
                )
            current = parent
        if not current.unit_key.startswith("eom.is.large."):
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                "curriculum large-unit pointer is outside Integrated Science",
            )
        return current.unit_key

    @staticmethod
    def validate_structural_component(component: ItemComponentRecord) -> None:
        """Validate the shared canonical content-team component pointer shape."""

        metadata = component.metadata_json
        if (
            component.logical_name != ASSESSMENT_ITEM_CONTENT_FILE_NAME
            or component.schema_ref not in _CONTENT_TEAM_SCHEMA_REFS
            or component.media_type != ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE
            or component.required is not True
            or metadata.get("editorial_markdown_member") != "content-team-item.md"
            or not _is_sha256(metadata.get("editorial_markdown_sha256"))
            or not _is_sha256(component.sha256)
        ):
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ITEM_CONTENT_POINTER_INVALID",
                "planning Item content is not one complete content-team V2 pointer",
            )

    @staticmethod
    def _latest_reviews(
        session: Session, *, revision_ids: tuple[str, ...]
    ) -> dict[str, ItemReviewRecord]:
        if not revision_ids:
            return {}
        latest: dict[str, ItemReviewRecord] = {}
        for review in session.scalars(
            select(ItemReviewRecord)
            .where(ItemReviewRecord.item_revision_id.in_(revision_ids))
            .order_by(
                ItemReviewRecord.item_revision_id,
                ItemReviewRecord.created_at.desc(),
                ItemReviewRecord.item_review_record_id.desc(),
            )
        ):
            latest.setdefault(review.item_revision_id, review)
        return latest

    def _validate_artifact_pointers(
        self,
        session: Session,
        rated_rows: tuple[tuple[_StructuralCandidate, ItemReviewRecord], ...],
    ) -> tuple[
        dict[str, ArtifactRecord],
        dict[str, ArtifactRevisionRecord],
    ]:
        artifact_ids = {
            value
            for row, review in rated_rows
            for value in (
                row.revision.manifest_artifact_id,
                row.component.artifact_id,
                review.review_artifact_id,
            )
        }
        revision_ids = {
            value
            for row, review in rated_rows
            for value in (
                row.revision.manifest_artifact_revision_id,
                row.component.artifact_revision_id,
                review.review_artifact_revision_id,
            )
        }
        artifacts = {
            row.logical_artifact_id: row
            for row in session.scalars(
                select(ArtifactRecord).where(ArtifactRecord.logical_artifact_id.in_(artifact_ids))
            )
        }
        revisions = {
            row.revision_id: row
            for row in session.scalars(
                select(ArtifactRevisionRecord).where(
                    ArtifactRevisionRecord.revision_id.in_(revision_ids)
                )
            )
        }
        for row, review in rated_rows:
            self._validate_item_manifest(
                row,
                artifacts=artifacts,
                revisions=revisions,
            )
            self._validate_review_pointer(
                review,
                artifacts=artifacts,
                revisions=revisions,
            )
        return artifacts, revisions

    def _validate_item_manifest(
        self,
        row: _StructuralCandidate,
        *,
        artifacts: dict[str, ArtifactRecord],
        revisions: dict[str, ArtifactRevisionRecord],
    ) -> None:
        artifact = artifacts.get(row.revision.manifest_artifact_id)
        revision = revisions.get(row.revision.manifest_artifact_revision_id)
        payload = self._read_member(
            artifact,
            revision,
            artifact_id=row.revision.manifest_artifact_id,
            revision_id=row.revision.manifest_artifact_revision_id,
            artifact_type="item-revision-manifest",
            member_path="item-revision-manifest.json",
            expected_sha256=row.revision.manifest_sha256,
            max_bytes=MAX_ITEM_MANIFEST_BYTES,
        )
        value = _json_object(payload, "ASSEMBLY_ITEM_MANIFEST_INVALID")
        try:
            validate_contract("item-revision-manifest", value)
        except (JsonSchemaValidationError, ValueError) as exc:
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ITEM_MANIFEST_INVALID",
                "Item revision manifest does not satisfy its pinned schema",
            ) from exc
        components = value.get("components")
        expected_component = {
            "component_type": row.component.component_type,
            "ordinal": row.component.ordinal,
            "schema_ref": row.component.schema_ref,
            "media_type": row.component.media_type,
            "artifact_id": row.component.artifact_id,
            "artifact_revision_id": row.component.artifact_revision_id,
            "sha256": row.component.sha256,
            "logical_name": row.component.logical_name,
            "required": row.component.required,
        }
        if (
            value.get("item_id") != row.item.item_id
            or value.get("item_revision_id") != row.revision.item_revision_id
            or value.get("revision_number") != row.revision.revision_number
            or not isinstance(components, list)
            or sum(component == expected_component for component in components) != 1
        ):
            self._fail(
                "ASSEMBLY_ITEM_MANIFEST_INVALID",
                "Item manifest does not bind its exact Item/content component",
            )

    def _validate_review_pointer(
        self,
        review: ItemReviewRecord,
        *,
        artifacts: dict[str, ArtifactRecord],
        revisions: dict[str, ArtifactRevisionRecord],
    ) -> None:
        review_result_schema = review.severity_summary.get("review_result_schema")
        if review_result_schema in {"review-result@7.0", "review-result@8.0"}:
            decision_schema = MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA
            decision_schema_ref = MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF
        elif review_result_schema == "review-result@9.0":
            decision_schema = MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA
            decision_schema_ref = MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA_REF
        elif review_result_schema == "review-result@10.0":
            decision_schema = MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA
            decision_schema_ref = MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA_REF
        else:
            self._fail(
                "ASSEMBLY_REVIEW_POINTER_INVALID",
                "review row does not identify a supported immutable decision family",
            )
        artifact = artifacts.get(review.review_artifact_id)
        revision = revisions.get(review.review_artifact_revision_id)
        if (
            revision is None
            or revision.manifest.get("primary_file") != MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME
            or not isinstance(revision.manifest.get("files"), list)
            or len(revision.manifest["files"]) != 1
        ):
            self._fail(
                "ASSEMBLY_REVIEW_POINTER_INVALID",
                "review decision artifact does not expose its one canonical member",
            )
        payload = self._read_member(
            artifact,
            revision,
            artifact_id=review.review_artifact_id,
            revision_id=review.review_artifact_revision_id,
            artifact_type="mock-exam-item-review-decision",
            member_path=MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
            expected_sha256=review.review_sha256,
            max_bytes=MAX_REVIEW_BYTES,
            expected_media_type="application/json",
            expected_schema_ref=decision_schema_ref,
        )
        value = _json_object(payload, "ASSEMBLY_REVIEW_POINTER_INVALID")
        try:
            validate_contract(decision_schema, value)
            if review_result_schema == "review-result@10.0":
                decision: MockExamItemReviewDecisionV1 = (
                    MockExamItemReviewDecisionV3.model_validate(value)
                )
            elif review_result_schema == "review-result@9.0":
                decision = MockExamItemReviewDecisionV2.model_validate(value)
            else:
                decision = MockExamItemReviewDecisionV1.model_validate(value)
        except (JsonSchemaValidationError, ValueError) as exc:
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_REVIEW_POINTER_INVALID",
                "review decision artifact does not satisfy its pinned schema",
            ) from exc
        summary = review.severity_summary
        if (
            decision.item_review_record_id != review.item_review_record_id
            or decision.item_revision_id != review.item_revision_id
            or decision.workflow_id != review.workflow_id
            or decision.decision != review.decision
            or decision.final_rating != summary.get("final_rating")
            or decision.rating_policy_revision_id != summary.get("rating_policy_revision_id")
            or decision.rating_policy_sha256 != summary.get("rating_policy_sha256")
            or decision.decision_sha256 != summary.get("decision_sha256")
            or decision.idempotency_key_sha256 != summary.get("idempotency_key_sha256")
            or decision.source_review.step_run_id != summary.get("review_step_run_id")
            or decision.source_review.artifact_id != summary.get("source_review_artifact_id")
            or decision.source_review.artifact_revision_id
            != summary.get("source_review_artifact_revision_id")
            or decision.source_review.sha256 != summary.get("source_review_sha256")
            or decision.source_review.result_schema != summary.get("review_result_schema")
            or decision.source_review.finding_counts.model_dump(mode="json")
            != summary.get("finding_counts")
            or decision.human_approval.approval_request_id
            != summary.get("human_approval_request_id")
            or decision.human_approval.reviewer_operator_id != review.reviewer_actor_id
            or (
                isinstance(decision, MockExamItemReviewDecisionV3)
                and decision.source_review.trusted_evidence_usage_receipts.model_dump(mode="json")
                != summary.get("trusted_evidence_usage_receipts")
            )
            or (
                not isinstance(decision, MockExamItemReviewDecisionV3)
                and "trusted_evidence_usage_receipts" in summary
            )
        ):
            self._fail(
                "ASSEMBLY_REVIEW_POINTER_INVALID",
                "review row and canonical decision artifact have different identities",
            )

    def _load_candidate_content(
        self,
        row: _StructuralCandidate,
        *,
        artifacts: dict[str, ArtifactRecord],
        revisions: dict[str, ArtifactRevisionRecord],
    ) -> _CandidateContent:
        artifact = artifacts.get(row.component.artifact_id)
        revision = revisions.get(row.component.artifact_revision_id)
        raw_content = self._read_member(
            artifact,
            revision,
            artifact_id=row.component.artifact_id,
            revision_id=row.component.artifact_revision_id,
            artifact_type="assessment-item-content",
            member_path=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            expected_sha256=row.component.sha256,
            max_bytes=MAX_ITEM_CONTENT_BYTES,
            expected_media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            expected_schema_ref=row.component.schema_ref,
        )
        metadata = row.component.metadata_json
        markdown_sha256 = cast(str, metadata["editorial_markdown_sha256"])
        is_v3 = row.component.schema_ref in _CONTENT_TEAM_V3_SCHEMA_REFS
        markdown_schema_ref = (
            "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
            if is_v3
            else "eom://schemas/hwpx/content-team-editorial-markdown/1.0"
        )
        metadata_markdown_schema_ref = metadata.get("editorial_markdown_schema_ref")
        if (is_v3 and metadata_markdown_schema_ref != markdown_schema_ref) or (
            not is_v3 and metadata_markdown_schema_ref not in {None, markdown_schema_ref}
        ):
            self._fail(
                "ASSEMBLY_ITEM_CONTENT_POINTER_INVALID",
                "planning Item Markdown schema differs from its content schema",
            )
        self._read_member(
            artifact,
            revision,
            artifact_id=row.component.artifact_id,
            revision_id=row.component.artifact_revision_id,
            artifact_type="assessment-item-content",
            member_path="content-team-item.md",
            expected_sha256=markdown_sha256,
            max_bytes=MAX_EDITORIAL_MARKDOWN_BYTES,
            expected_media_type="text/markdown",
            expected_schema_ref=markdown_schema_ref,
        )
        value = _json_object(raw_content, "ASSEMBLY_ITEM_CONTENT_INVALID")
        try:
            schema_name = "assessment-item-content-v3" if is_v3 else "assessment-item-content-v2"
            content_model = AssessmentItemContentV3 if is_v3 else AssessmentItemContentV2
            validate_contract(schema_name, value)
            content = content_model.model_validate(value)
        except ValueError as exc:
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ITEM_CONTENT_INVALID",
                "content-team Item does not satisfy its pinned canonical contract",
            ) from exc
        pointer_values = {
            "item_component_id": row.component.item_component_id,
            "artifact_id": row.component.artifact_id,
            "artifact_revision_id": row.component.artifact_revision_id,
            "member_path": ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            "schema_ref": (
                ASSESSMENT_ITEM_CONTENT_V3_SCHEMA_REF
                if is_v3
                else ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF
            ),
            "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            "sha256": row.component.sha256,
            "editorial_markdown_member": "content-team-item.md",
            "editorial_markdown_sha256": markdown_sha256,
        }
        pointer: MockExamContentPointerContract
        if is_v3:
            pointer = MockExamContentPointerV2.model_validate(
                {
                    **pointer_values,
                    "editorial_markdown_schema_ref": markdown_schema_ref,
                }
            )
        else:
            pointer = MockExamContentPointerV1.model_validate(pointer_values)
        return _CandidateContent(
            pointer=pointer,
            value=content,
        )

    def _read_member(
        self,
        artifact: ArtifactRecord | None,
        revision: ArtifactRevisionRecord | None,
        *,
        artifact_id: str,
        revision_id: str,
        artifact_type: str | None,
        member_path: str,
        expected_sha256: str,
        max_bytes: int,
        expected_media_type: str | None = None,
        expected_schema_ref: str | None = None,
    ) -> bytes:
        if (
            artifact is None
            or revision is None
            or not artifact.approved
            or not revision.approved
            or artifact.logical_artifact_id != artifact_id
            or revision.logical_artifact_id != artifact_id
            or revision.revision_id != revision_id
            or artifact.job_id != revision.job_id
            or (artifact_type is not None and artifact.artifact_type != artifact_type)
            or revision.manifest_hash != content_sha256(revision.manifest)
            or revision.manifest.get("logical_artifact_id") != artifact_id
            or revision.manifest.get("revision_id") != revision_id
            or not _is_sha256(expected_sha256)
            or Path(member_path).name != member_path
            or max_bytes < 1
        ):
            self._fail(
                "ASSEMBLY_ARTIFACT_POINTER_INVALID",
                "artifact member pointer does not resolve to immutable approved evidence",
            )
        files = revision.manifest.get("files")
        if not isinstance(files, list):
            self._fail(
                "ASSEMBLY_ARTIFACT_MANIFEST_INVALID",
                "artifact manifest has no typed member list",
            )
        names = [value.get("file_name") for value in files if isinstance(value, dict)]
        matches = [
            value
            for value in files
            if isinstance(value, dict) and value.get("file_name") == member_path
        ]
        if (
            len(names) != len(files)
            or any(not isinstance(name, str) for name in names)
            or len(names) != len(set(names))
            or len(matches) != 1
        ):
            self._fail(
                "ASSEMBLY_ARTIFACT_MANIFEST_INVALID",
                "artifact manifest member names are not unique and complete",
            )
        member = matches[0]
        expected_size = member.get("bytes")
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or not 0 < expected_size <= max_bytes
            or member.get("sha256") != expected_sha256
            or (expected_media_type is not None and member.get("media_type") != expected_media_type)
            or (expected_schema_ref is not None and member.get("schema_ref") != expected_schema_ref)
            or (
                revision.manifest.get("primary_file") == member_path
                and revision.content_hash != expected_sha256
            )
        ):
            self._fail(
                "ASSEMBLY_ARTIFACT_MANIFEST_INVALID",
                "artifact manifest member differs from its pinned pointer",
            )
        expected_root = self.settings.nas_artifact_root / artifact_id / revision_id
        if Path(revision.nas_path) != expected_root:
            self._fail(
                "ASSEMBLY_ARTIFACT_STORAGE_INVALID",
                "artifact revision does not use its canonical storage location",
            )
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_fd = -1
        artifact_fd = -1
        revision_fd = -1
        try:
            root_fd = os.open(self.settings.nas_artifact_root, directory_flags)
            artifact_fd = os.open(artifact_id, directory_flags, dir_fd=root_fd)
            revision_fd = os.open(revision_id, directory_flags, dir_fd=artifact_fd)
            root_before = os.fstat(revision_fd)
            payload = _read_exact_file(
                revision_fd,
                member_path,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            if _stat_identity(root_before) != _stat_identity(os.fstat(revision_fd)):
                self._fail(
                    "ASSEMBLY_ARTIFACT_STORAGE_INVALID",
                    "artifact root changed while reading its member",
                )
            return payload
        except OSError as exc:
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ARTIFACT_STORAGE_INVALID",
                "artifact member could not be read through its pinned path",
            ) from exc
        finally:
            if revision_fd >= 0:
                os.close(revision_fd)
            if artifact_fd >= 0:
                os.close(artifact_fd)
            if root_fd >= 0:
                os.close(root_fd)

    @staticmethod
    def _usage_snapshot(
        session: Session,
        *,
        revision_ids: tuple[str, ...],
        captured_at: datetime,
    ) -> tuple[dict[str, tuple[int, datetime | None, str]], MockExamUsageSnapshotV1]:
        rows_by_revision: dict[str, list[dict[str, Any]]] = {
            revision_id: [] for revision_id in revision_ids
        }
        if revision_ids:
            for row in session.scalars(
                select(UsageRecord).where(
                    UsageRecord.item_revision_id.in_(revision_ids),
                    UsageRecord.recorded_at <= captured_at,
                )
            ):
                rows_by_revision[row.item_revision_id].append(
                    {
                        "source": "usage_records",
                        "usage_record_id": row.usage_record_id,
                        "item_id": row.item_id,
                        "item_revision_id": row.item_revision_id,
                        "deliverable_id": row.deliverable_id,
                        "deliverable_revision_id": row.deliverable_revision_id,
                        "recorded_at": _utc_text(row.recorded_at),
                    }
                )
            for legacy_row in session.scalars(
                select(UsageRecordV1Record).where(
                    UsageRecordV1Record.item_revision_id.in_(revision_ids),
                    UsageRecordV1Record.recorded_at <= captured_at,
                )
            ):
                rows_by_revision[legacy_row.item_revision_id].append(
                    {
                        "source": "usage_records_v1",
                        "usage_record_id": legacy_row.usage_record_id,
                        "item_id": legacy_row.item_id,
                        "item_revision_id": legacy_row.item_revision_id,
                        "deliverable_id": legacy_row.deliverable_id,
                        "deliverable_revision_id": legacy_row.deliverable_revision_id,
                        "recorded_at": _utc_text(legacy_row.recorded_at),
                    }
                )
        flattened: list[dict[str, Any]] = []
        result: dict[str, tuple[int, datetime | None, str]] = {}
        for revision_id in revision_ids:
            records = sorted(
                rows_by_revision[revision_id],
                key=lambda value: (
                    cast(str, value["recorded_at"]),
                    cast(str, value["source"]),
                    cast(str, value["usage_record_id"]),
                ),
            )
            flattened.extend(records)
            latest = (
                datetime.fromisoformat(cast(str, records[-1]["recorded_at"]).replace("Z", "+00:00"))
                if records
                else None
            )
            result[revision_id] = (
                len(records),
                latest,
                content_sha256({"item_revision_id": revision_id, "records": records}),
            )
        flattened.sort(
            key=lambda value: (
                cast(str, value["item_revision_id"]),
                cast(str, value["recorded_at"]),
                cast(str, value["source"]),
                cast(str, value["usage_record_id"]),
            )
        )
        captured_text = _utc_text(captured_at)
        snapshot_value: dict[str, Any] = {
            "schema_version": "mock-exam-usage-snapshot/1.0",
            "captured_at": captured_text,
            "candidate_revision_count": len(revision_ids),
            "usage_record_count": len(flattened),
            "usage_records_sha256": content_sha256(flattened),
        }
        snapshot_sha256 = content_sha256(snapshot_value)
        snapshot = MockExamUsageSnapshotV1.model_validate(
            {
                **snapshot_value,
                "usage_snapshot_id": (
                    "usagesnapshot_" + snapshot_sha256.removeprefix("sha256:")[:32]
                ),
                "snapshot_sha256": snapshot_sha256,
            }
        )
        return result, snapshot

    @staticmethod
    def _fail(code: str, message: str) -> Never:
        raise MockExamCandidateResolutionError(code, message)


def _read_exact_file(
    directory_fd: int,
    name: str,
    *,
    expected_size: int,
    expected_sha256: str,
) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != expected_size
        ):
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ARTIFACT_STORAGE_INVALID",
                "artifact member metadata differs from its manifest",
            )
        chunks: list[bytes] = []
        remaining = expected_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if (
            len(payload) != expected_size
            or sha256_bytes(payload) != expected_sha256
            or _stat_identity(opened) != _stat_identity(os.fstat(descriptor))
        ):
            raise MockExamCandidateResolutionError(
                "ASSEMBLY_ARTIFACT_STORAGE_INVALID",
                "artifact member bytes differ from their pinned hash",
            )
        return payload
    finally:
        os.close(descriptor)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _json_object(raw: bytes, code: str) -> dict[str, Any]:
    try:
        value: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MockExamCandidateResolutionError(code, "artifact member is not valid JSON") from exc
    if not isinstance(value, dict):
        raise MockExamCandidateResolutionError(code, "artifact JSON member is not an object")
    return cast(dict[str, Any], value)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MockExamCandidateResolutionError(
            "ASSEMBLY_USAGE_TIME_INVALID", "usage timestamp must be timezone-aware"
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
