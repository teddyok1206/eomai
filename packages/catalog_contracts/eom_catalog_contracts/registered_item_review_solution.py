"""Immutable registered review references, not authorization or a full solution DAG."""

from __future__ import annotations

import json
from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_contracts.models import FrozenModel, Sha256

REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA = "registered-item-review-solution-evidence"
REGISTERED_ITEM_REVIEW_SOLUTION_REF = (
    "eom://schemas/knowledge/registered-item-review-solution-evidence/1.0"
)
MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES = 16 * 1024


class RegisteredItemReviewRoleReference(FrozenModel):
    """Original role result identity; the resolver must verify its successful occurrence."""

    model_config = ConfigDict(revalidate_instances="always")

    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    step_key: Literal["authoring", "review"]
    attempt: int = Field(strict=True, ge=1)
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    artifact: ArtifactMemberPointer

    @model_validator(mode="before")
    @classmethod
    def preserve_original_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_role_result(self) -> RegisteredItemReviewRoleReference:
        if (
            self.artifact.member_path != "result.json"
            or self.artifact.media_type != "application/json"
            or self.artifact.schema_ref
            not in {f"{self.step_key}-result@11.0", f"{self.step_key}-result@12.0"}
        ):
            raise ValueError("REGISTERED_ITEM_REVIEW_ROLE_REFERENCE_INVALID")
        return self


class RegisteredItemReviewSolutionEvidence(FrozenModel):
    """Pointer-only evidence; every consuming owner must reauthorize the exact source."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["registered-item-review-solution-evidence/1.0"]
    evidence_kind: Literal["REGISTERED_ITEM_REVIEW_SOLUTION"]
    source: ApprovedItemKnowledgeSourceV2
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    registration_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    registration_manifest: ArtifactMemberPointer
    item_content: ArtifactMemberPointer
    authoring: RegisteredItemReviewRoleReference
    review: RegisteredItemReviewRoleReference
    authoring_receipt_sha256: Sha256
    review_receipt_sha256: Sha256
    evidence_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def exact_wire_values(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA,
            MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES,
        )

    @model_validator(mode="after")
    def closed_source_and_role_pair(self) -> RegisteredItemReviewSolutionEvidence:
        source_member = self.source.artifact_member
        source_pointer = ArtifactMemberPointer(
            **{field: getattr(source_member, field) for field in ArtifactMemberPointer.model_fields}
        )
        steps = (
            self.registration_step_run_id,
            self.authoring.step_run_id,
            self.review.step_run_id,
        )
        members = (
            self.registration_manifest,
            self.item_content,
            self.authoring.artifact,
            self.review.artifact,
        )
        if (
            self.source.source_class != "APPROVED_ITEM"
            or source_pointer != self.item_content
            or self.authoring.step_key != "authoring"
            or self.review.step_key != "review"
            or self.authoring.artifact.schema_ref.rsplit("@", 1)[1]
            != self.review.artifact.schema_ref.rsplit("@", 1)[1]
            or len(set(steps)) != len(steps)
            or self.authoring.job_id == self.review.job_id
            or len({member.artifact_id for member in members}) != len(members)
            or len({member.artifact_revision_id for member in members}) != len(members)
            or self.authoring_receipt_sha256 == self.review_receipt_sha256
            or self.evidence_sha256 != registered_item_review_solution_evidence_sha256(self)
        ):
            raise ValueError("REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_INVALID")
        return self


def registered_item_review_solution_evidence_sha256(value: object) -> str:
    """Compute the self-excluding canonical digest; this does not authorize or validate."""
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_INVALID")
    payload = {key: item for key, item in document.items() if key != "evidence_sha256"}
    if len(canonical_json_bytes(payload)) > MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES:
        raise ValueError("REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_INVALID")
    return content_sha256(payload)


def registered_item_review_solution_evidence_bytes(
    value: RegisteredItemReviewSolutionEvidence,
) -> bytes:
    validated = RegisteredItemReviewSolutionEvidence.model_validate(value)
    return canonical_json_bytes(validated)


def parse_registered_item_review_solution_evidence(
    raw: bytes,
) -> RegisteredItemReviewSolutionEvidence:
    if not isinstance(raw, bytes) or len(raw) > MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES:
        raise ValueError("REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_INVALID")
    try:
        document = json.loads(raw)
        if canonical_json_bytes(document) != raw:
            raise ValueError("noncanonical registered review evidence")
    except (ValueError, TypeError, RecursionError):
        raise ValueError("REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_INVALID") from None
    return RegisteredItemReviewSolutionEvidence.model_validate(document)
