"""Bounded current-source registered REVIEW resolution, never analysis V10.

Metadata/receipts are read in indexed sets; each immutable member is materialized
once. Source authorization remains an explicit actual-operator owner boundary.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, NoReturn

from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2, AssessmentItemContentV3
from eom_catalog_contracts.assessment_item import ASSESSMENT_ITEM_CONTENT_FILE_NAME
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewRoleReference,
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.evidence_usage_validation import (
    canonical_review_evidence_set_sha256,
    validate_independent_review_draft,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow import ArtifactPointer, RoleWorkerInput
from eom_workflow.control_plane import (
    ReviewEvidenceUsageValidationReceiptV2,
    ReviewEvidenceUsageValidationReceiptV3,
)
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV11,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamRegistrationRoleResultV11,
    ContentTeamRegistrationRoleResultV12,
    ContentTeamReviewRoleResultV11,
    ContentTeamReviewRoleResultV12,
    IndependentReviewReportV1,
    IndependentReviewReportV2,
    RoleResultBase,
)
from eom_workflow.schemas import validate_role_result
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.artifacts import CatalogArtifactService, CatalogJsonRevisionRequest
from eom_catalog_service.evidence_usage_receipts import (
    BatchEvidenceUsageReceiptResolver,
    EvidenceUsagePairRequest,
    EvidenceUsageReceiptPair,
    EvidenceUsageReceiptResolutionError,
    MockExamEvidenceUsageReceiptResolver,
)
from eom_catalog_service.item_content_contract import (
    canonical_content_team_item_materialization,
    read_item_content,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext

MAX_REGISTERED_REVIEW_MEMBER_BYTES = 4 * 1024**2
MAX_REGISTERED_REVIEW_SOURCES = 1024
_COMPONENT_BY_STEP = {
    "authoring": "UPPER_STEM",
    "review": "REVIEW_REPORT",
    "registration": "METADATA",
}
_ROLE_BY_STEP: dict[str, Literal["authoring", "review", "item_management"]] = {
    "authoring": "authoring",
    "review": "review",
    "registration": "item_management",
}


class RegisteredItemReviewSolutionResolutionError(ValueError):
    """An unavailable or inconsistent registered-review source; no latest fallback."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ResolvedRegisteredItemReviewSolution:
    evidence: RegisteredItemReviewSolutionEvidence
    authoring: ContentTeamAuthoringRoleResultV11 | ContentTeamAuthoringRoleResultV12
    review: ContentTeamReviewRoleResultV11 | ContentTeamReviewRoleResultV12

    @property
    def draft(self) -> AssessmentItemContentV3:
        return self.authoring.output.draft

    @property
    def report(self) -> IndependentReviewReportV1 | IndependentReviewReportV2:
        return self.review.output.independent_review_report

    @property
    def review_completed_at(self) -> datetime:
        return self.review.completed_at


@dataclass(frozen=True, slots=True)
class LockedRegisteredItemReviewSources:
    """Retained same-root rows, NOT a source permission or immutable read cache."""

    session: Session
    root: SessionTransaction
    nested: SessionTransaction | None
    thread_id: int
    item_revisions: tuple[ItemRevisionRecord, ...]
    components: tuple[ItemComponentRecord, ...]
    workflows: tuple[WorkflowInstanceRecord, ...]
    steps: tuple[WorkflowStepRunRecord, ...]
    logicals: tuple[ArtifactRecord, ...]
    artifacts: tuple[ArtifactRevisionRecord, ...]
    jobs: tuple[JobRecord, ...]
    receipt_events: tuple[JobEventRecord, ...]

    def assert_current(self, session: Session) -> None:
        if (
            session is not self.session
            or threading.get_ident() != self.thread_id
            or session.get_transaction() is not self.root
            or not self.root.is_active
            or session.get_nested_transaction() is not self.nested
            or (self.nested is not None and not self.nested.is_active)
        ):
            _fail("LOCK_ROOT_CHANGED")


def lock_registered_item_review_sources(
    session: Session,
    *,
    sources: tuple[ApprovedItemKnowledgeSourceV2, ...],
) -> LockedRegisteredItemReviewSources:
    """Hold exact publication proof metadata through the caller's write root.

    Kept separate from the read-only resolver: ordinary retrieval must never
    acquire row locks or turn into a publication permission. No NAS reads here.
    Canonical writers serialize role/receipt changes on the held Workflow/Job;
    the existing resolver still proves every member and trusted receipt after it.
    """
    if (
        not isinstance(sources, tuple)
        or not sources
        or len(sources) > MAX_REGISTERED_REVIEW_SOURCES
        or session.new
        or session.dirty
        or session.deleted
    ):
        _fail("LOCK_SELECTION_INVALID")
    nested = session.get_nested_transaction()
    checked = tuple(
        ApprovedItemKnowledgeSourceV2.model_validate(raw_similarity_contract_value(source))
        for source in sources
    )
    if any(row.source_class != "APPROVED_ITEM" for row in checked) or len(
        {row.item_revision_id for row in checked}
    ) != len(checked):
        _fail("LOCK_SELECTION_INVALID")
    count = len(checked)
    item_revisions = tuple(
        session.scalars(
            select(ItemRevisionRecord)
            .where(
                ItemRevisionRecord.item_revision_id.in_(
                    tuple(row.item_revision_id for row in checked)
                )
            )
            .order_by(ItemRevisionRecord.item_revision_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if {row.item_revision_id for row in item_revisions} != {
        row.item_revision_id for row in checked
    }:
        _fail("LOCK_SOURCE_MISSING")
    components = tuple(
        session.scalars(
            select(ItemComponentRecord)
            .where(
                ItemComponentRecord.item_revision_id.in_(
                    tuple(row.item_revision_id for row in checked)
                )
            )
            .order_by(
                ItemComponentRecord.item_revision_id,
                ItemComponentRecord.component_type,
                ItemComponentRecord.ordinal,
            )
            .limit(100 * count + 1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    workflows = tuple(
        session.scalars(
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.workflow_id.in_(
                    tuple(row.workflow_id for row in item_revisions)
                )
            )
            .order_by(WorkflowInstanceRecord.workflow_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id.in_(tuple(row.workflow_id for row in workflows)),
                WorkflowStepRunRecord.step_key.in_(tuple(_COMPONENT_BY_STEP)),
                WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
            )
            .order_by(WorkflowStepRunRecord.step_run_id)
            .limit(3 * count + 1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if len(components) > 100 * count or len(steps) > 3 * count:
        _fail("LOCK_BUDGET_EXCEEDED")
    pointers = tuple(ArtifactPointer.model_validate(row.output_pointer_manifest) for row in steps)
    logical_ids = {row.artifact_id for row in components}
    revision_ids = {row.artifact_revision_id for row in components}
    logical_ids.update(row.manifest_artifact_id for row in item_revisions)
    revision_ids.update(row.manifest_artifact_revision_id for row in item_revisions)
    logical_ids.update(row.logical_artifact_id for row in pointers)
    revision_ids.update(row.revision_id for row in pointers)
    logicals = tuple(
        session.scalars(
            select(ArtifactRecord)
            .where(ArtifactRecord.logical_artifact_id.in_(logical_ids))
            .order_by(ArtifactRecord.logical_artifact_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    artifacts = tuple(
        session.scalars(
            select(ArtifactRevisionRecord)
            .where(ArtifactRevisionRecord.revision_id.in_(revision_ids))
            .order_by(ArtifactRevisionRecord.revision_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    jobs = tuple(
        session.scalars(
            select(JobRecord)
            .where(
                JobRecord.job_id.in_(
                    {row.job_id for row in artifacts} | {row.job_id for row in pointers}
                )
            )
            .order_by(JobRecord.job_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    receipt_job_ids = tuple(
        row.job_id for row in pointers if row.step_key in {"authoring", "review"}
    )
    events = tuple(
        session.scalars(
            select(JobEventRecord)
            .where(
                JobEventRecord.job_id.in_(receipt_job_ids),
                JobEventRecord.event == "ARTIFACT_COMMITTED",
            )
            .order_by(JobEventRecord.job_id, JobEventRecord.sequence)
            .limit(2 * count + 1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if (
        len(events) > 2 * count
        or {row.logical_artifact_id for row in logicals} != logical_ids
        or {row.revision_id for row in artifacts} != revision_ids
        or {row.job_id for row in jobs}
        != {row.job_id for row in artifacts} | {row.job_id for row in pointers}
    ):
        _fail("LOCK_PROOF_MISSING")
    root = session.get_transaction()
    if root is None or not root.is_active:
        _fail("LOCK_ROOT_CHANGED")
    value = LockedRegisteredItemReviewSources(
        session,
        root,
        nested,
        threading.get_ident(),
        item_revisions,
        components,
        workflows,
        steps,
        logicals,
        artifacts,
        jobs,
        events,
    )
    value.assert_current(session)
    return value


@dataclass(frozen=True)
class _PreparedSource:
    """Current-call records only; neither a cache nor an authorization grant."""

    source: ApprovedItemKnowledgeSourceV2
    item: ItemRecord
    revision: ItemRevisionRecord
    components: tuple[ItemComponentRecord, ...]
    workflow: WorkflowInstanceRecord
    steps: dict[str, WorkflowStepRunRecord]
    family: str
    content: ArtifactMemberPointer
    manifest: ArtifactMemberPointer


@dataclass(frozen=True)
class _RoleRecords:
    logicals: dict[str, ArtifactRecord]
    revisions: dict[str, ArtifactRevisionRecord]
    jobs: dict[str, JobRecord]


def _fail(reason: str) -> NoReturn:
    raise RegisteredItemReviewSolutionResolutionError("REGISTERED_ITEM_REVIEW_" + reason)


def _component_document(component: ItemComponentRecord) -> dict[str, Any]:
    return {
        "component_type": component.component_type,
        "ordinal": component.ordinal,
        "schema_ref": component.schema_ref,
        "media_type": component.media_type,
        "artifact_id": component.artifact_id,
        "artifact_revision_id": component.artifact_revision_id,
        "sha256": component.sha256,
        "logical_name": component.logical_name,
        "required": component.required,
    }


def _one_component(components: tuple[ItemComponentRecord, ...], kind: str) -> ItemComponentRecord:
    found = tuple(row for row in components if row.component_type == kind)
    if len(found) != 1 or found[0].ordinal != 0 or not found[0].required:
        _fail("COMPONENT_INVALID")
    return found[0]


def _member(component: ItemComponentRecord) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=component.artifact_id,
        artifact_revision_id=component.artifact_revision_id,
        member_path=component.logical_name,
        sha256=component.sha256,
        schema_ref=component.schema_ref,
        media_type=component.media_type,
    )


def _read_file_set_member(
    reader: PinnedArtifactReadContext,
    pointer: ArtifactMemberPointer,
    artifact_type: str,
) -> tuple[dict[str, Any], int]:
    member = reader.read_pinned(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        expected_artifact_types={artifact_type},
        expected_primary_file=pointer.member_path,
        max_bytes=MAX_REGISTERED_REVIEW_MEMBER_BYTES,
        historical_metadata_compatibility=artifact_type == "item-revision-manifest",
    )
    document: object = json.loads(member.payload)
    if not isinstance(document, dict) or sha256_bytes(member.payload) != pointer.sha256:
        _fail("MEMBER_INVALID")
    return document, len(member.payload)


def _input_pointers(step: WorkflowStepRunRecord) -> tuple[ArtifactPointer, ...]:
    raw = step.input_pointer_manifest.get("upstream_artifacts")
    if not isinstance(raw, list):
        _fail("STEP_INPUT_INVALID")
    return tuple(ArtifactPointer.model_validate(value) for value in raw)


def _role_provenance(
    records: _RoleRecords,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    component: ItemComponentRecord,
    family: str,
) -> ArtifactPointer:
    pointer = ArtifactPointer.model_validate(step.output_pointer_manifest)
    role = _ROLE_BY_STEP[step.step_key]
    expected_schema = f"{step.step_key}-result@{family}.0"
    logical = records.logicals.get(pointer.logical_artifact_id)
    revision = records.revisions.get(pointer.revision_id)
    job = records.jobs.get(pointer.job_id)
    if logical is None or revision is None or job is None:
        _fail("ROLE_PROVENANCE_INVALID")
    manifest = ArtifactManifest.model_validate(revision.manifest)
    worker_input = RoleWorkerInput.model_validate(job.request)
    if (
        step.step_type != "agent"
        or step.worker_role != role
        or step.state != "SUCCEEDED"
        or step.superseded_by_step_run_id is not None
        or pointer.step_key != step.step_key
        or pointer.attempt != step.attempt
        or pointer.job_id != step.platform_job_id
        or pointer.result_schema != expected_schema
        or step.result_schema != expected_schema
        or component.schema_ref != expected_schema
        or component.media_type != "application/json"
        or component.logical_name != f"{step.step_key}-result"
        or component.artifact_id != pointer.logical_artifact_id
        or component.artifact_revision_id != pointer.revision_id
        or component.sha256 != pointer.content_hash
        or not logical.approved
        or not revision.approved
        or logical.job_id != pointer.job_id
        or logical.artifact_type != f"workflow_{role}"
        or revision.logical_artifact_id != pointer.logical_artifact_id
        or revision.job_id != pointer.job_id
        or revision.content_hash != pointer.content_hash
        or revision.manifest_hash != content_sha256(manifest)
        or revision.content_bytes != manifest.content_bytes
        or manifest.job_id != pointer.job_id
        or manifest.logical_artifact_id != pointer.logical_artifact_id
        or manifest.revision_id != pointer.revision_id
        or manifest.content_hash != pointer.content_hash
        or job.status != "SUCCEEDED"
        or job.completed_at is None
        or job.task_type != f"workflow_{role}"
        or job.logical_artifact_id != pointer.logical_artifact_id
        or job.revision_id != pointer.revision_id
        or job.protocol_version != workflow.role_schema_version
        or job.worker_slot_id != manifest.worker_slot
        or job.request_hash
        != content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
        or worker_input.protocol_version != job.protocol_version
        or worker_input.workflow_id != workflow.workflow_id
        or worker_input.step_run_id != step.step_run_id
        or worker_input.job_id != pointer.job_id
        or worker_input.attempt != pointer.attempt
        or worker_input.role != role
        or worker_input.artifact.logical_artifact_id != pointer.logical_artifact_id
        or worker_input.artifact.revision_id != pointer.revision_id
        or worker_input.upstream_artifacts != _input_pointers(step)
    ):
        _fail("ROLE_PROVENANCE_INVALID")
    return pointer


def _role_result(
    records: _RoleRecords,
    documents: dict[str, dict[str, Any]],
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    pointer: ArtifactPointer,
) -> tuple[ArtifactPointer, RoleResultBase]:
    revision = records.revisions[pointer.revision_id]
    job = records.jobs[pointer.job_id]
    role = _ROLE_BY_STEP[step.step_key]
    expected_schema = pointer.result_schema
    raw = documents[pointer.revision_id]
    if raw != revision.result or content_sha256(raw) != pointer.content_hash:
        _fail("ROLE_RESULT_INVALID")
    result = validate_role_result(raw, role, expected_schema)
    if (
        result.workflow_id != workflow.workflow_id
        or result.step_run_id != step.step_run_id
        or result.job_id != pointer.job_id
        or result.protocol_version != job.protocol_version
        or result.artifact.logical_artifact_id != pointer.logical_artifact_id
        or result.artifact.revision_id != pointer.revision_id
    ):
        _fail("ROLE_RESULT_INVALID")
    return pointer, result


def _role_reference(
    step: WorkflowStepRunRecord, pointer: ArtifactPointer
) -> RegisteredItemReviewRoleReference:
    return RegisteredItemReviewRoleReference.model_validate(
        {
            "step_run_id": step.step_run_id,
            "step_key": step.step_key,
            "attempt": pointer.attempt,
            "job_id": pointer.job_id,
            "artifact": ArtifactMemberPointer(
                artifact_id=pointer.logical_artifact_id,
                artifact_revision_id=pointer.revision_id,
                member_path="result.json",
                sha256=pointer.content_hash,
                schema_ref=pointer.result_schema,
                media_type="application/json",
            ),
        }
    )


def resolve_registered_item_review_solution(
    session: Session,
    *,
    source: ApprovedItemKnowledgeSourceV2,
    artifacts: CatalogArtifactService,
    receipts: MockExamEvidenceUsageReceiptResolver,
    authorize_source: Callable[[ApprovedItemKnowledgeSourceV2], None],
) -> ResolvedRegisteredItemReviewSolution:
    """Preserved scalar API, composed through the same bounded resolution path."""

    def one_receipt(
        requests: tuple[EvidenceUsagePairRequest, ...],
    ) -> tuple[EvidenceUsageReceiptPair, ...]:
        request = requests[0]
        return (
            receipts.resolve_mock_exam_pair(
                workflow_id=request.workflow_id,
                authoring_step_run_id=request.authoring_step_run_id,
                authoring=request.authoring,
                review_step_run_id=request.review_step_run_id,
                review=request.review,
                expected_authoring_receipt_sha256=request.expected_authoring_receipt_sha256,
                expected_review_receipt_sha256=request.expected_review_receipt_sha256,
            ),
        )

    return _resolve_sources(session, (source,), artifacts, one_receipt, authorize_source)[0]


def resolve_registered_item_review_solutions(
    session: Session,
    *,
    sources: tuple[ApprovedItemKnowledgeSourceV2, ...],
    artifacts: CatalogArtifactService,
    receipts: BatchEvidenceUsageReceiptResolver,
    authorize_source: Callable[[ApprovedItemKnowledgeSourceV2], None],
) -> tuple[ResolvedRegisteredItemReviewSolution, ...]:
    """All-or-error batch, retaining exact caller order and current authorization."""
    return _resolve_sources(
        session,
        sources,
        artifacts,
        lambda requests: receipts.resolve_pairs_in_session(session, requests),
        authorize_source,
    )


def _resolve_sources(
    session: Session,
    sources: tuple[ApprovedItemKnowledgeSourceV2, ...],
    artifacts: CatalogArtifactService,
    receipt_batch: Callable[
        [tuple[EvidenceUsagePairRequest, ...]], tuple[EvidenceUsageReceiptPair, ...]
    ],
    authorize_source: Callable[[ApprovedItemKnowledgeSourceV2], None],
) -> tuple[ResolvedRegisteredItemReviewSolution, ...]:
    if not isinstance(sources, tuple) or len(sources) > MAX_REGISTERED_REVIEW_SOURCES:
        _fail("BATCH_INVALID")
    checked = tuple(
        ApprovedItemKnowledgeSourceV2.model_validate(raw_similarity_contract_value(source))
        for source in sources
    )
    if any(source.source_class != "APPROVED_ITEM" for source in checked):
        _fail("SOURCE_INVALID")
    if len({source.item_revision_id for source in checked}) != len(checked):
        _fail("BATCH_DUPLICATE_SOURCE")
    if not checked:
        return ()
    for source in checked:
        authorize_source(source)
    if session.new or session.dirty or session.deleted:
        _fail("PENDING_MUTATION")
    try:
        prepared = _read_sources(session, checked)
        pointers = tuple(
            ArtifactPointer.model_validate(row.steps[key].output_pointer_manifest)
            for row in prepared
            for key in _COMPONENT_BY_STEP
        )
        records = _RoleRecords(
            {
                row.logical_artifact_id: row
                for row in session.scalars(
                    select(ArtifactRecord)
                    .where(
                        ArtifactRecord.logical_artifact_id.in_(
                            tuple(pointer.logical_artifact_id for pointer in pointers)
                        )
                    )
                    .execution_options(populate_existing=True)
                )
            },
            {
                row.revision_id: row
                for row in session.scalars(
                    select(ArtifactRevisionRecord)
                    .where(
                        ArtifactRevisionRecord.revision_id.in_(
                            tuple(pointer.revision_id for pointer in pointers)
                        )
                    )
                    .execution_options(populate_existing=True)
                )
            },
            {
                row.job_id: row
                for row in session.scalars(
                    select(JobRecord)
                    .where(JobRecord.job_id.in_(tuple(pointer.job_id for pointer in pointers)))
                    .execution_options(populate_existing=True)
                )
            },
        )
        provenances = {
            row.steps[key].step_run_id: _role_provenance(
                records,
                row.workflow,
                row.steps[key],
                _one_component(row.components, kind),
                row.family,
            )
            for row in prepared
            for key, kind in _COMPONENT_BY_STEP.items()
        }
        reader = PinnedArtifactReadContext(session, artifacts.settings)
        reader.prefetch(
            tuple(
                (pointer.artifact_id, pointer.artifact_revision_id)
                for row in prepared
                for pointer in (row.manifest, row.content)
            )
        )
        documents = artifacts.load_json_revisions(
            tuple(
                CatalogJsonRevisionRequest(
                    pointer.logical_artifact_id,
                    pointer.revision_id,
                    pointer.content_hash,
                    MAX_REGISTERED_REVIEW_MEMBER_BYTES,
                )
                for pointer in pointers
            )
        )
        requests = tuple(_receipt_request(row) for row in prepared)
        pairs = receipt_batch(requests)
        if len(pairs) != len(prepared):
            _fail("RECEIPT_INVALID")
        result = tuple(
            _resolve_one(row, records, documents, pair, reader, provenances)
            for row, pair in zip(prepared, pairs, strict=True)
        )
    except RegisteredItemReviewSolutionResolutionError:
        raise
    except EvidenceUsageReceiptResolutionError as exc:
        raise RegisteredItemReviewSolutionResolutionError(
            "REGISTERED_ITEM_REVIEW_RECEIPT_INVALID"
        ) from exc
    except (OSError, ValueError, TypeError, KeyError, JsonSchemaValidationError) as exc:
        raise RegisteredItemReviewSolutionResolutionError(
            "REGISTERED_ITEM_REVIEW_CLOSURE_INVALID"
        ) from exc
    for source in checked:
        authorize_source(source)
    return result


def _read_sources(
    session: Session, sources: tuple[ApprovedItemKnowledgeSourceV2, ...]
) -> tuple[_PreparedSource, ...]:
    count = len(sources)
    items = {
        row.item_id: row
        for row in session.scalars(
            select(ItemRecord)
            .where(ItemRecord.item_id.in_(tuple(source.item_id for source in sources)))
            .execution_options(populate_existing=True)
        )
    }
    revisions = {
        row.item_revision_id: row
        for row in session.scalars(
            select(ItemRevisionRecord)
            .where(
                ItemRevisionRecord.item_revision_id.in_(
                    tuple(source.item_revision_id for source in sources)
                )
            )
            .execution_options(populate_existing=True)
        )
    }
    components: dict[str, list[ItemComponentRecord]] = defaultdict(list)
    rows = tuple(
        session.scalars(
            select(ItemComponentRecord)
            .where(
                ItemComponentRecord.item_revision_id.in_(
                    tuple(source.item_revision_id for source in sources)
                )
            )
            .order_by(
                ItemComponentRecord.item_revision_id,
                ItemComponentRecord.component_type,
                ItemComponentRecord.ordinal,
            )
            .limit(100 * count + 1)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows) > 100 * count:
        _fail("COMPONENT_INVALID")
    for component in rows:
        components[component.item_revision_id].append(component)
    workflows = {
        row.workflow_id: row
        for row in session.scalars(
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.workflow_id.in_(
                    tuple(row.workflow_id for row in revisions.values())
                )
            )
            .execution_options(populate_existing=True)
        )
    }
    steps: dict[str, list[WorkflowStepRunRecord]] = defaultdict(list)
    rows_steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id.in_(tuple(workflows)),
                WorkflowStepRunRecord.step_key.in_(tuple(_COMPONENT_BY_STEP)),
                WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
            )
            .limit(3 * count + 1)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows_steps) > 3 * count:
        _fail("FINAL_STEP_INVALID")
    for step in rows_steps:
        steps[step.workflow_id].append(step)
    return tuple(
        _prepare_source(
            source,
            items.get(source.item_id),
            revisions.get(source.item_revision_id),
            tuple(components.get(source.item_revision_id, ())),
            workflows,
            steps,
        )
        for source in sources
    )


def _prepare_source(
    source: ApprovedItemKnowledgeSourceV2,
    item: ItemRecord | None,
    revision: ItemRevisionRecord | None,
    components: tuple[ItemComponentRecord, ...],
    workflows: dict[str, WorkflowInstanceRecord],
    steps: dict[str, list[WorkflowStepRunRecord]],
) -> _PreparedSource:
    if (
        item is None
        or revision is None
        or item.lifecycle_state != "ACTIVE"
        or item.current_revision_id != source.item_revision_id
        or revision.item_id != source.item_id
        or revision.revision_state != "APPROVED"
        or revision.approved_at is None
        or revision.approved_by is None
        or revision.metadata_sha256 != content_sha256(revision.metadata_json)
    ):
        _fail("SOURCE_INELIGIBLE")
    if len(components) > 100:
        _fail("COMPONENT_INVALID")
    component = _one_component(components, "ITEM_CONTENT")
    content = _member(component)
    expected = source.artifact_member
    if component.logical_name != ASSESSMENT_ITEM_CONTENT_FILE_NAME:
        _fail("COMPONENT_INVALID")
    if content != ArtifactMemberPointer(
        **expected.model_dump(
            include={
                "artifact_id",
                "artifact_revision_id",
                "member_path",
                "sha256",
                "schema_ref",
                "media_type",
            }
        )
    ):
        _fail("SOURCE_POINTER_MISMATCH")
    manifest = ArtifactMemberPointer(
        artifact_id=revision.manifest_artifact_id,
        artifact_revision_id=revision.manifest_artifact_revision_id,
        member_path="item-revision-manifest.json",
        sha256=revision.manifest_sha256,
        schema_ref=(
            "eom://schemas/item-registry/item-revision-manifest-v2"
            if revision.workflow_definition_version == "1.16.0"
            else "eom://schemas/item-registry/item-revision-manifest-v1"
        ),
        media_type="application/json",
    )
    workflow = workflows.get(revision.workflow_id)
    if (
        workflow is None
        or workflow.definition_key != "generic-item-development"
        or workflow.definition_version != revision.workflow_definition_version
        or workflow.state != "COMPLETED"
    ):
        _fail("REGISTRATION_INVALID")
    selected_steps = tuple(steps.get(workflow.workflow_id, ()))
    by_step = {step.step_key: step for step in selected_steps}
    if len(selected_steps) != 3 or set(by_step) != set(_COMPONENT_BY_STEP):
        _fail("FINAL_STEP_INVALID")
    if by_step["registration"].step_run_id != revision.source_workflow_step_run_id:
        _fail("REGISTRATION_INVALID")
    family = {"workflow-role/1.23.0": "11", "workflow-role/1.24.0": "12"}.get(
        workflow.role_schema_version
    )
    if family is None:
        _fail("UNAVAILABLE")
    return _PreparedSource(
        source, item, revision, components, workflow, by_step, family, content, manifest
    )


def _receipt_request(row: _PreparedSource) -> EvidenceUsagePairRequest:
    expected = tuple(
        _one_component(row.components, kind).metadata_json.get(
            "evidence_usage_validation_receipt_sha256"
        )
        for kind in ("UPPER_STEM", "REVIEW_REPORT")
    )
    if any(not isinstance(value, str) for value in expected):
        _fail("RECEIPT_INVALID")
    return EvidenceUsagePairRequest(
        row.workflow.workflow_id,
        row.steps["authoring"].step_run_id,
        ArtifactPointer.model_validate(row.steps["authoring"].output_pointer_manifest),
        row.steps["review"].step_run_id,
        ArtifactPointer.model_validate(row.steps["review"].output_pointer_manifest),
        expected_authoring_receipt_sha256=expected[0],
        expected_review_receipt_sha256=expected[1],
    )


def _resolve_one(
    prepared: _PreparedSource,
    records: _RoleRecords,
    documents: dict[str, dict[str, Any]],
    pair: EvidenceUsageReceiptPair,
    reader: PinnedArtifactReadContext,
    provenances: dict[str, ArtifactPointer],
) -> ResolvedRegisteredItemReviewSolution:
    source, item, revision = prepared.source, prepared.item, prepared.revision
    components, workflow, by_step = prepared.components, prepared.workflow, prepared.steps
    content_pointer, manifest_pointer = prepared.content, prepared.manifest
    content_component = _one_component(components, "ITEM_CONTENT")
    manifest, _manifest_bytes = _read_file_set_member(
        reader, manifest_pointer, "item-revision-manifest"
    )
    validate_contract(
        "item-revision-manifest-v2"
        if manifest_pointer.schema_ref.endswith("-v2")
        else "item-revision-manifest",
        manifest,
    )
    if (
        workflow is None
        or workflow.definition_key != "generic-item-development"
        or workflow.definition_version != revision.workflow_definition_version
        or workflow.state != "COMPLETED"
        or manifest["item_id"] != item.item_id
        or manifest["item_revision_id"] != revision.item_revision_id
        or manifest["revision_number"] != revision.revision_number
        or manifest["workflow"]
        != {
            "workflow_id": workflow.workflow_id,
            "definition_key": workflow.definition_key,
            "definition_version": workflow.definition_version,
        }
        or manifest["content_pack"]["release_id"] != revision.content_pack_release_id
        or manifest["metadata"]["sha256"] != revision.metadata_sha256
        or manifest["components"] != [_component_document(row) for row in components]
    ):
        _fail("REGISTRATION_INVALID")
    resolved = {
        key: _role_result(
            records, documents, workflow, by_step[key], provenances[by_step[key].step_run_id]
        )
        for key in _COMPONENT_BY_STEP
    }
    authoring_pointer, authoring = resolved["authoring"]
    review_pointer, review = resolved["review"]
    registration = resolved["registration"][1]
    if (
        not isinstance(
            authoring, ContentTeamAuthoringRoleResultV11 | ContentTeamAuthoringRoleResultV12
        )
        or not isinstance(review, ContentTeamReviewRoleResultV11 | ContentTeamReviewRoleResultV12)
        or not isinstance(
            registration,
            ContentTeamRegistrationRoleResultV11 | ContentTeamRegistrationRoleResultV12,
        )
        or review.output.review.decision != "ready_for_human"
        or any(row.severity == "blocking" for row in review.output.review.findings)
        or authoring_pointer not in _input_pointers(by_step["review"])
        or authoring_pointer not in _input_pointers(by_step["registration"])
        or review_pointer not in _input_pointers(by_step["registration"])
        or content_component.metadata_json.get("authoring_artifact_revision_id")
        != authoring_pointer.revision_id
        or authoring.output.metadata.knowledge_source_mode != "graph_grounded"
    ):
        _fail("REVIEW_INVALID")
    authoring_receipt_sha = _one_component(components, "UPPER_STEM").metadata_json.get(
        "evidence_usage_validation_receipt_sha256"
    )
    review_receipt_sha = _one_component(components, "REVIEW_REPORT").metadata_json.get(
        "evidence_usage_validation_receipt_sha256"
    )
    if not isinstance(authoring_receipt_sha, str) or not isinstance(review_receipt_sha, str):
        _fail("RECEIPT_INVALID")
    report = review.output.independent_review_report
    if (
        not isinstance(
            pair.review,
            ReviewEvidenceUsageValidationReceiptV2 | ReviewEvidenceUsageValidationReceiptV3,
        )
        or pair.review.independent_review_report_sha256
        != content_sha256(report.model_dump(mode="json"))
        or pair.review.review_evidence_set_sha256 != canonical_review_evidence_set_sha256(review)
        or pair.authoring.receipt_sha256 != authoring_receipt_sha
        or pair.review.receipt_sha256 != review_receipt_sha
    ):
        _fail("RECEIPT_INVALID")
    validate_independent_review_draft(review, authoring.output.draft.model_dump(mode="json"))
    content_document, content_bytes = _read_file_set_member(
        reader, content_pointer, "assessment-item-content"
    )
    content = read_item_content(content_pointer.schema_ref, content_document)
    if (
        not isinstance(content, AssessmentItemContentV3)
        or content_bytes != source.artifact_member.bytes
        or content != canonical_content_team_item_materialization(authoring.output.draft)
    ):
        _fail("MATERIALIZATION_INVALID")
    body = {
        "schema_version": "registered-item-review-solution-evidence/1.0",
        "evidence_kind": "REGISTERED_ITEM_REVIEW_SOLUTION",
        "source": source.model_dump(mode="json"),
        "workflow_id": workflow.workflow_id,
        "registration_step_run_id": by_step["registration"].step_run_id,
        "registration_manifest": manifest_pointer.model_dump(mode="json"),
        "item_content": content_pointer.model_dump(mode="json"),
        "authoring": _role_reference(by_step["authoring"], authoring_pointer).model_dump(
            mode="json"
        ),
        "review": _role_reference(by_step["review"], review_pointer).model_dump(mode="json"),
        "authoring_receipt_sha256": pair.authoring.receipt_sha256,
        "review_receipt_sha256": pair.review.receipt_sha256,
    }
    evidence = RegisteredItemReviewSolutionEvidence.model_validate(
        {**body, "evidence_sha256": content_sha256(body)}
    )
    return ResolvedRegisteredItemReviewSolution(evidence, authoring, review)
