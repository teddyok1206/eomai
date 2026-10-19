"""Resolve one registered Item's bounded independent review, never analysis V10.

This is deliberately a single-source vertical slice. It is not a bulk INDEX
adapter: callers must not loop over a population until a bounded metadata and
receipt batch port exists. Authorization remains with the existing Catalog owner
and is required explicitly before dereferencing and before returning evidence.
"""

from __future__ import annotations

import json
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
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
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
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.evidence_usage_receipts import (
    EvidenceUsageReceiptResolutionError,
    MockExamEvidenceUsageReceiptResolver,
)
from eom_catalog_service.item_content_contract import (
    canonical_content_team_item_materialization,
    read_item_content,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import resolve_pinned_artifact_member

MAX_REGISTERED_REVIEW_MEMBER_BYTES = 4 * 1024**2
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
    session: Session,
    artifacts: CatalogArtifactService,
    pointer: ArtifactMemberPointer,
    artifact_type: str,
) -> tuple[dict[str, Any], int]:
    member = resolve_pinned_artifact_member(
        session,
        artifacts.settings,
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


def _role_result(
    session: Session,
    artifacts: CatalogArtifactService,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    component: ItemComponentRecord,
    family: str,
) -> tuple[ArtifactPointer, RoleResultBase]:
    pointer = ArtifactPointer.model_validate(step.output_pointer_manifest)
    role = _ROLE_BY_STEP[step.step_key]
    expected_schema = f"{step.step_key}-result@{family}.0"
    logical = session.get(ArtifactRecord, pointer.logical_artifact_id, populate_existing=True)
    revision = session.get(ArtifactRevisionRecord, pointer.revision_id, populate_existing=True)
    job = session.get(JobRecord, pointer.job_id, populate_existing=True)
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
    raw = artifacts.load_json_revision(
        artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        content_hash=pointer.content_hash,
        max_bytes=MAX_REGISTERED_REVIEW_MEMBER_BYTES,
    )
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
    """Resolve ONE source inside its actual-operator-authorized Catalog read.

    The mandatory callback must use the owner's current actor/policy boundary;
    neither the source DTO nor approved database state supplies permission. No
    caller is wired to this API yet, especially not population/INDEX processing.
    """
    source = ApprovedItemKnowledgeSourceV2.model_validate(raw_similarity_contract_value(source))
    if source.source_class != "APPROVED_ITEM":
        _fail("SOURCE_INVALID")
    authorize_source(source)
    if session.new or session.dirty or session.deleted:
        _fail("PENDING_MUTATION")
    try:
        result = _resolve_one(session, source, artifacts, receipts)
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
    authorize_source(source)
    return result


def _resolve_one(
    session: Session,
    source: ApprovedItemKnowledgeSourceV2,
    artifacts: CatalogArtifactService,
    receipts: MockExamEvidenceUsageReceiptResolver,
) -> ResolvedRegisteredItemReviewSolution:
    item = session.get(ItemRecord, source.item_id, populate_existing=True)
    revision = session.get(ItemRevisionRecord, source.item_revision_id, populate_existing=True)
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
    components = tuple(
        session.scalars(
            select(ItemComponentRecord)
            .where(ItemComponentRecord.item_revision_id == source.item_revision_id)
            .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
            .limit(101)
            .execution_options(populate_existing=True)
        )
    )
    if len(components) > 100:
        _fail("COMPONENT_INVALID")
    content_component = _one_component(components, "ITEM_CONTENT")
    if content_component.logical_name != ASSESSMENT_ITEM_CONTENT_FILE_NAME:
        _fail("COMPONENT_INVALID")
    content_pointer = _member(content_component)
    expected_content = source.artifact_member
    if content_pointer != ArtifactMemberPointer(
        **expected_content.model_dump(
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
    manifest_pointer = ArtifactMemberPointer(
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
    manifest, _manifest_bytes = _read_file_set_member(
        session, artifacts, manifest_pointer, "item-revision-manifest"
    )
    validate_contract(
        "item-revision-manifest-v2"
        if manifest_pointer.schema_ref.endswith("-v2")
        else "item-revision-manifest",
        manifest,
    )
    workflow = session.get(WorkflowInstanceRecord, revision.workflow_id, populate_existing=True)
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
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                WorkflowStepRunRecord.step_key.in_(tuple(_COMPONENT_BY_STEP)),
                WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    )
    by_step = {step.step_key: step for step in steps}
    if len(steps) != 3 or set(by_step) != set(_COMPONENT_BY_STEP):
        _fail("FINAL_STEP_INVALID")
    if by_step["registration"].step_run_id != revision.source_workflow_step_run_id:
        _fail("REGISTRATION_INVALID")
    family = {"workflow-role/1.23.0": "11", "workflow-role/1.24.0": "12"}.get(
        workflow.role_schema_version
    )
    if family is None:
        _fail("UNAVAILABLE")
    resolved = {
        key: _role_result(
            session, artifacts, workflow, by_step[key], _one_component(components, kind), family
        )
        for key, kind in _COMPONENT_BY_STEP.items()
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
    pair = receipts.resolve_mock_exam_pair(
        workflow_id=workflow.workflow_id,
        authoring_step_run_id=by_step["authoring"].step_run_id,
        authoring=authoring_pointer,
        review_step_run_id=by_step["review"].step_run_id,
        review=review_pointer,
        expected_authoring_receipt_sha256=authoring_receipt_sha,
        expected_review_receipt_sha256=review_receipt_sha,
    )
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
        session, artifacts, content_pointer, "assessment-item-content"
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
