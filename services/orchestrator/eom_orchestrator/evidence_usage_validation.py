"""Trusted, plan-aware validation of Graph-grounded authoring evidence usage."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    EvidenceBundleManifestV2,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundleManifestV5,
    candidate_visible_image_instruction_paths,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    AuthoringEvidenceUsageValidationReceipt,
    AuthoringEvidenceUsageValidationReceiptV2,
    ControlSchemaError,
    EvidenceResultArtifactPointer,
    EvidenceResultArtifactPointerV2,
    ResolvedExecutionPlanV3,
    ResolvedExecutionPlanV11,
    ReviewEvidenceUsageValidationReceipt,
    ReviewEvidenceUsageValidationReceiptV2,
    validate_control_contract,
)
from eom_workflow.models import (
    ArtifactPointer,
    ContentTeamAuthoringRoleResultV10,
    ContentTeamAuthoringRoleResultV11,
    ContentTeamReviewRoleResultV10,
    ContentTeamReviewRoleResultV11,
    EvidenceUsageCitationV1,
    RoleResult,
    RoleWorkerInput,
)
from eom_workflow.schemas import WorkflowSchemaError, validate_role_result
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    ResolvedEvidenceMaterials,
    authorized_execution_artifact_revisions,
    plan_stages_evidence_manifest,
    resolve_evidence_materials,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord

_ZERO_SHA256 = "sha256:" + "0" * 64
_APPLICATION_BY_USE = {
    "GROUNDING": "CONCEPT_GROUNDING",
    "REFERENCE_PATTERN": "STRUCTURE_PATTERN",
    "AVOID_COPY": "AVOID_COPY_CHECK",
}
_SEMANTIC_DRAFT_ROOTS = frozenset(
    {
        "answer",
        "bottom_stem",
        "choices",
        "explanations",
        "inquiry",
        "labeled_blocks",
        "statements",
        "stem",
        "visuals",
    }
)
_CONTEXT_EVIDENCE_LINE = re.compile(
    r"^- `(evidenceitem_[0-9a-f]{32})` score=([0-9]{1,4}) "
    r"use=(GROUNDING|REFERENCE_PATTERN|AVOID_COPY)(?:\s|$)"
)
_ARRAY_INDEX = re.compile(r"^(?:0|[1-9][0-9]*)$")


EvidenceManifest = (
    EvidenceBundleManifestV2
    | EvidenceBundleManifestV3
    | EvidenceBundleManifestV4
    | EvidenceBundleManifestV5
)
EvidenceReceipt = (
    AuthoringEvidenceUsageValidationReceipt
    | ReviewEvidenceUsageValidationReceipt
    | AuthoringEvidenceUsageValidationReceiptV2
    | ReviewEvidenceUsageValidationReceiptV2
)
ResultArtifactPointer = EvidenceResultArtifactPointer | EvidenceResultArtifactPointerV2


class EvidenceUsageValidationError(ValueError):
    """Stable fail-closed result error raised before Artifact commit."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def evidence_receipt_required_for_result(result: RoleResult) -> bool:
    """Return whether a submitted evidence-aware result makes a non-null claim."""

    if isinstance(result, ContentTeamAuthoringRoleResultV10):
        return result.output.evidence_usage is not None
    if isinstance(result, ContentTeamReviewRoleResultV10 | ContentTeamReviewRoleResultV11):
        return result.output.evidence_usage_attestation is not None
    return False


def evidence_receipt_event_data(
    result: RoleResult,
    receipt: EvidenceReceipt | None,
    *,
    logical_artifact_id: str,
    revision_id: str,
    content_hash: str,
) -> dict[str, object]:
    """Validate the receipt/pending Artifact binding before any canonical storage write."""

    required = evidence_receipt_required_for_result(result)
    if required != (receipt is not None):
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_MISSING",
            "evidence-bearing result requires exactly one validation receipt",
        )
    if receipt is None:
        return {}
    expected_step = "authoring" if result.role == "authoring" else "review"
    if (
        receipt.step_key != expected_step
        or receipt.result_artifact.logical_artifact_id != logical_artifact_id
        or receipt.result_artifact.revision_id != revision_id
        or receipt.result_artifact.content_hash != content_hash
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_RESULT_MISMATCH",
            "validation receipt differs from the pending result Artifact",
        )
    return {"evidence_usage_validation_receipt": receipt.model_dump(mode="json")}


def canonical_citation_set_sha256(citations: Sequence[EvidenceUsageCitationV1]) -> str:
    """Hash an already canonical typed citation tuple with explicit domain separation."""

    return content_sha256(
        {
            "schema_version": "evidence-usage-citation-set/1.0",
            "citations": [citation.model_dump(mode="json") for citation in citations],
        }
    )


def validate_evidence_usage_for_commit(
    session: Session,
    *,
    plan_id: str | None,
    step_key: str,
    worker_input: RoleWorkerInput,
    result: RoleResult,
    result_artifact: ResultArtifactPointer,
    canonical_artifact_root: Path,
) -> EvidenceReceipt | None:
    """Reload trusted pins and produce the receipt required for one @10 result commit."""

    if not isinstance(
        result,
        ContentTeamAuthoringRoleResultV10
        | ContentTeamReviewRoleResultV10
        | ContentTeamReviewRoleResultV11,
    ):
        return None
    successor = isinstance(
        result, ContentTeamAuthoringRoleResultV11 | ContentTeamReviewRoleResultV11
    )
    expected_protocol = "workflow-role/1.23.0" if successor else "workflow-role/1.20.0"
    if isinstance(result, ContentTeamAuthoringRoleResultV11):
        expected_result_schema = "authoring-result@11.0"
    elif isinstance(result, ContentTeamAuthoringRoleResultV10):
        expected_result_schema = "authoring-result@10.0"
    elif isinstance(result, ContentTeamReviewRoleResultV11):
        expected_result_schema = "review-result@11.0"
    else:
        expected_result_schema = "review-result@10.0"
    if (
        worker_input.protocol_version != expected_protocol
        or worker_input.role != result.role
        or worker_input.job_id != result.job_id
        or worker_input.workflow_id != result.workflow_id
        or worker_input.step_run_id != result.step_run_id
        or worker_input.artifact != result.artifact
        or result_artifact.logical_artifact_id != result.artifact.logical_artifact_id
        or result_artifact.revision_id != result.artifact.revision_id
        or result_artifact.result_schema != expected_result_schema
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_RESULT_IDENTITY_MISMATCH",
            "evidence-aware result differs from its exact worker input or pending Artifact",
        )
    if successor and not isinstance(result_artifact, EvidenceResultArtifactPointerV2):
        raise EvidenceUsageValidationError(
            "EVIDENCE_RESULT_IDENTITY_MISMATCH", "@11 result pointer family differs"
        )
    if plan_id is None:
        _require_no_evidence_claim(result)
        if isinstance(result, ContentTeamReviewRoleResultV11):
            _validate_ungrounded_review_result_v11(
                session,
                worker_input=worker_input,
                result=result,
                canonical_artifact_root=canonical_artifact_root,
            )
        return None
    plan_record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if plan_record is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_MISSING", "evidence validation plan is missing"
        )
    plan_document = plan_record.canonical_document
    if not isinstance(plan_document, dict):
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_INVALID", "evidence validation plan is invalid"
        )
    expected_plan_schema = (
        "resolved-execution-plan/11.0" if successor else "resolved-execution-plan/3.0"
    )
    if plan_document.get("schema_version") != expected_plan_schema:
        _require_no_evidence_claim(result)
        if isinstance(result, ContentTeamReviewRoleResultV11):
            _validate_ungrounded_review_result_v11(
                session,
                worker_input=worker_input,
                result=result,
                canonical_artifact_root=canonical_artifact_root,
            )
        return None
    try:
        plan = (
            ResolvedExecutionPlanV11.model_validate(plan_document)
            if successor
            else ResolvedExecutionPlanV3.model_validate(plan_document)
        )
    except ValidationError as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_INVALID", "evidence validation plan is invalid"
        ) from exc
    if (
        plan.plan_id != plan_id
        or plan.plan_sha256 != plan_record.plan_sha256
        or plan.workflow_id != result.workflow_id
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_STALE", "evidence validation plan identity differs"
        )
    if not plan_stages_evidence_manifest(plan):
        raise EvidenceUsageValidationError(
            "EVIDENCE_PROTOCOL_PLAN_MISMATCH",
            (
                "@11 evidence usage requires the immutable 1.11 workflow family"
                if successor
                else "@10 evidence usage requires the immutable 1.10 workflow family"
            ),
        )
    steps = tuple(item for item in plan.steps if item.step_key == step_key)
    if len(steps) != 1 or steps[0].role != result.role:
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_STEP_MISSING", "evidence validation plan step differs"
        )
    if steps[0].evidence_access != "EVIDENCE_CONTEXT":
        if successor:
            raise EvidenceUsageValidationError(
                "EVIDENCE_PROTOCOL_PLAN_MISMATCH",
                "@11 Graph plan review and authoring steps require pinned evidence context",
            )
        _require_no_evidence_claim(result)
        return None

    try:
        authorized = authorized_execution_artifact_revisions(
            session, plan_id=plan_id, step_key=step_key
        )
        materials = resolve_evidence_materials(
            session,
            plan=plan,
            canonical_artifact_root=canonical_artifact_root,
            authorized_artifact_revision_ids=authorized,
        )
    except (ControlPlaneError, ValidationError) as exc:
        # Pointer resolution errors are result-validation failures at this post-worker boundary.
        raise EvidenceUsageValidationError(
            "EVIDENCE_MATERIAL_RESOLUTION_FAILED",
            "pinned evidence material cannot be re-resolved",
        ) from exc

    if isinstance(result, ContentTeamAuthoringRoleResultV11):
        if not isinstance(result_artifact, EvidenceResultArtifactPointerV2):
            raise EvidenceUsageValidationError(
                "EVIDENCE_RESULT_IDENTITY_MISMATCH", "@11 result pointer family differs"
            )
        citation_hash = _validate_authoring_result(plan, materials, result)
        return _authoring_receipt_v2(plan, result_artifact, citation_hash)
    if isinstance(result, ContentTeamAuthoringRoleResultV10):
        if not isinstance(result_artifact, EvidenceResultArtifactPointer):
            raise EvidenceUsageValidationError(
                "EVIDENCE_RESULT_IDENTITY_MISMATCH", "@10 result pointer family differs"
            )
        citation_hash = _validate_authoring_result(plan, materials, result)
        return _authoring_receipt(plan, result_artifact, citation_hash)

    if isinstance(result, ContentTeamReviewRoleResultV11):
        return _validate_review_result_v11(
            session,
            plan=plan,
            materials=materials,
            worker_input=worker_input,
            result=result,
            result_artifact=result_artifact,
            canonical_artifact_root=canonical_artifact_root,
        )

    if not isinstance(result_artifact, EvidenceResultArtifactPointer):
        raise EvidenceUsageValidationError(
            "EVIDENCE_RESULT_IDENTITY_MISMATCH", "@10 result pointer family differs"
        )
    return _validate_review_result(
        session,
        plan=plan,
        materials=materials,
        worker_input=worker_input,
        result=result,
        result_artifact=result_artifact,
        canonical_artifact_root=canonical_artifact_root,
    )


def _require_no_evidence_claim(
    result: (
        ContentTeamAuthoringRoleResultV10
        | ContentTeamReviewRoleResultV10
        | ContentTeamReviewRoleResultV11
    ),
) -> None:
    claim = (
        result.output.evidence_usage
        if isinstance(result, ContentTeamAuthoringRoleResultV10)
        else result.output.evidence_usage_attestation
    )
    if claim is not None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_UNPINNED_CLAIM", "result claims evidence without a pinned evidence step"
        )


def _validate_authoring_result(
    plan: ResolvedExecutionPlanV3,
    materials: ResolvedEvidenceMaterials,
    result: ContentTeamAuthoringRoleResultV10,
) -> str:
    usage = result.output.evidence_usage
    if result.output.metadata.knowledge_source_mode != "graph_grounded" or usage is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_USAGE_MISSING", "Graph-grounded authoring evidence usage is missing"
        )
    if (
        usage.evidence_bundle_id != plan.evidence_bundle_id
        or usage.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
        or usage.retrieval_request_id != plan.retrieval_request_id
        or usage.graph_snapshot_revision_id != plan.graph_snapshot.graph_snapshot_revision_id
        or usage.evidence_manifest_sha256 != plan.evidence_manifest_sha256
        or usage.evidence_context_sha256 != plan.evidence_context_artifact.sha256
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_USAGE_PIN_MISMATCH", "authoring evidence usage differs from exact plan pins"
        )
    _validate_citations(
        materials.manifest,
        materials.context_payload,
        usage.citations,
        result.output.draft.model_dump(mode="json"),
    )
    _validate_required_image_presentation(
        plan,
        materials.manifest,
        usage.citations,
        result.output.draft.model_dump(mode="json"),
    )
    _validate_required_table_presentation(
        plan,
        materials.manifest,
        usage.citations,
        result.output.draft.model_dump(mode="json"),
    )
    return canonical_citation_set_sha256(usage.citations)


def _validate_required_image_presentation(
    plan: ResolvedExecutionPlanV3,
    manifest: EvidenceManifest,
    citations: Sequence[EvidenceUsageCitationV1],
    draft: Mapping[str, Any],
) -> None:
    """Bind an image-filtered RAG request to an authored and cited image presentation.

    The immutable retrieval requirement is authoritative.  Maps and sets keep the validation
    linear in the bounded manifest, citation, and visual collections.
    """

    if "image" not in plan.retrieval_requirement.required_item_elements:
        return
    instruction_paths = candidate_visible_image_instruction_paths(draft)
    if instruction_paths:
        raise EvidenceUsageValidationError(
            "EVIDENCE_CANDIDATE_VISIBLE_IMAGE_INSTRUCTION",
            "candidate-visible Item text contains an internal image-production instruction at "
            + ", ".join(instruction_paths),
        )
    visuals = draft.get("visuals")
    if not isinstance(visuals, list | tuple):
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_IMAGE_MISSING",
            "image-filtered evidence requires typed authoring visuals",
        )
    image_ordinals = tuple(
        index
        for index, visual in enumerate(visuals)
        if isinstance(visual, Mapping) and visual.get("kind") == "IMAGE"
    )
    if not image_ordinals:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_IMAGE_MISSING",
            "image-filtered evidence requires at least one authored IMAGE slot",
        )
    labeled_blocks = draft.get("labeled_blocks")
    if not isinstance(labeled_blocks, list | tuple):
        data_ordinals: tuple[int, ...] = ()
    else:
        data_ordinals = tuple(
            index
            for index, block in enumerate(labeled_blocks)
            if isinstance(block, Mapping) and block.get("kind") == "DATA"
        )
    mixed_material = "table" in plan.retrieval_requirement.required_item_elements
    if not mixed_material and not data_ordinals:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_IMAGE_DATA_MISSING",
            "image-filtered evidence requires a separate authored DATA material block",
        )

    entries_by_id = {entry.evidence_id: entry for entry in manifest.entries}
    cited_structure_paths: set[str] = set()
    for citation in citations:
        entry = entries_by_id.get(citation.evidence_id)
        if (
            entry is not None
            and entry.use == "REFERENCE_PATTERN"
            and entry.source.source_class == "PAST_EXAM"
            and citation.application == "STRUCTURE_PATTERN"
        ):
            cited_structure_paths.update(citation.draft_json_paths)
    required_paths = {
        "/stem",
        *(f"/labeled_blocks/{ordinal}/content" for ordinal in data_ordinals),
        *(f"/visuals/{ordinal}/kind" for ordinal in image_ordinals),
    }
    if not required_paths.issubset(cited_structure_paths):
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_IMAGE_STRUCTURE_UNCITED",
            "required image presentation is not bound to past-exam structure evidence",
        )


def _validate_required_table_presentation(
    plan: ResolvedExecutionPlanV3,
    manifest: EvidenceManifest,
    citations: Sequence[EvidenceUsageCitationV1],
    draft: Mapping[str, Any],
) -> None:
    """Bind each requested native table to exact past-exam structure evidence.

    A table is authored content, not a raster placeholder. Maps and sets keep the check linear in
    the bounded manifest, citations, headers, and cells while preserving visual order.
    """

    if "table" not in plan.retrieval_requirement.required_item_elements:
        return
    visuals = draft.get("visuals")
    if not isinstance(visuals, list | tuple):
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_TABLE_MISSING",
            "table-filtered evidence requires typed authoring visuals",
        )
    table_ordinals = tuple(
        index
        for index, visual in enumerate(visuals)
        if isinstance(visual, Mapping) and visual.get("kind") == "TABLE"
    )
    if not table_ordinals:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REQUIRED_TABLE_MISSING",
            "table-filtered evidence requires at least one authored TABLE",
        )

    entries_by_id = {entry.evidence_id: entry for entry in manifest.entries}
    cited_structure_paths: set[str] = set()
    for citation in citations:
        entry = entries_by_id.get(citation.evidence_id)
        if (
            entry is not None
            and entry.use == "REFERENCE_PATTERN"
            and entry.source.source_class == "PAST_EXAM"
            and citation.application == "STRUCTURE_PATTERN"
        ):
            cited_structure_paths.update(citation.draft_json_paths)

    for ordinal in table_ordinals:
        visual = visuals[ordinal]
        assert isinstance(visual, Mapping)
        if f"/visuals/{ordinal}/kind" not in cited_structure_paths:
            raise EvidenceUsageValidationError(
                "EVIDENCE_REQUIRED_TABLE_STRUCTURE_UNCITED",
                "required table kind is not bound to past-exam structure evidence",
            )
        scalar_paths = {
            *(
                f"/visuals/{ordinal}/headers/{index}"
                for index, _ in enumerate(visual.get("headers", ()))
            ),
            *(
                f"/visuals/{ordinal}/rows/{row_index}/{column_index}"
                for row_index, row in enumerate(visual.get("rows", ()))
                if isinstance(row, list | tuple)
                for column_index, _ in enumerate(row)
            ),
        }
        if not scalar_paths.intersection(cited_structure_paths):
            raise EvidenceUsageValidationError(
                "EVIDENCE_REQUIRED_TABLE_STRUCTURE_UNCITED",
                "required table has no cited header or cell leaf",
            )


def _validate_review_result(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV3,
    materials: ResolvedEvidenceMaterials,
    worker_input: RoleWorkerInput,
    result: ContentTeamReviewRoleResultV10,
    result_artifact: EvidenceResultArtifactPointer,
    canonical_artifact_root: Path,
) -> ReviewEvidenceUsageValidationReceipt:
    attestation = result.output.evidence_usage_attestation
    if attestation is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_ATTESTATION_MISSING", "review evidence attestation is missing"
        )
    pointers = tuple(
        pointer
        for pointer in worker_input.upstream_artifacts
        if pointer.step_key == "authoring" and pointer.result_schema == "authoring-result@10.0"
    )
    if len(pointers) != 1:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_POINTER_INVALID",
            "review requires one exact @10 authoring Artifact pointer",
        )
    pointer = pointers[0]
    if attestation.authoring_artifact.model_dump(mode="json") != {
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": pointer.content_hash,
        "result_schema": pointer.result_schema,
    }:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_POINTER_MISMATCH",
            "review attestation differs from its exact authoring pointer",
        )
    authoring = _resolve_authoring_result(
        session,
        pointer=pointer,
        workflow_id=result.workflow_id,
        canonical_artifact_root=canonical_artifact_root,
    )
    if not isinstance(authoring, ContentTeamAuthoringRoleResultV10) or isinstance(
        authoring, ContentTeamAuthoringRoleResultV11
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result family differs"
        )
    authoring_hash = _validate_authoring_result(plan, materials, authoring)
    review_hash = canonical_citation_set_sha256(attestation.citations)
    authoring_usage = authoring.output.evidence_usage
    assert authoring_usage is not None
    if attestation.citations != authoring_usage.citations or review_hash != authoring_hash:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_CITATIONS_MISMATCH",
            "review citations differ from the exact authoring result",
        )
    return _review_receipt(
        plan,
        result_artifact=result_artifact,
        authoring_artifact=EvidenceResultArtifactPointer(
            logical_artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
            content_hash=pointer.content_hash,
            result_schema="authoring-result@10.0",
        ),
        authoring_hash=authoring_hash,
        review_hash=review_hash,
    )


_ALLOWED_EVIDENCE_USES_BY_REVIEW_PURPOSE = {
    "SCIENTIFIC_VALIDATION": frozenset({"GROUNDING", "REFERENCE_PATTERN"}),
    "CURRICULUM_SCOPE": frozenset({"GROUNDING", "REFERENCE_PATTERN"}),
    "ORIGINALITY_CHECK": frozenset({"REFERENCE_PATTERN", "AVOID_COPY"}),
    "VISUAL_VALIDATION": frozenset({"GROUNDING", "REFERENCE_PATTERN"}),
}


def canonical_review_evidence_set_sha256(result: ContentTeamReviewRoleResultV11) -> str:
    """Hash the canonical bounded evidence set independently selected by review."""

    return content_sha256(
        {
            "schema_version": "independent-review-evidence-set/1.0",
            "evidence_references": [
                reference.model_dump(mode="json")
                for reference in result.output.independent_review_report.evidence_references
            ],
        }
    )


def _validate_review_result_v11(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV3,
    materials: ResolvedEvidenceMaterials,
    worker_input: RoleWorkerInput,
    result: ContentTeamReviewRoleResultV11,
    result_artifact: ResultArtifactPointer,
    canonical_artifact_root: Path,
) -> ReviewEvidenceUsageValidationReceiptV2:
    if not isinstance(plan, ResolvedExecutionPlanV11) or not isinstance(
        result_artifact, EvidenceResultArtifactPointerV2
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_PROTOCOL_PLAN_MISMATCH",
            "@11 review requires its successor plan and result pointer",
        )
    attestation = result.output.evidence_usage_attestation
    if attestation is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_ATTESTATION_MISSING", "review evidence attestation is missing"
        )
    pointers = tuple(
        pointer
        for pointer in worker_input.upstream_artifacts
        if pointer.step_key == "authoring" and pointer.result_schema == "authoring-result@11.0"
    )
    if len(pointers) != 1:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_POINTER_INVALID",
            "review requires one exact @11 authoring Artifact pointer",
        )
    pointer = pointers[0]
    if attestation.authoring_artifact.model_dump(mode="json") != {
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": pointer.content_hash,
        "result_schema": pointer.result_schema,
    }:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_POINTER_MISMATCH",
            "review attestation differs from its exact authoring pointer",
        )
    authoring = _resolve_authoring_result(
        session,
        pointer=pointer,
        workflow_id=result.workflow_id,
        canonical_artifact_root=canonical_artifact_root,
        successor=True,
    )
    if not isinstance(authoring, ContentTeamAuthoringRoleResultV11):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result family differs"
        )
    authoring_hash = _validate_authoring_result(plan, materials, authoring)
    review_hash = canonical_citation_set_sha256(attestation.citations)
    authoring_usage = authoring.output.evidence_usage
    assert authoring_usage is not None
    if attestation.citations != authoring_usage.citations or review_hash != authoring_hash:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_CITATIONS_MISMATCH",
            "review citations differ from the exact authoring result",
        )
    draft = authoring.output.draft.model_dump(mode="json")
    _validate_independent_review_report(materials, result, draft)
    report_hash = content_sha256(result.output.independent_review_report.model_dump(mode="json"))
    review_evidence_hash = canonical_review_evidence_set_sha256(result)
    return _review_receipt_v2(
        plan,
        result_artifact=result_artifact,
        authoring_artifact=EvidenceResultArtifactPointerV2(
            logical_artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
            content_hash=pointer.content_hash,
            result_schema="authoring-result@11.0",
        ),
        authoring_hash=authoring_hash,
        review_hash=review_hash,
        report_hash=report_hash,
        review_evidence_hash=review_evidence_hash,
    )


def _validate_independent_review_report(
    materials: ResolvedEvidenceMaterials,
    result: ContentTeamReviewRoleResultV11,
    draft: Mapping[str, Any],
) -> None:
    report = result.output.independent_review_report
    entries = {entry.evidence_id: entry for entry in materials.manifest.entries}
    context_ids = _validated_context_evidence_ids(materials.manifest, materials.context_payload)
    solution_grounded_scientific = False
    for reference in report.evidence_references:
        entry = entries.get(reference.evidence_id)
        if entry is None or reference.evidence_id not in context_ids:
            raise EvidenceUsageValidationError(
                "EVIDENCE_REVIEW_REFERENCE_UNKNOWN",
                "independent review reference is absent from pinned evidence materials",
            )
        if not set(reference.anchor_ids).issubset(set(entry.anchor_ids)):
            raise EvidenceUsageValidationError(
                "EVIDENCE_REVIEW_ANCHOR_UNKNOWN",
                "independent review anchor is absent from its manifest entry",
            )
        for purpose in reference.purposes:
            if entry.use not in _ALLOWED_EVIDENCE_USES_BY_REVIEW_PURPOSE[purpose]:
                raise EvidenceUsageValidationError(
                    "EVIDENCE_REVIEW_PURPOSE_INVALID",
                    "independent review purpose is incompatible with manifest use",
                )
            if entry.answer_bearing and purpose != "ORIGINALITY_CHECK":
                raise EvidenceUsageValidationError(
                    "EVIDENCE_REVIEW_ANSWER_BEARING_INVALID",
                    "answer-bearing evidence may only be used for originality comparison",
                )
        if (
            "SCIENTIFIC_VALIDATION" in reference.purposes
            and getattr(entry, "solution_evidence", None) is not None
        ):
            solution_grounded_scientific = True
    if isinstance(materials.manifest, EvidenceBundleManifestV5) and not (
        solution_grounded_scientific
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_SOLUTION_REPORT_UNUSED",
            "solution-enriched evidence must ground at least one scientific review claim",
        )

    _validate_independent_review_draft(result, draft)


def _validate_independent_review_draft(
    result: ContentTeamReviewRoleResultV11,
    draft: Mapping[str, Any],
) -> None:
    """Bind the bounded independent report to one exact authored draft."""

    report = result.output.independent_review_report
    answer = draft.get("answer")
    authored_answer = answer.get("number") if isinstance(answer, Mapping) else None
    if report.answer_review.authored_answer_number != authored_answer:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_AUTHORED_ANSWER_MISMATCH",
            "independent review does not bind the authored answer",
        )
    choices = draft.get("choices")
    if not isinstance(choices, list | tuple) or len(choices) != 5:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_CHOICE_COVERAGE_INVALID",
            "independent review requires the exact five authored choices",
        )
    for index, diagnostic in enumerate(report.choice_diagnostics):
        choice = choices[index]
        if (
            not isinstance(choice, Mapping)
            or choice.get("number") != diagnostic.number
            or f"/choices/{index}/text" not in diagnostic.draft_json_paths
        ):
            raise EvidenceUsageValidationError(
                "EVIDENCE_REVIEW_CHOICE_COVERAGE_INVALID",
                "choice diagnostic differs from its exact authored choice",
            )

    statements = draft.get("statements")
    statement_values = statements if isinstance(statements, list | tuple) else ()
    if bool(statement_values) != bool(report.statement_diagnostics) or len(
        statement_values
    ) not in {
        0,
        3,
    }:
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_STATEMENT_COVERAGE_INVALID",
            "statement diagnostics must exactly match an absent or three-statement draft",
        )
    for index, statement_diagnostic in enumerate(report.statement_diagnostics):
        statement = statement_values[index]
        if (
            not isinstance(statement, Mapping)
            or statement.get("label") != statement_diagnostic.label
            or f"/statements/{index}/text" not in statement_diagnostic.draft_json_paths
        ):
            raise EvidenceUsageValidationError(
                "EVIDENCE_REVIEW_STATEMENT_COVERAGE_INVALID",
                "statement diagnostic differs from its exact authored statement",
            )

    visuals = draft.get("visuals")
    has_visual = isinstance(visuals, list | tuple) and bool(visuals)
    if has_visual == (report.visual_assessment.status == "NOT_APPLICABLE"):
        raise EvidenceUsageValidationError(
            "EVIDENCE_REVIEW_VISUAL_COVERAGE_INVALID",
            "visual assessment applicability differs from the authored draft",
        )
    pointer_groups = [
        *(claim.draft_json_paths for claim in report.answer_review.claims),
        *(choice.draft_json_paths for choice in report.choice_diagnostics),
        *(statement.draft_json_paths for statement in report.statement_diagnostics),
        report.explanation_assessment.draft_json_paths,
        report.curriculum_assessment.draft_json_paths,
        report.originality_assessment.draft_json_paths,
        report.visual_assessment.draft_json_paths,
    ]
    for pointers in pointer_groups:
        for pointer_value in pointers:
            _resolve_semantic_leaf(draft, pointer_value)


def _validate_ungrounded_review_result_v11(
    session: Session,
    *,
    worker_input: RoleWorkerInput,
    result: ContentTeamReviewRoleResultV11,
    canonical_artifact_root: Path,
) -> None:
    """Validate general-knowledge review against its immutable authoring Artifact."""

    pointers = tuple(
        pointer
        for pointer in worker_input.upstream_artifacts
        if pointer.step_key == "authoring" and pointer.result_schema == "authoring-result@11.0"
    )
    if len(pointers) != 1:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_POINTER_INVALID",
            "review requires one exact @11 authoring Artifact pointer",
        )
    authoring = _resolve_authoring_result(
        session,
        pointer=pointers[0],
        workflow_id=result.workflow_id,
        canonical_artifact_root=canonical_artifact_root,
        successor=True,
    )
    if (
        not isinstance(authoring, ContentTeamAuthoringRoleResultV11)
        or authoring.output.metadata.knowledge_source_mode != "general_model_knowledge"
        or authoring.output.evidence_usage is not None
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID",
            "general-knowledge review requires an exact ungrounded @11 authoring result",
        )
    _validate_independent_review_draft(
        result,
        authoring.output.draft.model_dump(mode="json"),
    )


def _validate_citations(
    manifest: EvidenceManifest,
    context_payload: bytes,
    citations: Sequence[EvidenceUsageCitationV1],
    draft: Mapping[str, Any],
) -> None:
    entries = {entry.evidence_id: entry for entry in manifest.entries}
    context_ids = _validated_context_evidence_ids(manifest, context_payload)
    for citation in citations:
        entry = entries.get(citation.evidence_id)
        if entry is None or citation.evidence_id not in context_ids:
            raise EvidenceUsageValidationError(
                "EVIDENCE_CITATION_UNKNOWN", "citation is absent from pinned evidence materials"
            )
        if citation.application != _APPLICATION_BY_USE[entry.use]:
            raise EvidenceUsageValidationError(
                "EVIDENCE_CITATION_APPLICATION_INVALID",
                "citation application differs from manifest use",
            )
        if entry.answer_bearing and citation.application != "AVOID_COPY_CHECK":
            raise EvidenceUsageValidationError(
                "EVIDENCE_ANSWER_BEARING_USE_INVALID",
                "answer-bearing evidence cannot support a positive draft claim",
            )
        if not set(citation.anchor_ids).issubset(set(entry.anchor_ids)):
            raise EvidenceUsageValidationError(
                "EVIDENCE_CITATION_ANCHOR_UNKNOWN",
                "citation anchor is absent from its manifest entry",
            )
        for pointer in citation.draft_json_paths:
            _resolve_semantic_leaf(draft, pointer)


def _validated_context_evidence_ids(
    manifest: EvidenceManifest, context_payload: bytes
) -> frozenset[str]:
    try:
        context = context_payload.decode("utf-8")
    except UnicodeError as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_CONTEXT_INVALID", "evidence context is not UTF-8"
        ) from exc
    observed: list[tuple[str, int, str]] = []
    for line in context.splitlines():
        if not line.startswith("- `evidenceitem_"):
            continue
        matched = _CONTEXT_EVIDENCE_LINE.match(line)
        if matched is None:
            raise EvidenceUsageValidationError(
                "EVIDENCE_CONTEXT_INVALID", "evidence context entry is malformed"
            )
        observed.append((matched.group(1), int(matched.group(2)), matched.group(3)))
    expected = [(entry.evidence_id, entry.relevance_milli, entry.use) for entry in manifest.entries]
    if observed != expected:
        raise EvidenceUsageValidationError(
            "EVIDENCE_CONTEXT_MANIFEST_MISMATCH",
            "evidence context ranked entries differ from the manifest",
        )
    return frozenset(evidence_id for evidence_id, _, _ in observed)


def _resolve_semantic_leaf(draft: Mapping[str, Any], pointer: str) -> None:
    segments = pointer.removeprefix("/").split("/")
    decoded = tuple(segment.replace("~1", "/").replace("~0", "~") for segment in segments)
    canonical = "/" + "/".join(segment.replace("~", "~0").replace("/", "~1") for segment in decoded)
    if canonical != pointer or not decoded or decoded[0] not in _SEMANTIC_DRAFT_ROOTS:
        raise EvidenceUsageValidationError(
            "EVIDENCE_DRAFT_POINTER_INVALID",
            "citation path is not a canonical semantic draft pointer",
        )
    value: Any = draft
    for segment in decoded:
        if isinstance(value, Mapping):
            if segment not in value:
                raise EvidenceUsageValidationError(
                    "EVIDENCE_DRAFT_POINTER_MISSING", "citation path does not resolve"
                )
            value = value[segment]
        elif isinstance(value, list | tuple):
            if not _ARRAY_INDEX.fullmatch(segment):
                raise EvidenceUsageValidationError(
                    "EVIDENCE_DRAFT_POINTER_INVALID",
                    "citation path has a noncanonical array index",
                )
            index = int(segment)
            if index >= len(value):
                raise EvidenceUsageValidationError(
                    "EVIDENCE_DRAFT_POINTER_MISSING", "citation array index is out of range"
                )
            value = value[index]
        else:
            raise EvidenceUsageValidationError(
                "EVIDENCE_DRAFT_POINTER_MISSING", "citation traverses a scalar value"
            )
    if isinstance(value, Mapping | list | tuple) or value is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_DRAFT_POINTER_NOT_LEAF", "citation path must resolve to a scalar leaf"
        )


def _resolve_authoring_result(
    session: Session,
    *,
    pointer: ArtifactPointer,
    workflow_id: str,
    canonical_artifact_root: Path,
    successor: bool = False,
) -> ContentTeamAuthoringRoleResultV10 | ContentTeamAuthoringRoleResultV11:
    expected_schema = "authoring-result@11.0" if successor else "authoring-result@10.0"
    expected_protocol = "workflow-role/1.23.0" if successor else "workflow-role/1.20.0"
    logical = session.get(ArtifactRecord, pointer.logical_artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
    job = session.get(JobRecord, pointer.job_id)
    if logical is None or revision is None or job is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_ARTIFACT_STALE", "authoring Artifact pointer is stale"
        )
    try:
        stored_input = RoleWorkerInput.model_validate(job.request)
    except ValidationError as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_ARTIFACT_STALE", "authoring Artifact pointer is stale"
        ) from exc
    if (
        not logical.approved
        or not revision.approved
        or logical.job_id != pointer.job_id
        or revision.job_id != pointer.job_id
        or revision.logical_artifact_id != pointer.logical_artifact_id
        or revision.content_hash != pointer.content_hash
        or job.job_id != pointer.job_id
        or job.protocol_version != stored_input.protocol_version
        or job.logical_artifact_id != pointer.logical_artifact_id
        or job.revision_id != pointer.revision_id
        or pointer.step_key != "authoring"
        or pointer.result_schema != expected_schema
        or pointer.attempt != stored_input.attempt
        or stored_input.protocol_version != expected_protocol
        or stored_input.role != "authoring"
        or stored_input.job_id != pointer.job_id
        or stored_input.workflow_id != workflow_id
        or stored_input.artifact.logical_artifact_id != pointer.logical_artifact_id
        or stored_input.artifact.revision_id != pointer.revision_id
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_ARTIFACT_STALE", "authoring Artifact pointer is stale"
        )
    artifact_root = _canonical_root(canonical_artifact_root)
    expected_root = artifact_root / pointer.logical_artifact_id / pointer.revision_id
    if Path(revision.nas_path) != expected_root:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_STORAGE_MISMATCH", "authoring Artifact storage is not canonical"
        )
    _require_safe_revision_root(expected_root, artifact_root)
    manifest = revision.manifest
    if (
        manifest.get("job_id") != pointer.job_id
        or manifest.get("logical_artifact_id") != pointer.logical_artifact_id
        or manifest.get("revision_id") != pointer.revision_id
        or manifest.get("content_hash") != pointer.content_hash
        or manifest.get("content_bytes") != revision.content_bytes
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_MANIFEST_MISMATCH", "authoring Artifact manifest differs"
        )
    payload = _read_exact_result(expected_root / "result.json", revision.content_bytes)
    if sha256_bytes(payload) != pointer.content_hash:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_HASH_MISMATCH", "authoring result bytes differ"
        )
    try:
        document = json.loads(payload.decode("utf-8"))
        if not isinstance(document, dict) or canonical_json_bytes(document) != payload:
            raise ValueError("authoring result is not canonical JSON")
        if document != revision.result:
            raise ValueError("authoring result differs from database record")
        result = validate_role_result(document, "authoring", expected_schema)
    except (
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        WorkflowSchemaError,
    ) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result is invalid"
        ) from exc
    if successor:
        if not isinstance(result, ContentTeamAuthoringRoleResultV11):
            raise EvidenceUsageValidationError(
                "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result type differs"
            )
        validated_result: ContentTeamAuthoringRoleResultV10 | ContentTeamAuthoringRoleResultV11 = (
            result
        )
    elif not isinstance(result, ContentTeamAuthoringRoleResultV10) or isinstance(
        result, ContentTeamAuthoringRoleResultV11
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result type differs"
        )
    else:
        validated_result = result
    if (
        validated_result.job_id != pointer.job_id
        or validated_result.workflow_id != workflow_id
        or validated_result.step_run_id != stored_input.step_run_id
        or validated_result.role != stored_input.role
        or validated_result.artifact != stored_input.artifact
    ):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_IDENTITY_MISMATCH",
            "authoring result envelope differs from its exact pointer and Job request",
        )
    return validated_result


def _canonical_root(path: Path) -> Path:
    try:
        metadata = path.lstat()
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or path.resolve(strict=True) != path
        ):
            raise ValueError("unsafe Artifact root")
    except (OSError, ValueError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_ARTIFACT_ROOT_INVALID", "canonical Artifact root is unavailable"
        ) from exc
    return path


def _require_safe_revision_root(path: Path, artifact_root: Path) -> None:
    current = artifact_root
    try:
        for component in path.relative_to(artifact_root).parts:
            current /= component
            metadata = current.lstat()
            if current.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("unsafe Artifact revision directory")
        if current.resolve(strict=True) != path:
            raise ValueError("Artifact revision escaped its canonical root")
    except (OSError, ValueError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_FILE_INVALID", "authoring Artifact path is unsafe"
        ) from exc


def _read_exact_result(path: Path, expected_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != expected_bytes
            ):
                raise ValueError("authoring result metadata differs")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_FILE_INVALID", "authoring result is unsafe or unreadable"
        ) from exc
    return payload


def _receipt_common(plan: ResolvedExecutionPlanV3) -> dict[str, object]:
    return {
        "schema_version": "evidence-usage-validation-receipt/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "evidence_bundle_id": plan.evidence_bundle_id,
        "evidence_bundle_revision_id": plan.evidence_bundle_revision_id,
        "retrieval_request_id": plan.retrieval_request_id,
        "retrieval_request_sha256": plan.retrieval_request_sha256,
        "graph_snapshot_revision_id": plan.graph_snapshot.graph_snapshot_revision_id,
        "graph_snapshot_sha256": plan.graph_snapshot.manifest_sha256,
        "evidence_manifest_artifact": plan.evidence_manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": plan.evidence_manifest_sha256,
        "evidence_context_artifact": plan.evidence_context_artifact.model_dump(mode="json"),
    }


def _authoring_receipt(
    plan: ResolvedExecutionPlanV3,
    result_artifact: EvidenceResultArtifactPointer,
    citation_hash: str,
) -> AuthoringEvidenceUsageValidationReceipt:
    document = {
        **_receipt_common(plan),
        "step_key": "authoring",
        "result_artifact": result_artifact.model_dump(mode="json"),
        "authoring_citation_set_sha256": citation_hash,
        "receipt_sha256": _ZERO_SHA256,
    }
    document["receipt_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "receipt_sha256"}
    )
    try:
        validate_control_contract("evidence-usage-validation-receipt", document)
        return AuthoringEvidenceUsageValidationReceipt.model_validate(document)
    except (ControlSchemaError, JsonSchemaValidationError, ValidationError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_INVALID", "authoring evidence receipt is invalid"
        ) from exc


def _review_receipt(
    plan: ResolvedExecutionPlanV3,
    *,
    result_artifact: EvidenceResultArtifactPointer,
    authoring_artifact: EvidenceResultArtifactPointer,
    authoring_hash: str,
    review_hash: str,
) -> ReviewEvidenceUsageValidationReceipt:
    document = {
        **_receipt_common(plan),
        "step_key": "review",
        "result_artifact": result_artifact.model_dump(mode="json"),
        "authoring_artifact": authoring_artifact.model_dump(mode="json"),
        "authoring_citation_set_sha256": authoring_hash,
        "review_citation_set_sha256": review_hash,
        "citation_sets_equal": True,
        "receipt_sha256": _ZERO_SHA256,
    }
    document["receipt_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "receipt_sha256"}
    )
    try:
        validate_control_contract("evidence-usage-validation-receipt", document)
        return ReviewEvidenceUsageValidationReceipt.model_validate(document)
    except (ControlSchemaError, JsonSchemaValidationError, ValidationError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_INVALID", "review evidence receipt is invalid"
        ) from exc


def _receipt_common_v2(plan: ResolvedExecutionPlanV11) -> dict[str, object]:
    return {
        "schema_version": "evidence-usage-validation-receipt/2.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "evidence_bundle_id": plan.evidence_bundle_id,
        "evidence_bundle_revision_id": plan.evidence_bundle_revision_id,
        "retrieval_request_id": plan.retrieval_request_id,
        "retrieval_request_sha256": plan.retrieval_request_sha256,
        "graph_snapshot_revision_id": plan.graph_snapshot.graph_snapshot_revision_id,
        "graph_snapshot_sha256": plan.graph_snapshot.manifest_sha256,
        "evidence_manifest_artifact": plan.evidence_manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": plan.evidence_manifest_sha256,
        "evidence_context_artifact": plan.evidence_context_artifact.model_dump(mode="json"),
    }


def _authoring_receipt_v2(
    plan: ResolvedExecutionPlanV3,
    result_artifact: EvidenceResultArtifactPointerV2,
    citation_hash: str,
) -> AuthoringEvidenceUsageValidationReceiptV2:
    if not isinstance(plan, ResolvedExecutionPlanV11):
        raise EvidenceUsageValidationError(
            "EVIDENCE_PROTOCOL_PLAN_MISMATCH", "@11 receipt requires a successor plan"
        )
    document = {
        **_receipt_common_v2(plan),
        "step_key": "authoring",
        "result_artifact": result_artifact.model_dump(mode="json"),
        "authoring_citation_set_sha256": citation_hash,
        "receipt_sha256": _ZERO_SHA256,
    }
    document["receipt_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "receipt_sha256"}
    )
    try:
        validate_control_contract("evidence-usage-validation-receipt-v2", document)
        return AuthoringEvidenceUsageValidationReceiptV2.model_validate(document)
    except (ControlSchemaError, JsonSchemaValidationError, ValidationError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_INVALID", "authoring successor evidence receipt is invalid"
        ) from exc


def _review_receipt_v2(
    plan: ResolvedExecutionPlanV11,
    *,
    result_artifact: EvidenceResultArtifactPointerV2,
    authoring_artifact: EvidenceResultArtifactPointerV2,
    authoring_hash: str,
    review_hash: str,
    report_hash: str,
    review_evidence_hash: str,
) -> ReviewEvidenceUsageValidationReceiptV2:
    document = {
        **_receipt_common_v2(plan),
        "step_key": "review",
        "result_artifact": result_artifact.model_dump(mode="json"),
        "authoring_artifact": authoring_artifact.model_dump(mode="json"),
        "authoring_citation_set_sha256": authoring_hash,
        "review_citation_set_sha256": review_hash,
        "citation_sets_equal": True,
        "independent_review_report_sha256": report_hash,
        "review_evidence_set_sha256": review_evidence_hash,
        "receipt_sha256": _ZERO_SHA256,
    }
    document["receipt_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "receipt_sha256"}
    )
    try:
        validate_control_contract("evidence-usage-validation-receipt-v2", document)
        return ReviewEvidenceUsageValidationReceiptV2.model_validate(document)
    except (ControlSchemaError, JsonSchemaValidationError, ValidationError) as exc:
        raise EvidenceUsageValidationError(
            "EVIDENCE_RECEIPT_INVALID", "review successor evidence receipt is invalid"
        ) from exc
