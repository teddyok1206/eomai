"""Orchestrator-only publication of reviewed local-image training control values."""

from __future__ import annotations

import re
from datetime import datetime

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageQualityEvaluationPlan,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCropProposalSet,
    LocalImageTrainingCropReview,
    validate_contract,
)
from pydantic import BaseModel

from eom_orchestrator.control_artifacts import ControlArtifactPublisher

AUTHORIZATION_MEMBER = "manifests/training-authorization.json"
AUTHORIZATION_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-authorization/1.0"
AUTHORIZATION_ARTIFACT_TYPE = "control_local_image_training_authorization"
EVALUATION_PLAN_MEMBER = "manifests/evaluation-plan.json"
EVALUATION_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"
EVALUATION_PLAN_ARTIFACT_TYPE = "control_local_image_quality_evaluation_plan"
CROP_PROPOSAL_MEMBER = "manifests/crop-proposals.json"
CROP_PROPOSAL_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0"
CROP_PROPOSAL_ARTIFACT_TYPE = "control_local_image_training_crop_proposals"
CROP_REVIEW_MEMBER = "manifests/crop-review.json"
CROP_REVIEW_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-crop-review/1.0"
CROP_REVIEW_ARTIFACT_TYPE = "control_local_image_training_crop_review"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class LocalImageTrainingControlArtifactPublisher:
    """Adapt one approved value to the sole NAS-writing Orchestrator boundary."""

    def __init__(self, publisher: ControlArtifactPublisher, *, source_commit: str) -> None:
        if _COMMIT.fullmatch(source_commit) is None:
            raise ValueError("local-image training source commit is invalid")
        self.publisher = publisher
        self.source_commit = source_commit

    def commit_authorization(
        self,
        authorization: LocalImageTrainingAuthorization,
    ) -> ImageEvaluationArtifactMember:
        return self._commit_document(
            value=authorization,
            contract_name="training-authorization",
            member=AUTHORIZATION_MEMBER,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            artifact_type=AUTHORIZATION_ARTIFACT_TYPE,
            idempotency_prefix="local-image-training-authorization",
            identity_sha256=authorization.authorization_sha256,
            created_at=authorization.approved_at,
        )

    def commit_evaluation_plan(
        self,
        plan: LocalImageQualityEvaluationPlan,
    ) -> ImageEvaluationArtifactMember:
        return self._commit_document(
            value=plan,
            contract_name="quality-evaluation-plan",
            member=EVALUATION_PLAN_MEMBER,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            artifact_type=EVALUATION_PLAN_ARTIFACT_TYPE,
            idempotency_prefix="local-image-quality-evaluation-plan",
            identity_sha256=plan.plan_sha256,
            created_at=plan.created_at,
        )

    def commit_crop_proposal_set(
        self,
        proposal_set: LocalImageTrainingCropProposalSet,
    ) -> ImageEvaluationArtifactMember:
        return self._commit_document(
            value=proposal_set,
            contract_name="training-crop-proposal-set",
            member=CROP_PROPOSAL_MEMBER,
            schema_ref=CROP_PROPOSAL_SCHEMA_REF,
            artifact_type=CROP_PROPOSAL_ARTIFACT_TYPE,
            idempotency_prefix="local-image-training-crop-proposals",
            identity_sha256=proposal_set.proposal_set_sha256,
            created_at=proposal_set.created_at,
        )

    def commit_crop_review(
        self,
        review: LocalImageTrainingCropReview,
    ) -> ImageEvaluationArtifactMember:
        return self._commit_document(
            value=review,
            contract_name="training-crop-review",
            member=CROP_REVIEW_MEMBER,
            schema_ref=CROP_REVIEW_SCHEMA_REF,
            artifact_type=CROP_REVIEW_ARTIFACT_TYPE,
            idempotency_prefix="local-image-training-crop-review",
            identity_sha256=review.review_sha256,
            created_at=review.reviewed_at,
        )

    def _commit_document(
        self,
        *,
        value: BaseModel,
        contract_name: str,
        member: str,
        schema_ref: str,
        artifact_type: str,
        idempotency_prefix: str,
        identity_sha256: str,
        created_at: datetime,
    ) -> ImageEvaluationArtifactMember:
        document = value.model_dump(mode="json")
        validate_contract(contract_name, document)
        payload = canonical_json_bytes(document)
        digest = sha256_bytes(payload)
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=member,
            schema_ref=schema_ref,
            media_type="application/json",
            artifact_type=artifact_type,
            idempotency_key=(idempotency_prefix + ":" + identity_sha256.removeprefix("sha256:")),
            created_at=created_at,
            source_commit=self.source_commit,
        )
        pointer = published.pointer
        if (
            pointer.logical_name != member
            or pointer.schema_ref != schema_ref
            or pointer.media_type != "application/json"
            or pointer.sha256 != digest
        ):
            raise ValueError("orchestrator returned a drifted local-image control pointer")
        return ImageEvaluationArtifactMember(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=member,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=digest,
        )
