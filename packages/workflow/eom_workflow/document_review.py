"""Immutable value contracts for page-anchored PDF document review."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from eom_catalog_contracts import (
    PdfReviewDocumentPointer,
)
from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DocumentId = Annotated[str, Field(pattern=r"^document_[0-9a-f]{32}$")]
DocumentRevisionId = Annotated[str, Field(pattern=r"^documentrev_[0-9a-f]{32}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


def normalize_pdf_review_guidance(value: str) -> str:
    """Return the bounded canonical user-guidance representation."""

    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    if not normalized:
        raise ValueError("PDF review guidance cannot be empty")
    if len(normalized) > 8000:
        raise ValueError("PDF review guidance exceeds 8000 characters")
    if any(ord(character) < 32 and character not in "\n\t" for character in normalized):
        raise ValueError("PDF review guidance contains a control character")
    return normalized


class PdfReviewPresetSnapshot(FrozenModel):
    schema_version: Literal["pdf-review-preset/1.0"] = "pdf-review-preset/1.0"
    preset_key: Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]
    preset_revision_id: str = Field(pattern=r"^reviewpresetrev_[0-9a-f]{32}$")
    display_name: Literal["N제", "주간지", "모의고사"]
    criteria: tuple[
        Annotated[
            str,
            Field(
                min_length=3,
                max_length=500,
                pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
            ),
        ],
        ...,
    ] = Field(min_length=1, max_length=32)
    preset_sha256: Sha256

    @model_validator(mode="after")
    def validate_preset_identity(self) -> PdfReviewPresetSnapshot:
        display_names = {
            "PROBLEM_SET": "N제",
            "WEEKLY_WORKBOOK": "주간지",
            "MOCK_EXAM": "모의고사",
        }
        if self.display_name != display_names[self.preset_key]:
            raise ValueError("PDF review preset display name differs from its key")
        if self.criteria != tuple(dict.fromkeys(self.criteria)):
            raise ValueError("PDF review preset criteria must be unique and ordered")
        value = self.model_dump(mode="json", exclude={"preset_sha256"})
        if content_sha256(value) != self.preset_sha256:
            raise ValueError("PDF review preset hash differs")
        return self


class PdfDocumentReviewRequest(FrozenModel):
    schema_version: Literal["pdf-document-review-request/1.0"] = "pdf-document-review-request/1.0"
    document: PdfReviewDocumentPointer
    preset: PdfReviewPresetSnapshot
    additional_guidance: str | None = Field(default=None, min_length=1, max_length=8000)
    additional_guidance_sha256: Sha256 | None = None
    locale: Literal["ko-KR"] = "ko-KR"
    request_sha256: Sha256

    @field_validator("additional_guidance")
    @classmethod
    def normalize_guidance(cls, value: str | None) -> str | None:
        return None if value is None else normalize_pdf_review_guidance(value)

    @model_validator(mode="after")
    def validate_request_hashes(self) -> PdfDocumentReviewRequest:
        expected_guidance_hash = (
            content_sha256(self.additional_guidance)
            if self.additional_guidance is not None
            else None
        )
        if self.additional_guidance_sha256 != expected_guidance_hash:
            raise ValueError("PDF review guidance hash differs")
        value = self.model_dump(mode="json", exclude={"request_sha256"})
        if content_sha256(value) != self.request_sha256:
            raise ValueError("PDF document review request hash differs")
        return self


class PdfDocumentReviewWorkerRequest(FrozenModel):
    request_name: Literal["PDF_DOCUMENT_REVIEW_REQUEST"] = "PDF_DOCUMENT_REVIEW_REQUEST"
    review_request: PdfDocumentReviewRequest


class PdfReviewRegion(FrozenModel):
    x_ppm: int = Field(ge=0, le=999999)
    y_ppm: int = Field(ge=0, le=999999)
    width_ppm: int = Field(ge=1, le=1000000)
    height_ppm: int = Field(ge=1, le=1000000)

    @model_validator(mode="after")
    def remain_inside_page(self) -> PdfReviewRegion:
        if self.x_ppm + self.width_ppm > 1_000_000:
            raise ValueError("PDF review region exceeds the page width")
        if self.y_ppm + self.height_ppm > 1_000_000:
            raise ValueError("PDF review region exceeds the page height")
        return self


class PdfReviewAnchor(FrozenModel):
    anchor_id: str = Field(pattern=r"^reviewanchor_[0-9a-f]{32}$")
    page_number: int = Field(ge=1, le=2000)
    page_image_sha256: Sha256
    region: PdfReviewRegion
    quote: str | None = Field(default=None, min_length=1, max_length=1000)
    quote_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_quote_hash(self) -> PdfReviewAnchor:
        expected = content_sha256(self.quote) if self.quote is not None else None
        if self.quote_sha256 != expected:
            raise ValueError("PDF review anchor quote hash differs")
        return self


PdfReviewAxis = Literal[
    "SCIENTIFIC_ACCURACY",
    "ANSWER_UNIQUENESS",
    "SOLUTION_CONSISTENCY",
    "CURRICULUM_SCOPE",
    "ORIGINALITY",
    "VISUAL_CONTENT",
    "EDITORIAL_CLARITY",
    "TYPOGRAPHY",
    "DOCUMENT_STRUCTURE",
    "ASSESSMENT_BALANCE",
]
PdfReviewCategory = Literal[
    "SCIENTIFIC_ACCURACY",
    "ANSWER_CORRECTNESS",
    "EXPLANATION_CONSISTENCY",
    "CURRICULUM_SCOPE",
    "ORIGINALITY",
    "VISUAL_CONTENT",
    "EDITORIAL_CLARITY",
    "TYPOGRAPHY",
    "STRUCTURE",
    "ASSESSMENT_BALANCE",
    "OTHER",
]
PdfReviewSeverity = Literal["BLOCKER", "HIGH", "MEDIUM", "LOW", "NOTE"]


class PdfReviewVerificationTarget(FrozenModel):
    target_id: str = Field(pattern=r"^reviewtarget_[0-9a-f]{32}$")
    axis: PdfReviewAxis
    page_numbers: tuple[int, ...] = Field(min_length=1, max_length=2000)
    anchors: tuple[PdfReviewAnchor, ...] = Field(max_length=16)
    status: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    conclusion: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_target_collections(self) -> PdfReviewVerificationTarget:
        if self.page_numbers != tuple(sorted(set(self.page_numbers))):
            raise ValueError("PDF review target page numbers must be sorted and unique")
        anchor_ids = tuple(anchor.anchor_id for anchor in self.anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("PDF review target anchors must be sorted and unique")
        if any(anchor.page_number not in self.page_numbers for anchor in self.anchors):
            raise ValueError("PDF review target anchor is outside its declared pages")
        return self


class PdfReviewCandidateFinding(FrozenModel):
    candidate_id: str = Field(pattern=r"^reviewcandidate_[0-9a-f]{32}$")
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    category: PdfReviewCategory
    severity: PdfReviewSeverity
    title: str = Field(min_length=1, max_length=160)
    anchors: tuple[PdfReviewAnchor, ...] = Field(min_length=1, max_length=8)
    disposition: Literal["CONFIRMED", "DEMOTED", "UNCERTAIN"]
    rationale: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_anchor_ids(self) -> PdfReviewCandidateFinding:
        anchor_ids = tuple(anchor.anchor_id for anchor in self.anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("PDF review candidate anchors must be sorted and unique")
        return self


class PdfReviewRecommendation(FrozenModel):
    operation: Literal["REPLACE", "INSERT", "DELETE", "MOVE", "REDRAW", "VERIFY", "NONE"]
    instruction: str = Field(min_length=1, max_length=4000)
    before_text: str | None = Field(default=None, max_length=2000)
    after_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_operation_payload(self) -> PdfReviewRecommendation:
        if self.operation == "REPLACE" and (self.before_text is None or self.after_text is None):
            raise ValueError("REPLACE recommendation requires before and after text")
        if self.operation == "DELETE" and self.before_text is None:
            raise ValueError("DELETE recommendation requires before text")
        if self.operation == "INSERT" and self.after_text is None:
            raise ValueError("INSERT recommendation requires after text")
        if self.operation in {"REDRAW", "VERIFY", "NONE", "MOVE"} and (
            self.before_text is not None or self.after_text is not None
        ):
            raise ValueError(f"{self.operation} recommendation cannot carry replacement text")
        return self


class PdfReviewFinding(FrozenModel):
    finding_id: str = Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")
    candidate_id: str = Field(pattern=r"^reviewcandidate_[0-9a-f]{32}$")
    ordinal: int = Field(ge=1, le=512)
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    category: PdfReviewCategory
    severity: PdfReviewSeverity
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    anchors: tuple[PdfReviewAnchor, ...] = Field(min_length=1, max_length=8)
    recommendation: PdfReviewRecommendation

    @model_validator(mode="after")
    def validate_anchor_ids(self) -> PdfReviewFinding:
        anchor_ids = tuple(anchor.anchor_id for anchor in self.anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("PDF review finding anchors must be sorted and unique")
        return self


class PdfDocumentReviewOutput(FrozenModel):
    review_request_sha256: Sha256
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    source_pdf_sha256: Sha256
    preset_key: Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]
    preset_revision_id: str = Field(pattern=r"^reviewpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    additional_guidance_sha256: Sha256 | None
    review_status: Literal["COMPLETE", "NEEDS_HUMAN_DECISION"]
    summary: str = Field(min_length=1, max_length=4000)
    verification_targets: tuple[PdfReviewVerificationTarget, ...] = Field(
        min_length=1, max_length=256
    )
    candidate_findings: tuple[PdfReviewCandidateFinding, ...] = Field(max_length=512)
    findings: tuple[PdfReviewFinding, ...] = Field(max_length=512)
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_relations(self) -> PdfDocumentReviewOutput:
        target_ids = tuple(target.target_id for target in self.verification_targets)
        if target_ids != tuple(sorted(set(target_ids))):
            raise ValueError("PDF review targets must be sorted and unique")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidate_findings)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("PDF review candidates must be sorted and unique")
        if tuple(finding.ordinal for finding in self.findings) != tuple(
            range(1, len(self.findings) + 1)
        ):
            raise ValueError("PDF review finding ordinals must be contiguous from one")
        finding_ids = tuple(finding.finding_id for finding in self.findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("PDF review finding IDs must be unique")
        confirmed = {
            candidate.candidate_id: candidate
            for candidate in self.candidate_findings
            if candidate.disposition == "CONFIRMED"
        }
        if tuple(finding.candidate_id for finding in self.findings) != tuple(sorted(confirmed)):
            raise ValueError("PDF review findings must exactly cover confirmed candidates")
        for finding in self.findings:
            candidate = confirmed[finding.candidate_id]
            if (
                finding.finding_code != candidate.finding_code
                or finding.category != candidate.category
                or finding.severity != candidate.severity
                or finding.title != candidate.title
                or finding.anchors != candidate.anchors
            ):
                raise ValueError("PDF review finding differs from its confirmed candidate")
        has_uncertain = any(
            candidate.disposition == "UNCERTAIN" for candidate in self.candidate_findings
        )
        expected_status = "NEEDS_HUMAN_DECISION" if has_uncertain else "COMPLETE"
        if self.review_status != expected_status:
            raise ValueError("PDF review status differs from candidate dispositions")
        return self


def validate_pdf_document_review_output_against_request(
    output: PdfDocumentReviewOutput,
    request: PdfDocumentReviewRequest,
) -> None:
    """Bind a worker result to the exact immutable request and rendered pages."""

    if (
        output.review_request_sha256 != request.request_sha256
        or output.document_id != request.document.document_id
        or output.document_revision_id != request.document.document_revision_id
        or output.source_pdf_sha256 != request.document.source_pdf.sha256
        or output.preset_key != request.preset.preset_key
        or output.preset_revision_id != request.preset.preset_revision_id
        or output.preset_sha256 != request.preset.preset_sha256
        or output.additional_guidance_sha256 != request.additional_guidance_sha256
    ):
        raise ValueError("PDF review result identity differs from its immutable request")
    page_hashes = {page.page_number: page.page_image.sha256 for page in request.document.pages}
    anchors = (
        anchor
        for collection in (
            tuple(anchor for target in output.verification_targets for anchor in target.anchors),
            tuple(
                anchor for candidate in output.candidate_findings for anchor in candidate.anchors
            ),
            tuple(anchor for finding in output.findings for anchor in finding.anchors),
        )
        for anchor in collection
    )
    for anchor in anchors:
        if page_hashes.get(anchor.page_number) != anchor.page_image_sha256:
            raise ValueError("PDF review anchor differs from its pinned page image")
