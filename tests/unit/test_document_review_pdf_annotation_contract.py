from __future__ import annotations

from typing import Any

import pytest
from eom_catalog_contracts import (
    CreateDocumentReviewAnnotatedPdfs,
    DocumentReviewAnnotatedPdfMember,
    DocumentReviewAnnotationPage,
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationSource,
    DocumentReviewPdfAnnotationManifest,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationRenderer,
    DocumentReviewPdfAnnotationResult,
    DocumentReviewResultMemberPointer,
    PdfReviewArtifactMemberPointer,
    validate_contract,
)
from eom_identifiers import content_sha256
from pydantic import ValidationError


def _member(
    path: str, media_type: str, schema_ref: str, fill: str
) -> PdfReviewArtifactMemberPointer:
    return PdfReviewArtifactMemberPointer(
        artifact_id=f"artifact_{fill * 32}",
        artifact_revision_id=f"rev_{fill * 32}",
        member_path=path,
        sha256=f"sha256:{fill * 64}",
        schema_ref=schema_ref,
        media_type=media_type,
        content_length=100,
    )


def _source(role: str, fill: str) -> DocumentReviewAnnotationSource:
    return DocumentReviewAnnotationSource(
        role=role,
        document_id=f"document_{fill * 32}",
        document_revision_id=f"documentrev_{fill * 32}",
        source_pdf=_member(
            "source/original.pdf",
            "application/pdf",
            "eom://schemas/document-review/pdf-source/1.0",
            fill,
        ),
        page_count=1,
        pages=(
            DocumentReviewAnnotationPage(
                page_number=1,
                page_image=_member(
                    "pages/page-0001.png",
                    "image/png",
                    "eom://schemas/document-review/pdf-page-render/1.0",
                    fill,
                ),
            ),
        ),
    )


def _mark(role: str, fill: str, ordinal: int) -> DocumentReviewPdfAnnotationMark:
    return DocumentReviewPdfAnnotationMark(
        finding_id=f"reviewfinding_{fill * 32}",
        anchor_id=f"reviewanchor_{fill * 32}",
        ordinal=ordinal,
        document_role=role,
        page_number=1,
        page_image_sha256=f"sha256:{fill * 64}",
        region=DocumentReviewAnnotationRegion(
            x_ppm=100_000,
            y_ppm=100_000,
            width_ppm=200_000,
            height_ppm=100_000,
        ),
    )


def _request() -> CreateDocumentReviewAnnotatedPdfs:
    annotations = (_mark("QUESTION", "a", 1), _mark("SOLUTION", "b", 1))
    payload: dict[str, Any] = {
        "schema_version": "document-review-pdf-annotation-request/1.0",
        "operation": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS",
        "actor_id": "operator_test",
        "idempotency_key": "annotation:test:0001",
        "workflow_id": f"workflow_{'c' * 32}",
        "review_result": DocumentReviewResultMemberPointer(
            artifact_id=f"artifact_{'d' * 32}",
            artifact_revision_id=f"rev_{'d' * 32}",
            sha256=f"sha256:{'d' * 64}",
            content_length=100,
            schema_ref=(
                "https://eom.local/schemas/workflow/roles/"
                "paired-document-review-result-v2.schema.json"
            ),
        ),
        "sources": (_source("QUESTION", "a"), _source("SOLUTION", "b")),
        "annotations": annotations,
        "annotation_set_sha256": content_sha256(
            [value.model_dump(mode="json") for value in annotations]
        ),
    }
    payload["request_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "idempotency_key"}
    )
    return CreateDocumentReviewAnnotatedPdfs.model_validate(payload)


def test_annotation_request_is_schema_and_model_exact() -> None:
    value = _request()
    validate_contract("document-review-pdf-annotation-request", value.model_dump(mode="json"))
    assert value.sources[0].role == "QUESTION"
    assert value.sources[1].role == "SOLUTION"


def test_annotation_request_rejects_tampered_page_hash_and_request_hash() -> None:
    payload = _request().model_dump(mode="json")
    payload["annotations"][0]["page_image_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ValidationError, match="pinned page"):
        CreateDocumentReviewAnnotatedPdfs.model_validate(payload)

    payload = _request().model_dump(mode="json")
    payload["request_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ValidationError, match="self-hash"):
        CreateDocumentReviewAnnotatedPdfs.model_validate(payload)


def test_annotation_manifest_and_result_are_self_hashed() -> None:
    request = _request()
    outputs = (
        DocumentReviewAnnotatedPdfMember(
            document_role="QUESTION",
            member_path="annotated/question.pdf",
            sha256=f"sha256:{'1' * 64}",
            content_length=1000,
        ),
        DocumentReviewAnnotatedPdfMember(
            document_role="SOLUTION",
            member_path="annotated/solution.pdf",
            sha256=f"sha256:{'2' * 64}",
            content_length=1100,
        ),
    )
    annotation_id = f"docannotation_{'3' * 32}"
    renderer = DocumentReviewPdfAnnotationRenderer(
        qpdf_version="qpdf version 11.9.0",
        qpdf_sha256=f"sha256:{'4' * 64}",
        rsvg_convert_version="rsvg-convert version 2.58.0",
        rsvg_convert_sha256=f"sha256:{'5' * 64}",
        pdfinfo_version="pdfinfo version 24.02.0",
        pdfinfo_sha256=f"sha256:{'6' * 64}",
    )
    manifest_payload: dict[str, Any] = {
        "schema_version": "document-review-pdf-annotation-manifest/1.0",
        "annotation_id": annotation_id,
        "workflow_id": request.workflow_id,
        "request_sha256": request.request_sha256,
        "review_result_sha256": request.review_result.sha256,
        "sources": request.sources,
        "annotations": request.annotations,
        "annotation_set_sha256": request.annotation_set_sha256,
        "renderer": renderer,
        "outputs": outputs,
    }
    manifest_payload["manifest_sha256"] = content_sha256(manifest_payload)
    manifest = DocumentReviewPdfAnnotationManifest.model_validate(manifest_payload)
    validate_contract(
        "document-review-pdf-annotation-manifest",
        manifest.model_dump(mode="json"),
    )

    result_payload: dict[str, Any] = {
        "schema_version": "document-review-pdf-annotation-result/1.0",
        "annotation_id": annotation_id,
        "workflow_id": request.workflow_id,
        "request_sha256": request.request_sha256,
        "review_result_sha256": request.review_result.sha256,
        "annotation_set_sha256": request.annotation_set_sha256,
        "outputs": outputs,
        "manifest_sha256": manifest.manifest_sha256,
    }
    result_payload["result_sha256"] = content_sha256(result_payload)
    result = DocumentReviewPdfAnnotationResult.model_validate(result_payload)
    validate_contract("document-review-pdf-annotation-result", result.model_dump(mode="json"))
    assert result.result_sha256 == result_payload["result_sha256"]
