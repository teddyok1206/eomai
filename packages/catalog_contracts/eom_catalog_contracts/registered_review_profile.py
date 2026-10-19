"""Distinct, bounded registered-review comparisons; never accepted V10 reasoning."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, field_validator, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)

REGISTERED_REVIEW_PROFILE_SCHEMA = "item-inference-transfer-v2"
REGISTERED_REVIEW_PROFILE_REF = "eom://schemas/knowledge/item-inference-transfer/2.0"
REGISTERED_REVIEW_EXTRACTOR_VERSION = "registered-item-review-comparison/1.0"
MAX_REGISTERED_REVIEW_PROFILE_BYTES = 512 * 1024
REVIEW_REASONING_LIMITATION = (
    "원 독립 검토의 공개 결론만 재사용하며 전체 풀이 DAG나 핵심 착상을 확정하지 않습니다."
)
REVIEW_PIXEL_LIMITATION = "이 결정적 텍스트 투영은 원 PDF/PNG 이미지의 픽셀을 검사하지 않았습니다."

ReviewJsonPointer = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
    ),
]
ReviewClaimKind = Literal[
    "ANSWER_SUMMARY", "ANSWER_CLAIM", "CHOICE_DIAGNOSTIC", "STATEMENT_DIAGNOSTIC"
]
ReviewClaimVerdict = Literal["MATCH", "MISMATCH", "CORRECT", "DISTRACTOR", "TRUE", "FALSE"]


class _ReviewValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_raw_value(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class RegisteredReviewSourceBasis(_ReviewValue):
    """Pinned source values, not current authorization or registered-storage proof."""

    source: ApprovedItemKnowledgeSourceV2
    graph_snapshot: KnowledgeGraphSnapshotPointer
    review_evidence: RegisteredItemReviewSolutionEvidence

    @model_validator(mode="after")
    def exact_registered_source(self) -> RegisteredReviewSourceBasis:
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.source != self.review_evidence.source
            or self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
        ):
            raise ValueError("registered review source/Graph pointer differs")
        return self


class RegisteredReviewClaim(_ReviewValue):
    """One original conclusion, with report locations distinct from draft locations."""

    claim_id: str = Field(pattern=r"^reviewclaim_[0-9a-f]{32}$")
    kind: ReviewClaimKind
    subject: str = Field(min_length=1, max_length=64)
    verdict: ReviewClaimVerdict | None
    text: str = Field(min_length=1, max_length=4000)
    review_json_pointers: tuple[ReviewJsonPointer, ...] = Field(min_length=1, max_length=4)
    draft_json_paths: tuple[ReviewJsonPointer, ...] = Field(min_length=1, max_length=16)
    evidence_ids: tuple[Annotated[str, Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")], ...] = Field(
        max_length=16
    )

    @field_validator("text", "subject")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("review conclusion contains a control character")
        return value

    @model_validator(mode="after")
    def original_conclusion_shape(self) -> RegisteredReviewClaim:
        for values in (self.review_json_pointers, self.draft_json_paths, self.evidence_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("review conclusion references must be sorted and unique")
        if any(
            not pointer.startswith("/output/independent_review_report/")
            for pointer in self.review_json_pointers
        ):
            raise ValueError("review conclusion pointer is outside the original report")
        choices = {"①", "②", "③", "④", "⑤"}
        if self.kind == "ANSWER_SUMMARY":
            valid = self.subject in choices and self.verdict in {"MATCH", "MISMATCH"}
        elif self.kind == "ANSWER_CLAIM":
            valid = (
                re.fullmatch(r"claim_[a-z0-9][a-z0-9_]{0,31}", self.subject) is not None
                and self.verdict is None
            )
        elif self.kind == "CHOICE_DIAGNOSTIC":
            valid = self.subject in choices and self.verdict in {"CORRECT", "DISTRACTOR"}
        else:
            valid = self.subject in {"ㄱ", "ㄴ", "ㄷ"} and self.verdict in {"TRUE", "FALSE"}
        if not valid or (self.kind != "ANSWER_SUMMARY" and len(self.text) > 2000):
            raise ValueError("review conclusion family/subject/verdict differs")
        digest = content_sha256(self.model_dump(mode="json", exclude={"claim_id"}))[7:39]
        if self.claim_id != "reviewclaim_" + digest:
            raise ValueError("review conclusion identity differs from its original values")
        return self


def _profile_ids(document: dict[str, object]) -> tuple[str, str]:
    basis = RegisteredReviewSourceBasis.model_validate(document["source_basis"])
    logical = content_sha256(
        {
            "item_id": basis.source.item_id,
            "item_revision_id": basis.source.item_revision_id,
            "evidence_kind": "REGISTERED_ITEM_REVIEW_SOLUTION",
            "extractor_version": REGISTERED_REVIEW_EXTRACTOR_VERSION,
        }
    )
    revision = content_sha256(
        {
            key: value
            for key, value in document.items()
            if key not in {"profile_id", "profile_revision_id", "profile_sha256"}
        }
    )
    return "inferenceprofile_" + logical[7:39], "inferenceprofilerev_" + revision[39:]


class RegisteredReviewProfile(_ReviewValue):
    """Profile2 deliberately has no invented facets, solution steps or Graph anchors."""

    schema_version: Literal["item-inference-transfer-profile/2.0"]
    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    source_basis: RegisteredReviewSourceBasis
    claims: tuple[RegisteredReviewClaim, ...] = Field(min_length=7, max_length=25)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = Field(
        min_length=2, max_length=8
    )
    extractor_version: Literal["registered-item-review-comparison/1.0"]
    created_at: UtcDatetime
    profile_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REGISTERED_REVIEW_PROFILE_SCHEMA, MAX_REGISTERED_REVIEW_PROFILE_BYTES
        )

    @model_validator(mode="after")
    def closed_profile(self) -> RegisteredReviewProfile:
        ids = tuple(claim.claim_id for claim in self.claims)
        keys = {(claim.kind, claim.subject) for claim in self.claims}
        summaries = tuple(claim for claim in self.claims if claim.kind == "ANSWER_SUMMARY")
        answers = tuple(claim for claim in self.claims if claim.kind == "ANSWER_CLAIM")
        choices = tuple(claim for claim in self.claims if claim.kind == "CHOICE_DIAGNOSTIC")
        statements = tuple(claim for claim in self.claims if claim.kind == "STATEMENT_DIAGNOSTIC")
        if (
            ids != tuple(sorted(set(ids)))
            or len(keys) != len(self.claims)
            or len(summaries) != 1
            or not 1 <= len(answers) <= 16
            or {claim.subject for claim in choices} != {"①", "②", "③", "④", "⑤"}
            or {claim.subject for claim in statements} not in (set(), {"ㄱ", "ㄴ", "ㄷ"})
            or tuple(claim.subject for claim in choices if claim.verdict == "CORRECT")
            != (summaries[0].subject,)
            or len(self.limitations) != len(set(self.limitations))
            or not {REVIEW_REASONING_LIMITATION, REVIEW_PIXEL_LIMITATION}.issubset(self.limitations)
        ):
            raise ValueError("registered review profile coverage/limitations differ")
        document = self.model_dump(mode="json")
        if (self.profile_id, self.profile_revision_id) != _profile_ids(document):
            raise ValueError("registered review profile identity differs")
        if self.profile_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "profile_sha256"}
        ):
            raise ValueError("registered review profile hash differs")
        return self


class RegisteredReviewProfilePointer(_ReviewValue):
    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    profile_sha256: Sha256
    schema_ref: Literal["eom://schemas/knowledge/item-inference-transfer/2.0"] = (
        "eom://schemas/knowledge/item-inference-transfer/2.0"
    )

    @classmethod
    def from_profile(cls, profile: RegisteredReviewProfile) -> RegisteredReviewProfilePointer:
        checked = RegisteredReviewProfile.model_validate(profile)
        return cls(
            profile_id=checked.profile_id,
            profile_revision_id=checked.profile_revision_id,
            profile_sha256=checked.profile_sha256,
        )


def build_registered_review_profile(
    *,
    source_basis: RegisteredReviewSourceBasis,
    claims: tuple[RegisteredReviewClaim, ...],
    created_at: datetime,
) -> RegisteredReviewProfile:
    """Seal the one canonical identity rule; storage/current source checks are external."""
    basis = RegisteredReviewSourceBasis.model_validate(source_basis)
    checked_claims = tuple(RegisteredReviewClaim.model_validate(claim) for claim in claims)
    document: dict[str, object] = {
        "schema_version": "item-inference-transfer-profile/2.0",
        "source_basis": basis.model_dump(mode="json"),
        "claims": [claim.model_dump(mode="json") for claim in checked_claims],
        "limitations": [REVIEW_REASONING_LIMITATION, REVIEW_PIXEL_LIMITATION],
        "extractor_version": REGISTERED_REVIEW_EXTRACTOR_VERSION,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    profile_id, revision_id = _profile_ids(document)
    document.update(profile_id=profile_id, profile_revision_id=revision_id)
    return RegisteredReviewProfile.model_validate(
        document | {"profile_sha256": content_sha256(document)}
    )


def registered_review_profile_text(profile: RegisteredReviewProfile) -> str:
    """Lossless bounded feature rendering; never truncate a scientific conclusion."""
    checked = RegisteredReviewProfile.model_validate(profile)
    # Audit IDs/pointers affect the profile identity, not numerical feature order.
    ordered = sorted(
        checked.claims,
        key=lambda claim: (
            claim.kind,
            claim.subject if claim.kind != "ANSWER_CLAIM" else "",
            claim.verdict or "",
            claim.text,
        ),
    )
    return "\n\n".join(
        f"{claim.kind} "
        f"{claim.subject if claim.kind != 'ANSWER_CLAIM' else ''} "
        f"{claim.verdict or ''}\n{claim.text}"
        for claim in ordered
    )


def registered_review_profile_bytes(profile: RegisteredReviewProfile) -> bytes:
    checked = RegisteredReviewProfile.model_validate(profile)
    return canonical_json_bytes(checked.model_dump(mode="json"))
