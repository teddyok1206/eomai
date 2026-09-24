"""Immutable Graph evidence contracts for paired document review."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.document_review import PdfReviewDocumentPointer
from eom_catalog_contracts.knowledge import (
    EducationalRetrievalRequirement,
    EvidenceBudget,
    EvidenceBundlePublicationResultV5,
    KnowledgeSourceClass,
    PermissionKeyValue,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256


class DocumentReviewEvidenceSource(FrozenModel):
    """One role-addressed immutable PDF used for deterministic evidence planning."""

    role: Literal["QUESTION", "SOLUTION"]
    document: PdfReviewDocumentPointer


class DocumentReviewEvidenceSourceIdentity(FrozenModel):
    """Compact source identity retained by the self-hashed evidence plan."""

    role: Literal["QUESTION", "SOLUTION"]
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    source_pdf_sha256: Sha256


class DocumentReviewEvidenceExtractor(FrozenModel):
    extractor_key: Literal["poppler-pdftotext"] = "poppler-pdftotext"
    executable_sha256: Sha256
    max_text_bytes: Literal[8388608] = 8388608
    max_terms: Literal[512] = 512


class DocumentReviewEvidencePlan(FrozenModel):
    """Catalog-produced exact lexical scope and published Evidence Bundle."""

    schema_version: Literal["document-review-evidence-plan/1.0"] = (
        "document-review-evidence-plan/1.0"
    )
    documents: tuple[
        DocumentReviewEvidenceSourceIdentity,
        DocumentReviewEvidenceSourceIdentity,
    ] = Field(min_length=2, max_length=2)
    term_set_sha256: Sha256
    topic_keys: tuple[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")], ...] = Field(
        min_length=1, max_length=20
    )
    extractor: DocumentReviewEvidenceExtractor
    requirement: EducationalRetrievalRequirement
    publication: EvidenceBundlePublicationResultV5
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_plan(self) -> DocumentReviewEvidencePlan:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("document review evidence plan requires QUESTION then SOLUTION")
        identities = tuple(
            (value.document_id, value.document_revision_id) for value in self.documents
        )
        if len(set(identities)) != 2:
            raise ValueError("document review evidence sources must be distinct")
        if self.topic_keys != tuple(sorted(set(self.topic_keys))):
            raise ValueError("document review evidence topic keys must be sorted and unique")
        if (
            self.requirement.query_kind != "ITEM_PREPARATION"
            or self.requirement.curriculum_root_key is not None
            or self.requirement.topic_keys != self.topic_keys
            or self.requirement.required_item_elements
            != ("choice", "equation", "image", "paragraph", "statement_set", "table")
            or self.publication.graph_snapshot.graph_snapshot_revision_id == ""
        ):
            raise ValueError("document review evidence plan differs from its closed scope")
        if content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"})) != (
            self.plan_sha256
        ):
            raise ValueError("document review evidence plan hash differs")
        return self


class CreateDocumentReviewEvidenceCommand(FrozenModel):
    """Private Catalog command; Catalog selects snapshot and document-derived topics."""

    schema_version: Literal["document-review-evidence-request/1.0"] = (
        "document-review-evidence-request/1.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_EVIDENCE"] = "CREATE_DOCUMENT_REVIEW_EVIDENCE"
    documents: tuple[DocumentReviewEvidenceSource, DocumentReviewEvidenceSource] = Field(
        min_length=2,
        max_length=2,
    )
    corpus_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    source_classes: tuple[KnowledgeSourceClass, ...] = Field(min_length=1, max_length=5)
    evidence_budget: EvidenceBudget
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requester_role: Literal["ADMIN", "EDITOR", "REVIEWER"]
    requester_permission_keys: tuple[PermissionKeyValue, ...] = Field(
        min_length=1,
        max_length=128,
    )
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")
    submission_sha256: Sha256

    @model_validator(mode="after")
    def closed_sorted_and_hashed(self) -> CreateDocumentReviewEvidenceCommand:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("document review evidence command requires QUESTION then SOLUTION")
        identities = tuple(
            (value.document.document_id, value.document.document_revision_id)
            for value in self.documents
        )
        if len(set(identities)) != 2:
            raise ValueError("document review evidence command sources must be distinct")
        for values, label in (
            (self.source_classes, "source classes"),
            (self.requester_permission_keys, "permission keys"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"document review evidence {label} must be sorted and unique")
        body = self.model_dump(mode="json", exclude={"idempotency_key", "submission_sha256"})
        if content_sha256(body) != self.submission_sha256:
            raise ValueError("document review evidence command hash differs")
        return self


class DocumentReviewEvidenceResponse(FrozenModel):
    """Bounded Catalog response carrying either one exact plan or one stable error."""

    schema_version: Literal["document-review-evidence-response/1.0"] = (
        "document-review-evidence-response/1.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_EVIDENCE"] = "CREATE_DOCUMENT_REVIEW_EVIDENCE"
    status: Literal["OK", "ERROR"]
    plan: DocumentReviewEvidencePlan | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exactly_one_variant(self) -> DocumentReviewEvidenceResponse:
        if self.status == "OK" and self.plan is not None and self.error_code is None:
            return self
        if self.status == "ERROR" and self.plan is None and self.error_code is not None:
            return self
        raise ValueError("document review evidence response variant is incomplete")
