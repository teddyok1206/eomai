"""Official Catalog boundary for generated Item analysis publication into Graph RAG."""

from __future__ import annotations

from typing import NoReturn, Protocol

from eom_catalog_contracts.approved_item_graph_publication import (
    APPROVED_ITEM_GRAPH_PUBLICATION_COMMAND_SCHEMA,
    APPROVED_ITEM_GRAPH_PUBLICATION_RESULT_SCHEMA,
    ApprovedItemGraphPublicationResult,
    PublishApprovedItemAnalysesCommand,
)
from eom_catalog_contracts.item_review import (
    InspectMockExamReviewEligibilityQuery,
    MockExamReviewEligibilityResult,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    AutomaticItemCurriculumAlignmentBinding,
    KnowledgeGraphPublicationResult,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow import ContentTeamItemBrief
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_business_fingerprint,
)
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_item_graph_publication_service import (
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationReceipt,
    AutomaticItemGraphPublicationService,
)
from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    EducationRetrievalRequestRecord,
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
)
from eom_catalog_service.mock_exam_item_review_publication_service import (
    MockExamItemReviewPublicationError,
    MockExamItemReviewPublicationService,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord

_PRODUCTION_WORKFLOW_FAMILIES = {
    "1.8.0": (
        "workflow-role/1.17.0",
        "1.13.0",
        frozenset(
            {
                "eom.assessment.item-content/2.0",
                "eom://schemas/item-registry/assessment-item-content-v2",
            }
        ),
    ),
    "1.9.0": (
        "workflow-role/1.19.0",
        "1.14.0",
        frozenset(
            {
                "eom.assessment.item-content/3.0",
                "eom://schemas/item-registry/assessment-item-content-v3",
            }
        ),
    ),
}
_RETRIEVAL_NAMESPACE = "approved-item-auto-alignment"
_PUBLICATION_NAMESPACE = "approved-item-auto-graph"


class ApprovedItemGraphPublicationError(RuntimeError):
    """Stable failure raised before an invalid generated Item can enter Graph RAG."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MockExamReviewEligibilityResolver(Protocol):
    """Bounded official review resolver required before generated-Item Graph publication."""

    def inspect_eligibility_batch(
        self,
        queries: tuple[InspectMockExamReviewEligibilityQuery, ...],
    ) -> tuple[MockExamReviewEligibilityResult, ...]: ...


class ApprovedItemGraphPublicationService:
    """Publish generated one-Item workflow outputs after explicit analysis acceptance."""

    def __init__(
        self,
        engine: Engine,
        *,
        publication: KnowledgeGraphPublicationService | None = None,
        retrieval: KnowledgeRetrievalApplicationService | None = None,
        review_eligibility: MockExamReviewEligibilityResolver | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.publication = publication or KnowledgeGraphPublicationService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)
        self.review_eligibility = review_eligibility or MockExamItemReviewPublicationService(engine)

    def publish(
        self,
        command: PublishApprovedItemAnalysesCommand,
    ) -> ApprovedItemGraphPublicationResult:
        """Publish or replay one exact, bounded generated-Item analysis set."""

        validate_contract(
            APPROVED_ITEM_GRAPH_PUBLICATION_COMMAND_SCHEMA,
            command.model_dump(mode="json"),
        )
        publication_key = self._publication_idempotency_key(command)
        replay = self._existing_publication(command, publication_key)
        if replay is not None:
            return replay
        self._validate_input_pointers(command)
        self._validate_official_review_eligibility(command)

        expected_slot_unit_keys: tuple[str, ...] = ()

        def validate_origins(
            session: Session,
            analyses: tuple[AcceptedAnalysisProposal, ...],
        ) -> None:
            nonlocal expected_slot_unit_keys
            expected_slot_unit_keys = self._validate_current_v2_item_analyses(
                session,
                analyses,
                command.expected_workflow_ids,
            )

        common = AutomaticItemGraphPublicationService(
            self.engine,
            access_policy_revision_id=command.access_policy_revision_id,
            publication=self.publication,
            retrieval=self.retrieval,
        )
        candidates = tuple(
            AutomaticItemGraphCandidate(
                analysis_run_id=analysis_run_id,
                requested_by_operator_id=command.requested_by_operator_id,
                graph_snapshot_revision_id=(command.expected_current_graph_snapshot_revision_id),
            )
            for analysis_run_id in command.accepted_analysis_run_ids
        )
        try:
            receipt = common.publish(
                candidates,
                required_source_class="APPROVED_ITEM",
                retrieval_idempotency_namespace=_RETRIEVAL_NAMESPACE,
                publication_idempotency_namespace=_PUBLICATION_NAMESPACE,
                publisher_version="1.7.0",
                publication_idempotency_key=publication_key,
                publication_authorized_at=command.authorized_at,
                analysis_validator=validate_origins,
                alignment_validator=lambda alignments: self._validate_slot_unit_alignments(
                    command.accepted_analysis_run_ids,
                    expected_slot_unit_keys,
                    alignments,
                ),
            )
        except KnowledgeGraphPublicationError as exc:
            raise ApprovedItemGraphPublicationError(exc.code, str(exc)) from exc
        except ValueError as exc:
            message = str(exc)
            code = (
                "APPROVED_ITEM_GRAPH_ALREADY_PUBLISHED"
                if "already belongs" in message
                else "APPROVED_ITEM_GRAPH_ANALYSIS_INELIGIBLE"
            )
            raise ApprovedItemGraphPublicationError(code, message) from exc
        return self._result_from_created(command, receipt)

    def _validate_official_review_eligibility(
        self,
        command: PublishApprovedItemAnalysesCommand,
    ) -> None:
        queries = tuple(
            InspectMockExamReviewEligibilityQuery(workflow_id=workflow_id)
            for workflow_id in command.expected_workflow_ids
        )
        try:
            reviews = self.review_eligibility.inspect_eligibility_batch(queries)
        except MockExamItemReviewPublicationError as exc:
            raise ApprovedItemGraphPublicationError(
                "APPROVED_ITEM_GRAPH_REVIEW_INELIGIBLE",
                "official Workflow review eligibility could not be resolved",
            ) from exc
        if tuple(row.workflow_id for row in reviews) != command.expected_workflow_ids or any(
            row.approval_state != "APPROVED"
            or not row.eligible
            or row.finding_counts.blocking != 0
            or row.reviewer_operator_id != command.requested_by_operator_id
            or row.approved_at is None
            or row.approved_at > command.authorized_at
            for row in reviews
        ):
            raise ApprovedItemGraphPublicationError(
                "APPROVED_ITEM_GRAPH_REVIEW_INELIGIBLE",
                "every Workflow must have zero blocking findings and exact operator approval",
            )

    def _validate_input_pointers(self, command: PublishApprovedItemAnalysesCommand) -> None:
        """Resolve both caller-pinned revisions and hashes before any side effect."""

        with self.sessions() as session:
            snapshot = session.get(
                KnowledgeGraphSnapshotRecord,
                command.expected_current_graph_snapshot_revision_id,
            )
            policy = session.get(
                EducationRetrievalAccessPolicyRevisionRecord,
                command.access_policy_revision_id,
            )
            if (
                snapshot is None
                or snapshot.state != "PUBLISHED"
                or snapshot.snapshot_sha256 != command.expected_current_graph_snapshot_sha256
            ):
                raise ApprovedItemGraphPublicationError(
                    "APPROVED_ITEM_GRAPH_BASE_POINTER_INVALID",
                    "expected Graph snapshot revision and hash do not resolve exactly",
                )
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.corpus_key == command.corpus_key
                )
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.graph_id != snapshot.graph_id
                or corpus.current_graph_snapshot_revision_id
                != command.expected_current_graph_snapshot_revision_id
            ):
                raise ApprovedItemGraphPublicationError(
                    "KNOWLEDGE_GRAPH_STALE_CURRENT",
                    "knowledge corpus changed after Graph publication authorization",
                )
            if (
                policy is None
                or policy.state != "RELEASED"
                or policy.content_sha256 != command.access_policy_sha256
            ):
                raise ApprovedItemGraphPublicationError(
                    "APPROVED_ITEM_GRAPH_ACCESS_POLICY_INVALID",
                    "retrieval access policy revision and hash do not resolve exactly",
                )

    @staticmethod
    def _publication_idempotency_key(command: PublishApprovedItemAnalysesCommand) -> str:
        digest = content_sha256(
            {
                "idempotency_key": command.idempotency_key,
            }
        ).removeprefix("sha256:")
        return f"{_PUBLICATION_NAMESPACE}:{digest}"

    def _existing_publication(
        self,
        command: PublishApprovedItemAnalysesCommand,
        publication_key: str,
    ) -> ApprovedItemGraphPublicationResult | None:
        with self.sessions() as session:
            publication = session.scalar(
                select(KnowledgeGraphPublicationRecord).where(
                    KnowledgeGraphPublicationRecord.idempotency_key == publication_key
                )
            )
            if publication is None:
                return None
            snapshot = session.get(
                KnowledgeGraphSnapshotRecord,
                publication.graph_snapshot_revision_id,
            )
            if snapshot is None:
                self._raise_replay_conflict("replayed Graph snapshot pointer is dangling")
            assert snapshot is not None
            prior_ids = (
                set(
                    session.scalars(
                        select(KnowledgeSnapshotAnalysisRecord.analysis_run_id).where(
                            KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                            == snapshot.previous_graph_snapshot_revision_id
                        )
                    )
                )
                if snapshot.previous_graph_snapshot_revision_id is not None
                else set()
            )
            published_ids = set(
                session.scalars(
                    select(KnowledgeSnapshotAnalysisRecord.analysis_run_id).where(
                        KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                        == snapshot.graph_snapshot_revision_id
                    )
                )
            )
            requested_ids = set(command.accepted_analysis_run_ids)
            if (
                snapshot.previous_graph_snapshot_revision_id
                != command.expected_current_graph_snapshot_revision_id
                or publication.published_by_operator_id != command.requested_by_operator_id
                or publication.authorized_at != command.authorized_at
                or not prior_ids.issubset(published_ids)
                or published_ids - prior_ids != requested_ids
            ):
                self._raise_replay_conflict(
                    "Graph publication idempotency identity has different input"
                )
            item_revision_ids = self._replay_item_revision_ids(session, command)
            self._validate_replay_retrievals(session, command)
            try:
                graph_result = KnowledgeGraphPublicationService._result(session, publication)
            except KnowledgeGraphPublicationError as exc:
                raise ApprovedItemGraphPublicationError(exc.code, str(exc)) from exc
            return self._build_result(
                command=command,
                graph_result=graph_result,
                graph_snapshot_sha256=snapshot.snapshot_sha256,
                item_revision_ids=item_revision_ids,
                outcome="REPLAYED",
            )

    @staticmethod
    def _replay_item_revision_ids(
        session: Session,
        command: PublishApprovedItemAnalysesCommand,
    ) -> tuple[str, ...]:
        rows = tuple(
            session.execute(
                select(
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                    KnowledgeAnalysisRunRecord.item_revision_id,
                    ItemRevisionRecord.workflow_id,
                )
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeAnalysisRunRecord.item_revision_id,
                )
                .where(
                    KnowledgeAnalysisRunRecord.analysis_run_id.in_(
                        command.accepted_analysis_run_ids
                    )
                )
            )
        )
        pointers_by_run = {
            analysis_run_id: (item_revision_id, workflow_id)
            for analysis_run_id, item_revision_id, workflow_id in rows
            if item_revision_id is not None
        }
        if set(pointers_by_run) != set(command.accepted_analysis_run_ids):
            ApprovedItemGraphPublicationService._raise_replay_conflict(
                "replayed analysis-to-Item pointers do not resolve exactly"
            )
        if (
            tuple(pointers_by_run[run_id][1] for run_id in command.accepted_analysis_run_ids)
            != command.expected_workflow_ids
        ):
            ApprovedItemGraphPublicationService._raise_replay_conflict(
                "replayed analysis-to-Workflow pointers differ from the command"
            )
        return tuple(pointers_by_run[run_id][0] for run_id in command.accepted_analysis_run_ids)

    @staticmethod
    def _validate_replay_retrievals(
        session: Session,
        command: PublishApprovedItemAnalysesCommand,
    ) -> None:
        keys = {
            run_id: (
                f"{_RETRIEVAL_NAMESPACE}:{run_id}:"
                f"{command.expected_current_graph_snapshot_revision_id}"
            )
            for run_id in command.accepted_analysis_run_ids
        }
        rows = tuple(
            session.scalars(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key.in_(keys.values())
                )
            )
        )
        by_key = {row.idempotency_key: row for row in rows}
        if len(by_key) != len(keys):
            ApprovedItemGraphPublicationService._raise_replay_conflict(
                "replayed automatic alignment evidence is missing"
            )
        if any(
            (row := by_key[keys[run_id]]).access_policy_revision_id
            != command.access_policy_revision_id
            or row.graph_snapshot_revision_id != command.expected_current_graph_snapshot_revision_id
            or row.requester_operator_id != command.requested_by_operator_id
            or row.state != "PUBLISHED"
            for run_id in command.accepted_analysis_run_ids
        ):
            ApprovedItemGraphPublicationService._raise_replay_conflict(
                "replayed automatic alignment evidence has different input"
            )

    @staticmethod
    def _validate_current_v2_item_analyses(
        session: Session,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        expected_workflow_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        run_ids = tuple(analysis.analysis_run_id for analysis in analyses)
        if len(run_ids) != len(expected_workflow_ids):
            raise ValueError("analysis and expected Workflow sets are not aligned")
        rows = tuple(
            session.execute(
                select(
                    KnowledgeAnalysisRunRecord,
                    ItemRevisionRecord,
                    ItemRecord,
                    WorkflowInstanceRecord,
                    WorkflowDefinitionRecord,
                )
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeAnalysisRunRecord.item_revision_id,
                )
                .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
                .join(
                    WorkflowInstanceRecord,
                    WorkflowInstanceRecord.workflow_id == ItemRevisionRecord.workflow_id,
                )
                .join(
                    WorkflowDefinitionRecord,
                    WorkflowDefinitionRecord.definition_id == WorkflowInstanceRecord.definition_id,
                )
                .where(KnowledgeAnalysisRunRecord.analysis_run_id.in_(run_ids))
            )
        )
        by_run = {
            run.analysis_run_id: (run, revision, item, workflow, definition)
            for run, revision, item, workflow, definition in rows
        }
        if len(by_run) != len(run_ids):
            raise ValueError("accepted generated Item analysis pointer is missing")
        production_request_ids: set[str] = set()
        workflow_call_ids: set[str] = set()
        workflow_family_versions: set[str] = set()
        slot_positions: list[int] = []
        slot_unit_keys: list[str] = []
        for analysis, expected_workflow_id in zip(
            analyses,
            expected_workflow_ids,
            strict=True,
        ):
            source = analysis.source
            run, revision, item, workflow, definition = by_run[analysis.analysis_run_id]
            request_source = run.canonical_request.get("source")
            try:
                workflow_request = load_persisted_workflow_request(workflow.initial_request)
            except PydanticValidationError as exc:
                raise ValueError("generated Item Workflow request is invalid") from exc
            occurrence = workflow_request.production_occurrence
            expected_resolution = workflow_request.expected_resolution
            registration = workflow.runtime_context.get("item_registration")
            accepted_resolution = workflow.runtime_context.get("accepted_resolution")
            family = _PRODUCTION_WORKFLOW_FAMILIES.get(revision.workflow_definition_version or "")
            if family is None:
                raise ValueError("generated Item Workflow version is unsupported")
            role_protocol, pack_version, content_schema_refs = family
            family_version = revision.workflow_definition_version
            if (
                not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or source.source_class != "APPROVED_ITEM"
                or source.artifact_member.schema_ref not in content_schema_refs
                or analysis.accepted_result.schema_ref
                != "eom://schemas/knowledge/knowledge-analysis-result/2.0"
                or run.state != "ACCEPTED"
                or run.source_kind != "APPROVED_ITEM_REVISION"
                or run.canonical_request.get("schema_version") != "knowledge-analysis-request/2.0"
                or not isinstance(request_source, dict)
                or request_source.get("source_class") != "APPROVED_ITEM"
                or run.item_id != source.item_id
                or run.item_revision_id != source.item_revision_id
                or revision.item_id != source.item_id
                or revision.workflow_id != expected_workflow_id
                or revision.revision_number != 1
                or revision.revision_state != "APPROVED"
                or item.lifecycle_state != "ACTIVE"
                or item.current_revision_id != source.item_revision_id
                or workflow.workflow_id != expected_workflow_id
                or workflow.definition_key != "generic-item-development"
                or workflow.definition_version != family_version
                or workflow.definition_hash != definition.definition_hash
                or workflow.definition_id != definition.definition_id
                or workflow.role_schema_version != role_protocol
                or workflow.state != "COMPLETED"
                or workflow.stage != "COMPLETED"
                or workflow.current_step_key != "complete"
                or workflow.completed_at is None
                or workflow.request_payload != workflow.initial_request
                or workflow.request_hash
                != workflow_business_fingerprint(
                    definition,
                    workflow_request,
                )
                or definition.definition_key != "generic-item-development"
                or definition.definition_version != family_version
                or definition.definition_hash != content_sha256(definition.canonical_definition)
                or workflow_request.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
                or workflow_request.registry_intent is None
                or workflow_request.registry_intent.mode != "CREATE_ITEM"
                or workflow_request.content_pack is None
                or workflow_request.content_pack.pack_key != "generated-knowledge-item"
                or workflow_request.execution_preset_key != "knowledge-grounded-item"
                or not isinstance(workflow_request.item_brief, ContentTeamItemBrief)
                or workflow_request.item_brief.mock_exam_slot is None
                or occurrence is None
                or expected_resolution is None
                or expected_resolution.workflow_definition_key != "generic-item-development"
                or expected_resolution.workflow_definition_version != family_version
                or expected_resolution.workflow_definition_sha256 != workflow.definition_hash
                or expected_resolution.content_pack_release_id != revision.content_pack_release_id
                or expected_resolution.content_pack_version != pack_version
                or accepted_resolution != expected_resolution.model_dump(mode="json")
                or not isinstance(registration, dict)
                or registration.get("item_id") != source.item_id
                or registration.get("item_revision_id") != source.item_revision_id
                or registration.get("revision_number") != 1
            ):
                raise ValueError(
                    "analysis must resolve to one fresh completed supported paired "
                    "generic-item-development "
                    "CREATE_ITEM Workflow and its active current approved Item"
                )
            production_request_ids.add(occurrence.production_request_id)
            workflow_call_ids.add(occurrence.workflow_call_id)
            workflow_family_versions.add(family_version)
            slot_positions.append(workflow_request.item_brief.mock_exam_slot.position)
            slot_unit_keys.append(
                workflow_request.item_brief.mock_exam_slot.curriculum_selected_unit_key
            )
        if (
            len(production_request_ids) != 1
            or len(workflow_call_ids) != len(analyses)
            or len(workflow_family_versions) != 1
            or tuple(slot_positions) != tuple(range(1, 26))
        ):
            raise ValueError(
                "published Workflows must be 25 ordered unique CREATE_ITEM calls from one "
                "production request"
            )
        return tuple(slot_unit_keys)

    @staticmethod
    def _validate_slot_unit_alignments(
        analysis_run_ids: tuple[str, ...],
        expected_unit_keys: tuple[str, ...],
        alignments: tuple[AutomaticItemCurriculumAlignmentBinding, ...],
    ) -> None:
        unit_id_by_key = {
            row.unit_key: row.curriculum_unit_id for row in integrated_science_curriculum_units()
        }
        if not (len(analysis_run_ids) == len(expected_unit_keys) == len(alignments) == 25):
            raise ValueError("generated Item slot and alignment sets are not exact")
        for analysis_run_id, unit_key, alignment in zip(
            analysis_run_ids,
            expected_unit_keys,
            alignments,
            strict=True,
        ):
            expected_unit_id = unit_id_by_key.get(unit_key)
            if (
                alignment.analysis_run_id != analysis_run_id
                or expected_unit_id is None
                or expected_unit_id not in alignment.curriculum_unit_ids
            ):
                raise ValueError(
                    "automatic alignment does not include its originating mock-exam slot unit"
                )

    def _result_from_created(
        self,
        command: PublishApprovedItemAnalysesCommand,
        receipt: AutomaticItemGraphPublicationReceipt,
    ) -> ApprovedItemGraphPublicationResult:
        revision_ids = tuple(binding.item_revision_id for binding in receipt.alignments)
        with self.sessions() as session:
            snapshot = session.get(
                KnowledgeGraphSnapshotRecord,
                receipt.graph_publication.graph_snapshot.graph_snapshot_revision_id,
            )
            if snapshot is None:
                raise ApprovedItemGraphPublicationError(
                    "APPROVED_ITEM_GRAPH_RESULT_POINTER_INVALID",
                    "published Graph snapshot pointer does not resolve",
                )
            return self._build_result(
                command=command,
                graph_result=receipt.graph_publication,
                graph_snapshot_sha256=snapshot.snapshot_sha256,
                item_revision_ids=revision_ids,
                outcome="CREATED",
            )

    @staticmethod
    def _build_result(
        *,
        command: PublishApprovedItemAnalysesCommand,
        graph_result: KnowledgeGraphPublicationResult,
        graph_snapshot_sha256: str,
        item_revision_ids: tuple[str, ...],
        outcome: str,
    ) -> ApprovedItemGraphPublicationResult:
        publication_id = graph_result.publication_id
        corpus_key = graph_result.corpus_key
        graph_snapshot = graph_result.graph_snapshot
        revision_number = graph_result.revision_number
        published_at = graph_result.published_at
        value: dict[str, object] = {
            "schema_version": "approved-item-graph-publication-result/1.0",
            "publication_id": publication_id,
            "corpus_key": corpus_key,
            "previous_graph_snapshot_revision_id": (
                command.expected_current_graph_snapshot_revision_id
            ),
            "previous_graph_snapshot_sha256": (command.expected_current_graph_snapshot_sha256),
            "graph_snapshot": graph_snapshot.model_dump(mode="json"),
            "graph_snapshot_sha256": graph_snapshot_sha256,
            "revision_number": revision_number,
            "accepted_analysis_run_ids": list(command.accepted_analysis_run_ids),
            "expected_workflow_ids": list(command.expected_workflow_ids),
            "item_revision_ids": list(item_revision_ids),
            "authorized_at": command.authorized_at.isoformat().replace("+00:00", "Z"),
            "outcome": outcome,
            "published_at": published_at.isoformat().replace("+00:00", "Z"),
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        result = ApprovedItemGraphPublicationResult.model_validate(value)
        validate_contract(
            APPROVED_ITEM_GRAPH_PUBLICATION_RESULT_SCHEMA,
            result.model_dump(mode="json"),
        )
        return result

    @staticmethod
    def _raise_replay_conflict(message: str) -> NoReturn:
        raise ApprovedItemGraphPublicationError(
            "APPROVED_ITEM_GRAPH_IDEMPOTENCY_CONFLICT",
            message,
        )
