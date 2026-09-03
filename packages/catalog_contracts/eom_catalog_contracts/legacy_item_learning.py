"""Contracts for legacy-item editorial compatibility beside existing Graph learning."""

from __future__ import annotations

import re
from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime, _safe_text

EditorialAuthorityKind = Literal["CONTENT_TEAM_PROMPT", "HWP_QUESTION_EDITOR_PROFILE"]
EditorialCheckKind = Literal[
    "CONTENT_CONTRACT",
    "MARKDOWN_PROJECTION",
    "HWPX_RENDERABILITY",
    "LOSSLESSNESS",
]

_ITEM_CONTENT_PATH_PATTERN = re.compile(r"[^./\x00-\x1f]+(?:\.[^./\x00-\x1f]+)*")


def _require_self_hash(model: FrozenModel, field_name: str) -> None:
    expected = content_sha256(model.model_dump(mode="json", exclude={field_name}))
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} does not match canonical content")


class LegacyLearnedItemPointer(FrozenModel):
    """Exact approved Item Revision that may enter the existing knowledge graph."""

    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    item_content: OriginArtifactMemberPointer
    extraction_acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    extraction_acceptance_sha256: Sha256
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    item_origin_profile_sha256: Sha256
    lifecycle_state: Literal["APPROVED"] = "APPROVED"

    @model_validator(mode="after")
    def canonical_item_content(self) -> LegacyLearnedItemPointer:
        if (
            self.item_content.schema_ref
            not in {
                "eom://schemas/item-registry/assessment-item-content-v1",
                "eom://schemas/item-registry/assessment-item-content-v2",
            }
            or self.item_content.media_type != "application/json"
        ):
            raise ValueError("legacy learning requires a canonical Item content member")
        return self


class LegacyItemPromotionRequest(FrozenModel):
    """Reviewed command that promotes one accepted proposal into the Item registry."""

    schema_version: Literal["legacy-item-promotion-request/1.0"] = (
        "legacy-item-promotion-request/1.0"
    )
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: Sha256
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    primary_taxonomy_ref: str | None = Field(default=None, max_length=256)
    difficulty_band: str | None = Field(default=None, max_length=64)
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LegacyItemPromotionRequest:
        _require_self_hash(self, "request_sha256")
        return self


class EditorialAuthorityPointer(FrozenModel):
    """One immutable content-team authority; EOM does not invent editorial authority."""

    authority_kind: EditorialAuthorityKind
    reference_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    reference_revision: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){1,2}$")
    artifact_member: OriginArtifactMemberPointer

    @model_validator(mode="after")
    def markdown_authority(self) -> EditorialAuthorityPointer:
        if self.artifact_member.media_type != "text/markdown":
            raise ValueError("editorial authority must be an immutable Markdown member")
        return self


class HwpQuestionEditorProfilePointer(FrozenModel):
    """Exact executable handoff snapshot; workers receive metadata, not ZIP bytes."""

    renderer_profile: Literal["content-team-hwp-question-editor-v1"] = (
        "content-team-hwp-question-editor-v1"
    )
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    archive_member_path: Literal["handoff-source.zip"] = "handoff-source.zip"
    archive_schema_ref: Literal["eom://schemas/hwpx/content-team-handoff-archive/1.0"] = (
        "eom://schemas/hwpx/content-team-handoff-archive/1.0"
    )
    archive_media_type: Literal["application/zip"] = "application/zip"
    archive_sha256: Sha256
    profile_sha256: Sha256


class LegacyItemEditorialCompatibilityPolicy(FrozenModel):
    """Released system policy for lifecycle, bounds, and authority provenance only."""

    schema_version: Literal["legacy-item-editorial-compatibility-policy/1.0"] = (
        "legacy-item-editorial-compatibility-policy/1.0"
    )
    compatibility_policy_revision_id: str = Field(
        pattern=r"^editorialcompatpolicyrev_[0-9a-f]{32}$"
    )
    state: Literal["RELEASED"] = "RELEASED"
    required_authorities: tuple[EditorialAuthorityKind, ...] = Field(min_length=2, max_length=2)
    required_checks: tuple[EditorialCheckKind, ...] = Field(min_length=4, max_length=4)
    maximum_issue_count: Literal[128] = 128
    maximum_result_bytes: int = Field(ge=4096, le=2 * 1024 * 1024)
    automatic_retry: Literal[False] = False
    close_compatible_tuple: Literal[True] = True
    released_at: UtcDatetime
    released_by: ActorId
    content_sha256: Sha256

    @model_validator(mode="after")
    def lifecycle_only_policy(self) -> LegacyItemEditorialCompatibilityPolicy:
        if self.required_authorities != (
            "CONTENT_TEAM_PROMPT",
            "HWP_QUESTION_EDITOR_PROFILE",
        ):
            raise ValueError("compatibility policy requires only the two content-team authorities")
        if self.required_checks != (
            "CONTENT_CONTRACT",
            "MARKDOWN_PROJECTION",
            "HWPX_RENDERABILITY",
            "LOSSLESSNESS",
        ):
            raise ValueError("compatibility policy requires the complete deterministic checks")
        _require_self_hash(self, "content_sha256")
        return self


class LegacyItemEditorialCompatibilityRequest(FrozenModel):
    schema_version: Literal["legacy-item-editorial-compatibility-request/1.0"] = (
        "legacy-item-editorial-compatibility-request/1.0"
    )
    compatibility_request_id: str = Field(pattern=r"^editorialcompatreq_[0-9a-f]{32}$")
    predecessor_compatibility_run_id: str | None = Field(
        default=None, pattern=r"^editorialcompatrun_[0-9a-f]{32}$"
    )
    source: LegacyLearnedItemPointer
    authorities: tuple[EditorialAuthorityPointer, ...] = Field(min_length=2, max_length=2)
    renderer_profile: HwpQuestionEditorProfilePointer
    compatibility_policy_revision_id: str = Field(
        pattern=r"^editorialcompatpolicyrev_[0-9a-f]{32}$"
    )
    compatibility_policy_sha256: Sha256
    requested_checks: tuple[EditorialCheckKind, ...] = Field(min_length=4, max_length=4)
    created_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_authorities_checks_and_hash(self) -> LegacyItemEditorialCompatibilityRequest:
        authority_kinds = tuple(item.authority_kind for item in self.authorities)
        if authority_kinds != ("CONTENT_TEAM_PROMPT", "HWP_QUESTION_EDITOR_PROFILE"):
            raise ValueError("compatibility request requires the ordered content-team authorities")
        authority_revisions = tuple(
            item.artifact_member.artifact_revision_id for item in self.authorities
        )
        if len(set(authority_revisions)) != len(authority_revisions):
            raise ValueError("editorial authority revisions must be distinct")
        expected_checks: tuple[EditorialCheckKind, ...] = (
            "CONTENT_CONTRACT",
            "MARKDOWN_PROJECTION",
            "HWPX_RENDERABILITY",
            "LOSSLESSNESS",
        )
        if self.requested_checks != expected_checks:
            raise ValueError("compatibility request requires the complete ordered check set")
        _require_self_hash(self, "request_sha256")
        return self


class EditorialCompatibilityIssue(FrozenModel):
    issue_id: str = Field(pattern=r"^editorialissue_[0-9a-f]{32}$")
    authority_kind: EditorialAuthorityKind
    authority_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    authority_sha256: Sha256
    rule_locator: str = Field(min_length=1, max_length=256)
    category: Literal[
        "CONTENT_CONTRACT",
        "MARKDOWN_STRUCTURE",
        "VISUAL_LAYOUT",
        "EQUATION_NOTATION",
        "HWPX_RENDERING",
        "LOSSY_TRANSFORMATION",
        "OTHER_AUTHORITY_RULE",
    ]
    severity: Literal["ADAPTATION_REQUIRED", "BLOCKING"]
    item_content_paths: tuple[str, ...] = Field(min_length=1, max_length=64)
    observation: str = Field(min_length=1, max_length=2000)
    required_adaptation: str = Field(min_length=1, max_length=2000)

    _text = field_validator("rule_locator", "observation", "required_adaptation")(_safe_text)

    @field_validator("item_content_paths")
    @classmethod
    def safe_unique_content_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("editorial issue Item content paths must be unique")
        if any(
            len(path) > 256 or _ITEM_CONTENT_PATH_PATTERN.fullmatch(path) is None for path in value
        ):
            raise ValueError("editorial issue Item content path is unsafe")
        return value


class EditorialDeterministicCheck(FrozenModel):
    check_kind: EditorialCheckKind
    outcome: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    validator_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    validator_revision: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){1,2}$")
    evidence_sha256: Sha256


class LegacyItemEditorialCompatibilityProposal(FrozenModel):
    """Authority-grounded worker observation; deterministic checks stay server-owned."""

    schema_version: Literal["legacy-item-editorial-compatibility-proposal/1.0"] = (
        "legacy-item-editorial-compatibility-proposal/1.0"
    )
    compatibility_request_id: str = Field(pattern=r"^editorialcompatreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    source: LegacyLearnedItemPointer
    authorities: tuple[EditorialAuthorityPointer, ...] = Field(min_length=2, max_length=2)
    renderer_profile: HwpQuestionEditorProfilePointer
    status: Literal["COMPATIBLE", "NEEDS_ADAPTATION", "BLOCKED"]
    issues: tuple[EditorialCompatibilityIssue, ...] = Field(max_length=128)
    completed_at: UtcDatetime
    proposal_sha256: Sha256

    @model_validator(mode="after")
    def authority_grounded_observation(self) -> LegacyItemEditorialCompatibilityProposal:
        authority_kinds = tuple(item.authority_kind for item in self.authorities)
        if authority_kinds != ("CONTENT_TEAM_PROMPT", "HWP_QUESTION_EDITOR_PROFILE"):
            raise ValueError("compatibility proposal requires ordered content-team authorities")
        authority_by_kind = {item.authority_kind: item for item in self.authorities}
        if len(authority_by_kind) != 2:
            raise ValueError("compatibility proposal authority kinds must be unique")
        for issue in self.issues:
            authority = authority_by_kind[issue.authority_kind]
            if (
                issue.authority_artifact_revision_id
                != authority.artifact_member.artifact_revision_id
                or issue.authority_sha256 != authority.artifact_member.sha256
            ):
                raise ValueError("editorial issue does not bind its exact authority revision")
        issue_ids = tuple(item.issue_id for item in self.issues)
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("editorial compatibility issue IDs must be unique")
        if self.status == "COMPATIBLE" and self.issues:
            raise ValueError("compatible proposal must not contain editorial issues")
        if self.status != "COMPATIBLE" and not self.issues:
            raise ValueError("non-compatible proposal requires authority-grounded issues")
        if self.status == "BLOCKED" and not any(
            issue.severity == "BLOCKING" for issue in self.issues
        ):
            raise ValueError("blocked proposal requires a blocking authority-grounded issue")
        _require_self_hash(self, "proposal_sha256")
        return self


class LegacyItemEditorialCompatibilityResult(FrozenModel):
    schema_version: Literal["legacy-item-editorial-compatibility-result/1.0"] = (
        "legacy-item-editorial-compatibility-result/1.0"
    )
    compatibility_result_id: str = Field(pattern=r"^editorialcompatresult_[0-9a-f]{32}$")
    compatibility_request_id: str = Field(pattern=r"^editorialcompatreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    source: LegacyLearnedItemPointer
    authorities: tuple[EditorialAuthorityPointer, ...] = Field(min_length=2, max_length=2)
    renderer_profile: HwpQuestionEditorProfilePointer
    proposal_artifact: OriginArtifactMemberPointer
    proposal_sha256: Sha256
    status: Literal["COMPATIBLE", "NEEDS_ADAPTATION", "BLOCKED"]
    issues: tuple[EditorialCompatibilityIssue, ...] = Field(max_length=128)
    deterministic_checks: tuple[EditorialDeterministicCheck, ...] = Field(
        min_length=4, max_length=4
    )
    lossless_projection: bool
    convergence_state: Literal["OPEN", "CLOSED"]
    completed_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def authority_grounding_and_convergence(self) -> LegacyItemEditorialCompatibilityResult:
        if (
            self.proposal_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal/1.0"
            or self.proposal_artifact.media_type != "application/json"
        ):
            raise ValueError("compatibility result requires its exact worker proposal pointer")
        authority_kinds = tuple(item.authority_kind for item in self.authorities)
        if authority_kinds != ("CONTENT_TEAM_PROMPT", "HWP_QUESTION_EDITOR_PROFILE"):
            raise ValueError("compatibility result requires the ordered content-team authorities")
        authority_by_kind = {item.authority_kind: item for item in self.authorities}
        if len(authority_by_kind) != 2:
            raise ValueError("compatibility result authority kinds must be unique")
        for issue in self.issues:
            authority = authority_by_kind[issue.authority_kind]
            if (
                issue.authority_artifact_revision_id
                != authority.artifact_member.artifact_revision_id
                or issue.authority_sha256 != authority.artifact_member.sha256
            ):
                raise ValueError("editorial issue does not bind its exact authority revision")
        issue_ids = tuple(item.issue_id for item in self.issues)
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("editorial compatibility issue IDs must be unique")
        expected_checks: tuple[EditorialCheckKind, ...] = (
            "CONTENT_CONTRACT",
            "MARKDOWN_PROJECTION",
            "HWPX_RENDERABILITY",
            "LOSSLESSNESS",
        )
        if tuple(item.check_kind for item in self.deterministic_checks) != expected_checks:
            raise ValueError("compatibility result requires the complete ordered check set")
        compatible = self.status == "COMPATIBLE"
        checks_pass = all(check.outcome == "PASS" for check in self.deterministic_checks)
        if compatible:
            if self.issues or not self.lossless_projection or not checks_pass:
                raise ValueError("compatible result must be issue-free, lossless, and pass checks")
            if self.convergence_state != "CLOSED":
                raise ValueError("compatible exact revision tuple must be closed")
        else:
            if not self.issues or self.convergence_state != "OPEN":
                raise ValueError("non-compatible result requires grounded issues and remains open")
            if self.status == "BLOCKED" and not any(
                issue.severity == "BLOCKING" for issue in self.issues
            ):
                raise ValueError("blocked result requires a blocking authority-grounded issue")
        _require_self_hash(self, "result_sha256")
        return self
