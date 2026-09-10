"""Exact, versioned compatibility for one immutable legacy Item media pointer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent, MediaArtifactPointer
from eom_catalog_contracts.legacy_assessment import (
    AssessmentArtifactMemberPointer,
    LegacyAssessmentItemProposal,
    LegacyItemExtractionRequest,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF = (
    "eom://schemas/legacy-assessment/legacy-item-media-pointer-compatibility-policy/1.0"
)
LEGACY_ITEM_MEDIA_COMPATIBILITY_MEMBER = "legacy-item-media-pointer-compatibility.json"
LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE = "legacy-item-media-pointer-compatibility-v1.json"
LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE_SHA256 = (
    "sha256:614b18e4f62b02175e617b7f8d41889ad863c27fbe8e15cc01a1322b193a9203"
)


class LegacyItemMediaCompatibilityEntry(FrozenModel):
    """One fully pinned historical transcription and its reviewed target."""

    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: Sha256
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    result_sha256: Sha256
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    bundle_manifest_sha256: Sha256
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10_000)
    content_path: str = Field(pattern=r"^body\[[0-9]+\]$")
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    target_page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    target_source_role: Literal["PROBLEM_DOCUMENT"]
    target_physical_page: int = Field(ge=1)
    target_schema_ref: Literal["eom://schemas/legacy-assessment/page-image/1.0"]
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    source: MediaArtifactPointer
    target: MediaArtifactPointer
    reason_code: Literal["WORKER_LOGICAL_ARTIFACT_ID_TRANSCRIPTION"]

    @model_validator(mode="after")
    def logical_id_only_correction(self) -> LegacyItemMediaCompatibilityEntry:
        if self.source.artifact_id == self.target.artifact_id:
            raise ValueError("legacy media compatibility must change the logical Artifact ID")
        source_rest = self.source.model_dump(mode="json", exclude={"artifact_id"})
        target_rest = self.target.model_dump(mode="json", exclude={"artifact_id"})
        if source_rest != target_rest:
            raise ValueError("legacy media compatibility may change only the logical Artifact ID")
        return self

    def matches_source_chain(
        self,
        *,
        acceptance_id: str,
        acceptance_sha256: str,
        extraction_result_id: str,
        result_sha256: str,
        request: LegacyItemExtractionRequest,
        proposal: LegacyAssessmentItemProposal,
    ) -> bool:
        return (
            acceptance_id == self.acceptance_id
            and acceptance_sha256 == self.acceptance_sha256
            and extraction_result_id == self.extraction_result_id
            and result_sha256 == self.result_sha256
            and request.extraction_request_id == self.extraction_request_id
            and request.request_sha256 == self.request_sha256
            and request.bundle.assessment_source_bundle_revision_id == self.bundle_revision_id
            and request.bundle.bundle_manifest_sha256 == self.bundle_manifest_sha256
            and proposal.item_proposal_id == self.item_proposal_id
            and proposal.item_number == self.item_number
        )


class LegacyItemMediaCompatibilityPolicy(FrozenModel):
    """One-entry policy whose immutable Artifact becomes an Item component."""

    schema_version: Literal["legacy-item-media-pointer-compatibility-policy/1.0"]
    policy_id: str = Field(pattern=r"^legacyitemmediapolicy_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^legacyitemmediapolicyrev_[0-9a-f]{32}$")
    entries: tuple[LegacyItemMediaCompatibilityEntry, ...] = Field(
        min_length=1,
        max_length=1,
    )
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_self_hash(self) -> LegacyItemMediaCompatibilityPolicy:
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("legacy Item media compatibility policy hash is invalid")
        return self


@dataclass(frozen=True)
class AppliedLegacyItemMediaCompatibility:
    """Canonical content plus the exact policy entry used to derive it."""

    content: AssessmentItemContent
    entry: LegacyItemMediaCompatibilityEntry | None


def apply_legacy_item_media_compatibility(
    *,
    policy: LegacyItemMediaCompatibilityPolicy,
    acceptance_id: str,
    acceptance_sha256: str,
    extraction_result_id: str,
    result_sha256: str,
    request: LegacyItemExtractionRequest,
    proposal: LegacyAssessmentItemProposal,
) -> AppliedLegacyItemMediaCompatibility:
    """Derive canonical Item content only for the policy's exact immutable source chain."""

    entries = tuple(
        entry
        for entry in policy.entries
        if entry.matches_source_chain(
            acceptance_id=acceptance_id,
            acceptance_sha256=acceptance_sha256,
            extraction_result_id=extraction_result_id,
            result_sha256=result_sha256,
            request=request,
            proposal=proposal,
        )
    )
    if not entries:
        source_pointer_present = any(
            getattr(block, "artifact", None) == entry.source
            for entry in policy.entries
            for block in proposal.item_content.body
        )
        known_slot_present = any(
            proposal.item_proposal_id == entry.item_proposal_id
            or (acceptance_id == entry.acceptance_id and proposal.item_number == entry.item_number)
            for entry in policy.entries
        )
        if source_pointer_present or known_slot_present:
            raise ValueError("legacy Item media compatibility scope is stale")
        return AppliedLegacyItemMediaCompatibility(content=proposal.item_content, entry=None)
    if len(entries) != 1:
        raise ValueError("legacy Item media compatibility source match is ambiguous")
    entry = entries[0]
    body_index = int(entry.content_path.removeprefix("body[").removesuffix("]"))
    if body_index >= len(proposal.item_content.body):
        raise ValueError("legacy Item media compatibility content path is stale")
    block = proposal.item_content.body[body_index]
    artifact = getattr(block, "artifact", None)
    if block.block_id != entry.block_id or artifact != entry.source:
        raise ValueError("legacy Item media compatibility source block is stale")

    target_page = tuple(
        page
        for page in request.page_inputs
        if page.page_input_id == entry.target_page_input_id
        and page.source_role == entry.target_source_role
        and page.physical_page == entry.target_physical_page
        and page.image.schema_ref == entry.target_schema_ref
        and _same_media_pointer(page.image, entry.target)
    )
    anchor_map = tuple(
        mapping
        for mapping in proposal.content_anchor_map
        if mapping.content_path == entry.content_path
    )
    target_anchors = tuple(
        anchor
        for anchor in proposal.source_anchors
        if anchor.anchor_id == entry.source_anchor_id
        and anchor.source_role == entry.target_source_role
        and anchor.physical_page == entry.target_physical_page
        and anchor.source.schema_ref == entry.target_schema_ref
        and _same_media_pointer(anchor.source, entry.target)
    )
    if (
        len(target_page) != 1
        or len(anchor_map) != 1
        or anchor_map[0].source_anchor_ids != (entry.source_anchor_id,)
        or len(target_anchors) != 1
    ):
        raise ValueError("legacy Item media compatibility target lacks exact source evidence")

    document = proposal.item_content.model_dump(mode="json")
    body = document.get("body")
    if not isinstance(body, list) or not isinstance(body[body_index], dict):
        raise ValueError("legacy Item media compatibility content body is invalid")
    body[body_index]["artifact"] = entry.target.model_dump(mode="json")
    return AppliedLegacyItemMediaCompatibility(
        content=AssessmentItemContent.model_validate(document),
        entry=entry,
    )


def _same_media_pointer(
    source: AssessmentArtifactMemberPointer,
    target: MediaArtifactPointer,
) -> bool:
    return (
        source.artifact_id == target.artifact_id
        and source.artifact_revision_id == target.artifact_revision_id
        and source.member_path == target.artifact_member
        and source.sha256 == target.sha256
        and source.media_type == target.media_type
    )


@lru_cache(maxsize=1)
def load_legacy_item_media_compatibility_policy() -> LegacyItemMediaCompatibilityPolicy:
    """Load the reviewed package resource only when both byte and content pins validate."""

    raw = (
        files("eom_catalog_contracts")
        .joinpath(
            "resources",
            "legacy-assessment",
            LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE,
        )
        .read_bytes()
    )
    resource_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    if resource_sha256 != LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE_SHA256:
        raise ValueError("packaged legacy Item media compatibility resource hash mismatch")
    value = json.loads(raw)
    validate_contract("legacy-item-media-pointer-compatibility-policy", value)
    return LegacyItemMediaCompatibilityPolicy.model_validate(value)


__all__ = [
    "LEGACY_ITEM_MEDIA_COMPATIBILITY_MEMBER",
    "LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE",
    "LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE_SHA256",
    "LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF",
    "AppliedLegacyItemMediaCompatibility",
    "LegacyItemMediaCompatibilityEntry",
    "LegacyItemMediaCompatibilityPolicy",
    "apply_legacy_item_media_compatibility",
    "load_legacy_item_media_compatibility_policy",
]
