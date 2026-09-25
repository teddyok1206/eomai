"""Orchestrator-only publication of reviewed local-image training control values."""

from __future__ import annotations

import re

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageTrainingAuthorization,
    validate_contract,
)

from eom_orchestrator.control_artifacts import ControlArtifactPublisher

AUTHORIZATION_MEMBER = "manifests/training-authorization.json"
AUTHORIZATION_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-authorization/1.0"
AUTHORIZATION_ARTIFACT_TYPE = "control_local_image_training_authorization"
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
        document = authorization.model_dump(mode="json")
        validate_contract("training-authorization", document)
        payload = canonical_json_bytes(document)
        digest = sha256_bytes(payload)
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=AUTHORIZATION_MEMBER,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            media_type="application/json",
            artifact_type=AUTHORIZATION_ARTIFACT_TYPE,
            idempotency_key=(
                "local-image-training-authorization:"
                + authorization.authorization_sha256.removeprefix("sha256:")
            ),
            created_at=authorization.approved_at,
            source_commit=self.source_commit,
        )
        pointer = published.pointer
        if (
            pointer.logical_name != AUTHORIZATION_MEMBER
            or pointer.schema_ref != AUTHORIZATION_SCHEMA_REF
            or pointer.media_type != "application/json"
            or pointer.sha256 != digest
        ):
            raise ValueError("orchestrator returned a drifted training authorization pointer")
        return ImageEvaluationArtifactMember(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=AUTHORIZATION_MEMBER,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            media_type="application/json",
            sha256=digest,
        )
