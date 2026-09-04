"""Bridge reviewed legacy-source rights evidence to the policy-pointer boundary.

The policy domain remains independently replaceable.  Until its dedicated registry exists,
this adapter resolves an exact immutable rights-review Artifact and exposes a deterministic,
one-to-one policy identity.  It never accepts an unbacked operator boolean or filesystem path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts import (
    LegacyRightsReviewPointerV2,
    LegacySourceRightsReviewV2,
    RightsPolicyPointer,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from eom_catalog_service.legacy_assessment_models import AssessmentSourceBundleRevisionRecord
from eom_catalog_service.legacy_source_selection_boundary import LegacyRightsReviewResolver


class LegacyAssessmentRightsError(RuntimeError):
    """Content-free fail-closed error for rights-policy projection."""


def rights_policy_pointer_from_review(
    review: LegacySourceRightsReviewV2,
) -> RightsPolicyPointer:
    """Project the exact review identity without truncating or re-hashing it."""

    return RightsPolicyPointer(
        rights_policy_id=("rightspolicy_" + review.rights_review_id.removeprefix("rightsreview_")),
        rights_policy_revision_id=(
            "rightspolicyrev_" + review.rights_review_revision_id.removeprefix("rightsreviewrev_")
        ),
        rights_policy_sha256=review.rights_review_sha256,
    )


@dataclass(frozen=True)
class _ResolvedPolicy:
    pointer: RightsPolicyPointer
    review: LegacySourceRightsReviewV2


class LegacyAssessmentRightsPolicyAdapter:
    """Resolve a small reviewed binding set and enforce assessment-corpus use."""

    def __init__(
        self,
        *,
        resolver: LegacyRightsReviewResolver,
        review_pointers: Iterable[LegacyRightsReviewPointerV2],
    ) -> None:
        policies: dict[tuple[str, str], _ResolvedPolicy] = {}
        try:
            for review_pointer in review_pointers:
                review = resolver.resolve(review_pointer)
                policy_pointer = rights_policy_pointer_from_review(review)
                key = (
                    policy_pointer.rights_policy_id,
                    policy_pointer.rights_policy_revision_id,
                )
                if key in policies:
                    raise LegacyAssessmentRightsError("duplicate rights policy binding")
                policies[key] = _ResolvedPolicy(pointer=policy_pointer, review=review)
        except LegacyAssessmentRightsError:
            raise
        except Exception as exc:
            raise LegacyAssessmentRightsError("rights review binding is unavailable") from exc
        if not policies:
            raise LegacyAssessmentRightsError("at least one rights review binding is required")
        self._policies = policies

    def verify(
        self,
        pointer: RightsPolicyPointer,
        *,
        intended_use: Literal["ORIGIN_REGISTRATION", "ASSESSMENT_CORPUS_ANALYSIS"],
    ) -> None:
        resolved = self._policies.get((pointer.rights_policy_id, pointer.rights_policy_revision_id))
        if resolved is None or resolved.pointer != pointer:
            raise LegacyAssessmentRightsError("rights policy pointer is stale")
        review = resolved.review
        allowed_roles = set(review.allowed_roles)
        if (
            review.document_type != "ASSESSMENT_ITEM"
            or review.rights_state not in {"CLEARED_INTERNAL", "CLEARED_LICENSED"}
            or not review.allowed_internal_processing
            or "ADMIN" not in allowed_roles
        ):
            raise LegacyAssessmentRightsError("rights review disallows assessment registration")
        if intended_use == "ASSESSMENT_CORPUS_ANALYSIS" and (
            not review.allowed_model_exposure
            or not review.allowed_page_image_materialization
            or "DATA_ANALYST_WORKER" not in allowed_roles
        ):
            raise LegacyAssessmentRightsError("rights review disallows assessment analysis")


class RegisteredAssessmentRightsPolicyResolver:
    """Resolve a policy only through an immutable, previously reviewed bundle revision.

    Bundle registration already validates the exact rights-review Artifact.  This resolver is for
    later promotion and origin-registration dereferences, where the dominant access is an indexed
    exact policy tuple lookup rather than repeated filesystem pointer configuration.
    """

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def verify(
        self,
        pointer: RightsPolicyPointer,
        *,
        intended_use: Literal["ORIGIN_REGISTRATION", "ASSESSMENT_CORPUS_ANALYSIS"],
    ) -> None:
        with self.sessions() as session:
            matches = tuple(
                session.scalars(
                    select(AssessmentSourceBundleRevisionRecord)
                    .where(
                        AssessmentSourceBundleRevisionRecord.rights_policy_id
                        == pointer.rights_policy_id,
                        AssessmentSourceBundleRevisionRecord.rights_policy_revision_id
                        == pointer.rights_policy_revision_id,
                        AssessmentSourceBundleRevisionRecord.rights_policy_sha256
                        == pointer.rights_policy_sha256,
                        AssessmentSourceBundleRevisionRecord.state.in_(("REVIEWED", "SUPERSEDED")),
                    )
                    .limit(1)
                )
            )
        if len(matches) != 1:
            raise LegacyAssessmentRightsError(
                f"registered rights policy is unavailable for {intended_use.lower()}"
            )
