"""Official origin-scoped Graph publication for ordinary registered @11/@12 Items."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NoReturn

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    AutomaticItemCurriculumAlignmentBindingV2,
    CurriculumRetrievalScope,
)
from eom_catalog_contracts.ordinary_item_graph_publication import (
    ORDINARY_ITEM_GRAPH_COMMAND_SCHEMA,
    ORDINARY_ITEM_GRAPH_RESULT_SCHEMA,
    OrdinaryItemGraphPublicationResult,
    PublishOrdinaryApprovedItemAnalysesCommand,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_identity_service.models import (
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import (
    ResolvedExecutionPlanV11,
    ResolvedExecutionPlanV12,
    ResolvedExecutionPlanV16,
    ResolvedExecutionPlanV17,
    ResolvedExecutionPlanV19,
)
from eom_workflow.similarity_control import parse_post_registration_grounded_plan
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_business_fingerprint,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_curriculum_alignment import (
    AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
)
from eom_catalog_service.automatic_item_graph_publication_service import (
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
)
from eom_catalog_service.evidence_usage_receipts import OrchestratorEvidenceUsageReceiptResolver
from eom_catalog_service.knowledge_graph_models import (
    CurriculumUnitRecord,
    EducationRetrievalAccessPolicyRevisionRecord,
    EducationRetrievalRequestRecord,
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.registered_item_review_solution_resolver import (
    lock_registered_item_review_sources,
    resolve_registered_item_review_solutions,
)

_RETRIEVAL_NAMESPACE = "ordinary-item-origin-align"
_PUBLICATION_NAMESPACE = "ordinary-item-graph"
_FAMILIES: dict[
    str, tuple[str, type[ResolvedExecutionPlanV11] | type[ResolvedExecutionPlanV12]]
] = {
    "1.11.0": ("workflow-role/1.23.0", ResolvedExecutionPlanV11),
    "1.12.0": ("workflow-role/1.23.0", ResolvedExecutionPlanV11),
    "1.13.0": ("workflow-role/1.24.0", ResolvedExecutionPlanV12),
    "1.14.0": ("workflow-role/1.24.0", ResolvedExecutionPlanV16),
    "1.15.0": ("workflow-role/1.24.0", ResolvedExecutionPlanV17),
    "1.16.0": ("workflow-role/1.24.0", ResolvedExecutionPlanV19),
}
_REQUIRED_PERMISSIONS = frozenset(
    {
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.KNOWLEDGE_GRAPH_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
    }
)


class OrdinaryItemGraphPublicationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(reason: str) -> NoReturn:
    raise OrdinaryItemGraphPublicationError("ORDINARY_ITEM_GRAPH_" + reason)


class OrdinaryItemGraphPublicationService:
    """No analysis creation, source grants, occurrence fabrication or implicit latest."""

    def __init__(
        self,
        engine: Engine,
        *,
        publication: KnowledgeGraphPublicationService | None = None,
        retrieval: KnowledgeRetrievalApplicationService | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.publication = publication or KnowledgeGraphPublicationService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)
        self.receipts = OrchestratorEvidenceUsageReceiptResolver(self.sessions)

    def publish(
        self,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
    ) -> OrdinaryItemGraphPublicationResult:
        command = PublishOrdinaryApprovedItemAnalysesCommand.model_validate(
            raw_similarity_contract_value(command)
        )
        validate_contract(ORDINARY_ITEM_GRAPH_COMMAND_SCHEMA, command.model_dump(mode="json"))
        key = (
            _PUBLICATION_NAMESPACE
            + ":"
            + content_sha256({"idempotency_key": command.idempotency_key}).removeprefix("sha256:")
        )
        with self.sessions() as session:
            self._authorize(session, command)
            replay = session.scalar(
                select(KnowledgeGraphPublicationRecord).where(
                    KnowledgeGraphPublicationRecord.idempotency_key == key
                )
            )
            if replay is not None:
                # Use the existing bounded public accepted-analysis resolver. A replay
                # still reauthorizes the exact immutable source, never the new head.
                analyses = tuple(
                    row.analysis
                    for offset in range(0, len(command.sources), 3)
                    for row in self.publication.resolve_accepted_analyses(
                        session,
                        tuple(
                            value.analysis_run_id for value in command.sources[offset : offset + 3]
                        ),
                    ).values()
                )
                self._validate_current(session, command, analyses)
                return self._result(session, command, replay, "REPLAYED")
            self._validate_base(session, command)

        common = AutomaticItemGraphPublicationService(
            self.engine,
            access_policy_revision_id=command.access_policy_revision_id,
            publication=self.publication,
            retrieval=self.retrieval,
        )
        receipt = common.publish(
            tuple(
                AutomaticItemGraphCandidate(
                    value.analysis_run_id,
                    command.requested_by_operator_id,
                    command.expected_graph_snapshot.graph_snapshot_revision_id,
                )
                for value in command.sources
            ),
            required_source_class="APPROVED_ITEM",
            retrieval_idempotency_namespace=_RETRIEVAL_NAMESPACE,
            publication_idempotency_namespace=_PUBLICATION_NAMESPACE,
            publisher_version="1.9.0",
            publication_idempotency_key=key,
            publication_authorized_at=command.authorized_at,
            analysis_validator=lambda session, analyses: self._validate_current(
                session, command, analyses
            ),
            alignment_scope_resolver=lambda session, context, analyses: self._scopes(
                session, context, command
            ),
            alignment_validator=lambda values: self._validate_alignments(command, values),
        )
        with self.sessions() as session:
            publication = session.get(
                KnowledgeGraphPublicationRecord, receipt.graph_publication.publication_id
            )
            if publication is None:
                _fail("PUBLICATION_MISSING")
            assert publication is not None
            return self._result(session, command, publication, "CREATED")

    def _validate_base(
        self,
        session: Session,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
    ) -> None:
        snapshot = self._validate_pinned_base(session, command)
        prior = command.expected_graph_snapshot
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == command.corpus_key
            )
        )
        if (
            snapshot is None
            or snapshot.snapshot_sha256 != command.expected_graph_snapshot_sha256
            or corpus is None
            or corpus.lifecycle_state != "ACTIVE"
            or corpus.graph_id != prior.graph_id
            or corpus.current_graph_snapshot_revision_id != prior.graph_snapshot_revision_id
        ):
            _fail("STALE_CURRENT")

    def _validate_pinned_base(
        self, session: Session, command: PublishOrdinaryApprovedItemAnalysesCommand
    ) -> KnowledgeGraphSnapshotRecord:
        prior = command.expected_graph_snapshot
        snapshot = session.scalar(
            select(KnowledgeGraphSnapshotRecord)
            .where(
                KnowledgeGraphSnapshotRecord.graph_snapshot_revision_id
                == prior.graph_snapshot_revision_id
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            snapshot is None
            or snapshot.state != "PUBLISHED"
            or snapshot.snapshot_sha256 != command.expected_graph_snapshot_sha256
            or self.retrieval.resolve_snapshot_pointer(session, prior.graph_snapshot_revision_id)
            != prior
        ):
            _fail("BASE_POINTER_INVALID")
        return snapshot

    def _authorize(
        self,
        session: Session,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
    ) -> None:
        # Row locks cover only the actual actor's existing grants. Revocation cannot
        # race the final publication, but no identity-wide/NAS outer lock is held.
        actor = session.scalar(
            select(OperatorRecord)
            .where(OperatorRecord.operator_id == command.requested_by_operator_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        assignments = tuple(
            session.scalars(
                select(OperatorRoleAssignmentRecord)
                .where(
                    OperatorRoleAssignmentRecord.operator_id == command.requested_by_operator_id,
                    OperatorRoleAssignmentRecord.revoked_at.is_(None),
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        role_ids = tuple(row.role_id for row in assignments)
        roles = tuple(
            session.scalars(
                select(RoleRecord)
                .where(RoleRecord.role_id.in_(role_ids))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        permissions = tuple(
            session.scalars(
                select(RolePermissionRecord)
                .where(RolePermissionRecord.role_id.in_(role_ids))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        permission_rows = tuple(
            session.scalars(
                select(PermissionRecord)
                .where(
                    PermissionRecord.permission_id.in_(
                        tuple(row.permission_id for row in permissions)
                    )
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        policy_row = session.scalar(
            select(EducationRetrievalAccessPolicyRevisionRecord)
            .where(
                EducationRetrievalAccessPolicyRevisionRecord.access_policy_revision_id
                == command.access_policy_revision_id
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            actor is None
            or actor.status != "ACTIVE"
            or actor.deleted_at is not None
            or actor.must_change_password
            or not roles
            or not permission_rows
            or "ADMIN"
            not in {
                role.role_key
                for _assignment, role in active_role_assignments(
                    session, command.requested_by_operator_id
                )
            }
            or not _REQUIRED_PERMISSIONS.issubset(
                effective_permissions(session, command.requested_by_operator_id)
            )
            or policy_row is None
            or policy_row.state != "RELEASED"
            or policy_row.content_sha256 != command.access_policy_sha256
        ):
            _fail("FORBIDDEN")
        policy = self.retrieval.resolve_access_policy(
            session, command.access_policy_revision_id, sha256=command.access_policy_sha256
        )
        if (
            "ADMIN" not in policy.allowed_requester_roles
            or "ITEM_PREPARATION" not in policy.allowed_query_kinds
            or not {"APPROVED_ITEM", "CURRICULUM", "TEXTBOOK"}.issubset(
                set(policy.allowed_source_classes)
            )
            or any(
                getattr(policy.maximum_budget, name) < value
                for name, value in AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET.items()
            )
        ):
            _fail("FORBIDDEN")

    def _validate_current(
        self,
        session: Session,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
        analyses: tuple[AcceptedAnalysisProposal, ...],
    ) -> None:
        if session.new or session.dirty or session.deleted:
            _fail("PENDING_MUTATION")
        self._authorize(session, command)
        self._validate_pinned_base(session, command)
        if tuple(row.analysis_run_id for row in analyses) != tuple(
            row.analysis_run_id for row in command.sources
        ) or any(
            analysis.source != selected.source
            or analysis.accepted_result != selected.accepted_result
            for analysis, selected in zip(analyses, command.sources, strict=True)
        ):
            _fail("ANALYSIS_POINTER_INVALID")
        sources = tuple(row.source for row in command.sources)
        workflow_ids = tuple(row.workflow_id for row in command.sources)
        runs = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord)
                .where(
                    KnowledgeAnalysisRunRecord.analysis_run_id.in_(
                        tuple(row.analysis_run_id for row in command.sources)
                    )
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        revisions = tuple(
            session.scalars(
                select(ItemRevisionRecord)
                .where(
                    ItemRevisionRecord.item_revision_id.in_(
                        tuple(row.item_revision_id for row in sources)
                    )
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        items = tuple(
            session.scalars(
                select(ItemRecord)
                .where(ItemRecord.item_id.in_(tuple(row.item_id for row in sources)))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        locked = lock_registered_item_review_sources(session, sources=sources)
        workflows = locked.workflows
        definitions = tuple(
            session.scalars(
                select(WorkflowDefinitionRecord)
                .where(
                    WorkflowDefinitionRecord.definition_id.in_(
                        tuple(row.definition_id for row in workflows)
                    )
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        plans = tuple(
            session.scalars(
                select(ResolvedExecutionPlanRecord)
                .where(ResolvedExecutionPlanRecord.workflow_id.in_(workflow_ids))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        # Registration-role proof locks are shared with mixed embedding capture.
        # This publisher additionally owns accepted-base and predecessor Graph pins.
        artifact_ids = {row.accepted_result.artifact_id for row in command.sources}
        revision_ids = {row.accepted_result.artifact_revision_id for row in command.sources}
        artifact_ids.add(command.expected_graph_snapshot.manifest_artifact.artifact_id)
        revision_ids.add(command.expected_graph_snapshot.manifest_artifact.artifact_revision_id)
        artifact_ids.update(row.proposal_artifact_id for row in runs if row.proposal_artifact_id)
        revision_ids.update(
            row.proposal_artifact_revision_id for row in runs if row.proposal_artifact_revision_id
        )
        logicals = tuple(
            session.scalars(
                select(ArtifactRecord)
                .where(ArtifactRecord.logical_artifact_id.in_(artifact_ids))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        artifacts = tuple(
            session.scalars(
                select(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.revision_id.in_(revision_ids))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        jobs = tuple(
            session.scalars(
                select(JobRecord)
                .where(JobRecord.job_id.in_(tuple(row.job_id for row in artifacts)))
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        self._validate_origins(command, runs, revisions, items, workflows, definitions, plans)
        if (
            {row.logical_artifact_id for row in logicals} != artifact_ids
            or {row.revision_id for row in artifacts} != revision_ids
            or {row.job_id for row in jobs} != {row.job_id for row in artifacts}
            or any(not row.approved for row in (*logicals, *locked.logicals))
            or any(not row.approved for row in (*artifacts, *locked.artifacts))
            or any(row.status != "SUCCEEDED" for row in (*jobs, *locked.jobs))
        ):
            _fail("PRODUCER_WITHDRAWN")

        # The public accepted-analysis owner revalidates actual bytes, manifest,
        # source and producer; its existing three-source bound is preserved.
        current = tuple(
            value.analysis
            for offset in range(0, len(command.sources), 3)
            for value in self.publication.resolve_accepted_analyses(
                session,
                tuple(row.analysis_run_id for row in command.sources[offset : offset + 3]),
            ).values()
        )
        if current != analyses:
            _fail("ANALYSIS_POINTER_INVALID")
        allowed = {row.item_revision_id: row for row in sources}
        items_by_id = {row.item_id: row for row in items}
        revisions_by_id = {row.item_revision_id: row for row in revisions}

        def authorize_source(source: ApprovedItemKnowledgeSourceV2) -> None:
            # Permissions/policy and these current rows are already locked in this
            # root. Per-source callbacks stay O(1), without repeating RBAC queries.
            item = items_by_id.get(source.item_id)
            revision = revisions_by_id.get(source.item_revision_id)
            if (
                allowed.get(source.item_revision_id) != source
                or item is None
                or revision is None
                or item.lifecycle_state != "ACTIVE"
                or item.current_revision_id != source.item_revision_id
                or revision.revision_state != "APPROVED"
            ):
                _fail("SOURCE_INVALID")

        resolved = resolve_registered_item_review_solutions(
            session,
            sources=sources,
            artifacts=self.publication.artifacts,
            receipts=self.receipts,
            authorize_source=authorize_source,
        )
        if len(resolved) != len(command.sources) or any(
            row.evidence.workflow_id != selected.workflow_id
            or row.evidence.evidence_sha256 != selected.review_evidence_sha256
            for row, selected in zip(resolved, command.sources, strict=True)
        ):
            _fail("REVIEW_POINTER_INVALID")
        self._authorize(session, command)
        locked.assert_current(session)
        # References must outlive all Session.get calls in the batch proof.
        del locked, logicals, artifacts, jobs

    @staticmethod
    def _validate_origins(
        command: PublishOrdinaryApprovedItemAnalysesCommand,
        runs: Sequence[KnowledgeAnalysisRunRecord],
        revisions: Sequence[ItemRevisionRecord],
        items: Sequence[ItemRecord],
        workflows: Sequence[WorkflowInstanceRecord],
        definitions: Sequence[WorkflowDefinitionRecord],
        plans: Sequence[ResolvedExecutionPlanRecord],
    ) -> None:
        run_map = {row.analysis_run_id: row for row in runs}
        revision_map = {row.item_revision_id: row for row in revisions}
        item_map = {row.item_id: row for row in items}
        workflow_map = {row.workflow_id: row for row in workflows}
        definition_map = {row.definition_id: row for row in definitions}
        plan_map = {row.workflow_id: row for row in plans}
        for selected in command.sources:
            source = selected.source
            run, revision, item = (
                run_map.get(selected.analysis_run_id),
                revision_map.get(source.item_revision_id),
                item_map.get(source.item_id),
            )
            workflow, record = (
                workflow_map.get(selected.workflow_id),
                plan_map.get(selected.workflow_id),
            )
            if (
                run is None
                or revision is None
                or item is None
                or workflow is None
                or record is None
            ):
                _fail("ORIGIN_MISSING")
            assert run and revision and item and workflow and record
            definition = definition_map.get(workflow.definition_id)
            family = _FAMILIES.get(workflow.definition_version)
            if definition is None or family is None:
                _fail("ORIGIN_UNSUPPORTED")
            assert definition is not None and family is not None
            request = load_persisted_workflow_request(workflow.initial_request)
            plan = (
                parse_post_registration_grounded_plan(record.canonical_document)
                if workflow.definition_version == "1.16.0"
                else family[1].model_validate(record.canonical_document)
            )
            brief = request.item_brief
            scope = getattr(brief, "curriculum_scope", None)
            pack = workflow.runtime_context.get("content_pack")
            if (
                run.state != "ACCEPTED"
                or run.source_kind != "APPROVED_ITEM_REVISION"
                or run.item_id != source.item_id
                or run.item_revision_id != source.item_revision_id
                or run.canonical_request.get("schema_version") != "knowledge-analysis-request/2.0"
                or run.canonical_request.get("source") != source.model_dump(mode="json")
                or run.accepted_result_artifact_id != selected.accepted_result.artifact_id
                or run.accepted_result_artifact_revision_id
                != selected.accepted_result.artifact_revision_id
                or run.accepted_result_sha256 != selected.accepted_result.sha256
                or revision.item_id != source.item_id
                or revision.workflow_id != selected.workflow_id
                or revision.revision_state != "APPROVED"
                or item.lifecycle_state != "ACTIVE"
                or item.current_revision_id != source.item_revision_id
                or workflow.definition_key != "generic-item-development"
                or workflow.role_schema_version != family[0]
                or revision.workflow_definition_version != workflow.definition_version
                or workflow.definition_hash != definition.definition_hash
                or definition.definition_key != workflow.definition_key
                or definition.definition_version != workflow.definition_version
                or definition.definition_hash != content_sha256(definition.canonical_definition)
                or workflow.state != "COMPLETED"
                or workflow.stage != "COMPLETED"
                or workflow.current_step_key != "complete"
                or workflow.completed_at is None
                or workflow.initial_request != workflow.request_payload
                or workflow.request_hash != workflow_business_fingerprint(definition, request)
                or request.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
                or request.registry_intent is None
                or request.registry_intent.mode != "CREATE_ITEM"
                or request.content_pack is None
                or request.content_pack.pack_key != "generated-knowledge-item"
                or request.production_occurrence is not None
                or scope is None
                or scope.selected_level != "MIDDLE"
                or scope.selected_unit_key != selected.expected_curriculum_unit_key
                or request.educational_retrieval is None
                or request.educational_retrieval.corpus_key != command.corpus_key
                or plan.retrieval_requirement != request.educational_retrieval
                or not isinstance(pack, dict)
                or pack.get("release_id") != revision.content_pack_release_id
                or pack.get("release_id") != plan.content_pack_release_id
                or pack.get("release_sha256") != plan.content_pack_sha256
                or plan.workflow_id != workflow.workflow_id
                or plan.plan_id != record.plan_id
                or plan.workflow_definition_key != workflow.definition_key
                or plan.workflow_definition_version != workflow.definition_version
                or plan.workflow_definition_sha256 != workflow.definition_hash
                or plan.plan_sha256 != selected.expected_plan_sha256
                or record.plan_sha256 != plan.plan_sha256
                or record.resolved_at != plan.resolved_at
                or record.preset_id != plan.preset_id
                or record.preset_revision_id != plan.preset_revision_id
                or record.capacity_policy_revision_id != plan.capacity_policy_revision_id
                or record.graph_snapshot_revision_id
                != plan.graph_snapshot.graph_snapshot_revision_id
                or record.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
            ):
                _fail("ORIGIN_INVALID")

    @staticmethod
    def _scopes(
        session: Session,
        context: CurrentKnowledgeGraphStructure,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
    ) -> tuple[CurriculumRetrievalScope, ...]:
        by_key = {row.unit_key: row for row in context.structure.curriculum_units}
        selected = tuple(by_key.get(row.expected_curriculum_unit_key) for row in command.sources)
        if any(row is None or row.unit_level != "MINOR" for row in selected):
            _fail("UNIT_INVALID")
        unit_ids = tuple(row.curriculum_unit_id for row in selected if row is not None)
        rows = tuple(
            session.execute(
                select(CurriculumUnitRecord, KnowledgeNodeRecord)
                .join(
                    KnowledgeNodeRecord,
                    (
                        KnowledgeNodeRecord.graph_snapshot_revision_id
                        == CurriculumUnitRecord.graph_snapshot_revision_id
                    )
                    & (KnowledgeNodeRecord.node_id == CurriculumUnitRecord.node_id),
                )
                .where(
                    CurriculumUnitRecord.graph_snapshot_revision_id
                    == context.graph_snapshot_revision_id,
                    CurriculumUnitRecord.curriculum_unit_id.in_(unit_ids),
                )
            )
        )
        nodes = {unit.curriculum_unit_id: (unit, node) for unit, node in rows}
        scopes = []
        for unit in selected:
            assert unit is not None
            pair = nodes.get(unit.curriculum_unit_id)
            if (
                pair is None
                or pair[0].framework_revision_id != unit.framework_revision_id
                or pair[0].unit_level != "MINOR"
                or pair[1].stable_key != unit.node_stable_key
            ):
                _fail("UNIT_INVALID")
            scopes.append(
                CurriculumRetrievalScope(
                    framework_revision_id=unit.framework_revision_id,
                    root_unit_id=unit.curriculum_unit_id,
                    include_descendants=False,
                )
            )
        return tuple(scopes)

    @staticmethod
    def _validate_alignments(
        command: PublishOrdinaryApprovedItemAnalysesCommand,
        values: tuple[AutomaticItemCurriculumAlignmentBindingV2, ...],
    ) -> None:
        from eom_catalog_service.curriculum_graph_structure import (
            integrated_science_curriculum_units,
        )

        units = {
            row.unit_key: row.curriculum_unit_id for row in integrated_science_curriculum_units()
        }
        if len(values) != len(command.sources) or any(
            value.analysis_run_id != selected.analysis_run_id
            or value.curriculum_unit_ids != (units.get(selected.expected_curriculum_unit_key),)
            for value, selected in zip(values, command.sources, strict=True)
        ):
            _fail("ALIGNMENT_INVALID")

    def _result(
        self,
        session: Session,
        command: PublishOrdinaryApprovedItemAnalysesCommand,
        publication: KnowledgeGraphPublicationRecord,
        outcome: str,
    ) -> OrdinaryItemGraphPublicationResult:
        snapshot = session.get(KnowledgeGraphSnapshotRecord, publication.graph_snapshot_revision_id)
        prior = command.expected_graph_snapshot
        predecessor = session.get(KnowledgeGraphSnapshotRecord, prior.graph_snapshot_revision_id)
        previous_ids = set(
            session.scalars(
                select(KnowledgeSnapshotAnalysisRecord.analysis_run_id).where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                    == prior.graph_snapshot_revision_id
                )
            )
        )
        current_ids = set(
            session.scalars(
                select(KnowledgeSnapshotAnalysisRecord.analysis_run_id).where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                    == publication.graph_snapshot_revision_id
                )
            )
        )
        retrievals = tuple(
            session.scalars(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key.in_(
                        tuple(
                            f"{_RETRIEVAL_NAMESPACE}:{row.analysis_run_id}:{prior.graph_snapshot_revision_id}"
                            for row in command.sources
                        )
                    )
                )
            )
        )
        if (
            snapshot is None
            or predecessor is None
            or snapshot.publisher_version != "1.9.0"
            or snapshot.graph_id != prior.graph_id
            or snapshot.revision_number != predecessor.revision_number + 1
            or snapshot.previous_graph_snapshot_revision_id != prior.graph_snapshot_revision_id
            or predecessor.snapshot_sha256 != command.expected_graph_snapshot_sha256
            or self.retrieval.resolve_snapshot_pointer(session, prior.graph_snapshot_revision_id)
            != prior
            or publication.published_by_operator_id != command.requested_by_operator_id
            or publication.authorized_at != command.authorized_at
            or not previous_ids.issubset(current_ids)
            or current_ids - previous_ids != {row.analysis_run_id for row in command.sources}
            or len(retrievals) != len(command.sources)
            or any(
                row.state != "PUBLISHED"
                or row.requester_operator_id != command.requested_by_operator_id
                or row.access_policy_revision_id != command.access_policy_revision_id
                or row.graph_snapshot_revision_id != prior.graph_snapshot_revision_id
                for row in retrievals
            )
        ):
            _fail("REPLAY_CONFLICT")
        assert snapshot is not None
        value: dict[str, Any] = {
            "schema_version": "ordinary-item-graph-publication-result/1.0",
            "corpus_key": command.corpus_key,
            "publication_id": publication.publication_id,
            "previous_graph_snapshot": prior.model_dump(mode="json"),
            "previous_graph_snapshot_sha256": command.expected_graph_snapshot_sha256,
            "graph_snapshot": self.retrieval.resolve_snapshot_pointer(
                session, snapshot.graph_snapshot_revision_id
            ).model_dump(mode="json"),
            "graph_snapshot_sha256": snapshot.snapshot_sha256,
            "sources": [row.model_dump(mode="json") for row in command.sources],
            "authorized_at": command.authorized_at,
            "published_at": publication.published_at,
            "submission_sha256": command.submission_sha256,
            "outcome": outcome,
        }
        # Pydantic's UTC JSON representation is the canonical wire timestamp.
        for name in ("authorized_at", "published_at"):
            value[name] = value[name].isoformat().replace("+00:00", "Z")
        value["result_sha256"] = content_sha256(value)
        result = OrdinaryItemGraphPublicationResult.model_validate(value)
        validate_contract(ORDINARY_ITEM_GRAPH_RESULT_SCHEMA, result.model_dump(mode="json"))
        return result
