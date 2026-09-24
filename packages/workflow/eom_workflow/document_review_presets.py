"""Read-only immutable preset resolver for PDF document review."""

from __future__ import annotations

import json
from importlib import resources
from types import MappingProxyType
from typing import Literal, cast

from eom_catalog_contracts import DocumentReviewEvidencePlan, PdfReviewDocumentPointer
from eom_identifiers import content_sha256

from eom_workflow.document_review import (
    PairedDocumentReviewRequest,
    PairedDocumentReviewRequestV2,
    PairedReviewDocument,
    PdfDocumentReviewRequest,
    PdfReviewPresetSnapshot,
    normalize_pdf_review_guidance,
)

PdfReviewPresetKey = Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]
_FILES = MappingProxyType(
    {
        "PROBLEM_SET": "problem-set-v1.json",
        "WEEKLY_WORKBOOK": "weekly-workbook-v1.json",
        "MOCK_EXAM": "mock-exam-v1.json",
    }
)


def load_pdf_review_preset(key: PdfReviewPresetKey) -> PdfReviewPresetSnapshot:
    """Resolve one packaged preset by exact key in O(1)."""

    file_name = _FILES[key]
    resource = resources.files("eom_workflow").joinpath(
        "resources", "document-review-presets", file_name
    )
    try:
        raw: object = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PDF review preset is unreadable: {key}") from exc
    preset = PdfReviewPresetSnapshot.model_validate(raw)
    if preset.preset_key != key:
        raise ValueError(f"PDF review preset key differs: {key}")
    return preset


def pdf_review_preset_keys() -> tuple[PdfReviewPresetKey, ...]:
    return cast(tuple[PdfReviewPresetKey, ...], tuple(_FILES))


def build_pdf_document_review_request(
    *,
    document: PdfReviewDocumentPointer,
    preset_key: PdfReviewPresetKey,
    additional_guidance: str | None,
) -> PdfDocumentReviewRequest:
    """Pin one preset and canonical user guidance into an immutable review request."""

    normalized_guidance = (
        None if additional_guidance is None else normalize_pdf_review_guidance(additional_guidance)
    )
    value: dict[str, object] = {
        "schema_version": "pdf-document-review-request/1.0",
        "document": document.model_dump(mode="json"),
        "preset": load_pdf_review_preset(preset_key).model_dump(mode="json"),
        "additional_guidance": normalized_guidance,
        "additional_guidance_sha256": (
            None if normalized_guidance is None else content_sha256(normalized_guidance)
        ),
        "locale": "ko-KR",
    }
    value["request_sha256"] = content_sha256(value)
    return PdfDocumentReviewRequest.model_validate(value)


def build_paired_document_review_request(
    *,
    question_document: PdfReviewDocumentPointer,
    solution_document: PdfReviewDocumentPointer,
    preset_key: PdfReviewPresetKey,
    additional_guidance: str | None,
) -> PairedDocumentReviewRequest:
    """Pin two role-addressed documents and one preset into an immutable request."""

    normalized_guidance = (
        None if additional_guidance is None else normalize_pdf_review_guidance(additional_guidance)
    )
    documents = (
        PairedReviewDocument(role="QUESTION", document=question_document),
        PairedReviewDocument(role="SOLUTION", document=solution_document),
    )
    value: dict[str, object] = {
        "schema_version": "paired-document-review-request/1.0",
        "documents": [document.model_dump(mode="json") for document in documents],
        "preset": load_pdf_review_preset(preset_key).model_dump(mode="json"),
        "additional_guidance": normalized_guidance,
        "additional_guidance_sha256": (
            None if normalized_guidance is None else content_sha256(normalized_guidance)
        ),
        "locale": "ko-KR",
    }
    value["request_sha256"] = content_sha256(value)
    return PairedDocumentReviewRequest.model_validate(value)


def build_graph_grounded_paired_document_review_request(
    *,
    question_document: PdfReviewDocumentPointer,
    solution_document: PdfReviewDocumentPointer,
    evidence_plan: DocumentReviewEvidencePlan,
    preset_key: PdfReviewPresetKey,
    additional_guidance: str | None,
) -> PairedDocumentReviewRequestV2:
    """Pin paired sources, preset, guidance, and one exact Graph evidence plan."""

    normalized_guidance = (
        None if additional_guidance is None else normalize_pdf_review_guidance(additional_guidance)
    )
    documents = (
        PairedReviewDocument(role="QUESTION", document=question_document),
        PairedReviewDocument(role="SOLUTION", document=solution_document),
    )
    value: dict[str, object] = {
        "schema_version": "paired-document-review-request/2.0",
        "documents": [document.model_dump(mode="json") for document in documents],
        "preset": load_pdf_review_preset(preset_key).model_dump(mode="json"),
        "additional_guidance": normalized_guidance,
        "additional_guidance_sha256": (
            None if normalized_guidance is None else content_sha256(normalized_guidance)
        ),
        "locale": "ko-KR",
        "evidence_plan": evidence_plan.model_dump(mode="json"),
    }
    value["request_sha256"] = content_sha256(value)
    return PairedDocumentReviewRequestV2.model_validate(value)
