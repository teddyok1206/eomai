"""Resolve the one manifest-pinned historical Item media correction."""

from __future__ import annotations

import json
from collections.abc import Collection

from eom_catalog_contracts import (
    LEGACY_ITEM_MEDIA_COMPATIBILITY_MEMBER,
    LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE_SHA256,
    LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF,
    AssessmentItemContent,
    LegacyAssessmentItemProposal,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    LegacyItemMediaCompatibilityPolicy,
    apply_legacy_item_media_compatibility,
    load_legacy_item_media_compatibility_policy,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader
from eom_catalog_service.models import ItemComponentRecord
from eom_catalog_service.pinned_artifact_resolution import resolve_pinned_artifact_member

MAX_LEGACY_ITEM_MEDIA_COMPATIBILITY_BYTES = 64 * 1024


class LegacyItemMediaCompatibilityError(ValueError):
    """The exact corrected Item derivation or its manifest evidence is stale."""


def expected_promoted_legacy_item_content(
    session: Session,
    *,
    artifacts: CatalogArtifactReader,
    item_revision_id: str,
    acceptance: LegacyItemExtractionAcceptance,
    result: LegacyItemExtractionResult,
    request: LegacyItemExtractionRequest,
    proposal: LegacyAssessmentItemProposal,
    components: Collection[ItemComponentRecord] | None = None,
) -> AssessmentItemContent:
    """Return proposal content or its one authorized, manifest-pinned canonical correction."""

    try:
        expected_policy = load_legacy_item_media_compatibility_policy()
        applied = apply_legacy_item_media_compatibility(
            policy=expected_policy,
            acceptance_id=acceptance.acceptance_id,
            acceptance_sha256=acceptance.acceptance_sha256,
            extraction_result_id=result.extraction_result_id,
            result_sha256=result.result_sha256,
            request=request,
            proposal=proposal,
        )
    except (JsonSchemaValidationError, ValueError) as exc:
        raise LegacyItemMediaCompatibilityError(
            "legacy Item media compatibility derivation is stale"
        ) from exc

    scoped_components = tuple(
        component
        for component in (
            components
            if components is not None
            else session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == item_revision_id
                )
            )
        )
        if component.item_revision_id == item_revision_id
        and component.component_type == "OTHER"
        and component.schema_ref == LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF
    )
    if applied.entry is None:
        if scoped_components:
            raise LegacyItemMediaCompatibilityError(
                "ordinary legacy Item has unexpected media compatibility evidence"
            )
        return applied.content
    if len(scoped_components) != 1:
        raise LegacyItemMediaCompatibilityError(
            "corrected legacy Item lacks unique media compatibility evidence"
        )
    component = scoped_components[0]
    if (
        component.ordinal != 0
        or component.media_type != "application/json"
        or component.logical_name != LEGACY_ITEM_MEDIA_COMPATIBILITY_MEMBER
        or component.sha256 != LEGACY_ITEM_MEDIA_COMPATIBILITY_RESOURCE_SHA256
        or not component.required
        or component.metadata_json
        != {
            "policy_id": expected_policy.policy_id,
            "policy_revision_id": expected_policy.policy_revision_id,
            "policy_sha256": expected_policy.policy_sha256,
        }
    ):
        raise LegacyItemMediaCompatibilityError(
            "legacy Item media compatibility component identity is stale"
        )
    try:
        member = resolve_pinned_artifact_member(
            session,
            artifacts.settings,
            artifact_id=component.artifact_id,
            artifact_revision_id=component.artifact_revision_id,
            member_path=component.logical_name,
            sha256=component.sha256,
            media_type=component.media_type,
            schema_ref=component.schema_ref,
            expected_artifact_types={"legacy-item-media-pointer-compatibility"},
            expected_primary_file=LEGACY_ITEM_MEDIA_COMPATIBILITY_MEMBER,
            max_bytes=MAX_LEGACY_ITEM_MEDIA_COMPATIBILITY_BYTES,
        )
        value = json.loads(member.payload)
        validate_contract("legacy-item-media-pointer-compatibility-policy", value)
        actual_policy = LegacyItemMediaCompatibilityPolicy.model_validate(value)
    except (
        OSError,
        TypeError,
        ValueError,
        JsonSchemaValidationError,
        json.JSONDecodeError,
    ) as exc:
        raise LegacyItemMediaCompatibilityError(
            "legacy Item media compatibility Artifact is invalid"
        ) from exc
    if actual_policy != expected_policy:
        raise LegacyItemMediaCompatibilityError(
            "legacy Item media compatibility Artifact differs from the reviewed policy"
        )
    return applied.content


__all__ = [
    "LegacyItemMediaCompatibilityError",
    "expected_promoted_legacy_item_content",
]
