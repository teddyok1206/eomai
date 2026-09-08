"""Graph-pinned, policy-driven mock-exam assembly use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Never

from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
    CreateMockExamAssembly,
    CreatePlannedMockExamAssembly,
    MockExamAssemblyManifestContract,
    MockExamAssemblyManifestV1,
    MockExamAssemblyManifestV2,
    MockExamAssemblyPlacementV1,
    MockExamAssemblyPlanV1,
    MockExamAssemblyPolicyV1,
    PreviewMockExamAssemblyPlan,
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
    validate_contract,
    validate_mock_exam_placements,
    validate_mock_exam_planned_placements,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from eom_catalog_service.curriculum_graph_structure import (
    integrated_science_curriculum_units,
)
from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord,
    CurriculumUnitRecord,
    KnowledgeCorpusRecord,
    KnowledgeEdgeRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.legacy_usage_models import (
    AssessmentAssemblyRecord,
    AssessmentAssemblyRevisionRecord,
    AssessmentFormRecord,
    AssessmentFormRevisionRecord,
    AssessmentItemPlacementRecord,
)
from eom_catalog_service.mock_exam_candidate_repository import (
    MockExamCandidateRepository,
    MockExamCandidateResolutionError,
)
from eom_catalog_service.models import (
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemRevisionRecord,
)


class MockExamAssemblyError(RuntimeError):
    """Stable fail-closed assembly error safe for an API boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    return prefix + content_sha256(value).removeprefix("sha256:")[:32]


class MockExamAssemblyService:
    """Create one immutable Form/Assembly revision from pinned Graph Item revisions.

    Dominant access is exact key lookup plus two bounded bulk joins over 25 placements.
    Maps provide O(n) pointer resolution and duplicate detection; the transaction locks the
    unique ``(deliverable_id, form_key)`` aggregate before publishing current pointers.
    """

    def __init__(
        self,
        engine: Engine,
        candidates: MockExamCandidateRepository | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.candidates = candidates or MockExamCandidateRepository()

    def preview(self, query: PreviewMockExamAssemblyPlan) -> MockExamAssemblyPlanV1:
        """Resolve one immutable plan without creating a Form or Assembly row."""

        policy = self._validate_policy_pointer(query)
        layout = load_integrated_science_mock_exam_layout_policy()
        rating = load_integrated_science_mock_exam_rating_policy()
        planned_at = datetime.now(UTC)
        try:
            with self.sessions() as session:
                snapshot = self._resolve_snapshot(session, query)
                inputs = self.candidates.resolve(
                    session,
                    graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                    policy=policy,
                    rating_policy=rating,
                    planned_at=planned_at,
                )
        except MockExamCandidateResolutionError as exc:
            self._fail(exc.code, str(exc))
        return build_mock_exam_assembly_plan(
            policy=policy,
            layout_policy=layout,
            rating_policy=rating,
            graph_snapshot_revision_id=query.graph_snapshot_revision_id,
            graph_snapshot_sha256=query.graph_snapshot_sha256,
            usage_snapshot=inputs.usage_snapshot,
            resolved_candidate_count=inputs.resolved_candidate_count,
            candidates=inputs.candidates,
            planned_at=planned_at,
        )

    def create_planned(self, command: CreatePlannedMockExamAssembly) -> MockExamAssemblyManifestV2:
        """Create one released assembly from server-resolved planning evidence."""

        policy = self._validate_policy_pointer(command)
        layout = load_integrated_science_mock_exam_layout_policy()
        rating = load_integrated_science_mock_exam_rating_policy()
        with transaction(self.sessions) as session:
            deliverable, _deliverable_revision = self._resolve_deliverable(session, command)
            existing = self._planned_replay(session, command)
            if existing is not None:
                return existing
            snapshot = self._resolve_snapshot(session, command)
            current_time = datetime.now(UTC)
            if (
                not current_time - timedelta(minutes=15)
                <= command.planned_at
                <= (current_time + timedelta(seconds=5))
            ):
                self._fail(
                    "ASSEMBLY_PLAN_EXPIRED",
                    "the preview plan is outside its bounded creation window",
                )
            try:
                inputs = self.candidates.resolve(
                    session,
                    graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                    policy=policy,
                    rating_policy=rating,
                    planned_at=command.planned_at,
                )
            except MockExamCandidateResolutionError as exc:
                self._fail(exc.code, str(exc))
            plan = build_mock_exam_assembly_plan(
                policy=policy,
                layout_policy=layout,
                rating_policy=rating,
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                graph_snapshot_sha256=snapshot.snapshot_sha256,
                usage_snapshot=inputs.usage_snapshot,
                resolved_candidate_count=inputs.resolved_candidate_count,
                candidates=inputs.candidates,
                planned_at=command.planned_at,
            )
            if plan.plan_sha256 != command.expected_plan_sha256:
                self._fail(
                    "ASSEMBLY_PLAN_CHANGED",
                    "the current pinned candidates differ from the previewed plan",
                )
            if plan.status != "READY" or plan.validation is None:
                self._fail(
                    "ASSEMBLY_CANDIDATE_SHORTAGE",
                    "the current Graph and reviewed ratings cannot fill all 25 slots",
                )
            identity = self._planned_identity(command, plan)
            created_at = datetime.now(UTC)
            value: dict[str, Any] = {
                "schema_version": "mock-exam-assembly-manifest/2.0",
                **identity,
                "deliverable_id": deliverable.deliverable_id,
                "deliverable_revision_id": command.deliverable_revision_id,
                "form_key": command.form_key,
                "display_label": command.display_label,
                "plan": plan.model_dump(mode="json"),
                "revision_state": "RELEASED",
                "created_at": created_at.isoformat().replace("+00:00", "Z"),
                "created_by": command.actor_id,
            }
            value["manifest_sha256"] = content_sha256(value)
            manifest = MockExamAssemblyManifestV2.model_validate(value)
            validate_contract("mock-exam-assembly-manifest-v2", manifest.model_dump(mode="json"))
            self._persist_planned(session, command, manifest, created_at)
            return manifest

    def create(self, command: CreateMockExamAssembly) -> MockExamAssemblyManifestV1:
        policy = self._validate_policy_pointer(command)
        with transaction(self.sessions) as session:
            self._resolve_deliverable(session, command)
            snapshot = self._resolve_snapshot(session, command)
            resolved = self._resolve_placements(session, command, policy)
            identity = self._identity(command, resolved)
            existing = session.get(
                AssessmentAssemblyRevisionRecord,
                identity["assessment_assembly_revision_id"],
            )
            if existing is not None:
                manifest = MockExamAssemblyManifestV1.model_validate(existing.canonical_document)
                if self._manifest_identity(manifest) != identity:
                    self._fail(
                        "ASSEMBLY_REVISION_HASH_CONFLICT",
                        "assembly revision identity already has different content",
                    )
                return manifest

            created_at = datetime.now(UTC)
            validation = validate_mock_exam_placements(resolved, policy)
            value: dict[str, Any] = {
                "schema_version": "mock-exam-assembly-manifest/1.0",
                **identity,
                "deliverable_id": command.deliverable_id,
                "deliverable_revision_id": command.deliverable_revision_id,
                "policy_revision_id": policy.policy_revision_id,
                "policy_sha256": command.policy_sha256,
                "outline_key": policy.outline_key,
                "outline_revision": policy.outline_revision,
                "outline_sha256": policy.outline_sha256,
                "graph_snapshot_revision_id": snapshot.graph_snapshot_revision_id,
                "graph_snapshot_sha256": snapshot.snapshot_sha256,
                "placements": [row.model_dump(mode="json") for row in resolved],
                "validation": validation.model_dump(mode="json"),
                "revision_state": "RELEASED",
                "created_at": created_at.isoformat().replace("+00:00", "Z"),
                "created_by": command.actor_id,
            }
            value["manifest_sha256"] = content_sha256(value)
            manifest = MockExamAssemblyManifestV1.model_validate(value)
            validate_contract("mock-exam-assembly-manifest", manifest.model_dump(mode="json"))
            self._persist(session, command, manifest, created_at)
            return manifest

    @staticmethod
    def inspect(
        session: Session, assembly_revision_id: str
    ) -> MockExamAssemblyManifestContract | None:
        row = session.get(AssessmentAssemblyRevisionRecord, assembly_revision_id)
        if row is None:
            return None
        schema_version = row.canonical_document.get("schema_version")
        if schema_version == "mock-exam-assembly-manifest/1.0":
            manifest: MockExamAssemblyManifestContract = MockExamAssemblyManifestV1.model_validate(
                row.canonical_document
            )
        elif schema_version == "mock-exam-assembly-manifest/2.0":
            manifest = MockExamAssemblyManifestV2.model_validate(row.canonical_document)
        else:
            raise MockExamAssemblyError(
                "ASSEMBLY_MANIFEST_SCHEMA_UNSUPPORTED",
                "stored assembly uses an unsupported manifest schema",
            )
        if row.manifest_sha256 != manifest.manifest_sha256:
            raise MockExamAssemblyError(
                "ASSEMBLY_MANIFEST_POINTER_INVALID",
                "stored assembly hash does not match its canonical document",
            )
        policy = load_integrated_science_mock_exam_policy()
        policy_sha256 = content_sha256(policy.model_dump(mode="json"))
        if isinstance(manifest, MockExamAssemblyManifestV1):
            valid_projection = (
                manifest.policy_revision_id == policy.policy_revision_id
                and manifest.policy_sha256 == policy_sha256
                and validate_mock_exam_placements(manifest.placements, policy)
                == manifest.validation
            )
        else:
            layout = load_integrated_science_mock_exam_layout_policy()
            rating = load_integrated_science_mock_exam_rating_policy()
            plan = manifest.plan
            valid_projection = (
                plan.policy_revision_id == policy.policy_revision_id
                and plan.policy_sha256 == policy_sha256
                and plan.layout_policy_revision_id == layout.layout_policy_revision_id
                and plan.layout_policy_sha256 == content_sha256(layout.model_dump(mode="json"))
                and plan.rating_policy_revision_id == rating.rating_policy_revision_id
                and plan.rating_policy_sha256 == content_sha256(rating.model_dump(mode="json"))
                and plan.validation is not None
                and validate_mock_exam_planned_placements(plan.placements, policy)
                == plan.validation
            )
        if not valid_projection:
            raise MockExamAssemblyError(
                "ASSEMBLY_POLICY_PROJECTION_INVALID",
                "stored assembly no longer matches its pinned policy",
            )
        return manifest

    @staticmethod
    def _validate_policy_pointer(
        command: (
            CreateMockExamAssembly | CreatePlannedMockExamAssembly | PreviewMockExamAssemblyPlan
        ),
    ) -> MockExamAssemblyPolicyV1:
        policy = load_integrated_science_mock_exam_policy()
        if (
            command.policy_revision_id != policy.policy_revision_id
            or command.policy_sha256 != content_sha256(policy.model_dump(mode="json"))
        ):
            raise MockExamAssemblyError(
                "ASSEMBLY_POLICY_POINTER_INVALID", "policy pointer is not current"
            )
        return policy

    def _resolve_deliverable(
        self,
        session: Session,
        command: CreateMockExamAssembly | CreatePlannedMockExamAssembly,
    ) -> tuple[DeliverableRecord, DeliverableRevisionRecord]:
        deliverable = session.scalar(
            select(DeliverableRecord)
            .where(DeliverableRecord.deliverable_id == command.deliverable_id)
            .with_for_update()
        )
        deliverable_revision = session.get(
            DeliverableRevisionRecord, command.deliverable_revision_id
        )
        if (
            deliverable is None
            or deliverable.deliverable_type != "MOCK_EXAM"
            or deliverable_revision is None
            or deliverable_revision.deliverable_id != deliverable.deliverable_id
        ):
            self._fail(
                "ASSEMBLY_DELIVERABLE_POINTER_INVALID",
                "deliverable pointer is not an immutable mock-exam revision",
            )
        return deliverable, deliverable_revision

    def _planned_replay(
        self,
        session: Session,
        command: CreatePlannedMockExamAssembly,
    ) -> MockExamAssemblyManifestV2 | None:
        form = session.scalar(
            select(AssessmentFormRecord)
            .where(
                AssessmentFormRecord.deliverable_id == command.deliverable_id,
                AssessmentFormRecord.form_key == command.form_key,
            )
            .with_for_update()
        )
        if form is None:
            return None
        expected_form_id = _stable_id(
            "form_",
            {
                "deliverable_id": command.deliverable_id,
                "form_key": command.form_key,
            },
        )
        if form.assessment_form_id != expected_form_id:
            self._fail(
                "ASSEMBLY_FORM_CONFLICT",
                "form key resolves to an unexpected logical Form",
            )
        if form.current_revision_id is None:
            return None
        form_revision = session.get(AssessmentFormRevisionRecord, form.current_revision_id)
        assembly_revision = (
            session.get(
                AssessmentAssemblyRevisionRecord,
                form_revision.assessment_assembly_revision_id,
            )
            if form_revision is not None
            else None
        )
        if form_revision is None or assembly_revision is None:
            self._fail(
                "ASSEMBLY_REPLAY_POINTER_INVALID",
                "current Form revision does not resolve to its Assembly revision",
            )
        if assembly_revision.canonical_document.get("schema_version") != (
            "mock-exam-assembly-manifest/2.0"
        ):
            self._fail(
                "ASSEMBLY_FORM_CONFLICT",
                "form key already owns a non-planned Assembly",
            )
        manifest = MockExamAssemblyManifestV2.model_validate(assembly_revision.canonical_document)
        if (
            manifest.manifest_sha256 != assembly_revision.manifest_sha256
            or manifest.deliverable_id != command.deliverable_id
            or manifest.deliverable_revision_id != command.deliverable_revision_id
            or manifest.form_key != command.form_key
            or manifest.display_label != command.display_label
            or manifest.plan.policy_revision_id != command.policy_revision_id
            or manifest.plan.policy_sha256 != command.policy_sha256
            or manifest.plan.graph_snapshot_revision_id != command.graph_snapshot_revision_id
            or manifest.plan.graph_snapshot_sha256 != command.graph_snapshot_sha256
            or manifest.plan.plan_sha256 != command.expected_plan_sha256
            or manifest.plan.planned_at != command.planned_at
        ):
            self._fail(
                "ASSEMBLY_FORM_CONFLICT",
                "form key already owns an Assembly with different pinned inputs",
            )
        return manifest

    def _resolve_snapshot(
        self,
        session: Session,
        command: (
            CreateMockExamAssembly | CreatePlannedMockExamAssembly | PreviewMockExamAssemblyPlan
        ),
    ) -> KnowledgeGraphSnapshotRecord:
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
                KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
            )
        )
        snapshot = session.get(KnowledgeGraphSnapshotRecord, command.graph_snapshot_revision_id)
        if (
            corpus is None
            or snapshot is None
            or corpus.current_graph_snapshot_revision_id != command.graph_snapshot_revision_id
            or snapshot.graph_id != corpus.graph_id
            or snapshot.state != "PUBLISHED"
            or snapshot.ontology_version != "education-knowledge-graph/1.1"
            or snapshot.snapshot_sha256 != command.graph_snapshot_sha256
        ):
            self._fail(
                "ASSEMBLY_GRAPH_POINTER_INVALID",
                "assembly must pin the current published Integrated Science Graph",
            )
        return snapshot

    def _resolve_placements(
        self,
        session: Session,
        command: CreateMockExamAssembly,
        policy: MockExamAssemblyPolicyV1,
    ) -> tuple[MockExamAssemblyPlacementV1, ...]:
        revision_ids = tuple(row.item_revision_id for row in command.placements)
        revisions = {
            row.item_revision_id: row
            for row in session.scalars(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.item_revision_id.in_(revision_ids)
                )
            )
        }
        placement_node_ids = tuple(row.graph_placement_node_id for row in command.placements)
        references = {
            row.placement_node_id: row
            for row in session.scalars(
                select(AssessmentItemOccurrenceReferenceRecord).where(
                    AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id
                    == command.graph_snapshot_revision_id,
                    AssessmentItemOccurrenceReferenceRecord.placement_node_id.in_(
                        placement_node_ids
                    ),
                )
            )
        }
        expected_units = integrated_science_curriculum_units()
        unit_by_id = {row.curriculum_unit_id: row for row in expected_units}
        unit_by_key = {row.unit_key: row for row in expected_units}
        unit_keys_by_placement: dict[str, list[str]] = {}
        for placement_node_id, unit in session.execute(
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
                KnowledgeEdgeRecord.graph_snapshot_revision_id
                == command.graph_snapshot_revision_id,
                KnowledgeEdgeRecord.from_node_id.in_(placement_node_ids),
                KnowledgeEdgeRecord.edge_type == "ALIGNS_WITH_CURRICULUM",
            )
        ):
            expected = unit_by_id.get(unit.curriculum_unit_id)
            if (
                expected is None
                or unit.framework_revision_id != expected.framework_revision_id
                or unit.parent_unit_id != expected.parent_unit_id
                or unit.unit_level != expected.unit_level
                or unit.ordinal != expected.ordinal
            ):
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "Graph placement references an unreviewed curriculum unit",
                )
            unit_keys_by_placement.setdefault(placement_node_id, []).append(expected.unit_key)

        resolved: list[MockExamAssemblyPlacementV1] = []
        for selected in command.placements:
            revision = revisions.get(selected.item_revision_id)
            reference = references.get(selected.graph_placement_node_id)
            actual_unit_keys = tuple(
                sorted(set(unit_keys_by_placement.get(selected.graph_placement_node_id, ())))
            )
            if (
                revision is None
                or reference is None
                or revision.item_id != selected.item_id
                or reference.item_id != selected.item_id
                or reference.item_revision_id != selected.item_revision_id
                or revision.manifest_sha256 != selected.item_manifest_sha256
                or revision.revision_state not in policy.eligible_item_revision_states
                or reference.subject_key != policy.subject_key
                or (
                    reference.target_school_level == "HIGH_SCHOOL"
                    and reference.target_grade == 1
                    and reference.administration_month == 3
                )
            ):
                self._fail(
                    "ASSEMBLY_ITEM_POINTER_INVALID",
                    "an Item selection does not resolve to eligible Graph evidence",
                )
            if actual_unit_keys != selected.curriculum_unit_keys or not actual_unit_keys:
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "submitted curriculum pointers differ from the Graph",
                )
            try:
                major_keys = {
                    self._major_unit_key(unit_by_key[key], unit_by_id) for key in actual_unit_keys
                }
            except KeyError:
                self._fail(
                    "ASSEMBLY_CURRICULUM_POINTER_INVALID",
                    "submitted curriculum pointer is outside the reviewed outline",
                )
            if len(major_keys) != 1:
                self._fail(
                    "ASSEMBLY_MAJOR_UNIT_AMBIGUOUS",
                    "an Item selection crosses major curriculum units",
                )
            annotation_sha256 = content_sha256(
                {
                    "item_revision_id": revision.item_revision_id,
                    "graph_placement_node_id": reference.placement_node_id,
                    "curriculum_unit_keys": list(actual_unit_keys),
                    "coverage_role": selected.coverage_role,
                    "coverage_requirement_id": selected.coverage_requirement_id,
                    "is_inquiry": selected.is_inquiry,
                    "material_type": selected.material_type,
                }
            )
            placement_id = _stable_id(
                "placement_",
                {
                    "deliverable_revision_id": command.deliverable_revision_id,
                    "form_key": command.form_key,
                    "position": selected.position,
                    "item_revision_id": selected.item_revision_id,
                    "annotation_sha256": annotation_sha256,
                },
            )
            resolved.append(
                MockExamAssemblyPlacementV1(
                    **selected.model_dump(mode="json"),
                    placement_id=placement_id,
                    display_number=str(selected.position),
                    major_unit_key=next(iter(major_keys)),
                    item_type_key=revision.item_type_key,
                    difficulty_band=revision.difficulty_band,
                    review_annotation_sha256=annotation_sha256,
                )
            )
        return tuple(resolved)

    @staticmethod
    def _major_unit_key(unit: Any, unit_by_id: dict[str, Any]) -> str:
        current = unit
        while current.unit_level != "MIDDLE":
            if current.parent_unit_id is None:
                raise KeyError(current.curriculum_unit_id)
            current = unit_by_id[current.parent_unit_id]
        return str(current.unit_key)

    @staticmethod
    def _identity(
        command: CreateMockExamAssembly,
        placements: tuple[MockExamAssemblyPlacementV1, ...],
    ) -> dict[str, str]:
        form_id = _stable_id(
            "form_", {"deliverable_id": command.deliverable_id, "form_key": command.form_key}
        )
        assembly_id = _stable_id("assembly_", {"assessment_form_id": form_id})
        revision_identity = {
            "assessment_assembly_id": assembly_id,
            "deliverable_revision_id": command.deliverable_revision_id,
            "policy_revision_id": command.policy_revision_id,
            "policy_sha256": command.policy_sha256,
            "graph_snapshot_revision_id": command.graph_snapshot_revision_id,
            "graph_snapshot_sha256": command.graph_snapshot_sha256,
            "placements": [row.model_dump(mode="json") for row in placements],
        }
        assembly_revision_id = _stable_id("assemblyrev_", revision_identity)
        form_revision_id = _stable_id(
            "formrev_",
            {
                "assessment_form_id": form_id,
                "assessment_assembly_revision_id": assembly_revision_id,
                "deliverable_revision_id": command.deliverable_revision_id,
            },
        )
        return {
            "assessment_assembly_revision_id": assembly_revision_id,
            "assessment_assembly_id": assembly_id,
            "assessment_form_id": form_id,
            "assessment_form_revision_id": form_revision_id,
        }

    @staticmethod
    def _manifest_identity(manifest: MockExamAssemblyManifestV1) -> dict[str, str]:
        return {
            "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
            "assessment_assembly_id": manifest.assessment_assembly_id,
            "assessment_form_id": manifest.assessment_form_id,
            "assessment_form_revision_id": manifest.assessment_form_revision_id,
        }

    @staticmethod
    def _planned_identity(
        command: CreatePlannedMockExamAssembly,
        plan: MockExamAssemblyPlanV1,
    ) -> dict[str, str]:
        form_id = _stable_id(
            "form_",
            {
                "deliverable_id": command.deliverable_id,
                "form_key": command.form_key,
            },
        )
        assembly_id = _stable_id("assembly_", {"assessment_form_id": form_id})
        assembly_revision_id = _stable_id(
            "assemblyrev_",
            {
                "assessment_assembly_id": assembly_id,
                "deliverable_revision_id": command.deliverable_revision_id,
                "form_key": command.form_key,
                "plan_sha256": plan.plan_sha256,
            },
        )
        form_revision_id = _stable_id(
            "formrev_",
            {
                "assessment_form_id": form_id,
                "assessment_assembly_revision_id": assembly_revision_id,
                "deliverable_revision_id": command.deliverable_revision_id,
            },
        )
        return {
            "assessment_assembly_revision_id": assembly_revision_id,
            "assessment_assembly_id": assembly_id,
            "assessment_form_id": form_id,
            "assessment_form_revision_id": form_revision_id,
        }

    def _persist(
        self,
        session: Session,
        command: CreateMockExamAssembly,
        manifest: MockExamAssemblyManifestV1,
        created_at: datetime,
    ) -> None:
        form = session.scalar(
            select(AssessmentFormRecord)
            .where(
                AssessmentFormRecord.deliverable_id == command.deliverable_id,
                AssessmentFormRecord.form_key == command.form_key,
            )
            .with_for_update()
        )
        if form is None:
            form = AssessmentFormRecord(
                assessment_form_id=manifest.assessment_form_id,
                deliverable_id=command.deliverable_id,
                form_key=command.form_key,
                current_revision_id=None,
                lifecycle_state="ACTIVE",
                created_at=created_at,
                created_by=command.actor_id,
            )
            session.add(form)
            session.flush()
        elif (
            form.assessment_form_id != manifest.assessment_form_id
            or form.current_revision_id is not None
        ):
            self._fail(
                "ASSEMBLY_FORM_CONFLICT",
                "form key already resolves to another immutable assembly",
            )
        assembly = session.scalar(
            select(AssessmentAssemblyRecord)
            .where(AssessmentAssemblyRecord.assessment_form_id == form.assessment_form_id)
            .with_for_update()
        )
        if assembly is None:
            assembly = AssessmentAssemblyRecord(
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_form_id=form.assessment_form_id,
                current_revision_id=None,
                created_at=created_at,
                created_by=command.actor_id,
            )
            session.add(assembly)
            session.flush()
        elif (
            assembly.assessment_assembly_id != manifest.assessment_assembly_id
            or assembly.current_revision_id is not None
        ):
            self._fail(
                "ASSEMBLY_AGGREGATE_CONFLICT",
                "form already owns another immutable assembly revision",
            )
        assembly_revision = AssessmentAssemblyRevisionRecord(
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            assessment_assembly_id=manifest.assessment_assembly_id,
            assessment_form_id=manifest.assessment_form_id,
            revision_number=1,
            previous_revision_id=None,
            revision_state="RELEASED",
            total_points_milli=manifest.validation.total_points_milli,
            manifest_sha256=manifest.manifest_sha256,
            canonical_document=manifest.model_dump(mode="json"),
            created_at=created_at,
            created_by=command.actor_id,
            released_at=created_at,
        )
        session.add(assembly_revision)
        session.flush()
        session.add_all(
            AssessmentItemPlacementRecord(
                placement_id=row.placement_id,
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                section_key="main",
                section_ordinal=1,
                position=row.position,
                display_number=row.display_number,
                item_id=row.item_id,
                item_revision_id=row.item_revision_id,
                item_manifest_sha256=row.item_manifest_sha256,
                points_milli=row.points_milli,
                usage_role="PRIMARY",
                source_usage_plan_id=None,
            )
            for row in manifest.placements
        )
        form_revision = AssessmentFormRevisionRecord(
            assessment_form_revision_id=manifest.assessment_form_revision_id,
            assessment_form_id=manifest.assessment_form_id,
            revision_number=1,
            previous_revision_id=None,
            deliverable_revision_id=command.deliverable_revision_id,
            ordinal=1,
            display_label=command.display_label,
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            revision_state="RELEASED",
            revision_sha256=manifest.manifest_sha256,
            created_at=created_at,
            created_by=command.actor_id,
            released_at=created_at,
        )
        session.add(form_revision)
        session.flush()
        form.current_revision_id = manifest.assessment_form_revision_id
        assembly.current_revision_id = manifest.assessment_assembly_revision_id
        session.flush()

    def _persist_planned(
        self,
        session: Session,
        command: CreatePlannedMockExamAssembly,
        manifest: MockExamAssemblyManifestV2,
        created_at: datetime,
    ) -> None:
        if manifest.plan.validation is None:
            self._fail(
                "ASSEMBLY_PLAN_INVALID",
                "released planned Assembly has no validation projection",
            )
        form = session.scalar(
            select(AssessmentFormRecord)
            .where(
                AssessmentFormRecord.deliverable_id == command.deliverable_id,
                AssessmentFormRecord.form_key == command.form_key,
            )
            .with_for_update()
        )
        if form is None:
            form = AssessmentFormRecord(
                assessment_form_id=manifest.assessment_form_id,
                deliverable_id=command.deliverable_id,
                form_key=command.form_key,
                current_revision_id=None,
                lifecycle_state="ACTIVE",
                created_at=created_at,
                created_by=command.actor_id,
            )
            session.add(form)
            session.flush()
        elif (
            form.assessment_form_id != manifest.assessment_form_id
            or form.current_revision_id is not None
        ):
            self._fail(
                "ASSEMBLY_FORM_CONFLICT",
                "form key already resolves to another immutable Assembly",
            )
        assembly = session.scalar(
            select(AssessmentAssemblyRecord)
            .where(AssessmentAssemblyRecord.assessment_form_id == form.assessment_form_id)
            .with_for_update()
        )
        if assembly is None:
            assembly = AssessmentAssemblyRecord(
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_form_id=form.assessment_form_id,
                current_revision_id=None,
                created_at=created_at,
                created_by=command.actor_id,
            )
            session.add(assembly)
            session.flush()
        elif (
            assembly.assessment_assembly_id != manifest.assessment_assembly_id
            or assembly.current_revision_id is not None
        ):
            self._fail(
                "ASSEMBLY_AGGREGATE_CONFLICT",
                "Form already owns another immutable Assembly revision",
            )
        validation = manifest.plan.validation
        assembly_revision = AssessmentAssemblyRevisionRecord(
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            assessment_assembly_id=manifest.assessment_assembly_id,
            assessment_form_id=manifest.assessment_form_id,
            revision_number=1,
            previous_revision_id=None,
            revision_state="RELEASED",
            total_points_milli=validation.total_points_milli,
            manifest_sha256=manifest.manifest_sha256,
            canonical_document=manifest.model_dump(mode="json"),
            created_at=created_at,
            created_by=command.actor_id,
            released_at=created_at,
        )
        session.add(assembly_revision)
        session.flush()
        session.add_all(
            AssessmentItemPlacementRecord(
                placement_id=_stable_id(
                    "placement_",
                    {
                        "assessment_assembly_revision_id": (
                            manifest.assessment_assembly_revision_id
                        ),
                        "slot_id": row.slot_id,
                        "item_revision_id": row.item_revision_id,
                    },
                ),
                assessment_assembly_revision_id=(manifest.assessment_assembly_revision_id),
                section_key="main",
                section_ordinal=1,
                position=row.position,
                display_number=row.display_number,
                item_id=row.item_id,
                item_revision_id=row.item_revision_id,
                item_manifest_sha256=row.item_manifest_sha256,
                points_milli=row.points_milli,
                usage_role="PRIMARY",
                source_usage_plan_id=None,
            )
            for row in manifest.plan.placements
        )
        form_revision = AssessmentFormRevisionRecord(
            assessment_form_revision_id=manifest.assessment_form_revision_id,
            assessment_form_id=manifest.assessment_form_id,
            revision_number=1,
            previous_revision_id=None,
            deliverable_revision_id=command.deliverable_revision_id,
            ordinal=1,
            display_label=command.display_label,
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            revision_state="RELEASED",
            revision_sha256=manifest.manifest_sha256,
            created_at=created_at,
            created_by=command.actor_id,
            released_at=created_at,
        )
        session.add(form_revision)
        session.flush()
        form.current_revision_id = manifest.assessment_form_revision_id
        assembly.current_revision_id = manifest.assessment_assembly_revision_id
        session.flush()

    @staticmethod
    def _fail(code: str, message: str) -> Never:
        raise MockExamAssemblyError(code, message)
