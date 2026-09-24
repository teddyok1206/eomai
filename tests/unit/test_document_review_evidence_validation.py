from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import EvidenceBundleManifestV5, KnowledgeArtifactMemberPointer
from eom_orchestrator import document_review_evidence_validation as validation_module
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.document_review_evidence_validation import (
    validate_document_review_evidence_for_commit,
)
from eom_orchestrator.evidence_usage_validation import EvidenceUsageValidationError
from eom_workflow import (
    PairedDocumentReviewRequestV2,
    PairedDocumentReviewRoleResultV3,
    PairedDocumentReviewWorkerRequestV2,
    RoleWorkerInput,
)

from tests.unit.test_document_review_v3_protocol import _result

SHA = "sha256:" + "1" * 64
PLAN_SHA = "sha256:" + "2" * 64
EVIDENCE_PLAN_SHA = "sha256:" + "3" * 64


def _pointer(seed: str, *, manifest: bool) -> KnowledgeArtifactMemberPointer:
    return KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        sha256="sha256:" + seed * 64,
        schema_ref=(
            "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
            if manifest
            else "eom://schemas/knowledge/evidence-bundle-context/1.0"
        ),
        media_type="application/json" if manifest else "text/markdown",
        logical_name="manifest.json" if manifest else "context.md",
        member_path="evidence/manifest.json" if manifest else "evidence/context.md",
    )


def _runtime() -> tuple[
    object,
    RoleWorkerInput,
    PairedDocumentReviewRoleResultV3,
    object,
]:
    result = PairedDocumentReviewRoleResultV3.model_validate(_result())
    usage = result.output.evidence_usage
    request = PairedDocumentReviewRequestV2.model_construct(
        request_sha256=result.output.review_request_sha256,
        evidence_plan=SimpleNamespace(plan_sha256=EVIDENCE_PLAN_SHA),
    )
    worker_request = PairedDocumentReviewWorkerRequestV2.model_construct(review_request=request)
    worker_input = cast(
        RoleWorkerInput,
        SimpleNamespace(
            request=worker_request,
            workflow_id=result.workflow_id,
            protocol_version="workflow-role/1.27.0",
            role="support",
            job_id=result.job_id,
            step_run_id=result.step_run_id,
            attempt=1,
        ),
    )
    plan = SimpleNamespace(
        plan_id="execplan_" + "4" * 32,
        plan_sha256=PLAN_SHA,
        workflow_id=result.workflow_id,
        review_request_sha256=result.output.review_request_sha256,
        evidence_plan_sha256=EVIDENCE_PLAN_SHA,
        retrieval_request_id=usage.retrieval_request_id,
        graph_snapshot=SimpleNamespace(graph_snapshot_revision_id=usage.graph_snapshot_revision_id),
        evidence_bundle_id=usage.evidence_bundle_id,
        evidence_bundle_revision_id=usage.evidence_bundle_revision_id,
        evidence_manifest_artifact=_pointer("5", manifest=True),
        evidence_manifest_sha256=usage.manifest_sha256,
        evidence_context_artifact=KnowledgeArtifactMemberPointer(
            **(
                _pointer("6", manifest=False).model_dump(mode="python")
                | {"sha256": usage.context_sha256}
            )
        ),
    )
    entries = tuple(
        SimpleNamespace(
            evidence_id=citation.evidence_id,
            anchor_ids=citation.anchor_ids,
            use=(
                "REFERENCE_PATTERN"
                if citation.application == "ORIGINALITY_COMPARISON"
                else "GROUNDING"
            ),
            solution_evidence=(
                object() if citation.application == "SOLUTION_VERIFICATION" else None
            ),
        )
        for citation in usage.citations
    )
    manifest = EvidenceBundleManifestV5.model_construct(entries=entries)
    session = SimpleNamespace(
        get=lambda model, identity: (
            SimpleNamespace(canonical_document={}, plan_sha256=PLAN_SHA)
            if model is ResolvedExecutionPlanRecord and identity == plan.plan_id
            else None
        )
    )
    return session, worker_input, result, SimpleNamespace(plan=plan, manifest=manifest)


def _validate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: PairedDocumentReviewRoleResultV3 | None = None,
    manifest: EvidenceBundleManifestV5 | None = None,
):
    session, worker_input, default_result, fixture = _runtime()
    selected_result = result or default_result
    selected_manifest = manifest or fixture.manifest
    monkeypatch.setattr(
        validation_module.ResolvedExecutionPlanV15,
        "model_validate",
        lambda _value: fixture.plan,
    )
    monkeypatch.setattr(
        validation_module,
        "authorized_execution_artifact_revisions",
        lambda *_args, **_kwargs: frozenset({"rev_authorized"}),
    )
    monkeypatch.setattr(
        validation_module,
        "resolve_evidence_materials",
        lambda *_args, **_kwargs: SimpleNamespace(manifest=selected_manifest),
    )
    return validate_document_review_evidence_for_commit(
        cast(Any, session),
        plan_id=fixture.plan.plan_id,
        worker_input=worker_input,
        result=selected_result,
        result_artifact_id="artifact_" + "7" * 32,
        result_artifact_revision_id="rev_" + "8" * 32,
        result_content_sha256=SHA,
        canonical_artifact_root=cast(Any, "/unused"),
    )


def test_document_review_evidence_receipt_binds_exact_result_and_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _validate(monkeypatch)
    assert receipt.schema_version == "document-review-evidence-validation-receipt/1.0"
    assert receipt.result_content_sha256 == SHA
    assert receipt.review_request_sha256 == SHA
    assert receipt.receipt_sha256.startswith("sha256:")


def test_document_review_evidence_rejects_unknown_manifest_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, fixture = _runtime()
    manifest = EvidenceBundleManifestV5.model_construct(entries=fixture.manifest.entries[1:])
    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate(monkeypatch, manifest=manifest)
    assert captured.value.code == "DOCUMENT_REVIEW_EVIDENCE_CITATION_INVALID"


def test_document_review_evidence_rejects_container_path_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _result()
    output = value["output"]
    assert isinstance(output, dict)
    usage = output["evidence_usage"]
    assert isinstance(usage, dict)
    citations = usage["citations"]
    assert isinstance(citations, list)
    citations[0]["review_json_paths"] = ["/item_reviews/0/unit_checks"]
    result = PairedDocumentReviewRoleResultV3.model_validate(value)
    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate(monkeypatch, result=result)
    assert captured.value.code == "DOCUMENT_REVIEW_EVIDENCE_PATH_NOT_LEAF"


def test_document_review_solution_citation_requires_accepted_solution_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, fixture = _runtime()
    entries = tuple(
        SimpleNamespace(
            evidence_id=value.evidence_id,
            anchor_ids=value.anchor_ids,
            use=value.use,
            solution_evidence=None,
        )
        for value in fixture.manifest.entries
    )
    manifest = EvidenceBundleManifestV5.model_construct(entries=entries)
    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate(monkeypatch, manifest=manifest)
    assert captured.value.code == "DOCUMENT_REVIEW_SOLUTION_EVIDENCE_MISSING"
