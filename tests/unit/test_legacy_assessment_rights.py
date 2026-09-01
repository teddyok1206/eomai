from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    LegacyRightsReviewPointerV2,
    LegacySourceRightsReviewV2,
    RightsPolicyPointer,
)
from eom_catalog_service.legacy_assessment_rights import (
    LegacyAssessmentRightsError,
    LegacyAssessmentRightsPolicyAdapter,
    rights_policy_pointer_from_review,
)
from eom_identifiers import content_sha256


def _artifact_pointer(seed: str) -> dict[str, object]:
    return {
        "pointer_type": "ARTIFACT_MEMBER",
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": "source/problem.pdf",
        "schema_ref": "eom://schemas/legacy-assessment/source-document/1.0",
        "media_type": "application/pdf",
        "sha256": "sha256:" + seed * 64,
    }


def _review(*, model_exposure: bool = True) -> LegacySourceRightsReviewV2:
    value: dict[str, object] = {
        "schema_version": "legacy-source-rights-review/2.0",
        "rights_review_id": "rightsreview_" + "1" * 32,
        "rights_review_revision_id": "rightsreviewrev_" + "2" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source_owner_reference": "eom-authorized-assessment-corpus",
        "document_type": "ASSESSMENT_ITEM",
        "rights_state": "CLEARED_LICENSED",
        "allowed_internal_processing": True,
        "allowed_model_exposure": model_exposure,
        "allowed_roles": (
            ["ADMIN", "DATA_ANALYST_WORKER", "RIGHTS_REVIEWER"]
            if model_exposure
            else ["ADMIN", "RIGHTS_REVIEWER"]
        ),
        "allowed_excerpt_materialization": True,
        "allowed_page_image_materialization": True,
        "allowed_item_grounding": model_exposure,
        "answer_bearing": True,
        "retention_policy_key": "eom.assessment.licensed.internal.v1",
        "withdrawal_behavior": "RETIRE_FROM_NEW_RETRIEVAL",
        "source": {
            "pointer_type": "INVENTORY_ENTRY",
            "inventory_id": "legacyinventory_" + "3" * 32,
            "inventory_sha256": "sha256:" + "3" * 64,
            "entry_key": "legacyentry_" + "4" * 32,
            "content_sha256": "sha256:" + "4" * 64,
        },
        "evidence": [_artifact_pointer("5")],
        "reviewed_at": "2026-09-01T00:00:00Z",
        "reviewed_by": "rights-reviewer",
    }
    value["rights_review_sha256"] = content_sha256(value)
    return LegacySourceRightsReviewV2.model_validate(value)


def _pointer() -> LegacyRightsReviewPointerV2:
    return LegacyRightsReviewPointerV2.model_validate(
        {
            "pointer_type": "ARTIFACT_MEMBER",
            "artifact_id": "artifact_" + "6" * 32,
            "artifact_revision_id": "rev_" + "6" * 32,
            "member_path": "review/rights-review.json",
            "schema_ref": "eom://schemas/legacy-knowledge/rights-review/2.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "6" * 64,
        }
    )


class _Resolver:
    def __init__(self, review: LegacySourceRightsReviewV2) -> None:
        self.review = review

    def resolve(self, _pointer: LegacyRightsReviewPointerV2) -> LegacySourceRightsReviewV2:
        return self.review


def test_review_identity_projects_one_to_one_and_allows_reviewed_uses() -> None:
    review = _review()
    projected = rights_policy_pointer_from_review(review)
    assert projected.rights_policy_id.endswith("1" * 32)
    assert projected.rights_policy_revision_id.endswith("2" * 32)
    assert projected.rights_policy_sha256 == review.rights_review_sha256
    adapter = LegacyAssessmentRightsPolicyAdapter(
        resolver=_Resolver(review), review_pointers=(_pointer(),)
    )
    adapter.verify(projected, intended_use="ORIGIN_REGISTRATION")
    adapter.verify(projected, intended_use="ASSESSMENT_CORPUS_ANALYSIS")


def test_unbacked_or_hash_drifted_policy_pointer_fails_closed() -> None:
    review = _review()
    adapter = LegacyAssessmentRightsPolicyAdapter(
        resolver=_Resolver(review), review_pointers=(_pointer(),)
    )
    drifted = RightsPolicyPointer(
        **(
            rights_policy_pointer_from_review(review).model_dump(mode="json")
            | {"rights_policy_sha256": "sha256:" + "f" * 64}
        )
    )
    with pytest.raises(LegacyAssessmentRightsError, match="stale"):
        adapter.verify(drifted, intended_use="ASSESSMENT_CORPUS_ANALYSIS")


def test_review_without_worker_exposure_cannot_authorize_analysis() -> None:
    review = _review(model_exposure=False)
    adapter = LegacyAssessmentRightsPolicyAdapter(
        resolver=_Resolver(review), review_pointers=(_pointer(),)
    )
    adapter.verify(rights_policy_pointer_from_review(review), intended_use="ORIGIN_REGISTRATION")
    with pytest.raises(LegacyAssessmentRightsError, match="disallows assessment analysis"):
        adapter.verify(
            rights_policy_pointer_from_review(review),
            intended_use="ASSESSMENT_CORPUS_ANALYSIS",
        )


def test_duplicate_review_binding_is_rejected() -> None:
    review = _review()
    with pytest.raises(LegacyAssessmentRightsError, match="duplicate"):
        LegacyAssessmentRightsPolicyAdapter(
            resolver=_Resolver(review), review_pointers=(_pointer(), deepcopy(_pointer()))
        )
