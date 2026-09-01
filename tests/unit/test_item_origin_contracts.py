from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    AssessmentOccurrenceRevision,
    ItemOriginProfile,
    OrganizationRevision,
    OriginArtifactMemberPointer,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ZERO_SHA = "sha256:" + "0" * 64
NOW = "2026-09-01T00:00:00Z"


def _hashed(value: dict[str, object], field: str) -> dict[str, object]:
    return {**value, field: content_sha256(value)}


def _evidence(seed: str = "1") -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": "evidence/review.json",
        "schema_ref": "eom://schemas/item-origin/review-evidence/1.0",
        "media_type": "application/json",
        "sha256": "sha256:" + seed * 64,
    }


def _rights() -> dict[str, object]:
    return {
        "rights_policy_id": "rightspolicy_" + "1" * 32,
        "rights_policy_revision_id": "rightspolicyrev_" + "1" * 32,
        "rights_policy_sha256": ZERO_SHA,
    }


def _organization() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "organization-revision/1.0",
        "organization_id": "org_" + "1" * 32,
        "organization_revision_id": "orgrev_" + "1" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "organization_key": "organization.sample-agency",
        "revision_state": "REVIEWED",
        "organization_class": "NATIONAL_ASSESSMENT_AGENCY",
        "class_detail": None,
        "display_name": "표본 평가 기관",
        "locale": "ko-KR",
        "jurisdiction": {
            "country_code": "KR",
            "level": "NATIONAL",
            "jurisdiction_code": "KR",
        },
        "aliases": [
            {
                "alias_kind": "OFFICIAL",
                "locale": "ko-KR",
                "display_value": "표본 평가 기관",
                "normalized_value": "표본평가기관",
            }
        ],
        "effective_from": None,
        "effective_to": None,
        "source_evidence": [_evidence()],
        "rights_policy": _rights(),
        "created_at": NOW,
        "created_by": "admin_01",
    }
    return _hashed(value, "revision_sha256")


def _occurrence() -> dict[str, object]:
    organization = _organization()
    value: dict[str, object] = {
        "schema_version": "assessment-occurrence-revision/1.0",
        "assessment_occurrence_id": "occurrence_" + "1" * 32,
        "assessment_occurrence_revision_id": "occurrev_" + "1" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "occurrence_key": "assessment.sample.2024.integrated-science",
        "revision_state": "REVIEWED",
        "issuing_organization": {
            "organization_id": organization["organization_id"],
            "organization_revision_id": organization["organization_revision_id"],
            "revision_sha256": organization["revision_sha256"],
        },
        "occurrence_kind": "NATIONAL_ACHIEVEMENT",
        "exam_family_key": "assessment-family.sample",
        "administration_year": 2024,
        "administration_date": "2024-06-04",
        "session_key": "session.june",
        "subject_key": "integrated-science",
        "form_key": None,
        "region_key": None,
        "display_label": "2024년 6월 통합과학 표본 평가",
        "source_evidence": [_evidence("2")],
        "rights_policy": _rights(),
        "created_at": NOW,
        "created_by": "admin_01",
    }
    return _hashed(value, "revision_sha256")


def _origin_profile() -> dict[str, object]:
    organization = _organization()
    occurrence = _occurrence()
    value: dict[str, object] = {
        "schema_version": "item-origin-profile/1.0",
        "item_origin_profile_id": "originprofile_" + "1" * 32,
        "item_revision": {
            "item_id": "item_" + "1" * 32,
            "item_revision_id": "itemrev_" + "1" * 32,
            "item_manifest_sha256": ZERO_SHA,
        },
        "source_domain": "EXTERNAL_INSTITUTION",
        "creation_method": "IMPORTED",
        "source_organization": {
            "organization_id": organization["organization_id"],
            "organization_revision_id": organization["organization_revision_id"],
            "revision_sha256": organization["revision_sha256"],
        },
        "assessment_occurrences": [
            {
                "assessment_occurrence_id": occurrence["assessment_occurrence_id"],
                "assessment_occurrence_revision_id": occurrence[
                    "assessment_occurrence_revision_id"
                ],
                "occurrence_revision_sha256": occurrence["revision_sha256"],
            }
        ],
        "derivations": [],
        "rights_policy": _rights(),
        "provenance": [
            {
                "provenance_kind": "CONTENT_INTAKE",
                "logical_id": "intake_" + "1" * 32,
                "revision_id": "rev_" + "3" * 32,
                "evidence_sha256": ZERO_SHA,
            }
        ],
        "created_at": NOW,
        "created_by": "admin_01",
    }
    return _hashed(value, "profile_sha256")


def test_item_origin_schema_and_typed_models_agree() -> None:
    organization = _organization()
    occurrence = _occurrence()
    profile = _origin_profile()

    validate_contract("organization-revision", organization)
    validate_contract("assessment-occurrence-revision", occurrence)
    validate_contract("item-origin-profile", profile)

    assert OrganizationRevision.model_validate(organization).revision_state == "REVIEWED"
    assert AssessmentOccurrenceRevision.model_validate(occurrence).administration_year == 2024
    assert ItemOriginProfile.model_validate(profile).creation_method == "IMPORTED"


@pytest.mark.parametrize(
    "member_path",
    ("/absolute.json", "../escape.json", "a/../b.json", "a\\b.json", "a//b.json"),
)
def test_origin_pointer_rejects_unsafe_member_path(member_path: str) -> None:
    value = _evidence()
    value["member_path"] = member_path
    with pytest.raises(ValidationError, match="safe relative POSIX path"):
        OriginArtifactMemberPointer.model_validate(value)


def test_organization_rejects_duplicate_alias_and_invalid_class_detail() -> None:
    duplicate = _organization()
    aliases = duplicate["aliases"]
    assert isinstance(aliases, list)
    aliases.append(deepcopy(aliases[0]))
    duplicate["revision_sha256"] = content_sha256(
        {key: value for key, value in duplicate.items() if key != "revision_sha256"}
    )
    with pytest.raises(ValidationError, match="aliases must be unique"):
        OrganizationRevision.model_validate(duplicate)

    detail = _organization()
    detail["class_detail"] = "불필요한 세부 분류"
    detail["revision_sha256"] = content_sha256(
        {key: value for key, value in detail.items() if key != "revision_sha256"}
    )
    with pytest.raises(ValidationError, match="only OTHER_REVIEWED"):
        OrganizationRevision.model_validate(detail)


def test_occurrence_rejects_date_outside_administration_year() -> None:
    value = _occurrence()
    value["administration_date"] = "2025-01-01"
    value["revision_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "revision_sha256"}
    )
    with pytest.raises(ValidationError, match="must match administration year"):
        AssessmentOccurrenceRevision.model_validate(value)


def test_origin_profile_enforces_method_specific_provenance() -> None:
    value = _origin_profile()
    value["creation_method"] = "AI_GENERATED"
    value["profile_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "profile_sha256"}
    )
    with pytest.raises(ValidationError, match="workflow provenance"):
        ItemOriginProfile.model_validate(value)

    imported = _origin_profile()
    imported["provenance"] = [
        {
            "provenance_kind": "MANUAL_REVIEW",
            "logical_id": "itemacceptance_" + "1" * 32,
            "revision_id": "rev_" + "2" * 32,
            "evidence_sha256": ZERO_SHA,
        }
    ]
    imported["profile_sha256"] = content_sha256(
        {key: item for key, item in imported.items() if key != "profile_sha256"}
    )
    with pytest.raises(ValidationError, match="Content Intake provenance"):
        ItemOriginProfile.model_validate(imported)


def test_origin_profile_rejects_duplicate_occurrence_revision_pointer() -> None:
    value = _origin_profile()
    occurrences = value["assessment_occurrences"]
    assert isinstance(occurrences, list)
    occurrences.append(deepcopy(occurrences[0]))
    value["profile_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "profile_sha256"}
    )
    with pytest.raises(ValidationError, match="sorted and unique"):
        ItemOriginProfile.model_validate(value)


@pytest.mark.parametrize(
    ("source_kind", "logical_id", "revision_id"),
    (
        ("ITEM_REVISION", "edudoc_" + "1" * 32, "itemrev_" + "1" * 32),
        ("DOCUMENT_REVISION", "edudoc_" + "1" * 32, "itemrev_" + "1" * 32),
        (
            "ASSESSMENT_SOURCE_BUNDLE_REVISION",
            "assessbundle_" + "1" * 32,
            "itemrev_" + "1" * 32,
        ),
    ),
)
def test_origin_profile_rejects_derivation_kind_pointer_mismatch(
    source_kind: str, logical_id: str, revision_id: str
) -> None:
    value = _origin_profile()
    value["derivations"] = [
        {
            "source_kind": source_kind,
            "logical_id": logical_id,
            "revision_id": revision_id,
            "manifest_sha256": ZERO_SHA,
            "relation": "DERIVED_FROM",
        }
    ]
    value["profile_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "profile_sha256"}
    )
    with pytest.raises(ValidationError, match="kind does not match"):
        ItemOriginProfile.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("item-origin-profile", value)


@pytest.mark.parametrize(
    ("kind", "logical_id", "revision_id"),
    (
        ("WORKFLOW", "intake_" + "1" * 32, "execplan_" + "1" * 32),
        ("CONTENT_INTAKE", "intake_" + "1" * 32, None),
        ("ITEM_PROVENANCE", "provenance_" + "1" * 32, "rev_" + "1" * 32),
        ("MANUAL_REVIEW", "itemacceptance_" + "1" * 32, None),
    ),
)
def test_origin_profile_rejects_provenance_kind_pointer_mismatch(
    kind: str, logical_id: str, revision_id: str | None
) -> None:
    value = _origin_profile()
    value["provenance"] = [
        {
            "provenance_kind": kind,
            "logical_id": logical_id,
            "revision_id": revision_id,
            "evidence_sha256": ZERO_SHA,
        }
    ]
    if kind != "CONTENT_INTAKE":
        value["creation_method"] = "UNKNOWN"
    value["profile_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "profile_sha256"}
    )
    with pytest.raises(ValidationError, match=r"evidence pointer|immutable row"):
        ItemOriginProfile.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("item-origin-profile", value)
