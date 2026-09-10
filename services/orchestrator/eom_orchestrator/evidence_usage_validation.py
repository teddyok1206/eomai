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
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    AuthoringEvidenceUsageValidationReceipt,
    EvidenceResultArtifactPointer,
    ResolvedExecutionPlanV3,
    ReviewEvidenceUsageValidationReceipt,
    validate_control_contract,
)
from eom_workflow.models import (
    ArtifactPointer,
    ContentTeamAuthoringRoleResultV10,
    ContentTeamReviewRoleResultV10,
    EvidenceUsageCitationV1,
    RoleResult,
    RoleWorkerInput,
)
from eom_workflow.schemas import WorkflowSchemaError, validate_role_result
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


EvidenceManifest = EvidenceBundleManifestV2 | EvidenceBundleManifestV3 | EvidenceBundleManifestV4
EvidenceReceipt = AuthoringEvidenceUsageValidationReceipt | ReviewEvidenceUsageValidationReceipt


class EvidenceUsageValidationError(ValueError):
    """Stable fail-closed result error raised before Artifact commit."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def evidence_receipt_required_for_result(result: RoleResult) -> bool:
    """Return whether a submitted @10 result makes a non-null evidence claim."""

    if isinstance(result, ContentTeamAuthoringRoleResultV10):
        return result.output.evidence_usage is not None
    if isinstance(result, ContentTeamReviewRoleResultV10):
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
    expected_step = (
        "authoring" if isinstance(result, ContentTeamAuthoringRoleResultV10) else "review"
    )
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
    result_artifact: EvidenceResultArtifactPointer,
    canonical_artifact_root: Path,
) -> EvidenceReceipt | None:
    """Reload trusted pins and produce the receipt required for one @10 result commit."""

    if not isinstance(result, ContentTeamAuthoringRoleResultV10 | ContentTeamReviewRoleResultV10):
        return None
    if plan_id is None:
        _require_no_evidence_claim(result)
        return None
    plan_record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if plan_record is None:
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_MISSING", "evidence validation plan is missing"
        )
    if plan_record.canonical_document.get("schema_version") != "resolved-execution-plan/3.0":
        _require_no_evidence_claim(result)
        return None
    try:
        plan = ResolvedExecutionPlanV3.model_validate(plan_record.canonical_document)
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
            "@10 evidence usage requires the immutable 1.10 workflow family",
        )
    steps = tuple(item for item in plan.steps if item.step_key == step_key)
    if len(steps) != 1 or steps[0].role != result.role:
        raise EvidenceUsageValidationError(
            "EVIDENCE_PLAN_STEP_MISSING", "evidence validation plan step differs"
        )
    if steps[0].evidence_access != "EVIDENCE_CONTEXT":
        _require_no_evidence_claim(result)
        return None

    authorized = authorized_execution_artifact_revisions(
        session, plan_id=plan_id, step_key=step_key
    )
    try:
        materials = resolve_evidence_materials(
            session,
            plan=plan,
            canonical_artifact_root=canonical_artifact_root,
            authorized_artifact_revision_ids=authorized,
        )
    except ControlPlaneError as exc:
        # Pointer resolution errors are result-validation failures at this post-worker boundary.
        raise EvidenceUsageValidationError(
            "EVIDENCE_MATERIAL_RESOLUTION_FAILED",
            "pinned evidence material cannot be re-resolved",
        ) from exc

    if isinstance(result, ContentTeamAuthoringRoleResultV10):
        citation_hash = _validate_authoring_result(plan, materials, result)
        return _authoring_receipt(plan, result_artifact, citation_hash)

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
    result: ContentTeamAuthoringRoleResultV10 | ContentTeamReviewRoleResultV10,
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
    return canonical_citation_set_sha256(usage.citations)


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
) -> ContentTeamAuthoringRoleResultV10:
    logical = session.get(ArtifactRecord, pointer.logical_artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
    job = session.get(JobRecord, pointer.job_id)
    if (
        logical is None
        or revision is None
        or job is None
        or not logical.approved
        or not revision.approved
        or logical.job_id != pointer.job_id
        or revision.job_id != pointer.job_id
        or revision.logical_artifact_id != pointer.logical_artifact_id
        or revision.content_hash != pointer.content_hash
        or job.logical_artifact_id != pointer.logical_artifact_id
        or job.revision_id != pointer.revision_id
        or job.request.get("workflow_id") != workflow_id
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
        result = validate_role_result(document, "authoring", "authoring-result@10.0")
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
    if not isinstance(result, ContentTeamAuthoringRoleResultV10):
        raise EvidenceUsageValidationError(
            "EVIDENCE_AUTHORING_RESULT_INVALID", "authoring result type differs"
        )
    return result


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
    validate_control_contract("evidence-usage-validation-receipt", document)
    return AuthoringEvidenceUsageValidationReceipt.model_validate(document)


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
    validate_control_contract("evidence-usage-validation-receipt", document)
    return ReviewEvidenceUsageValidationReceipt.model_validate(document)
