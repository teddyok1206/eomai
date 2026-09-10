"""Concrete one-snapshot source for the exact Stage-C PDF learning proof."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NoReturn, TypeVar, cast

from eom_catalog_contracts import (
    AnalysisProof,
    AnalysisRecoveryLineage,
    ArtifactMember,
    AssessmentArtifactMemberPointer,
    AssessmentOccurrenceItemBinding,
    AssessmentSourceBundleMember,
    AssessmentSourceBundleRevision,
    BatchProof,
    CorpusCoverage,
    EffectiveExtractionDocuments,
    EffectiveKnowledgeAnalysisDocuments,
    EffectiveWorkUnit,
    GraphPlacement,
    GraphPlacementDatabaseEvidence,
    GraphSnapshot,
    GraphSnapshotAnalysisDatabaseEvidence,
    GraphSnapshotDatabaseEvidence,
    InstitutionalOriginProof,
    InventoryPointer,
    ItemCompletion,
    KnowledgeAnalysisProposalReceiptV8,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisResultV9,
    KnowledgeAnalysisRiskPolicy,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeAnalysisWorkerProposalV7,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    KnowledgeProposalArtifactMember,
    LegacyExtractionResultIdentityCollisions,
    LegacyItemCorpusCompletionCommand,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionRequest,
    LegacyItemExtractionValidationRecovery,
    LegacyRootAlias,
    LegacySourceInventoryV2,
    PdfSource,
    Quiescence,
    RecoveryAuthorization,
    RightsPolicyProof,
    SourceRelease,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisRiskPolicyRevisionRecord,
    KnowledgeAnalysisRunRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import ExecutionPresetRevision, ExecutionPresetRevisionV2
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, func, or_, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
)
from eom_catalog_service.knowledge_analysis_sources import (
    KnowledgeAnalysisSourceError,
    resolve_historically_approved_item_source,
)
from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord,
    KnowledgeCorpusRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_proposal_resolution import (
    KnowledgeProposalResolutionError,
    resolve_knowledge_analysis_proposal,
)
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleMemberRecord,
    AssessmentSourceBundleRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemCorpusCoverageRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_corpus_completion_service import (
    AcceptedTerminalWorkUnit,
    FailedTerminalWorkUnit,
    ResolvedBatchSnapshot,
    ResolvedCorpusCompletionSnapshot,
)
from eom_catalog_service.legacy_item_corpus_completion_source import (
    PostgresLegacyItemCorpusCompletionSource,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_media_compatibility_service import (
    LegacyItemMediaCompatibilityError,
    expected_promoted_legacy_item_content,
)
from eom_catalog_service.legacy_source_inventory import LegacySourceRootConfiguration
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginResolution,
    PastExamOriginStatus,
    past_exam_origin_inputs,
    resolve_past_exam_origins,
)
from eom_catalog_service.pdf_learning_completion_observation import (
    PostgresPdfLearningCompletionObservationRegistry,
)
from eom_catalog_service.pdf_learning_completion_runtime import (
    PdfLearningRuntimeBoundary,
    PdfLearningRuntimeObservation,
    SystemdPdfLearningRuntimeObserver,
)
from eom_catalog_service.pdf_learning_completion_service import (
    CurrentPdfLearningCompletionState,
    PdfLearningCompletionError,
    PdfLearningCompletionEvidence,
    PdfLearningCompletionObservation,
    PdfLearningCompletionRequest,
    ResolvedPdfLearningCompletionSnapshot,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactMember,
    resolve_pinned_artifact_member,
)
from eom_catalog_service.pinned_legacy_pdf_resolution import (
    ResolvedPinnedLegacyPdfSource,
    resolve_pinned_legacy_pdf_sources,
)
from eom_catalog_service.settings import CatalogSettings

MAX_CONTROL_BYTES = 32 * 1024 * 1024
MAX_GRAPH_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ITEM_MEMBER_BYTES = 16 * 1024 * 1024
ACTIVE_JOB_STATES = frozenset(
    {"CREATED", "VALIDATED", "QUEUED", "CLAIMED", "RUNNING", "VALIDATING_RESULT", "COMMITTING"}
)
ACTIVE_WORKFLOW_STATES = frozenset(
    {
        "REQUESTED",
        "RUNNING",
        "AWAITING_HUMAN_APPROVAL",
        "REWORK_REQUESTED",
        "APPROVED",
        "REGISTERING",
    }
)
ACTIVE_COMMAND_STATES = frozenset({"PENDING", "LEASED", "PROCESSING"})
ACTIVE_ANALYSIS_STATES = frozenset(
    {"REQUESTED", "RESOLVED", "QUEUED", "RUNNING", "VALIDATING", "NEEDS_REVIEW"}
)
TModel = TypeVar("TModel", bound=BaseModel)
_HISTORICAL_ANALYSIS_REQUESTS: dict[str, tuple[str, type[BaseModel]]] = {
    "knowledge-analysis-request/2.0": (
        "knowledge-analysis-request-v2",
        KnowledgeAnalysisRequestV2,
    ),
    "knowledge-analysis-request/3.0": (
        "knowledge-analysis-request-v3",
        KnowledgeAnalysisRequestV3,
    ),
    "knowledge-analysis-request/4.0": (
        "knowledge-analysis-request-v4",
        KnowledgeAnalysisRequestV4,
    ),
    "knowledge-analysis-request/5.0": (
        "knowledge-analysis-request-v5",
        KnowledgeAnalysisRequestV5,
    ),
    "knowledge-analysis-request/6.0": (
        "knowledge-analysis-request-v6",
        KnowledgeAnalysisRequestV6,
    ),
    "knowledge-analysis-request/7.0": (
        "knowledge-analysis-request-v7",
        KnowledgeAnalysisRequestV7,
    ),
    "knowledge-analysis-request/8.0": (
        "knowledge-analysis-request-v8",
        KnowledgeAnalysisRequestV8,
    ),
}


@dataclass(frozen=True)
class _ResolvedExtraction:
    inventory: InventoryPointer
    original_batch: BatchProof
    successor_batch: BatchProof
    recovery_authorization: RecoveryAuthorization
    historical_result_identity_collisions: LegacyExtractionResultIdentityCollisions | None
    corpus_coverage: CorpusCoverage
    pdf_sources: tuple[PdfSource, ...]
    pdf_observations: tuple[ResolvedPinnedLegacyPdfSource, ...]
    effective_work_units: tuple[EffectiveWorkUnit, ...]
    documents: tuple[EffectiveExtractionDocuments, ...]
    bundles: tuple[AssessmentSourceBundleRevision, ...]
    inventory_document: LegacySourceInventoryV2
    original_manifest: LegacyItemExtractionBatchManifestV2
    successor_manifest: LegacyItemExtractionBatchManifestV2
    recovery_document: LegacyItemExtractionValidationRecovery
    coverage_document: LegacyItemCorpusCoverage
    workflow_ids: tuple[str, ...]
    job_ids: tuple[str, ...]
    failed_predecessors: tuple[FailedTerminalWorkUnit, ...]


@dataclass(frozen=True)
class _ResolvedGraph:
    graph: GraphSnapshot
    snapshot_manifest: KnowledgeGraphSnapshotManifestV8
    structure_manifest: KnowledgeGraphStructureManifestV5
    projection_member_bytes: Mapping[str, bytes]
    database: GraphSnapshotDatabaseEvidence
    placements: tuple[GraphPlacementDatabaseEvidence, ...]
    analyses: tuple[GraphSnapshotAnalysisDatabaseEvidence, ...]


@dataclass(frozen=True)
class _ResolvedItems:
    items: tuple[ItemCompletion, ...]
    knowledge_documents: tuple[EffectiveKnowledgeAnalysisDocuments, ...]
    recoveries: tuple[AnalysisRecoveryLineage, ...]
    workflow_ids: tuple[str, ...]
    job_ids: tuple[str, ...]


@dataclass(frozen=True)
class _AcceptedAnalysisEvidence:
    run: KnowledgeAnalysisRunRecord
    request: KnowledgeAnalysisRequestV9
    result: KnowledgeAnalysisResultV9
    receipt: KnowledgeAnalysisProposalReceiptV8
    proposal: KnowledgeAnalysisWorkerProposalV7
    accepted: AcceptedAnalysisProposal
    preset: ExecutionPresetRevisionRecord
    risk_policy: KnowledgeAnalysisRiskPolicyRevisionRecord


class _PinnedCatalogArtifactReader(CatalogArtifactService):
    """Catalog reader whose every DB lookup is pinned to the caller's RR Session."""

    def __init__(
        self,
        session: Session,
        settings: CatalogSettings,
    ) -> None:
        self._session = session
        self.settings = settings

    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes:
        logical = self._session.get(ArtifactRecord, artifact_id)
        revision = self._session.get(ArtifactRevisionRecord, revision_id)
        if logical is None or revision is None:
            raise ValueError("pinned Artifact identity is absent")
        primary = revision.manifest.get("primary_file")
        manifest_artifact_type = revision.manifest.get("artifact_type")
        if not isinstance(primary, str) or not isinstance(manifest_artifact_type, str):
            raise ValueError("pinned Artifact primary member is absent")
        expected_manifest_types = (
            {"knowledge-analysis-proposal"}
            if logical.artifact_type == "workflow_support"
            and primary == "normalized/proposal-receipt.json"
            else {logical.artifact_type}
        )
        return resolve_pinned_artifact_member(
            self._session,
            self.settings,
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            expected_artifact_types={logical.artifact_type},
            expected_primary_file=primary,
            max_bytes=max_bytes,
            expected_manifest_artifact_types=expected_manifest_types,
        ).payload

    def verify_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> None:
        self.read_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )


class PostgresPdfLearningCompletionSource:
    """Assemble the exact proof under repeatable-read, then re-observe all mutable facts."""

    def __init__(
        self,
        engine: Engine,
        *,
        pdf_roots: LegacySourceRootConfiguration,
        settings: CatalogSettings | None = None,
        runtime: PdfLearningRuntimeBoundary | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.pdf_roots = pdf_roots
        self.runtime = runtime or SystemdPdfLearningRuntimeObserver()
        self.generic = PostgresLegacyItemCorpusCompletionSource(engine, self.settings)
        self.observations = PostgresPdfLearningCompletionObservationRegistry(engine)

    def resolve_completion_snapshot(
        self,
        request: PdfLearningCompletionRequest,
        *,
        source_release: SourceRelease,
    ) -> ResolvedPdfLearningCompletionSnapshot:
        runtime_before = self.runtime.observe()
        try:
            with self.sessions() as session, session.begin():
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    )
                # PostgreSQL statement_timestamp is captured by the first statement after the
                # isolation declaration, before any evidence read establishes the MVCC snapshot.
                observed_at = self._clock(session)
                generic = self.generic.resolve_completion_snapshot_in_session(
                    session, self._generic_command(request)
                )
                extraction = self._resolve_extraction(session, request, generic)
                graph = self._resolve_graph(session, request)
                items = self._resolve_items(session, extraction, graph)
                quiescence = self._quiescence(
                    session,
                    runtime_before,
                    extraction=extraction,
                    items=items,
                )
                evidence = PdfLearningCompletionEvidence(
                    inventory=extraction.inventory,
                    original_batch=extraction.original_batch,
                    successor_batch=extraction.successor_batch,
                    recovery_authorization=extraction.recovery_authorization,
                    historical_result_identity_collisions=(
                        extraction.historical_result_identity_collisions
                    ),
                    corpus_coverage=extraction.corpus_coverage,
                    pdf_sources=extraction.pdf_sources,
                    effective_work_units=extraction.effective_work_units,
                    graph_snapshot=graph.graph,
                    analysis_recoveries=items.recoveries,
                    quiescence=quiescence,
                )
                fingerprint = self._mutable_fingerprint(
                    runtime_before,
                    extraction.pdf_observations,
                    evidence=evidence,
                    items=items.items,
                    graph=graph,
                    failed_predecessors=extraction.failed_predecessors,
                )
                resolved = ResolvedPdfLearningCompletionSnapshot(
                    requested_by=request.corpus_completion.requested_by,
                    requester_active=True,
                    requester_authorized=True,
                    observed_at_utc=observed_at,
                    mutable_fingerprint_sha256=fingerprint,
                    evidence=evidence,
                    items=items.items,
                    effective_documents=extraction.documents,
                    knowledge_documents=items.knowledge_documents,
                    bundle_revisions=extraction.bundles,
                    inventory_document=extraction.inventory_document,
                    original_manifest=extraction.original_manifest,
                    successor_manifest=extraction.successor_manifest,
                    recovery_document=extraction.recovery_document,
                    coverage_document=extraction.coverage_document,
                    snapshot_manifest=graph.snapshot_manifest,
                    structure_manifest=graph.structure_manifest,
                    projection_member_bytes=graph.projection_member_bytes,
                    snapshot_database=graph.database,
                    placement_database_rows=graph.placements,
                    snapshot_analysis_database_rows=graph.analyses,
                )
        except PdfLearningCompletionError:
            raise
        except Exception as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_SOURCE_INVALID",
                "completion evidence could not be resolved in one stable snapshot",
                exc,
            )
        runtime_after = self.runtime.observe()
        if runtime_after != runtime_before:
            self._fail(
                "PDF_LEARNING_COMPLETION_RUNTIME_CHANGED",
                "runtime configuration changed during source observation",
            )
        return resolved

    def claim_first_observation(
        self,
        request: PdfLearningCompletionRequest,
        *,
        source_release: SourceRelease,
        completion_identity_sha256: str,
        mutable_fingerprint_sha256: str,
        observed_at_utc: datetime,
    ) -> PdfLearningCompletionObservation:
        return self.observations.claim(
            request,
            source_release=source_release,
            completion_identity_sha256=completion_identity_sha256,
            mutable_fingerprint_sha256=mutable_fingerprint_sha256,
            observed_at_utc=observed_at_utc,
        )

    def recheck_current_state(
        self,
        request: PdfLearningCompletionRequest,
        *,
        observation_identity_sha256: str,
    ) -> CurrentPdfLearningCompletionState:
        with self.sessions() as session:
            from eom_catalog_service.pdf_learning_completion_models import (
                PdfLearningCompletionObservationRecord,
            )

            authority = session.get(
                PdfLearningCompletionObservationRecord, observation_identity_sha256
            )
            if authority is None:
                self._fail(
                    "PDF_LEARNING_COMPLETION_OBSERVATION_MISSING",
                    "completion first observation is absent",
                )
            source_release = SourceRelease(
                git_commit=authority.source_commit,
                git_tree=authority.source_tree,
                git_archive_sha256=authority.source_archive_sha256,
            )
        resolved = self.resolve_completion_snapshot(request, source_release=source_release)
        return CurrentPdfLearningCompletionState(
            mutable_fingerprint_sha256=resolved.mutable_fingerprint_sha256,
            observed_at_utc=resolved.observed_at_utc,
        )

    # Resolution helpers follow.  They all receive the caller-owned Session and never open a
    # second database snapshot.

    def _resolve_extraction(
        self,
        session: Session,
        request: PdfLearningCompletionRequest,
        generic: ResolvedCorpusCompletionSnapshot,
    ) -> _ResolvedExtraction:
        completion = request.corpus_completion
        coverage_pointer = completion.coverage_artifact
        coverage_member = self._resolve_assessment_member(
            session,
            coverage_pointer,
            artifact_types={"control_legacy_item_corpus_coverage"},
            primary_file="coverage.json",
            max_bytes=MAX_CONTROL_BYTES,
        )
        coverage = self._typed_json(
            coverage_member.payload,
            route="legacy-item-corpus-coverage",
            model=LegacyItemCorpusCoverage,
        )
        coverage_record = session.get(LegacyItemCorpusCoverageRecord, coverage.coverage_id)
        if (
            coverage_record is None
            or coverage.coverage_id != completion.coverage_id
            or coverage.coverage_sha256 != completion.coverage_sha256
            or coverage.state != "COMPLETE"
            or (coverage.expected_item_count, coverage.accepted_item_count) != (520, 520)
            or (coverage.missing_item_count, coverage.conflict_item_count) != (0, 0)
            or coverage_record.inventory_id != coverage.inventory_id
            or coverage_record.inventory_sha256 != coverage.inventory_sha256
            or coverage_record.artifact_id != coverage_pointer.artifact_id
            or coverage_record.artifact_revision_id != coverage_pointer.artifact_revision_id
            or coverage_record.artifact_member_path != coverage_pointer.member_path
            or coverage_record.artifact_schema_ref != coverage_pointer.schema_ref
            or coverage_record.artifact_media_type != coverage_pointer.media_type
            or coverage_record.artifact_sha256 != coverage_pointer.sha256
            or coverage_record.expected_item_count != coverage.expected_item_count
            or coverage_record.accepted_item_count != coverage.accepted_item_count
            or coverage_record.missing_item_count != coverage.missing_item_count
            or coverage_record.conflict_item_count != coverage.conflict_item_count
            or coverage_record.state != coverage.state
            or coverage_record.coverage_sha256 != coverage.coverage_sha256
            or coverage_record.created_at.astimezone(UTC) != coverage.created_at
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_COVERAGE_INVALID",
                "registered COMPLETE coverage differs from its immutable Artifact",
            )

        original = generic.original_batch
        successor = generic.successor_batch
        replacements = {
            value.predecessor_work_unit_id: value for value in generic.recovery.replacements
        }
        original_terminals = {value.work_unit_id: value for value in original.work_units}
        successor_terminals = {value.work_unit_id: value for value in successor.work_units}
        successor_units = {value.work_unit_id: value for value in successor.manifest.work_units}
        failed_predecessors: list[FailedTerminalWorkUnit] = []
        if {
            value.work_unit_id
            for value in original.work_units
            if isinstance(value, FailedTerminalWorkUnit)
        } != set(replacements):
            self._fail(
                "PDF_LEARNING_COMPLETION_RECOVERY_PARTITION_INVALID",
                "failed predecessor set differs from recovery authorization",
            )
        for predecessor_id, replacement in replacements.items():
            failed = original_terminals.get(predecessor_id)
            if (
                not isinstance(failed, FailedTerminalWorkUnit)
                or failed.ordinal != replacement.predecessor_ordinal
                or failed.extraction_request_id != replacement.predecessor_extraction_request_id
                or failed.request_sha256 != replacement.predecessor_request_sha256
                or failed.error_code != replacement.failure_code
                or failed.workflow_id != replacement.predecessor_workflow_id
                or failed.platform_job_id != replacement.predecessor_platform_job_id
                or failed.workflow_failure_code != replacement.workflow_failure_code
                or failed.job_error_code != replacement.job_error_code
                or failed.failure_message_sha256 != replacement.failure_message_sha256
                or failed.result_present is not False
                or failed.receipt_present is not False
                or failed.acceptance_present is not False
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_RECOVERY_POINTER_DRIFT",
                    "failed predecessor differs from recovery authorization",
                )
            failed_predecessors.append(failed)
        effective_units: list[EffectiveWorkUnit] = []
        effective_documents: list[EffectiveExtractionDocuments] = []
        for original_unit in original.manifest.work_units:
            effective_replacement = replacements.get(original_unit.work_unit_id)
            effective_unit = (
                successor_units.get(effective_replacement.successor_work_unit_id)
                if effective_replacement is not None
                else original_unit
            )
            terminal = (
                successor_terminals.get(effective_replacement.successor_work_unit_id)
                if effective_replacement is not None
                else original_terminals.get(original_unit.work_unit_id)
            )
            if effective_unit is None or not isinstance(terminal, AcceptedTerminalWorkUnit):
                self._fail(
                    "PDF_LEARNING_COMPLETION_EFFECTIVE_EXTRACTION_INVALID",
                    "effective accepted extraction partition is incomplete",
                )
            extraction_request = effective_unit.request
            effective_units.append(
                EffectiveWorkUnit(
                    original_work_unit_id=original_unit.work_unit_id,
                    original_ordinal=original_unit.ordinal,
                    effective_batch_id=terminal.extraction_batch_id,
                    effective_work_unit_id=terminal.work_unit_id,
                    effective_ordinal=terminal.ordinal,
                    recovered=effective_replacement is not None,
                    bundle_id=extraction_request.bundle.assessment_source_bundle_id,
                    bundle_revision_id=(
                        extraction_request.bundle.assessment_source_bundle_revision_id
                    ),
                    bundle_manifest_sha256=extraction_request.bundle.bundle_manifest_sha256,
                    occurrence_id=extraction_request.occurrence.assessment_occurrence_id,
                    occurrence_revision_id=(
                        extraction_request.occurrence.assessment_occurrence_revision_id
                    ),
                    occurrence_revision_sha256=(
                        extraction_request.occurrence.occurrence_revision_sha256
                    ),
                    expected_item_numbers=extraction_request.expected_item_numbers,
                    expected_item_numbers_sha256=effective_unit.expected_item_numbers_sha256,
                    extraction_request_id=terminal.extraction_request_id,
                    request_sha256=terminal.request_sha256,
                    extraction_result_id=terminal.extraction_result_id,
                    result_sha256=terminal.result_sha256,
                    result_artifact=self._artifact_member(terminal.result_artifact),
                    extraction_receipt_sha256=terminal.extraction_receipt_sha256,
                    acceptance_id=terminal.acceptance_id,
                    acceptance_sha256=terminal.acceptance_sha256,
                    acceptance_artifact=self._artifact_member(terminal.acceptance_artifact),
                    acceptance_state="ACCEPTED",
                    coverage_state="COMPLETE",
                )
            )
            effective_documents.append(
                EffectiveExtractionDocuments(
                    effective_work_unit_id=terminal.work_unit_id,
                    receipt_storage="ARTIFACT_REVISION_RESULT_JSONB",
                    result=terminal.result,
                    extraction_receipt=terminal.extraction_receipt,
                    acceptance=terminal.acceptance,
                )
            )

        bundle_ids = tuple(sorted({value.bundle_revision_id for value in effective_units}))
        bundles = self._resolve_bundles(
            session,
            bundle_ids=bundle_ids,
            inventory=generic.inventory,
            inventory_pointer=original.manifest.inventory_artifact,
        )
        inventory_by_key = {value.entry_key: value for value in generic.inventory.entries}
        pdf_bindings: dict[str, set[str]] = defaultdict(set)
        for unit in original.manifest.work_units:
            bundle_revision_id = unit.request.bundle.assessment_source_bundle_revision_id
            for binding in unit.corpus_source_bindings:
                entry_key = binding.corpus_inventory_source.entry_key
                entry = inventory_by_key.get(entry_key)
                if entry is not None and entry.media_type == "application/pdf":
                    pdf_bindings[entry_key].add(bundle_revision_id)
        pdf_entries = tuple(
            value for value in generic.inventory.entries if value.entry_key in pdf_bindings
        )
        pdf_observations = resolve_pinned_legacy_pdf_sources(
            roots=self.pdf_roots,
            inventory_root_alias=LegacyRootAlias(generic.inventory.root_alias),
            inventory_root_configuration_sha256=generic.inventory.root_configuration_sha256,
            entries=pdf_entries,
        )
        pdf_sources = tuple(
            PdfSource(
                inventory_entry_key=value.entry_key,
                content_sha256=value.content_sha256,
                media_type="application/pdf",
                bundle_revision_ids=tuple(sorted(pdf_bindings[value.entry_key])),
            )
            for value in sorted(pdf_entries, key=lambda entry: entry.entry_key)
            if value.content_sha256 is not None
        )
        if len(pdf_sources) != 50 or len(pdf_observations) != 50:
            self._fail(
                "PDF_LEARNING_COMPLETION_PDF_SET_INVALID",
                "effective source bindings do not resolve exactly fifty PDFs",
            )

        batch_rows = tuple(
            session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord).where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                        (
                            original.manifest.extraction_batch_id,
                            successor.manifest.extraction_batch_id,
                        )
                    )
                )
            )
        )
        workflow_ids = tuple(
            sorted({value.workflow_id for value in batch_rows if value.workflow_id is not None})
        )
        job_ids = tuple(
            sorted(
                {value.platform_job_id for value in batch_rows if value.platform_job_id is not None}
            )
        )
        return _ResolvedExtraction(
            inventory=InventoryPointer(
                inventory_id=generic.inventory.inventory_id,
                inventory_sha256=generic.inventory.inventory_sha256,
                artifact=self._artifact_member(original.manifest.inventory_artifact),
            ),
            original_batch=self._batch_proof(original, role="ORIGINAL_SCOPE"),
            successor_batch=self._batch_proof(successor, role="VALIDATION_SUCCESSOR"),
            recovery_authorization=RecoveryAuthorization(
                recovery_sha256=generic.recovery.recovery_sha256,
                artifact=self._artifact_member(completion.recovery_artifact),
            ),
            historical_result_identity_collisions=(
                completion.historical_result_identity_collisions
            ),
            corpus_coverage=CorpusCoverage(
                coverage_id=coverage.coverage_id,
                coverage_sha256=coverage.coverage_sha256,
                artifact=self._artifact_member(coverage_pointer),
                state="COMPLETE",
                expected_item_count=520,
                accepted_item_count=520,
                missing_item_count=0,
                conflict_item_count=0,
            ),
            pdf_sources=pdf_sources,
            pdf_observations=pdf_observations,
            effective_work_units=tuple(effective_units),
            documents=tuple(effective_documents),
            bundles=bundles,
            inventory_document=generic.inventory,
            original_manifest=original.manifest,
            successor_manifest=successor.manifest,
            recovery_document=generic.recovery,
            coverage_document=coverage,
            workflow_ids=workflow_ids,
            job_ids=job_ids,
            failed_predecessors=tuple(
                sorted(failed_predecessors, key=lambda value: value.work_unit_id)
            ),
        )

    def _resolve_graph(
        self, session: Session, request: PdfLearningCompletionRequest
    ) -> _ResolvedGraph:
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == "integrated-science-textbooks"
            )
        )
        snapshot = session.get(KnowledgeGraphSnapshotRecord, request.graph_snapshot_revision_id)
        corpus_revision = (
            session.get(KnowledgeCorpusRevisionRecord, snapshot.corpus_revision_id)
            if snapshot is not None
            else None
        )
        if (
            corpus is None
            or snapshot is None
            or corpus_revision is None
            or corpus.lifecycle_state != "ACTIVE"
            or corpus.current_graph_snapshot_revision_id != snapshot.graph_snapshot_revision_id
            or corpus.current_corpus_revision_id != snapshot.corpus_revision_id
            or snapshot.graph_id != corpus.graph_id
            or snapshot.state != "PUBLISHED"
            or snapshot.snapshot_sha256 != request.graph_snapshot_sha256
            or snapshot.ontology_version != "education-knowledge-graph/1.1"
            or corpus_revision.corpus_id != corpus.corpus_id
            or corpus_revision.state != "PUBLISHED"
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_GRAPH_CURRENT_INVALID",
                "requested Graph is not the exact current published corpus snapshot",
            )
        manifest_pointer = KnowledgeArtifactMemberPointer(
            artifact_id=snapshot.manifest_artifact_id,
            artifact_revision_id=snapshot.manifest_artifact_revision_id,
            sha256=snapshot.manifest_sha256,
            schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/8.0",
            media_type="application/json",
            logical_name="manifest.json",
            member_path="projections/manifest.json",
        )
        manifest_member = self._resolve_knowledge_member(
            session,
            manifest_pointer,
            artifact_types={"knowledge-graph-snapshot-manifest"},
            primary_file="projections/manifest.json",
            max_bytes=MAX_GRAPH_MEMBER_BYTES,
        )
        manifest = self._typed_json(
            manifest_member.payload,
            route="knowledge-graph-snapshot-manifest-v8",
            model=KnowledgeGraphSnapshotManifestV8,
        )
        if (
            manifest.graph_id != snapshot.graph_id
            or manifest.graph_snapshot_revision_id != snapshot.graph_snapshot_revision_id
            or manifest.state != snapshot.state
            or manifest.ontology_version != snapshot.ontology_version
            or manifest.snapshot_sha256 != snapshot.snapshot_sha256
            or manifest.created_at != snapshot.created_at.astimezone(UTC)
            or manifest.counts.source_revisions != snapshot.source_count
            or manifest.counts.nodes != snapshot.node_count
            or manifest.counts.edges != snapshot.edge_count
            or manifest.counts.anchors != snapshot.anchor_count
            or manifest.projections.nodes.artifact_id != snapshot.projection_artifact_id
            or manifest.projections.nodes.artifact_revision_id
            != snapshot.projection_artifact_revision_id
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_GRAPH_MANIFEST_INVALID",
                "Graph snapshot row differs from its immutable manifest",
            )
        structure_member = self._resolve_knowledge_member(
            session,
            manifest.structure_manifest,
            artifact_types={"knowledge-graph-structure-manifest"},
            primary_file="evidence/graph-structure-manifest.json",
            max_bytes=MAX_GRAPH_MEMBER_BYTES,
        )
        structure = self._typed_json(
            structure_member.payload,
            route="knowledge-graph-structure-manifest-v5",
            model=KnowledgeGraphStructureManifestV5,
        )
        projection_pointers = tuple(
            value
            for value in (
                manifest.projections.nodes,
                manifest.projections.edges,
                manifest.projections.curriculum_closure,
                manifest.projections.markdown,
                manifest.projections.lexical_index,
            )
            if value is not None
        )
        projection_member_bytes: dict[str, bytes] = {}
        for pointer in projection_pointers:
            member = self._resolve_knowledge_member(
                session,
                pointer,
                artifact_types={"knowledge-graph-projection"},
                primary_file="projections/nodes.jsonl",
                max_bytes=MAX_GRAPH_MEMBER_BYTES,
            )
            projection_member_bytes[pointer.member_path] = member.payload

        placement_rows = tuple(
            session.scalars(
                select(AssessmentItemOccurrenceReferenceRecord)
                .where(
                    AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id
                    == snapshot.graph_snapshot_revision_id
                )
                .order_by(AssessmentItemOccurrenceReferenceRecord.placement_node_id)
            )
        )
        analysis_rows = tuple(
            session.scalars(
                select(KnowledgeSnapshotAnalysisRecord)
                .where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                    == snapshot.graph_snapshot_revision_id
                )
                .order_by(KnowledgeSnapshotAnalysisRecord.analysis_run_id)
            )
        )
        placements = tuple(
            GraphPlacementDatabaseEvidence(
                graph_snapshot_revision_id=value.graph_snapshot_revision_id,
                placement_node_id=value.placement_node_id,
                occurrence_node_id=value.occurrence_node_id,
                item_node_id=value.item_node_id,
                analysis_run_id=value.analysis_run_id,
                assessment_occurrence_id=value.assessment_occurrence_id,
                assessment_occurrence_revision_id=value.assessment_occurrence_revision_id,
                assessment_occurrence_revision_sha256=(value.assessment_occurrence_revision_sha256),
                occurrence_display_label=value.occurrence_display_label,
                administration_year=value.administration_year,
                administration_month=value.administration_month,
                target_school_level=cast(
                    Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"],
                    value.target_school_level,
                ),
                target_grade=value.target_grade,
                subject_key=value.subject_key,
                item_number=value.item_number,
                item_id=value.item_id,
                item_revision_id=value.item_revision_id,
                item_origin_profile_id=value.item_origin_profile_id,
                extraction_acceptance_id=value.extraction_acceptance_id,
                assessment_source_bundle_revision_id=(value.assessment_source_bundle_revision_id),
                placement_sha256=value.placement_sha256,
            )
            for value in placement_rows
        )
        analyses = tuple(
            GraphSnapshotAnalysisDatabaseEvidence(
                graph_snapshot_revision_id=value.graph_snapshot_revision_id,
                analysis_run_id=value.analysis_run_id,
                source_kind=cast(
                    Literal[
                        "CONTENT_INTAKE_FILE",
                        "APPROVED_ITEM_REVISION",
                        "DOCUMENT_REVISION",
                    ],
                    value.source_kind,
                ),
                source_revision_id=value.source_revision_id,
                source_artifact_id=value.source_artifact_id,
                source_artifact_revision_id=value.source_artifact_revision_id,
                source_sha256=value.source_sha256,
                accepted_result_artifact_id=value.accepted_result_artifact_id,
                accepted_result_artifact_revision_id=(value.accepted_result_artifact_revision_id),
                accepted_result_sha256=value.accepted_result_sha256,
            )
            for value in analysis_rows
        )
        database = GraphSnapshotDatabaseEvidence(
            corpus_id=corpus.corpus_id,
            corpus_key=corpus.corpus_key,
            corpus_lifecycle_state=cast(Literal["ACTIVE"], corpus.lifecycle_state),
            current_corpus_revision_id=corpus.current_corpus_revision_id,
            current_graph_snapshot_revision_id=corpus.current_graph_snapshot_revision_id,
            corpus_revision_id=corpus_revision.corpus_revision_id,
            corpus_source_set_sha256=corpus_revision.source_set_sha256,
            graph_id=snapshot.graph_id,
            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
            snapshot_state=snapshot.state,
            ontology_version=snapshot.ontology_version,
            manifest_artifact_id=snapshot.manifest_artifact_id,
            manifest_artifact_revision_id=snapshot.manifest_artifact_revision_id,
            manifest_sha256=snapshot.manifest_sha256,
            projection_artifact_id=snapshot.projection_artifact_id,
            projection_artifact_revision_id=snapshot.projection_artifact_revision_id,
            snapshot_sha256=snapshot.snapshot_sha256,
            created_at=snapshot.created_at.astimezone(UTC),
        )
        graph = GraphSnapshot(
            corpus_id=corpus.corpus_id,
            corpus_key="integrated-science-textbooks",
            corpus_lifecycle_state="ACTIVE",
            corpus_revision_id=corpus_revision.corpus_revision_id,
            corpus_source_set_sha256=corpus_revision.source_set_sha256,
            graph_id=snapshot.graph_id,
            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
            snapshot_state="PUBLISHED",
            snapshot_sha256=snapshot.snapshot_sha256,
            manifest_sha256=snapshot.manifest_sha256,
            manifest_artifact=manifest_pointer,
            projections=manifest.projections,
            structure_manifest_sha256=structure.manifest_sha256,
            structure_manifest_artifact=manifest.structure_manifest,
            snapshot_created_at=snapshot.created_at.astimezone(UTC),
            observed_as_current=True,
        )
        return _ResolvedGraph(
            graph=graph,
            snapshot_manifest=manifest,
            structure_manifest=structure,
            projection_member_bytes=projection_member_bytes,
            database=database,
            placements=placements,
            analyses=analyses,
        )

    def _resolve_items(
        self,
        session: Session,
        extraction: _ResolvedExtraction,
        graph: _ResolvedGraph,
    ) -> _ResolvedItems:
        expected_keys = {
            (unit.bundle_revision_id, item_number)
            for unit in extraction.effective_work_units
            for item_number in unit.expected_item_numbers
        }
        expected_acceptance_ids = {unit.acceptance_id for unit in extraction.effective_work_units}
        expected_acceptance_hashes = {
            unit.acceptance_sha256 for unit in extraction.effective_work_units
        }
        expected_bundle_ids = {unit.bundle_id for unit in extraction.effective_work_units}
        expected_bundle_revisions = {
            unit.bundle_revision_id for unit in extraction.effective_work_units
        }
        expected_bundle_hashes = {
            unit.bundle_manifest_sha256 for unit in extraction.effective_work_units
        }
        expected_occurrence_ids = {unit.occurrence_id for unit in extraction.effective_work_units}
        expected_occurrence_revisions = {
            unit.occurrence_revision_id for unit in extraction.effective_work_units
        }
        expected_occurrence_hashes = {
            unit.occurrence_revision_sha256 for unit in extraction.effective_work_units
        }
        structure_scope = tuple(
            value
            for value in graph.structure_manifest.assessment_item_occurrences
            if (
                (value.assessment_source_bundle_revision_id, value.item_number) in expected_keys
                or value.extraction_acceptance_id in expected_acceptance_ids
                or value.extraction_acceptance_sha256 in expected_acceptance_hashes
                or value.assessment_source_bundle_id in expected_bundle_ids
                or value.assessment_source_bundle_revision_id in expected_bundle_revisions
                or value.assessment_source_bundle_sha256 in expected_bundle_hashes
                or value.assessment_occurrence_id in expected_occurrence_ids
                or value.assessment_occurrence_revision_id in expected_occurrence_revisions
                or value.assessment_occurrence_revision_sha256 in expected_occurrence_hashes
            )
        )
        structure_by_key = {
            (value.assessment_source_bundle_revision_id, value.item_number): value
            for value in structure_scope
        }
        if (
            expected_keys != set(structure_by_key)
            or len(structure_by_key) != len(structure_scope)
            or len(expected_keys) != 520
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_GRAPH_ITEM_SET_INVALID",
                "Graph structure completion placement set is not exact",
            )
        structure_run_ids = {value.analysis_run_id for value in structure_scope}
        structure_item_ids = {value.item_id for value in structure_scope}
        structure_item_revision_ids = {value.item_revision_id for value in structure_scope}
        structure_origin_ids = {value.item_origin_profile_id for value in structure_scope}
        structure_placement_hashes = {value.placement_sha256 for value in structure_scope}
        placement_scope = tuple(
            value
            for value in graph.placements
            if (
                (value.assessment_source_bundle_revision_id, value.item_number) in expected_keys
                or value.analysis_run_id in structure_run_ids
                or value.item_id in structure_item_ids
                or value.item_revision_id in structure_item_revision_ids
                or value.item_origin_profile_id in structure_origin_ids
                or value.extraction_acceptance_id in expected_acceptance_ids
                or value.assessment_source_bundle_revision_id in expected_bundle_revisions
                or value.assessment_occurrence_id in expected_occurrence_ids
                or value.assessment_occurrence_revision_id in expected_occurrence_revisions
                or value.assessment_occurrence_revision_sha256 in expected_occurrence_hashes
                or value.placement_sha256 in structure_placement_hashes
            )
        )
        placement_by_run = {value.analysis_run_id: value for value in placement_scope}
        snapshot_analysis_by_run = {value.analysis_run_id: value for value in graph.analyses}
        run_ids = tuple(sorted(placement_by_run))
        if (
            len(run_ids) != 520
            or len(placement_by_run) != len(placement_scope)
            or not set(run_ids).issubset(snapshot_analysis_by_run)
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_GRAPH_ITEM_SET_INVALID",
                "current Graph does not expose exactly 520 unique assessment placements",
            )
        accepted_rows = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord)
                .where(KnowledgeAnalysisRunRecord.analysis_run_id.in_(run_ids))
                .order_by(KnowledgeAnalysisRunRecord.analysis_run_id)
            )
        )
        if len(accepted_rows) != 520 or any(value.state != "ACCEPTED" for value in accepted_rows):
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_SET_INVALID",
                "Graph assessment placements are not exact accepted analysis leaves",
            )
        history_rows, recoveries = self._resolve_analysis_history(
            session,
            accepted_rows=accepted_rows,
            snapshot_analyses=tuple(snapshot_analysis_by_run.values()),
        )
        reader = _PinnedCatalogArtifactReader(session, self.settings)
        analyses = tuple(
            self._load_accepted_analysis(session, reader, value) for value in accepted_rows
        )
        accepted_proposals = tuple(value.accepted for value in analyses)
        try:
            origin_resolutions = resolve_past_exam_origins(
                session, past_exam_origin_inputs(accepted_proposals)
            )
        except ValueError as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_ORIGIN_INVALID",
                "past-exam origin chain does not resolve exactly",
                exc,
            )
        origin_by_run = {value.analysis_run_id: value for value in origin_resolutions}
        if len(origin_by_run) != 520 or any(
            value.status != PastExamOriginStatus.ELIGIBLE for value in origin_resolutions
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ORIGIN_SCOPE_INVALID",
                "past-exam Graph cohort contains an excluded or duplicate origin",
            )

        sources = tuple(value.request.source for value in analyses)
        item_revision_ids = tuple(sorted({value.item_revision_id for value in sources}))
        item_ids = tuple(sorted({value.item_id for value in sources}))
        revisions = {
            value.item_revision_id: value
            for value in session.scalars(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.item_revision_id.in_(item_revision_ids)
                )
            )
        }
        promotion_workflow_ids = tuple(sorted({value.workflow_id for value in revisions.values()}))
        promotion_workflows = {
            value.workflow_id: value
            for value in session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.workflow_id.in_(promotion_workflow_ids)
                )
            )
        }
        if set(promotion_workflows) != set(promotion_workflow_ids):
            self._fail(
                "PDF_LEARNING_COMPLETION_PROMOTION_INVALID",
                "promoted Item workflow set is incomplete",
            )
        item_rows = {
            value.item_id: value
            for value in session.scalars(select(ItemRecord).where(ItemRecord.item_id.in_(item_ids)))
        }
        components_by_revision: dict[str, list[ItemComponentRecord]] = defaultdict(list)
        for value in session.scalars(
            select(ItemComponentRecord)
            .where(ItemComponentRecord.item_revision_id.in_(item_revision_ids))
            .order_by(
                ItemComponentRecord.item_revision_id,
                ItemComponentRecord.component_type,
                ItemComponentRecord.ordinal,
            )
        ):
            components_by_revision[value.item_revision_id].append(value)

        acceptance_ids = tuple(sorted({value.extraction_acceptance_id for value in sources}))
        decision_rows = tuple(
            session.scalars(
                select(LegacyItemExtractionDecisionRecord).where(
                    LegacyItemExtractionDecisionRecord.acceptance_id.in_(acceptance_ids)
                )
            )
        )
        decision_by_key: dict[tuple[str, str], LegacyItemExtractionDecisionRecord] = {}
        for decision_row in decision_rows:
            key = (decision_row.acceptance_id, decision_row.item_proposal_id)
            if key in decision_by_key:
                self._fail(
                    "PDF_LEARNING_COMPLETION_PROMOTION_INVALID",
                    "promotion decision identity is ambiguous",
                )
            decision_by_key[key] = decision_row

        profile_ids = tuple(sorted({value.item_origin_profile_id for value in origin_resolutions}))
        profiles = {
            value.item_origin_profile_id: value
            for value in session.scalars(
                select(ItemOriginProfileRecord).where(
                    ItemOriginProfileRecord.item_origin_profile_id.in_(profile_ids)
                )
            )
        }
        occurrence_links: dict[str, list[ItemOriginOccurrenceRecord]] = defaultdict(list)
        for occurrence_link_row in session.scalars(
            select(ItemOriginOccurrenceRecord).where(
                ItemOriginOccurrenceRecord.item_origin_profile_id.in_(profile_ids)
            )
        ):
            occurrence_links[occurrence_link_row.item_origin_profile_id].append(occurrence_link_row)
        derivations: dict[str, list[ItemOriginDerivationRecord]] = defaultdict(list)
        for derivation_row in session.scalars(
            select(ItemOriginDerivationRecord).where(
                ItemOriginDerivationRecord.item_origin_profile_id.in_(profile_ids)
            )
        ):
            derivations[derivation_row.item_origin_profile_id].append(derivation_row)
        occurrence_revision_ids = tuple(
            sorted(
                {
                    link.assessment_occurrence_revision_id
                    for values in occurrence_links.values()
                    for link in values
                }
            )
        )
        occurrence_revisions = {
            value.assessment_occurrence_revision_id: value
            for value in session.scalars(
                select(AssessmentOccurrenceRevisionRecord).where(
                    AssessmentOccurrenceRevisionRecord.assessment_occurrence_revision_id.in_(
                        occurrence_revision_ids
                    )
                )
            )
        }
        occurrence_ids = tuple(
            sorted({value.assessment_occurrence_id for value in occurrence_revisions.values()})
        )
        occurrence_logicals = {
            value.assessment_occurrence_id: value
            for value in session.scalars(
                select(AssessmentOccurrenceRecord).where(
                    AssessmentOccurrenceRecord.assessment_occurrence_id.in_(occurrence_ids)
                )
            )
        }
        bundle_rows = {
            value.assessment_source_bundle_revision_id: value
            for value in session.scalars(
                select(AssessmentSourceBundleRevisionRecord).where(
                    AssessmentSourceBundleRevisionRecord.assessment_source_bundle_revision_id.in_(
                        tuple(
                            sorted(
                                {
                                    value.bundle_revision_id
                                    for value in extraction.effective_work_units
                                }
                            )
                        )
                    )
                )
            )
        }
        structure_placements = {value.analysis_run_id: value for value in structure_scope}

        effective_by_acceptance = {
            value.acceptance_id: value for value in extraction.effective_work_units
        }
        documents_by_acceptance = {
            value.acceptance.acceptance_id: value for value in extraction.documents
        }
        completions: list[ItemCompletion] = []
        knowledge_documents: list[EffectiveKnowledgeAnalysisDocuments] = []
        analysis_workflow_ids = {value.workflow_id for value in history_rows}
        analysis_job_ids = {
            value.platform_job_id for value in history_rows if value.platform_job_id is not None
        }
        for evidence in analyses:
            run = evidence.run
            source = evidence.request.source
            origin_resolution = origin_by_run.get(run.analysis_run_id)
            revision = revisions.get(source.item_revision_id)
            promotion_workflow = (
                promotion_workflows.get(revision.workflow_id) if revision is not None else None
            )
            item = item_rows.get(source.item_id)
            decision = decision_by_key.get(
                (source.extraction_acceptance_id, source.item_proposal_id)
            )
            effective = effective_by_acceptance.get(source.extraction_acceptance_id)
            extraction_documents = documents_by_acceptance.get(source.extraction_acceptance_id)
            placement = structure_placements.get(run.analysis_run_id)
            placement_row = placement_by_run.get(run.analysis_run_id)
            if (
                origin_resolution is None
                or revision is None
                or promotion_workflow is None
                or item is None
                or decision is None
                or effective is None
                or extraction_documents is None
                or placement is None
                or placement_row is None
                or decision.decision != "ACCEPT"
                or decision.item_number != source.item_number
                or revision.registration_key
                != (
                    f"legacy-item-promotion:{source.extraction_acceptance_id}:"
                    f"{source.item_proposal_id}"
                )
                or revision.item_id != source.item_id
                or revision.revision_state != "APPROVED"
                or item.lifecycle_state != "ACTIVE"
                or item.current_revision_id != revision.item_revision_id
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_PROMOTION_INVALID",
                    "accepted proposal does not resolve to one current approved Item Revision",
                )
            components = tuple(components_by_revision.get(revision.item_revision_id, ()))
            content_components = tuple(
                value
                for value in components
                if value.component_type == "ITEM_CONTENT" and value.ordinal == 0
            )
            if len(content_components) != 1:
                self._fail(
                    "PDF_LEARNING_COMPLETION_ITEM_CONTENT_INVALID",
                    "promoted Item has no unique canonical content component",
                )
            content_component = content_components[0]
            item_manifest_artifact = ArtifactMember(
                artifact_id=revision.manifest_artifact_id,
                artifact_revision_id=revision.manifest_artifact_revision_id,
                member_path="item-revision-manifest.json",
                schema_ref="eom://schemas/item-registry/item-revision-manifest-v1",
                media_type="application/json",
                sha256=revision.manifest_sha256,
            )
            manifest_member = resolve_pinned_artifact_member(
                session,
                self.settings,
                artifact_id=item_manifest_artifact.artifact_id,
                artifact_revision_id=item_manifest_artifact.artifact_revision_id,
                member_path=item_manifest_artifact.member_path,
                sha256=item_manifest_artifact.sha256,
                schema_ref=item_manifest_artifact.schema_ref,
                media_type=item_manifest_artifact.media_type,
                expected_artifact_types={"item-revision-manifest"},
                expected_primary_file="item-revision-manifest.json",
                max_bytes=MAX_ITEM_MEMBER_BYTES,
                historical_metadata_compatibility=True,
            )
            manifest_value = self._json_mapping(manifest_member.payload)
            validate_contract("item-revision-manifest", manifest_value)
            self._validate_item_manifest(
                revision,
                promotion_workflow,
                components,
                manifest_value,
            )
            item_content_artifact = ArtifactMember(
                artifact_id=content_component.artifact_id,
                artifact_revision_id=content_component.artifact_revision_id,
                member_path=content_component.logical_name,
                schema_ref=content_component.schema_ref,
                media_type=content_component.media_type,
                sha256=content_component.sha256,
            )
            content_member = self._resolve_artifact_member_dynamic(
                session, item_content_artifact, max_bytes=MAX_ITEM_MEMBER_BYTES
            )
            content_value = self._json_mapping(content_member.payload)
            validate_contract("assessment-item-content", content_value)
            proposal = next(
                (
                    value
                    for value in extraction_documents.result.items
                    if value.item_proposal_id == source.item_proposal_id
                    and value.item_number == source.item_number
                ),
                None,
            )
            if proposal is None:
                self._fail(
                    "PDF_LEARNING_COMPLETION_ITEM_CONTENT_INVALID",
                    "promoted Item has no unique accepted extraction proposal",
                )
            try:
                extraction_request = LegacyItemExtractionRequest.model_validate(
                    promotion_workflow.initial_request["legacy_extraction_request"]
                )
                expected_item_content = expected_promoted_legacy_item_content(
                    session,
                    artifacts=reader,
                    item_revision_id=revision.item_revision_id,
                    acceptance=extraction_documents.acceptance,
                    result=extraction_documents.result,
                    request=extraction_request,
                    proposal=proposal,
                    components=components,
                )
            except (
                KeyError,
                TypeError,
                ValidationError,
                LegacyItemMediaCompatibilityError,
            ) as exc:
                self._fail(
                    "PDF_LEARNING_COMPLETION_ITEM_CONTENT_INVALID",
                    "promoted Item correction evidence does not resolve exactly",
                    exc,
                )
            expected_content_value = expected_item_content.model_dump(mode="json")
            if (
                content_component.sha256 != content_sha256(expected_content_value)
                or content_value != expected_content_value
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_ITEM_CONTENT_INVALID",
                    "promoted Item content differs from its authorized extraction derivation",
                )
            origin = self._origin_proof(
                origin_resolution=origin_resolution,
                profile=profiles.get(origin_resolution.item_origin_profile_id),
                occurrence_links=tuple(
                    occurrence_links.get(origin_resolution.item_origin_profile_id, ())
                ),
                derivations=tuple(derivations.get(origin_resolution.item_origin_profile_id, ())),
                occurrence_revision=occurrence_revisions.get(
                    origin_resolution.assessment_occurrence_revision_id
                ),
                occurrence_logical=occurrence_logicals.get(
                    origin_resolution.assessment_occurrence_id
                ),
                bundle=bundle_rows.get(origin_resolution.assessment_source_bundle_revision_id),
                revision=revision,
            )
            analysis_proof = AnalysisProof(
                analysis_run_id=run.analysis_run_id,
                predecessor_analysis_run_id=run.predecessor_analysis_run_id,
                analysis_request_id=run.analysis_request_id,
                request_sha256=run.request_sha256,
                submission_sha256=run.submission_sha256,
                state="ACCEPTED",
                successor_run_count=0,
                source_kind="APPROVED_ITEM_REVISION",
                source_revision_id=run.source_revision_id,
                item_id=cast(str, run.item_id),
                item_revision_id=cast(str, run.item_revision_id),
                source_artifact=self._artifact_member(source.artifact_member),
                preset_id=run.preset_id,
                preset_revision_id=run.preset_revision_id,
                preset_sha256=evidence.preset.content_sha256,
                risk_policy_revision_id=run.risk_policy_revision_id,
                risk_policy_sha256=evidence.risk_policy.content_sha256,
                accepted_result_artifact=self._artifact_member(evidence.accepted.accepted_result),
                accepted_result_sha256=cast(str, run.accepted_result_sha256),
            )
            graph_placement = self._graph_placement(
                graph=graph.graph,
                placement=placement,
            )
            completions.append(
                ItemCompletion(
                    bundle_revision_id=source.bundle.assessment_source_bundle_revision_id,
                    item_number=source.item_number,
                    effective_work_unit_id=effective.effective_work_unit_id,
                    acceptance_id=source.extraction_acceptance_id,
                    acceptance_sha256=source.extraction_acceptance_sha256,
                    item_proposal_id=source.item_proposal_id,
                    decision="ACCEPT",
                    promotion_registration_key=revision.registration_key,
                    item_id=source.item_id,
                    item_revision_id=source.item_revision_id,
                    item_lifecycle_state="ACTIVE",
                    item_current_revision_id=item.current_revision_id,
                    item_revision_state="APPROVED",
                    content_pack_release_id=revision.content_pack_release_id,
                    item_manifest_sha256=revision.manifest_sha256,
                    item_manifest_artifact=item_manifest_artifact,
                    item_content_artifact=item_content_artifact,
                    item_origin_profile_id=origin.item_origin_profile_id,
                    item_origin_profile_sha256=origin.item_origin_profile_sha256,
                    origin=origin,
                    analysis=analysis_proof,
                    graph_placement=graph_placement,
                )
            )
            knowledge_documents.append(
                EffectiveKnowledgeAnalysisDocuments(
                    analysis_run_id=run.analysis_run_id,
                    request_storage="KNOWLEDGE_ANALYSIS_RUN_CANONICAL_REQUEST_JSONB",
                    request=evidence.request,
                    result_storage="ARTIFACT_REVISION_RESULT_JSONB_AND_MEMBER",
                    result=evidence.result,
                    proposal_receipt=evidence.receipt,
                    proposal=evidence.proposal,
                )
            )
            analysis_workflow_ids.add(run.workflow_id)
            analysis_workflow_ids.add(revision.workflow_id)
            if run.platform_job_id is not None:
                analysis_job_ids.add(run.platform_job_id)

        sorted_items = tuple(
            sorted(completions, key=lambda value: (value.bundle_revision_id, value.item_number))
        )
        if len(sorted_items) != 520:
            self._fail(
                "PDF_LEARNING_COMPLETION_ITEM_SET_INVALID",
                "promotion/analysis/Graph chain count differs from exact 520",
            )
        return _ResolvedItems(
            items=sorted_items,
            knowledge_documents=tuple(
                sorted(knowledge_documents, key=lambda value: value.analysis_run_id)
            ),
            recoveries=recoveries,
            workflow_ids=tuple(sorted(analysis_workflow_ids)),
            job_ids=tuple(sorted(analysis_job_ids)),
        )

    def _resolve_bundles(
        self,
        session: Session,
        *,
        bundle_ids: tuple[str, ...],
        inventory: LegacySourceInventoryV2,
        inventory_pointer: AssessmentArtifactMemberPointer,
    ) -> tuple[AssessmentSourceBundleRevision, ...]:
        revision_rows = tuple(
            session.scalars(
                select(AssessmentSourceBundleRevisionRecord).where(
                    AssessmentSourceBundleRevisionRecord.assessment_source_bundle_revision_id.in_(
                        bundle_ids
                    )
                )
            )
        )
        if len(revision_rows) != len(bundle_ids) or {
            value.assessment_source_bundle_revision_id for value in revision_rows
        } != set(bundle_ids):
            self._fail(
                "PDF_LEARNING_COMPLETION_BUNDLE_INVALID",
                "reviewed source bundle revision set is incomplete",
            )
        logical_ids = tuple(sorted({value.assessment_source_bundle_id for value in revision_rows}))
        logicals = {
            value.assessment_source_bundle_id: value
            for value in session.scalars(
                select(AssessmentSourceBundleRecord).where(
                    AssessmentSourceBundleRecord.assessment_source_bundle_id.in_(logical_ids)
                )
            )
        }
        members_by_revision: dict[str, list[AssessmentSourceBundleMemberRecord]] = defaultdict(list)
        for member in session.scalars(
            select(AssessmentSourceBundleMemberRecord)
            .where(
                AssessmentSourceBundleMemberRecord.assessment_source_bundle_revision_id.in_(
                    bundle_ids
                )
            )
            .order_by(
                AssessmentSourceBundleMemberRecord.assessment_source_bundle_revision_id,
                AssessmentSourceBundleMemberRecord.ordinal,
            )
        ):
            members_by_revision[member.assessment_source_bundle_revision_id].append(member)
        inventory_by_key = {value.entry_key: value for value in inventory.entries}
        resolved: list[AssessmentSourceBundleRevision] = []
        for row in revision_rows:
            logical = logicals.get(row.assessment_source_bundle_id)
            member_rows = tuple(
                members_by_revision.get(row.assessment_source_bundle_revision_id, ())
            )
            if (
                logical is None
                or logical.lifecycle_state != "ACTIVE"
                or logical.current_revision_id != row.assessment_source_bundle_revision_id
                or row.state != "REVIEWED"
                or row.inventory_id != inventory.inventory_id
                or row.inventory_sha256 != inventory.inventory_sha256
                or self._artifact_member(inventory_pointer)
                != ArtifactMember(
                    artifact_id=row.inventory_artifact_id,
                    artifact_revision_id=row.inventory_artifact_revision_id,
                    member_path=row.inventory_artifact_member_path,
                    schema_ref=row.inventory_artifact_schema_ref,
                    media_type=row.inventory_artifact_media_type,
                    sha256=row.inventory_artifact_sha256,
                )
                or not member_rows
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_BUNDLE_INVALID",
                    "source bundle row differs from its inventory/current reviewed identity",
                )
            members: list[AssessmentSourceBundleMember] = []
            for member in member_rows:
                entry = inventory_by_key.get(member.inventory_entry_key)
                source = AssessmentArtifactMemberPointer(
                    artifact_id=member.source_artifact_id,
                    artifact_revision_id=member.source_artifact_revision_id,
                    member_path=member.source_member_path,
                    schema_ref=member.source_schema_ref,
                    media_type=member.source_media_type,
                    sha256=member.source_sha256,
                )
                if (
                    entry is None
                    or member.inventory_id != inventory.inventory_id
                    or member.inventory_sha256 != inventory.inventory_sha256
                    or member.inventory_content_sha256 != entry.content_sha256
                    or member.source_sha256 != entry.content_sha256
                ):
                    self._fail(
                        "PDF_LEARNING_COMPLETION_BUNDLE_MEMBER_INVALID",
                        "reviewed bundle member differs from its inventory entry",
                    )
                self._resolve_artifact_member_dynamic(
                    session,
                    self._artifact_member(source),
                    max_bytes=MAX_GRAPH_MEMBER_BYTES,
                )
                members.append(
                    AssessmentSourceBundleMember.model_validate(
                        {
                            "member_id": member.assessment_source_bundle_member_id,
                            "role": member.role,
                            "source": source.model_dump(mode="json"),
                            "inventory_source": {
                                "inventory_id": member.inventory_id,
                                "inventory_sha256": member.inventory_sha256,
                                "entry_key": member.inventory_entry_key,
                                "content_sha256": member.inventory_content_sha256,
                            },
                        }
                    )
                )
            try:
                resolved.append(
                    AssessmentSourceBundleRevision.model_validate(
                        {
                            "schema_version": "assessment-source-bundle/1.0",
                            "assessment_source_bundle_id": row.assessment_source_bundle_id,
                            "assessment_source_bundle_revision_id": (
                                row.assessment_source_bundle_revision_id
                            ),
                            "revision_number": row.revision_number,
                            "previous_revision_id": row.previous_revision_id,
                            "bundle_key": logical.bundle_key,
                            "state": row.state,
                            "inventory_id": row.inventory_id,
                            "inventory_sha256": row.inventory_sha256,
                            "inventory_artifact": inventory_pointer.model_dump(mode="json"),
                            "occurrence": {
                                "assessment_occurrence_id": row.assessment_occurrence_id,
                                "assessment_occurrence_revision_id": (
                                    row.assessment_occurrence_revision_id
                                ),
                                "occurrence_revision_sha256": (row.occurrence_revision_sha256),
                            },
                            "rights_policy": {
                                "rights_policy_id": row.rights_policy_id,
                                "rights_policy_revision_id": row.rights_policy_revision_id,
                                "rights_policy_sha256": row.rights_policy_sha256,
                            },
                            "members": [value.model_dump(mode="json") for value in members],
                            "reviewed_at": row.reviewed_at.astimezone(UTC),
                            "reviewed_by": row.reviewed_by,
                            "bundle_manifest_sha256": row.bundle_manifest_sha256,
                        }
                    )
                )
            except ValidationError as exc:
                self._fail(
                    "PDF_LEARNING_COMPLETION_BUNDLE_INVALID",
                    "reviewed source bundle does not match its canonical contract",
                    exc,
                )
        return tuple(
            sorted(
                resolved,
                key=lambda value: value.assessment_source_bundle_revision_id,
            )
        )

    @staticmethod
    def _batch_proof(
        batch: ResolvedBatchSnapshot,
        *,
        role: Literal["ORIGINAL_SCOPE", "VALIDATION_SUCCESSOR"],
    ) -> BatchProof:
        accepted = sum(isinstance(value, AcceptedTerminalWorkUnit) for value in batch.work_units)
        failed = sum(isinstance(value, FailedTerminalWorkUnit) for value in batch.work_units)
        return BatchProof(
            role=role,
            extraction_batch_id=batch.manifest.extraction_batch_id,
            manifest_sha256=batch.manifest.manifest_sha256,
            manifest_artifact=PostgresPdfLearningCompletionSource._artifact_member(
                batch.manifest_artifact
            ),
            inventory_id=batch.manifest.inventory_id,
            inventory_sha256=batch.manifest.inventory_sha256,
            state=batch.state,
            total_work_unit_count=len(batch.work_units),
            accepted_work_unit_count=accepted,
            failed_work_unit_count=failed,
            other_work_unit_count=len(batch.work_units) - accepted - failed,
        )

    @staticmethod
    def _artifact_member(
        pointer: (
            AssessmentArtifactMemberPointer
            | KnowledgeArtifactMemberPointer
            | KnowledgeAnalysisSourceArtifactMemberV2
            | KnowledgeProposalArtifactMember
        ),
    ) -> ArtifactMember:
        if pointer.schema_ref is None:
            raise ValueError("Artifact member schema reference is absent")
        return ArtifactMember(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
        )

    def _resolve_assessment_member(
        self,
        session: Session,
        pointer: AssessmentArtifactMemberPointer,
        *,
        artifact_types: Collection[str],
        primary_file: str,
        max_bytes: int,
    ) -> PinnedArtifactMember:
        return resolve_pinned_artifact_member(
            session,
            self.settings,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            expected_artifact_types=artifact_types,
            expected_primary_file=primary_file,
            max_bytes=max_bytes,
        )

    def _resolve_knowledge_member(
        self,
        session: Session,
        pointer: KnowledgeArtifactMemberPointer,
        *,
        artifact_types: Collection[str],
        primary_file: str,
        max_bytes: int,
        manifest_artifact_types: Collection[str] | None = None,
    ) -> PinnedArtifactMember:
        return resolve_pinned_artifact_member(
            session,
            self.settings,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            expected_artifact_types=artifact_types,
            expected_primary_file=primary_file,
            max_bytes=max_bytes,
            expected_manifest_artifact_types=manifest_artifact_types,
        )

    def _resolve_artifact_member_dynamic(
        self,
        session: Session,
        pointer: ArtifactMember,
        *,
        max_bytes: int,
    ) -> PinnedArtifactMember:
        logical = session.get(ArtifactRecord, pointer.artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        primary = revision.manifest.get("primary_file") if revision is not None else None
        if logical is None or revision is None or not isinstance(primary, str):
            raise ValueError("dynamic Artifact pointer does not resolve")
        return resolve_pinned_artifact_member(
            session,
            self.settings,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            expected_artifact_types={logical.artifact_type},
            expected_primary_file=primary,
            max_bytes=max_bytes,
        )

    @staticmethod
    def _json_mapping(payload: bytes) -> dict[str, object]:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=PostgresPdfLearningCompletionSource._unique_json_object,
            parse_constant=PostgresPdfLearningCompletionSource._reject_json_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("canonical JSON member is not an object")
        return value

    @classmethod
    def _typed_json(
        cls,
        payload: bytes,
        *,
        route: str,
        model: type[TModel],
    ) -> TModel:
        value = cls._json_mapping(payload)
        validate_contract(route, value)
        return model.model_validate(value)

    @staticmethod
    def _reject_json_constant(_value: str) -> NoReturn:
        raise ValueError("non-finite JSON is forbidden")

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, member in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = member
        return value

    def _resolve_analysis_history(
        self,
        session: Session,
        *,
        accepted_rows: tuple[KnowledgeAnalysisRunRecord, ...],
        snapshot_analyses: tuple[GraphSnapshotAnalysisDatabaseEvidence, ...],
    ) -> tuple[
        tuple[KnowledgeAnalysisRunRecord, ...],
        tuple[AnalysisRecoveryLineage, ...],
    ]:
        accepted_ids = {value.analysis_run_id for value in accepted_rows}
        snapshot_by_run = {value.analysis_run_id: value for value in snapshot_analyses}
        if (
            len(accepted_ids) != len(accepted_rows)
            or len(snapshot_by_run) != len(snapshot_analyses)
            or not accepted_ids.issubset(snapshot_by_run)
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_HISTORY_INVALID",
                "accepted analysis identity set is ambiguous",
            )
        source_revision_ids = tuple(sorted({value.source_revision_id for value in accepted_rows}))
        source_artifact_ids = tuple(sorted({value.source_artifact_id for value in accepted_rows}))
        source_artifact_revisions = tuple(
            sorted({value.source_artifact_revision_id for value in accepted_rows})
        )
        source_hashes = tuple(sorted({value.source_sha256 for value in accepted_rows}))
        result_artifact_ids = tuple(
            sorted(
                {
                    value.accepted_result_artifact_id
                    for value in accepted_rows
                    if value.accepted_result_artifact_id is not None
                }
            )
        )
        result_artifact_revisions = tuple(
            sorted(
                {
                    value.accepted_result_artifact_revision_id
                    for value in accepted_rows
                    if value.accepted_result_artifact_revision_id is not None
                }
            )
        )
        result_hashes = tuple(
            sorted(
                {
                    value.accepted_result_sha256
                    for value in accepted_rows
                    if value.accepted_result_sha256 is not None
                }
            )
        )
        scoped = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord).where(
                    or_(
                        KnowledgeAnalysisRunRecord.analysis_run_id.in_(accepted_ids),
                        KnowledgeAnalysisRunRecord.source_revision_id.in_(source_revision_ids),
                        KnowledgeAnalysisRunRecord.source_artifact_id.in_(source_artifact_ids),
                        KnowledgeAnalysisRunRecord.source_artifact_revision_id.in_(
                            source_artifact_revisions
                        ),
                        KnowledgeAnalysisRunRecord.source_sha256.in_(source_hashes),
                        KnowledgeAnalysisRunRecord.accepted_result_artifact_id.in_(
                            result_artifact_ids
                        ),
                        KnowledgeAnalysisRunRecord.accepted_result_artifact_revision_id.in_(
                            result_artifact_revisions
                        ),
                        KnowledgeAnalysisRunRecord.accepted_result_sha256.in_(result_hashes),
                    )
                )
            )
        )
        historical_rows: list[KnowledgeAnalysisRunRecord] = []
        current_rows: list[KnowledgeAnalysisRunRecord] = []
        for row in scoped:
            if self._validated_historical_analysis_request(row.canonical_request):
                historical_rows.append(row)
            else:
                current_rows.append(row)
        scoped_by_id = {value.analysis_run_id: value for value in current_rows}
        predecessor_ids = {
            value.predecessor_analysis_run_id
            for value in accepted_rows
            if value.predecessor_analysis_run_id is not None
        }
        child_rows = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord).where(
                    KnowledgeAnalysisRunRecord.predecessor_analysis_run_id.in_(
                        tuple(sorted(set(scoped_by_id) | accepted_ids | predecessor_ids))
                    )
                )
            )
        )
        for row in child_rows:
            scoped_by_id[row.analysis_run_id] = row
        if (
            len(scoped_by_id) != 524
            or len(predecessor_ids) != 4
            or set(scoped_by_id) != accepted_ids | predecessor_ids
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_HISTORY_INVALID",
                "analysis cohort is not exactly 520 accepted leaves plus four predecessors",
            )
        successors: dict[str, list[KnowledgeAnalysisRunRecord]] = defaultdict(list)
        for row in scoped_by_id.values():
            if row.predecessor_analysis_run_id is not None:
                successors[row.predecessor_analysis_run_id].append(row)
        if any(successors.get(run_id) for run_id in accepted_ids):
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_HISTORY_INVALID",
                "accepted analysis is not a terminal leaf",
            )

        recoveries: list[AnalysisRecoveryLineage] = []
        for accepted in accepted_rows:
            snapshot_row = snapshot_by_run[accepted.analysis_run_id]
            if (
                accepted.state != "ACCEPTED"
                or accepted.source_kind != "APPROVED_ITEM_REVISION"
                or snapshot_row.source_revision_id != accepted.source_revision_id
                or snapshot_row.source_artifact_id != accepted.source_artifact_id
                or snapshot_row.source_artifact_revision_id != accepted.source_artifact_revision_id
                or snapshot_row.source_sha256 != accepted.source_sha256
                or snapshot_row.accepted_result_artifact_id != accepted.accepted_result_artifact_id
                or snapshot_row.accepted_result_artifact_revision_id
                != accepted.accepted_result_artifact_revision_id
                or snapshot_row.accepted_result_sha256 != accepted.accepted_result_sha256
                or accepted.error_code is not None
                or not self._analysis_request_matches_run(accepted)
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_ANALYSIS_HISTORY_INVALID",
                    "accepted analysis row differs from Graph/current request evidence",
                )
            predecessor_id = accepted.predecessor_analysis_run_id
            if predecessor_id is None:
                continue
            predecessor = scoped_by_id.get(predecessor_id)
            predecessor_successors = tuple(successors.get(predecessor_id, ()))
            if (
                predecessor is None
                or predecessor.state != "FAILED"
                or predecessor.error_code is None
                or predecessor.accepted_result_artifact_id is not None
                or predecessor.accepted_result_artifact_revision_id is not None
                or predecessor.accepted_result_sha256 is not None
                or len(predecessor_successors) != 1
                or predecessor_successors[0].analysis_run_id != accepted.analysis_run_id
                or predecessor.item_id != accepted.item_id
                or predecessor.item_revision_id != accepted.item_revision_id
                or predecessor.source_kind != accepted.source_kind
                or predecessor.source_revision_id != accepted.source_revision_id
                or predecessor.source_artifact_id != accepted.source_artifact_id
                or predecessor.source_artifact_revision_id != accepted.source_artifact_revision_id
                or predecessor.source_sha256 != accepted.source_sha256
                or not self._analysis_request_matches_run(predecessor)
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_ANALYSIS_RECOVERY_INVALID",
                    "failed analysis predecessor is not the exact one-to-one retry lineage",
                )
            predecessor_request = KnowledgeAnalysisRequestV9.model_validate(
                predecessor.canonical_request
            )
            successor_request = KnowledgeAnalysisRequestV9.model_validate(
                accepted.canonical_request
            )
            if (
                predecessor_request.predecessor_analysis_run_id is not None
                or successor_request.predecessor_analysis_run_id != predecessor.analysis_run_id
                or predecessor_request.source != successor_request.source
                or predecessor_request.execution_preset_id != successor_request.execution_preset_id
                or predecessor_request.execution_preset_revision_id
                != successor_request.execution_preset_revision_id
                or predecessor_request.execution_preset_sha256
                != successor_request.execution_preset_sha256
                or predecessor_request.risk_policy_revision_id
                != successor_request.risk_policy_revision_id
                or predecessor_request.general_knowledge_mode
                != successor_request.general_knowledge_mode
                or predecessor_request.requested_outputs != successor_request.requested_outputs
                or predecessor_request.prior_graph_snapshot
                != successor_request.prior_graph_snapshot
            ):
                self._fail(
                    "PDF_LEARNING_COMPLETION_ANALYSIS_RECOVERY_INVALID",
                    "analysis retry changed a pinned dependency",
                )
            body = {
                "item_id": cast(str, accepted.item_id),
                "item_revision_id": cast(str, accepted.item_revision_id),
                "predecessor_analysis_run_id": predecessor.analysis_run_id,
                "predecessor_analysis_request_id": predecessor.analysis_request_id,
                "predecessor_request_sha256": predecessor.request_sha256,
                "predecessor_submission_sha256": predecessor.submission_sha256,
                "predecessor_state": "FAILED",
                "predecessor_error_code": predecessor.error_code,
                "predecessor_accepted_result_present": False,
                "predecessor_successor_count": 1,
                "successor_analysis_run_id": accepted.analysis_run_id,
                "successor_analysis_request_id": accepted.analysis_request_id,
                "successor_request_sha256": accepted.request_sha256,
                "successor_state": "ACCEPTED",
            }
            recoveries.append(
                AnalysisRecoveryLineage.model_validate(
                    {**body, "lineage_sha256": content_sha256(body)}
                )
            )
        if len(recoveries) != 4:
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_RECOVERY_INVALID",
                "analysis retry lineage is not exactly four",
            )
        return (
            tuple(
                sorted(
                    (*scoped_by_id.values(), *historical_rows),
                    key=lambda value: value.analysis_run_id,
                )
            ),
            tuple(
                sorted(
                    recoveries,
                    key=lambda value: value.predecessor_analysis_run_id,
                )
            ),
        )

    def _validated_historical_analysis_request(self, value: object) -> bool:
        if not isinstance(value, dict):
            return False
        schema_version = value.get("schema_version")
        if not isinstance(schema_version, str):
            return False
        contract = _HISTORICAL_ANALYSIS_REQUESTS.get(schema_version)
        if contract is None:
            return False
        route, model = contract
        try:
            validate_contract(route, value)
            model.model_validate(value)
        except (JsonSchemaValidationError, ValidationError, ValueError) as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_ANALYSIS_HISTORY_INVALID",
                "historical analysis request does not validate exactly",
                exc,
            )
        return True

    @staticmethod
    def _analysis_request_matches_run(run: KnowledgeAnalysisRunRecord) -> bool:
        try:
            validate_contract("knowledge-analysis-request-v9", run.canonical_request)
            request = KnowledgeAnalysisRequestV9.model_validate(run.canonical_request)
        except (ValidationError, ValueError):
            return False
        source = request.source
        return (
            request.analysis_request_id == run.analysis_request_id
            and request.request_sha256 == run.request_sha256
            and request.predecessor_analysis_run_id == run.predecessor_analysis_run_id
            and request.created_at == run.created_at.astimezone(UTC)
            and request.execution_preset_id == run.preset_id
            and request.execution_preset_revision_id == run.preset_revision_id
            and request.execution_preset_sha256
            == cast(str, run.canonical_request.get("execution_preset_sha256"))
            and request.risk_policy_revision_id == run.risk_policy_revision_id
            and run.risk_policy_sha256 == cast(str, run.canonical_request.get("risk_policy_sha256"))
            and source.source_kind == run.source_kind
            and source.item_revision_id == run.source_revision_id
            and source.item_id == run.item_id
            and source.item_revision_id == run.item_revision_id
            and source.artifact_member.artifact_id == run.source_artifact_id
            and source.artifact_member.artifact_revision_id == run.source_artifact_revision_id
            and source.artifact_member.sha256 == run.source_sha256
        )

    def _load_accepted_analysis(
        self,
        session: Session,
        reader: _PinnedCatalogArtifactReader,
        run: KnowledgeAnalysisRunRecord,
    ) -> _AcceptedAnalysisEvidence:
        try:
            validate_contract("knowledge-analysis-request-v9", run.canonical_request)
            request = KnowledgeAnalysisRequestV9.model_validate(run.canonical_request)
            source = request.source
            resolved_source = resolve_historically_approved_item_source(
                session,
                artifacts=reader,
                item_revision_id=source.item_revision_id,
                source_class="PAST_EXAM",
            )
            if resolved_source != source or not self._analysis_request_matches_run(run):
                raise ValueError("analysis source/request row differs")
            source_member = self._resolve_artifact_member_dynamic(
                session,
                self._artifact_member(source.artifact_member),
                max_bytes=MAX_ITEM_MEMBER_BYTES,
            )
            if len(source_member.payload) != source.artifact_member.bytes:
                raise ValueError("analysis item source byte count differs")
            validate_contract("assessment-item-content", self._json_mapping(source_member.payload))

            if (
                run.state != "ACCEPTED"
                or run.accepted_result_artifact_id is None
                or run.accepted_result_artifact_revision_id is None
                or run.accepted_result_sha256 is None
                or run.proposal_artifact_id is None
                or run.proposal_artifact_revision_id is None
                or run.proposal_content_set_sha256 is None
                or run.error_code is not None
            ):
                raise ValueError("accepted analysis terminal pointers are incomplete")
            accepted_pointer = KnowledgeArtifactMemberPointer(
                artifact_id=run.accepted_result_artifact_id,
                artifact_revision_id=run.accepted_result_artifact_revision_id,
                sha256=run.accepted_result_sha256,
                schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
                media_type="application/json",
                logical_name="accepted-result.json",
                member_path="evidence/accepted-result.json",
            )
            accepted_member = self._resolve_knowledge_member(
                session,
                accepted_pointer,
                artifact_types={"knowledge-analysis-accepted-result"},
                primary_file="evidence/accepted-result.json",
                max_bytes=MAX_ITEM_MEMBER_BYTES,
            )
            result = self._typed_json(
                accepted_member.payload,
                route="knowledge-analysis-result-v9",
                model=KnowledgeAnalysisResultV9,
            )
            accepted_revision = session.get(
                ArtifactRevisionRecord, run.accepted_result_artifact_revision_id
            )
            if accepted_revision is None:
                raise ValueError("accepted result revision is absent")
            validate_contract("knowledge-analysis-result-v9", accepted_revision.result)
            database_result = KnowledgeAnalysisResultV9.model_validate(accepted_revision.result)
            proposal_pointer = KnowledgeArtifactMemberPointer(
                artifact_id=result.proposal_receipt.artifact_id,
                artifact_revision_id=result.proposal_receipt.artifact_revision_id,
                sha256=result.proposal_receipt.sha256,
                schema_ref=result.proposal_receipt.schema_ref,
                media_type=result.proposal_receipt.media_type,
                logical_name=result.proposal_receipt.logical_name,
                member_path=result.proposal_receipt.member_path,
            )
            proposal_member = self._resolve_knowledge_member(
                session,
                proposal_pointer,
                artifact_types={"workflow_support"},
                primary_file="normalized/proposal-receipt.json",
                max_bytes=MAX_ITEM_MEMBER_BYTES,
                manifest_artifact_types={"knowledge-analysis-proposal"},
            )
            if len(proposal_member.payload) != result.proposal_receipt.bytes:
                raise ValueError("proposal receipt byte count differs")
            receipt = self._typed_json(
                proposal_member.payload,
                route="knowledge-analysis-proposal-receipt-v8",
                model=KnowledgeAnalysisProposalReceiptV8,
            )
            proposal_revision = session.get(
                ArtifactRevisionRecord, result.proposal_receipt.artifact_revision_id
            )
            if proposal_revision is None:
                raise ValueError("proposal receipt revision is absent")
            validate_contract("knowledge-analysis-proposal-receipt-v8", proposal_revision.result)
            database_receipt = KnowledgeAnalysisProposalReceiptV8.model_validate(
                proposal_revision.result
            )
            proposal = resolve_knowledge_analysis_proposal(reader, receipt)
            if not isinstance(proposal, KnowledgeAnalysisWorkerProposalV7):
                raise ValueError("analysis proposal is not V7")

            preset = session.get(ExecutionPresetRevisionRecord, run.preset_revision_id)
            risk_policy = session.get(
                KnowledgeAnalysisRiskPolicyRevisionRecord,
                run.risk_policy_revision_id,
            )
            if preset is None or risk_policy is None:
                raise ValueError("analysis policy dependency is absent")
            preset_model = (
                ExecutionPresetRevisionV2.model_validate(preset.canonical_document)
                if preset.schema_version == "execution-preset-revision/2.0"
                else ExecutionPresetRevision.model_validate(preset.canonical_document)
            )
            validate_contract("knowledge-analysis-risk-policy", risk_policy.canonical_document)
            risk_model = KnowledgeAnalysisRiskPolicy.model_validate(risk_policy.canonical_document)
            if (
                result != database_result
                or receipt != database_receipt
                or result.analysis_request_id != request.analysis_request_id
                or result.analysis_request_sha256 != request.request_sha256
                or result.source != source
                or receipt.analysis_request_id != request.analysis_request_id
                or receipt.source != source
                or result.proposal_receipt.artifact_id != run.proposal_artifact_id
                or result.proposal_receipt.artifact_revision_id != run.proposal_artifact_revision_id
                or proposal_revision.job_id != run.platform_job_id
                or result.proposal_content_set_sha256 != run.proposal_content_set_sha256
                or receipt.content_set_sha256 != run.proposal_content_set_sha256
                or result.counts != receipt.counts
                or result.general_knowledge_used != receipt.general_knowledge_used
                or result.minimum_confidence_milli != receipt.minimum_confidence_milli
                or result.blocking_ambiguity_count != receipt.blocking_ambiguity_count
                or run.anchor_count != receipt.counts.anchors
                or run.node_count != receipt.counts.nodes
                or run.edge_count != receipt.counts.edges
                or run.claim_count != receipt.counts.claims
                or run.component_count != receipt.counts.component_observations
                or run.ambiguity_count != receipt.counts.ambiguities
                or preset.state != "RELEASED"
                or preset_model.preset_id != run.preset_id
                or preset_model.preset_revision_id != run.preset_revision_id
                or preset_model.content_sha256 != preset.content_sha256
                or request.execution_preset_sha256 != preset.content_sha256
                or risk_policy.state != "RELEASED"
                or risk_model.content_sha256 != risk_policy.content_sha256
                or request.risk_policy_revision_id != risk_policy.risk_policy_revision_id
                or run.risk_policy_sha256 != risk_policy.content_sha256
            ):
                raise ValueError("accepted analysis document/row dependencies differ")
            accepted = AcceptedAnalysisProposal(
                analysis_run_id=run.analysis_run_id,
                source=source,
                accepted_result=accepted_pointer,
                proposal=proposal,
            )
        except (
            KnowledgeAnalysisSourceError,
            KnowledgeProposalResolutionError,
            ValidationError,
            ValueError,
        ) as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_ACCEPTED_ANALYSIS_INVALID",
                "accepted analysis evidence does not resolve exactly",
                exc,
            )
        return _AcceptedAnalysisEvidence(
            run=run,
            request=request,
            result=result,
            receipt=receipt,
            proposal=proposal,
            accepted=accepted,
            preset=preset,
            risk_policy=risk_policy,
        )

    @staticmethod
    def _validate_item_manifest(
        revision: ItemRevisionRecord,
        promotion_workflow: WorkflowInstanceRecord,
        components: tuple[ItemComponentRecord, ...],
        manifest: Mapping[str, object],
    ) -> None:
        content_pack = manifest.get("content_pack")
        workflow = manifest.get("workflow")
        metadata = manifest.get("metadata")
        manifest_components = manifest.get("components")
        created_at = manifest.get("created_at")
        if not all(
            isinstance(value, dict) for value in (content_pack, workflow, metadata)
        ) or not isinstance(manifest_components, list):
            raise ValueError("Item Revision manifest structure is incomplete")
        assert isinstance(content_pack, dict)
        assert isinstance(workflow, dict)
        assert isinstance(metadata, dict)
        expected_components = tuple(
            sorted(
                (
                    {
                        "component_type": value.component_type,
                        "ordinal": value.ordinal,
                        "schema_ref": value.schema_ref,
                        "media_type": value.media_type,
                        "artifact_id": value.artifact_id,
                        "artifact_revision_id": value.artifact_revision_id,
                        "sha256": value.sha256,
                        "logical_name": value.logical_name,
                        "required": value.required,
                    }
                    for value in components
                ),
                key=lambda value: (
                    cast(str, value["component_type"]),
                    cast(int, value["ordinal"]),
                ),
            )
        )
        actual_components = tuple(
            sorted(
                (value for value in manifest_components if isinstance(value, dict)),
                key=lambda value: (
                    str(value.get("component_type", "")),
                    int(value.get("ordinal", -1)),
                ),
            )
        )
        try:
            parsed_created_at = datetime.fromisoformat(
                cast(str, created_at).replace("Z", "+00:00")
            ).astimezone(UTC)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("Item Revision manifest timestamp is invalid") from exc
        if (
            len(actual_components) != len(manifest_components)
            or actual_components != expected_components
            or manifest.get("schema_version") != "1.0"
            or manifest.get("item_id") != revision.item_id
            or manifest.get("item_revision_id") != revision.item_revision_id
            or manifest.get("revision_number") != revision.revision_number
            or content_pack.get("release_id") != revision.content_pack_release_id
            or workflow.get("workflow_id") != revision.workflow_id
            or workflow.get("workflow_id") != promotion_workflow.workflow_id
            or workflow.get("definition_key") != promotion_workflow.definition_key
            or workflow.get("definition_version") != promotion_workflow.definition_version
            or revision.workflow_definition_version != promotion_workflow.definition_version
            or metadata.get("sha256") != revision.metadata_sha256
            or parsed_created_at != promotion_workflow.created_at.astimezone(UTC)
        ):
            raise ValueError("Item Revision manifest differs from canonical database rows")

    def _origin_proof(
        self,
        *,
        origin_resolution: PastExamOriginResolution,
        profile: ItemOriginProfileRecord | None,
        occurrence_links: tuple[ItemOriginOccurrenceRecord, ...],
        derivations: tuple[ItemOriginDerivationRecord, ...],
        occurrence_revision: AssessmentOccurrenceRevisionRecord | None,
        occurrence_logical: AssessmentOccurrenceRecord | None,
        bundle: AssessmentSourceBundleRevisionRecord | None,
        revision: ItemRevisionRecord,
    ) -> InstitutionalOriginProof:
        if (
            profile is None
            or occurrence_revision is None
            or occurrence_logical is None
            or bundle is None
            or len(occurrence_links) != 1
            or len(derivations) != 1
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ORIGIN_INVALID",
                "institutional origin chain has invalid cardinality",
            )
        occurrence_link = occurrence_links[0]
        derivation = derivations[0]
        if (
            profile.item_origin_profile_id != origin_resolution.item_origin_profile_id
            or profile.profile_sha256 != origin_resolution.item_origin_profile_sha256
            or profile.item_id != revision.item_id
            or profile.item_revision_id != revision.item_revision_id
            or profile.item_manifest_sha256 != revision.manifest_sha256
            or profile.source_domain != "EXTERNAL_INSTITUTION"
            or profile.creation_method != "UNKNOWN"
            or occurrence_link.assessment_occurrence_id
            != occurrence_revision.assessment_occurrence_id
            or occurrence_link.assessment_occurrence_revision_id
            != occurrence_revision.assessment_occurrence_revision_id
            or occurrence_link.occurrence_revision_sha256 != occurrence_revision.revision_sha256
            or occurrence_revision.schema_version != "assessment-occurrence-revision/2.0"
            or occurrence_revision.revision_state != "REVIEWED"
            or occurrence_logical.lifecycle_state != "ACTIVE"
            or occurrence_logical.current_revision_id
            != occurrence_revision.assessment_occurrence_revision_id
            or derivation.source_kind != "ASSESSMENT_SOURCE_BUNDLE_REVISION"
            or derivation.relation != "DIGITIZED_FROM"
            or derivation.logical_id != bundle.assessment_source_bundle_id
            or derivation.revision_id != bundle.assessment_source_bundle_revision_id
            or derivation.manifest_sha256 != bundle.bundle_manifest_sha256
            or bundle.state != "REVIEWED"
            or bundle.assessment_occurrence_id != occurrence_revision.assessment_occurrence_id
            or bundle.assessment_occurrence_revision_id
            != occurrence_revision.assessment_occurrence_revision_id
            or bundle.occurrence_revision_sha256 != occurrence_revision.revision_sha256
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ORIGIN_INVALID",
                "institutional Item origin differs from the resolved placement",
            )
        rights = RightsPolicyProof(
            rights_policy_id=profile.rights_policy_id,
            rights_policy_revision_id=profile.rights_policy_revision_id,
            rights_policy_sha256=profile.rights_policy_sha256,
        )
        if (
            occurrence_revision.rights_policy_id,
            occurrence_revision.rights_policy_revision_id,
            occurrence_revision.rights_policy_sha256,
        ) != (
            rights.rights_policy_id,
            rights.rights_policy_revision_id,
            rights.rights_policy_sha256,
        ) or (
            bundle.rights_policy_id,
            bundle.rights_policy_revision_id,
            bundle.rights_policy_sha256,
        ) != (
            rights.rights_policy_id,
            rights.rights_policy_revision_id,
            rights.rights_policy_sha256,
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_ORIGIN_RIGHTS_INVALID",
                "institutional origin rights policy pointers differ",
            )
        return InstitutionalOriginProof(
            item_origin_profile_id=profile.item_origin_profile_id,
            item_origin_profile_sha256=profile.profile_sha256,
            profile_item_id=profile.item_id,
            profile_item_revision_id=profile.item_revision_id,
            profile_item_manifest_sha256=profile.item_manifest_sha256,
            source_domain="EXTERNAL_INSTITUTION",
            creation_method="UNKNOWN",
            occurrence_relation_count=1,
            derivation_count=1,
            derivation_source_kind="ASSESSMENT_SOURCE_BUNDLE_REVISION",
            derivation_relation="DIGITIZED_FROM",
            assessment_source_bundle_id=bundle.assessment_source_bundle_id,
            assessment_source_bundle_revision_id=(bundle.assessment_source_bundle_revision_id),
            assessment_source_bundle_sha256=bundle.bundle_manifest_sha256,
            bundle_revision_state="REVIEWED",
            assessment_occurrence_id=occurrence_revision.assessment_occurrence_id,
            assessment_occurrence_revision_id=(
                occurrence_revision.assessment_occurrence_revision_id
            ),
            assessment_occurrence_revision_sha256=occurrence_revision.revision_sha256,
            occurrence_schema_version="assessment-occurrence-revision/2.0",
            occurrence_revision_state="REVIEWED",
            occurrence_lifecycle_state="ACTIVE",
            occurrence_current_revision_id=occurrence_logical.current_revision_id,
            profile_rights_policy=rights,
            occurrence_rights_policy=rights,
            bundle_rights_policy=rights,
        )

    @staticmethod
    def _graph_placement(
        *,
        graph: GraphSnapshot,
        placement: AssessmentOccurrenceItemBinding,
    ) -> GraphPlacement:
        body = placement.model_dump(mode="json", exclude={"placement_sha256"})
        if content_sha256(body) != placement.placement_sha256:
            raise ValueError("Graph placement self-hash differs")
        membership = {
            "graph_id": graph.graph_id,
            "graph_snapshot_revision_id": graph.graph_snapshot_revision_id,
            "graph_snapshot_sha256": graph.snapshot_sha256,
            **placement.model_dump(mode="json"),
        }
        return GraphPlacement.model_validate(
            {**membership, "membership_sha256": content_sha256(membership)}
        )

    def _quiescence(
        self,
        session: Session,
        runtime: PdfLearningRuntimeObservation,
        *,
        extraction: _ResolvedExtraction,
        items: _ResolvedItems,
    ) -> Quiescence:
        workflow_ids = tuple(sorted(set(extraction.workflow_ids) | set(items.workflow_ids)))
        job_ids = tuple(sorted(set(extraction.job_ids) | set(items.job_ids)))
        active_jobs = (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.job_id.in_(job_ids), JobRecord.status.in_(ACTIVE_JOB_STATES))
            )
            if job_ids
            else 0
        )
        active_workflows = (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(
                    WorkflowInstanceRecord.workflow_id.in_(workflow_ids),
                    WorkflowInstanceRecord.state.in_(ACTIVE_WORKFLOW_STATES),
                )
            )
            if workflow_ids
            else 0
        )
        active_commands = (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(
                    WorkflowCommandRecord.workflow_id.in_(workflow_ids),
                    WorkflowCommandRecord.state.in_(ACTIVE_COMMAND_STATES),
                )
            )
            if workflow_ids
            else 0
        )
        item_revision_ids = tuple(value.item_revision_id for value in items.items)
        active_analyses = session.scalar(
            select(func.count())
            .select_from(KnowledgeAnalysisRunRecord)
            .where(
                KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
                KnowledgeAnalysisRunRecord.source_revision_id.in_(item_revision_ids),
                KnowledgeAnalysisRunRecord.state.in_(ACTIVE_ANALYSIS_STATES),
            )
        )
        pending_work_units = session.scalar(
            select(func.count())
            .select_from(LegacyItemExtractionBatchWorkUnitRecord)
            .where(
                LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                    (
                        extraction.original_batch.extraction_batch_id,
                        extraction.successor_batch.extraction_batch_id,
                    )
                ),
                LegacyItemExtractionBatchWorkUnitRecord.state.not_in(("ACCEPTED", "FAILED")),
            )
        )
        held_by_slot = {
            slot: count
            for slot, count in session.execute(
                select(WorkerLeaseRecord.worker_slot_id, func.count())
                .where(
                    WorkerLeaseRecord.worker_slot_id.in_(("05", "06")),
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
                .group_by(WorkerLeaseRecord.worker_slot_id)
            )
        }
        return Quiescence.model_validate(
            {
                "automation_mode": runtime.automation_mode,
                "volatile_auto_overlay_present": runtime.volatile_auto_overlay_present,
                "deployment_hold": runtime.deployment_hold,
                "missing_keys": 0,
                "conflict_keys": 0,
                "duplicate_expected_keys": 0,
                "extra_effective_keys": 0,
                "unpromoted_items": 0,
                "active_analysis_leaves": active_analyses or 0,
                "failed_analysis_leaves": 0,
                "duplicate_analysis_leaves": 0,
                "graph_missing_items": 0,
                "graph_duplicate_items": 0,
                "source_pending_work_units": pending_work_units or 0,
                "promotion_pending_items": 0,
                "graph_pending_items": 0,
                "unaccounted_terminal_work_units": 0,
                "active_platform_jobs": active_jobs or 0,
                "active_workflows": active_workflows or 0,
                "active_workflow_commands": active_commands or 0,
                "active_analysis_runs": active_analyses or 0,
                "slot05_held_leases": held_by_slot.get("05", 0),
                "slot06_held_leases": held_by_slot.get("06", 0),
            }
        )

    @staticmethod
    def _mutable_fingerprint(
        runtime: PdfLearningRuntimeObservation,
        pdfs: tuple[ResolvedPinnedLegacyPdfSource, ...],
        *,
        evidence: PdfLearningCompletionEvidence,
        items: tuple[ItemCompletion, ...],
        graph: _ResolvedGraph,
        failed_predecessors: tuple[FailedTerminalWorkUnit, ...],
    ) -> str:
        return content_sha256(
            {
                "runtime": runtime.runtime_fingerprint_sha256,
                "pdfs": [value.__dict__ for value in pdfs],
                "evidence": {
                    "inventory": evidence.inventory.model_dump(mode="json"),
                    "original_batch": evidence.original_batch.model_dump(mode="json"),
                    "successor_batch": evidence.successor_batch.model_dump(mode="json"),
                    "recovery_authorization": evidence.recovery_authorization.model_dump(
                        mode="json"
                    ),
                    "corpus_coverage": evidence.corpus_coverage.model_dump(mode="json"),
                    "pdf_sources": [
                        value.model_dump(mode="json") for value in evidence.pdf_sources
                    ],
                    "effective_work_units": [
                        value.model_dump(mode="json") for value in evidence.effective_work_units
                    ],
                    "graph_snapshot": evidence.graph_snapshot.model_dump(mode="json"),
                    "analysis_recoveries": [
                        value.model_dump(mode="json") for value in evidence.analysis_recoveries
                    ],
                    "quiescence": evidence.quiescence.model_dump(mode="json"),
                },
                "items": [value.model_dump(mode="json") for value in items],
                "failed_extraction_predecessors": [
                    {
                        "extraction_batch_id": value.extraction_batch_id,
                        "work_unit_id": value.work_unit_id,
                        "ordinal": value.ordinal,
                        "state": value.state,
                        "extraction_request_id": value.extraction_request_id,
                        "request_sha256": value.request_sha256,
                        "error_code": value.error_code,
                        "workflow_id": value.workflow_id,
                        "platform_job_id": value.platform_job_id,
                        "workflow_failure_code": value.workflow_failure_code,
                        "job_error_code": value.job_error_code,
                        "failure_message_sha256": value.failure_message_sha256,
                        "result_present": value.result_present,
                        "receipt_present": value.receipt_present,
                        "acceptance_present": value.acceptance_present,
                        "completed_at": value.completed_at.astimezone(UTC).isoformat(),
                    }
                    for value in failed_predecessors
                ],
                "graph_database": graph.database.model_dump(mode="json"),
                "placements": [value.model_dump(mode="json") for value in graph.placements],
                "snapshot_analyses": [value.model_dump(mode="json") for value in graph.analyses],
            }
        )

    @staticmethod
    def _clock(session: Session) -> datetime:
        value = session.scalar(select(func.statement_timestamp()))
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("database observation clock is unavailable")
        return value.astimezone(UTC)

    @staticmethod
    def _generic_command(
        request: PdfLearningCompletionRequest,
    ) -> LegacyItemCorpusCompletionCommand:
        receipt = request.corpus_completion
        collision_version = receipt.historical_result_identity_collisions is not None
        command_document: dict[str, object] = {
            "schema_version": (
                "legacy-item-corpus-completion-command/1.1"
                if collision_version
                else "legacy-item-corpus-completion-command/1.0"
            ),
            "inventory_id": receipt.inventory_id,
            "inventory_sha256": receipt.inventory_sha256,
            "original_batch": {
                "extraction_batch_id": receipt.original_batch.extraction_batch_id,
                "manifest_sha256": receipt.original_batch.manifest_sha256,
            },
            "successor_batch": {
                "extraction_batch_id": receipt.successor_batch.extraction_batch_id,
                "manifest_sha256": receipt.successor_batch.manifest_sha256,
            },
            "recovery_sha256": receipt.recovery_sha256,
            "recovery_artifact": receipt.recovery_artifact.model_dump(mode="json"),
            "requested_by": receipt.requested_by,
            "command_sha256": receipt.command_sha256,
        }
        if receipt.historical_result_identity_collisions is not None:
            command_document["historical_result_identity_collisions"] = (
                receipt.historical_result_identity_collisions.model_dump(mode="json")
            )
        return LegacyItemCorpusCompletionCommand.model_validate(command_document)

    @staticmethod
    def _fail(code: str, message: str, cause: Exception | None = None) -> NoReturn:
        error = PdfLearningCompletionError(code, message)
        if cause is None:
            raise error
        raise error from cause


__all__ = ["PostgresPdfLearningCompletionSource"]
