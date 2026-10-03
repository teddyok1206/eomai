from __future__ import annotations

import copy

from eom_catalog_contracts import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_workflow import (
    PairedDocumentReviewRequestV2,
    PairedDocumentReviewWorkerRequestV2,
    PairedReviewDocument,
    RoleWorkerInput,
    load_pdf_review_preset,
)
from eom_workflow.models import ArtifactSpec
from eom_workflow.schemas import (
    constrained_result_schema,
    load_role_result_schema,
    validate_codex_structured_output_schema,
)
from jsonschema import Draft202012Validator


def test_paired_document_review_v3_constrained_evidence_reference_is_strict() -> None:
    # Isolate projection-consumed fields. Intake separately validates complete source/evidence pins.
    page = PdfReviewPagePointer.model_construct(
        page_number=1,
        page_image=PdfReviewArtifactMemberPointer.model_construct(sha256="sha256:" + "6" * 64),
    )
    document = PdfReviewDocumentPointer.model_construct(pages=(page,))
    request = PairedDocumentReviewRequestV2.model_construct(
        documents=(
            PairedReviewDocument.model_construct(role="QUESTION", document=document),
            PairedReviewDocument.model_construct(role="SOLUTION", document=document),
        ),
        preset=load_pdf_review_preset("MOCK_EXAM"),
        request_sha256="sha256:" + "7" * 64,
    )
    worker_input = RoleWorkerInput.model_construct(
        protocol_version="workflow-role/1.27.0",
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="support",
        request=PairedDocumentReviewWorkerRequestV2.model_construct(review_request=request),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
    )
    canonical = load_role_result_schema("pdf-document-review-result@3.0")
    before = copy.deepcopy(canonical)

    schema = constrained_result_schema("pdf-document-review-result@3.0", worker_input)
    validate_codex_structured_output_schema(schema)
    Draft202012Validator.check_schema(schema)
    definitions = schema["$defs"]
    evidence_ref = definitions["output"]["properties"]["evidence_usage"]
    assert evidence_ref == {"$ref": "#/$defs/evidence_usage"}
    assert "references/evidence/manifest.json" in definitions["evidence_usage"]["description"]
    assert "evidence_usage" in definitions["output"]["required"]
    assert canonical == before == load_role_result_schema("pdf-document-review-result@3.0")
