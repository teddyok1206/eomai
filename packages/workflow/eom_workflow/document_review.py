"""Immutable value contracts for page-anchored PDF document review."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from eom_catalog_contracts import (
    DocumentReviewEvidencePlan,
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
        if self.document.page_count > 32:
            raise ValueError("PDF document review V1 supports at most 32 pages")
        page_image_bytes = tuple(page.page_image.content_length for page in self.document.pages)
        if any(byte_count > 16 * 1024 * 1024 for byte_count in page_image_bytes):
            raise ValueError("PDF document review page image exceeds 16 MiB")
        if sum(page_image_bytes) > 128 * 1024 * 1024:
            raise ValueError("PDF document review page images exceed 128 MiB")
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
DocumentReviewRole = Literal["QUESTION", "SOLUTION"]


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


class PairedReviewDocument(FrozenModel):
    """One role-addressable immutable source in a paired review."""

    role: DocumentReviewRole
    document: PdfReviewDocumentPointer


class PairedDocumentReviewRequest(FrozenModel):
    """Exact question and solution document revisions reviewed as one aggregate."""

    schema_version: Literal["paired-document-review-request/1.0"] = (
        "paired-document-review-request/1.0"
    )
    documents: tuple[PairedReviewDocument, PairedReviewDocument] = Field(min_length=2, max_length=2)
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
    def validate_pair_and_hashes(self) -> PairedDocumentReviewRequest:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired document review requires QUESTION then SOLUTION")
        identities = tuple(
            (value.document.document_id, value.document.document_revision_id)
            for value in self.documents
        )
        if len(identities) != len(set(identities)):
            raise ValueError("paired document review sources must be distinct revisions")
        page_image_bytes = tuple(
            page.page_image.content_length
            for value in self.documents
            for page in value.document.pages
        )
        if any(value.document.page_count > 64 for value in self.documents):
            raise ValueError("paired document review supports at most 64 pages per source")
        if any(byte_count > 16 * 1024 * 1024 for byte_count in page_image_bytes):
            raise ValueError("paired document review page image exceeds 16 MiB")
        if sum(page_image_bytes) > 256 * 1024 * 1024:
            raise ValueError("paired document review page images exceed 256 MiB")
        expected_guidance_hash = (
            content_sha256(self.additional_guidance)
            if self.additional_guidance is not None
            else None
        )
        if self.additional_guidance_sha256 != expected_guidance_hash:
            raise ValueError("paired document review guidance hash differs")
        value = self.model_dump(mode="json", exclude={"request_sha256"})
        if content_sha256(value) != self.request_sha256:
            raise ValueError("paired document review request hash differs")
        return self


class PairedDocumentReviewWorkerRequest(FrozenModel):
    request_name: Literal["PAIRED_DOCUMENT_REVIEW_REQUEST"] = "PAIRED_DOCUMENT_REVIEW_REQUEST"
    review_request: PairedDocumentReviewRequest


class PairedDocumentReviewRequestV2(PairedDocumentReviewRequest):
    """Paired request bound to one exact Catalog-produced Graph evidence plan."""

    schema_version: Literal["paired-document-review-request/2.0"] = (
        "paired-document-review-request/2.0"  # type: ignore[assignment]
    )
    evidence_plan: DocumentReviewEvidencePlan

    @model_validator(mode="after")
    def exact_evidence_sources(self) -> PairedDocumentReviewRequestV2:
        expected = tuple(
            (
                value.role,
                value.document.document_id,
                value.document.document_revision_id,
                value.document.source_pdf.sha256,
            )
            for value in self.documents
        )
        actual = tuple(
            (
                value.role,
                value.document_id,
                value.document_revision_id,
                value.source_pdf_sha256,
            )
            for value in self.evidence_plan.documents
        )
        if actual != expected:
            raise ValueError("paired review Evidence Plan sources differ from the request")
        return self


class PairedDocumentReviewWorkerRequestV2(FrozenModel):
    request_name: Literal["PAIRED_DOCUMENT_REVIEW_REQUEST"] = "PAIRED_DOCUMENT_REVIEW_REQUEST"
    review_request: PairedDocumentReviewRequestV2


class PairedReviewAnchor(PdfReviewAnchor):
    document_role: DocumentReviewRole


class PairedReviewPageRef(FrozenModel):
    document_role: DocumentReviewRole
    page_number: int = Field(ge=1, le=2000)


class PairedReviewVerificationTarget(FrozenModel):
    target_id: str = Field(pattern=r"^reviewtarget_[0-9a-f]{32}$")
    axis: PdfReviewAxis
    page_refs: tuple[PairedReviewPageRef, ...] = Field(min_length=1, max_length=4000)
    anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=16)
    status: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    conclusion: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_target_collections(self) -> PairedReviewVerificationTarget:
        page_refs = tuple((value.document_role, value.page_number) for value in self.page_refs)
        if page_refs != tuple(sorted(set(page_refs))):
            raise ValueError("paired review target pages must be sorted and unique")
        anchor_ids = tuple(anchor.anchor_id for anchor in self.anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("paired review target anchors must be sorted and unique")
        if any(
            (anchor.document_role, anchor.page_number) not in page_refs for anchor in self.anchors
        ):
            raise ValueError("paired review target anchor is outside its declared pages")
        return self


class PairedReviewCandidateFinding(PdfReviewCandidateFinding):
    anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=8)


class PairedReviewFinding(PdfReviewFinding):
    anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=8)


class PairedReviewDocumentIdentity(FrozenModel):
    role: DocumentReviewRole
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    source_pdf_sha256: Sha256


class PairedReviewCrossDocumentCheck(FrozenModel):
    check_id: str = Field(pattern=r"^reviewcross_[0-9a-f]{32}$")
    question_anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=16)
    solution_anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=16)
    status: Literal["MATCHED", "MISMATCH", "MISSING", "INSUFFICIENT"]
    conclusion: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def require_role_exact_anchors(self) -> PairedReviewCrossDocumentCheck:
        if any(anchor.document_role != "QUESTION" for anchor in self.question_anchors):
            raise ValueError("question cross-check anchors must address the question document")
        if any(anchor.document_role != "SOLUTION" for anchor in self.solution_anchors):
            raise ValueError("solution cross-check anchors must address the solution document")
        if self.status == "MISSING":
            if self.solution_anchors:
                raise ValueError("missing solution cross-check must not invent solution anchors")
        elif not self.solution_anchors:
            raise ValueError("non-missing cross-check requires a solution anchor")
        for anchors in (self.question_anchors, self.solution_anchors):
            identities = tuple(anchor.anchor_id for anchor in anchors)
            if identities != tuple(sorted(set(identities))):
                raise ValueError("cross-document anchors must be sorted and unique")
        return self


class PairedReviewCrossDocumentCheckV2(PairedReviewCrossDocumentCheck):
    """Cross-document check bound to one exact exhaustive item record."""

    item_key: str = Field(pattern=r"^reviewitem_[0-9a-f]{32}$")


DocumentReviewEvidenceApplication = Literal[
    "CONCEPT_VERIFICATION",
    "SOLUTION_VERIFICATION",
    "ORIGINALITY_COMPARISON",
    "AVOID_COPY_CHECK",
]


class PairedReviewSolveStepCheck(FrozenModel):
    """One ordered, externally auditable step in the independent solution."""

    ordinal: int = Field(ge=1, le=64)
    status: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    claim_summary: str = Field(min_length=1, max_length=1000)
    verification_summary: str = Field(min_length=1, max_length=4000)
    question_anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def exact_question_anchors(self) -> PairedReviewSolveStepCheck:
        if any(value.document_role != "QUESTION" for value in self.question_anchors):
            raise ValueError("solve-step anchors must address the question document")
        anchor_ids = tuple(value.anchor_id for value in self.question_anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("solve-step anchors must be sorted and unique")
        return self


class PairedReviewUnitCheck(FrozenModel):
    """One explicit unit/dimension decision, including a justified non-applicable case."""

    check_id: str = Field(pattern=r"^reviewunit_[0-9a-f]{32}$")
    quantity: str = Field(min_length=1, max_length=160)
    value_expression: str | None = Field(default=None, min_length=1, max_length=500)
    expected_unit: str | None = Field(default=None, min_length=1, max_length=160)
    observed_unit: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["VERIFIED", "FAILED", "INSUFFICIENT", "NOT_APPLICABLE"]
    anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=8)
    conclusion: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def exact_applicability_and_anchors(self) -> PairedReviewUnitCheck:
        not_applicable = self.status == "NOT_APPLICABLE"
        if not_applicable != (
            self.value_expression is None
            and self.expected_unit is None
            and self.observed_unit is None
        ):
            raise ValueError("unit-check applicability differs from its unit payload")
        anchor_ids = tuple(value.anchor_id for value in self.anchors)
        if anchor_ids != tuple(sorted(set(anchor_ids))):
            raise ValueError("unit-check anchors must be sorted and unique")
        return self


class PairedReviewChoiceCheck(FrozenModel):
    """One ordered answer-choice decision grounded in the question and solution."""

    ordinal: int = Field(ge=1, le=10)
    choice_key: str = Field(min_length=1, max_length=32)
    verdict: Literal["CORRECT", "INCORRECT", "AMBIGUOUS", "INSUFFICIENT"]
    question_anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=8)
    solution_anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=8)
    rationale: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def exact_roles_and_anchors(self) -> PairedReviewChoiceCheck:
        if any(value.document_role != "QUESTION" for value in self.question_anchors):
            raise ValueError("choice question anchors must address the question document")
        if any(value.document_role != "SOLUTION" for value in self.solution_anchors):
            raise ValueError("choice solution anchors must address the solution document")
        for anchors in (self.question_anchors, self.solution_anchors):
            anchor_ids = tuple(value.anchor_id for value in anchors)
            if anchor_ids != tuple(sorted(set(anchor_ids))):
                raise ValueError("choice anchors must be sorted and unique")
        return self


class PairedReviewExplanationStepCheck(FrozenModel):
    """One ordered official-explanation step checked against the independently solved item."""

    ordinal: int = Field(ge=1, le=64)
    status: Literal["VERIFIED", "FAILED", "MISSING", "INSUFFICIENT"]
    claim_summary: str = Field(min_length=1, max_length=1000)
    verification_summary: str = Field(min_length=1, max_length=4000)
    question_anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=8)
    solution_anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def exact_roles_and_presence(self) -> PairedReviewExplanationStepCheck:
        if any(value.document_role != "QUESTION" for value in self.question_anchors):
            raise ValueError("explanation question anchors must address the question document")
        if any(value.document_role != "SOLUTION" for value in self.solution_anchors):
            raise ValueError("explanation solution anchors must address the solution document")
        if (self.status == "MISSING") != (not self.solution_anchors):
            raise ValueError("explanation missing status differs from its solution anchors")
        for anchors in (self.question_anchors, self.solution_anchors):
            anchor_ids = tuple(value.anchor_id for value in anchors)
            if anchor_ids != tuple(sorted(set(anchor_ids))):
                raise ValueError("explanation anchors must be sorted and unique")
        return self


class PairedReviewItemCheck(FrozenModel):
    """Auditable per-question solve, answer, unit, choice, explanation, and evidence record."""

    item_key: str = Field(pattern=r"^reviewitem_[0-9a-f]{32}$")
    ordinal: int = Field(ge=1, le=256)
    question_label: str = Field(min_length=1, max_length=64)
    response_format: Literal["MULTIPLE_CHOICE", "STATEMENT_COMBINATION", "SHORT_ANSWER", "OTHER"]
    question_anchors: tuple[PairedReviewAnchor, ...] = Field(min_length=1, max_length=16)
    solution_anchors: tuple[PairedReviewAnchor, ...] = Field(max_length=16)
    solve_summary: str = Field(min_length=1, max_length=4000)
    solve_steps: tuple[PairedReviewSolveStepCheck, ...] = Field(min_length=1, max_length=64)
    final_answer: str = Field(min_length=1, max_length=500)
    answer_status: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    condition_sufficiency: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    unit_checks: tuple[PairedReviewUnitCheck, ...] = Field(min_length=1, max_length=64)
    choice_checks: tuple[PairedReviewChoiceCheck, ...] = Field(max_length=10)
    explanation_steps: tuple[PairedReviewExplanationStepCheck, ...] = Field(
        min_length=1, max_length=64
    )
    evidence_status: Literal["SUPPORTED", "INSUFFICIENT"]
    evidence_citation_ids: tuple[
        Annotated[str, Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")], ...
    ] = Field(max_length=32)
    conclusion: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def exhaustive_item_relations(self) -> PairedReviewItemCheck:
        if any(value.document_role != "QUESTION" for value in self.question_anchors):
            raise ValueError("item question anchors must address the question document")
        if any(value.document_role != "SOLUTION" for value in self.solution_anchors):
            raise ValueError("item solution anchors must address the solution document")
        for anchors in (self.question_anchors, self.solution_anchors):
            anchor_ids = tuple(value.anchor_id for value in anchors)
            if anchor_ids != tuple(sorted(set(anchor_ids))):
                raise ValueError("item anchors must be sorted and unique")
        solve_ordinals = tuple(value.ordinal for value in self.solve_steps)
        if solve_ordinals != tuple(range(1, len(self.solve_steps) + 1)):
            raise ValueError("solve steps must be contiguous from one")
        unit_ids = tuple(value.check_id for value in self.unit_checks)
        if unit_ids != tuple(sorted(set(unit_ids))):
            raise ValueError("item unit checks must be sorted and unique")
        choice_ordinals = tuple(value.ordinal for value in self.choice_checks)
        choice_keys = tuple(value.choice_key for value in self.choice_checks)
        choice_bearing = self.response_format in {
            "MULTIPLE_CHOICE",
            "STATEMENT_COMBINATION",
        }
        if choice_bearing:
            if (
                len(self.choice_checks) < 2
                or choice_ordinals != tuple(range(1, len(self.choice_checks) + 1))
                or len(choice_keys) != len(set(choice_keys))
                or sum(value.verdict == "CORRECT" for value in self.choice_checks) != 1
            ):
                raise ValueError(
                    "choice-bearing item requires ordered unique choices and one answer"
                )
        elif self.choice_checks:
            raise ValueError("non-choice item cannot carry choice checks")
        explanation_ordinals = tuple(value.ordinal for value in self.explanation_steps)
        if explanation_ordinals != tuple(range(1, len(self.explanation_steps) + 1)):
            raise ValueError("explanation steps must be contiguous from one")
        citation_ids = self.evidence_citation_ids
        if citation_ids != tuple(sorted(set(citation_ids))):
            raise ValueError("item evidence citation IDs must be sorted and unique")
        if (self.evidence_status == "SUPPORTED") != bool(citation_ids):
            raise ValueError("item evidence status differs from its citation IDs")
        return self


class DocumentReviewEvidenceCitation(FrozenModel):
    """One manifest-visible citation applied to scalar leaves in item-review output."""

    evidence_id: str = Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")
    anchor_ids: tuple[Annotated[str, Field(pattern=r"^anchor_[a-z0-9][a-z0-9_-]{0,63}$")], ...] = (
        Field(min_length=1, max_length=32)
    )
    application: DocumentReviewEvidenceApplication
    item_keys: tuple[Annotated[str, Field(pattern=r"^reviewitem_[0-9a-f]{32}$")], ...] = Field(
        min_length=1, max_length=256
    )
    review_json_paths: tuple[str, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_citation(self) -> DocumentReviewEvidenceCitation:
        for values, label in (
            (self.anchor_ids, "anchor"),
            (self.item_keys, "item"),
            (self.review_json_paths, "review path"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(
                    f"document-review evidence {label} values must be sorted and unique"
                )
        for pointer in self.review_json_paths:
            if not pointer.startswith("/") or pointer == "/" or len(pointer) > 512:
                raise ValueError("document-review evidence path is not a bounded JSON Pointer")
            for token in pointer[1:].split("/"):
                if not token or re.search(r"~(?![01])", token):
                    raise ValueError("document-review evidence path is not RFC 6901 canonical")
        return self


class DocumentReviewEvidenceUsage(FrozenModel):
    """Exact Graph/Evidence identity and the reviewer's bounded citations."""

    evidence_bundle_id: str = Field(pattern=r"^evidence_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    context_sha256: Sha256
    citations: tuple[DocumentReviewEvidenceCitation, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_citations(self) -> DocumentReviewEvidenceUsage:
        evidence_ids = tuple(value.evidence_id for value in self.citations)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("document-review evidence citations must have sorted unique IDs")
        return self


class PairedDocumentReviewOutput(FrozenModel):
    review_request_sha256: Sha256
    documents: tuple[PairedReviewDocumentIdentity, PairedReviewDocumentIdentity] = Field(
        min_length=2, max_length=2
    )
    preset_key: Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]
    preset_revision_id: str = Field(pattern=r"^reviewpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    additional_guidance_sha256: Sha256 | None
    review_status: Literal["COMPLETE", "NEEDS_HUMAN_DECISION"]
    summary: str = Field(min_length=1, max_length=4000)
    verification_targets: tuple[PairedReviewVerificationTarget, ...] = Field(
        min_length=1, max_length=256
    )
    candidate_findings: tuple[PairedReviewCandidateFinding, ...] = Field(max_length=512)
    findings: tuple[PairedReviewFinding, ...] = Field(max_length=512)
    cross_document_checks: tuple[PairedReviewCrossDocumentCheck, ...] = Field(
        min_length=1, max_length=512
    )
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_relations(self) -> PairedDocumentReviewOutput:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review output requires QUESTION then SOLUTION")
        target_ids = tuple(target.target_id for target in self.verification_targets)
        if target_ids != tuple(sorted(set(target_ids))):
            raise ValueError("paired review targets must be sorted and unique")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidate_findings)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("paired review candidates must be sorted and unique")
        if tuple(finding.ordinal for finding in self.findings) != tuple(
            range(1, len(self.findings) + 1)
        ):
            raise ValueError("paired review finding ordinals must be contiguous from one")
        finding_ids = tuple(finding.finding_id for finding in self.findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("paired review finding IDs must be unique")
        confirmed = {
            candidate.candidate_id: candidate
            for candidate in self.candidate_findings
            if candidate.disposition == "CONFIRMED"
        }
        if tuple(finding.candidate_id for finding in self.findings) != tuple(sorted(confirmed)):
            raise ValueError("paired review findings must exactly cover confirmed candidates")
        for finding in self.findings:
            candidate = confirmed[finding.candidate_id]
            if (
                finding.finding_code != candidate.finding_code
                or finding.category != candidate.category
                or finding.severity != candidate.severity
                or finding.title != candidate.title
                or finding.anchors != candidate.anchors
            ):
                raise ValueError("paired review finding differs from its confirmed candidate")
        check_ids = tuple(value.check_id for value in self.cross_document_checks)
        if check_ids != tuple(sorted(set(check_ids))):
            raise ValueError("cross-document checks must be sorted and unique")
        has_uncertain = any(
            candidate.disposition == "UNCERTAIN" for candidate in self.candidate_findings
        ) or any(check.status == "INSUFFICIENT" for check in self.cross_document_checks)
        expected_status = "NEEDS_HUMAN_DECISION" if has_uncertain else "COMPLETE"
        if self.review_status != expected_status:
            raise ValueError("paired review status differs from its uncertain evidence")
        return self


class PairedDocumentReviewOutputV3(PairedDocumentReviewOutput):
    """Exhaustive paired review with exact page, item, and Graph evidence coverage."""

    page_coverage: tuple[PairedReviewPageRef, ...] = Field(min_length=2, max_length=4000)
    item_reviews: tuple[PairedReviewItemCheck, ...] = Field(min_length=1, max_length=256)
    cross_document_checks: tuple[PairedReviewCrossDocumentCheckV2, ...] = Field(
        min_length=1, max_length=512
    )
    evidence_usage: DocumentReviewEvidenceUsage

    @model_validator(mode="after")
    def validate_review_relations(self) -> PairedDocumentReviewOutputV3:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review output requires QUESTION then SOLUTION")
        expected_axes = {
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
        }
        target_ids = tuple(value.target_id for value in self.verification_targets)
        target_axes = tuple(value.axis for value in self.verification_targets)
        if (
            target_ids != tuple(sorted(set(target_ids)))
            or len(target_axes) != len(expected_axes)
            or set(target_axes) != expected_axes
        ):
            raise ValueError(
                "exhaustive paired review requires each verification axis exactly once"
            )
        page_keys = tuple((value.document_role, value.page_number) for value in self.page_coverage)
        if page_keys != tuple(sorted(set(page_keys))):
            raise ValueError("paired review page coverage must be sorted and unique")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidate_findings)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("paired review candidates must be sorted and unique")
        if tuple(finding.ordinal for finding in self.findings) != tuple(
            range(1, len(self.findings) + 1)
        ):
            raise ValueError("paired review finding ordinals must be contiguous from one")
        if len({finding.finding_id for finding in self.findings}) != len(self.findings):
            raise ValueError("paired review finding IDs must be unique")
        confirmed = {
            candidate.candidate_id: candidate
            for candidate in self.candidate_findings
            if candidate.disposition == "CONFIRMED"
        }
        if tuple(finding.candidate_id for finding in self.findings) != tuple(sorted(confirmed)):
            raise ValueError("paired review findings must exactly cover confirmed candidates")
        for finding in self.findings:
            candidate = confirmed[finding.candidate_id]
            if (
                finding.finding_code != candidate.finding_code
                or finding.category != candidate.category
                or finding.severity != candidate.severity
                or finding.title != candidate.title
                or finding.anchors != candidate.anchors
            ):
                raise ValueError("paired review finding differs from its confirmed candidate")

        item_keys = tuple(value.item_key for value in self.item_reviews)
        if (
            tuple(value.ordinal for value in self.item_reviews)
            != tuple(range(1, len(self.item_reviews) + 1))
            or len(item_keys) != len(set(item_keys))
            or len({value.question_label for value in self.item_reviews}) != len(self.item_reviews)
        ):
            raise ValueError("paired review items require contiguous order and unique identities")
        cross_ids = tuple(value.check_id for value in self.cross_document_checks)
        cross_item_keys = tuple(value.item_key for value in self.cross_document_checks)
        if (
            cross_ids != tuple(sorted(set(cross_ids)))
            or len(cross_item_keys) != len(set(cross_item_keys))
            or set(cross_item_keys) != set(item_keys)
        ):
            raise ValueError("cross-document checks must cover every item exactly once")

        citations = {value.evidence_id: value for value in self.evidence_usage.citations}
        declared_citations = {
            evidence_id for item in self.item_reviews for evidence_id in item.evidence_citation_ids
        }
        if declared_citations != set(citations):
            raise ValueError("item evidence IDs must exactly cover the global citation set")
        item_indexes = {value.item_key: index for index, value in enumerate(self.item_reviews)}
        applications_by_item: dict[str, set[str]] = {value: set() for value in item_keys}
        application_fields = {
            "CONCEPT_VERIFICATION": {
                "solve_summary",
                "solve_steps",
                "unit_checks",
                "choice_checks",
                "conclusion",
            },
            "SOLUTION_VERIFICATION": {
                "final_answer",
                "answer_status",
                "explanation_steps",
                "conclusion",
            },
            "ORIGINALITY_COMPARISON": {"conclusion"},
            "AVOID_COPY_CHECK": {"conclusion"},
        }
        for citation in citations.values():
            if not set(citation.item_keys).issubset(item_indexes):
                raise ValueError("evidence citation references an unknown review item")
            for item_key in citation.item_keys:
                applications_by_item[item_key].add(citation.application)
            for pointer in citation.review_json_paths:
                tokens = pointer[1:].split("/")
                if (
                    len(tokens) < 3
                    or tokens[0] != "item_reviews"
                    or not tokens[1].isdigit()
                    or int(tokens[1]) >= len(self.item_reviews)
                    or self.item_reviews[int(tokens[1])].item_key not in citation.item_keys
                    or tokens[2] not in application_fields[citation.application]
                ):
                    raise ValueError(
                        "evidence path is not bound to its declared review item application"
                    )
        for item in self.item_reviews:
            if item.evidence_status == "SUPPORTED":
                applications = applications_by_item[item.item_key]
                if not {
                    "CONCEPT_VERIFICATION",
                    "SOLUTION_VERIFICATION",
                }.issubset(applications) or not applications.intersection(
                    {"ORIGINALITY_COMPARISON", "AVOID_COPY_CHECK"}
                ):
                    raise ValueError(
                        "supported item needs concept, solution, and originality evidence"
                    )

        has_uncertain = any(
            candidate.disposition == "UNCERTAIN" for candidate in self.candidate_findings
        )
        has_nonverified_target = any(
            target.status != "VERIFIED" for target in self.verification_targets
        )
        has_cross_problem = any(check.status != "MATCHED" for check in self.cross_document_checks)
        has_item_problem = any(
            item.answer_status != "VERIFIED"
            or item.condition_sufficiency != "VERIFIED"
            or item.evidence_status != "SUPPORTED"
            or any(check.status != "VERIFIED" for check in item.solve_steps)
            or any(check.status not in {"VERIFIED", "NOT_APPLICABLE"} for check in item.unit_checks)
            or any(check.verdict in {"AMBIGUOUS", "INSUFFICIENT"} for check in item.choice_checks)
            or any(check.status != "VERIFIED" for check in item.explanation_steps)
            for item in self.item_reviews
        )
        expected_status = (
            "NEEDS_HUMAN_DECISION"
            if has_uncertain or has_nonverified_target or has_cross_problem or has_item_problem
            else "COMPLETE"
        )
        if self.review_status != expected_status:
            raise ValueError("paired review status differs from exhaustive verification evidence")
        return self


def validate_paired_document_review_output_against_request(
    output: PairedDocumentReviewOutput,
    request: PairedDocumentReviewRequest,
) -> None:
    """Bind a paired result to both exact sources and every role-addressed page."""

    expected_documents = tuple(
        PairedReviewDocumentIdentity(
            role=value.role,
            document_id=value.document.document_id,
            document_revision_id=value.document.document_revision_id,
            source_pdf_sha256=value.document.source_pdf.sha256,
        )
        for value in request.documents
    )
    if (
        output.review_request_sha256 != request.request_sha256
        or output.documents != expected_documents
        or output.preset_key != request.preset.preset_key
        or output.preset_revision_id != request.preset.preset_revision_id
        or output.preset_sha256 != request.preset.preset_sha256
        or output.additional_guidance_sha256 != request.additional_guidance_sha256
    ):
        raise ValueError("paired review result identity differs from its immutable request")
    page_hashes = {
        (value.role, page.page_number): page.page_image.sha256
        for value in request.documents
        for page in value.document.pages
    }
    anchors = (
        anchor
        for collection in (
            tuple(anchor for target in output.verification_targets for anchor in target.anchors),
            tuple(
                anchor for candidate in output.candidate_findings for anchor in candidate.anchors
            ),
            tuple(anchor for finding in output.findings for anchor in finding.anchors),
            tuple(
                anchor
                for check in output.cross_document_checks
                for anchor in (*check.question_anchors, *check.solution_anchors)
            ),
        )
        for anchor in collection
    )
    for anchor in anchors:
        if page_hashes.get((anchor.document_role, anchor.page_number)) != (
            anchor.page_image_sha256
        ):
            raise ValueError("paired review anchor differs from its pinned page image")


def validate_paired_document_review_v3_output_against_request(
    output: PairedDocumentReviewOutputV3,
    request: PairedDocumentReviewRequest,
) -> None:
    """Bind exhaustive page/item anchors to both immutable request documents."""

    validate_paired_document_review_output_against_request(output, request)
    expected_pages = tuple(
        sorted(
            (value.role, page.page_number)
            for value in request.documents
            for page in value.document.pages
        )
    )
    actual_pages = tuple((value.document_role, value.page_number) for value in output.page_coverage)
    if actual_pages != expected_pages:
        raise ValueError("paired review page coverage differs from the exact request pages")
    page_hashes = {
        (value.role, page.page_number): page.page_image.sha256
        for value in request.documents
        for page in value.document.pages
    }
    anchors = (
        anchor
        for item in output.item_reviews
        for anchor in (
            *item.question_anchors,
            *item.solution_anchors,
            *(anchor for step in item.solve_steps for anchor in step.question_anchors),
            *(anchor for check in item.unit_checks for anchor in check.anchors),
            *(
                anchor
                for check in item.choice_checks
                for anchor in (*check.question_anchors, *check.solution_anchors)
            ),
            *(
                anchor
                for step in item.explanation_steps
                for anchor in (*step.question_anchors, *step.solution_anchors)
            ),
        )
    )
    for anchor in anchors:
        if page_hashes.get((anchor.document_role, anchor.page_number)) != (
            anchor.page_image_sha256
        ):
            raise ValueError("paired review item anchor differs from its pinned page image")
