from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from eom_catalog_service.local_image_training_authorization import build_training_authorization
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_image_contracts import ImageEvaluationSourceSnapshot, ImageTrainingRightsPolicy
from eom_orchestrator.local_image_training_control_artifacts import (
    AUTHORIZATION_ARTIFACT_TYPE,
    AUTHORIZATION_MEMBER,
    AUTHORIZATION_SCHEMA_REF,
    LocalImageTrainingControlArtifactPublisher,
)
from eom_workflow import ControlArtifactPointer


class _Publisher:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def publish_bytes(self, **kwargs: object) -> object:
        self.arguments = kwargs
        payload = kwargs["payload"]
        assert isinstance(payload, bytes)
        return SimpleNamespace(
            pointer=ControlArtifactPointer(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                sha256=sha256_bytes(payload),
                schema_ref=AUTHORIZATION_SCHEMA_REF,
                media_type="application/json",
                logical_name=AUTHORIZATION_MEMBER,
            )
        )


def _authorization():
    return build_training_authorization(
        source_snapshot=ImageEvaluationSourceSnapshot(
            graph_revision_id="graphrev_" + "3" * 32,
            graph_snapshot_sha256="sha256:" + "4" * 64,
            graph_manifest_sha256="sha256:" + "5" * 64,
            target_count=520,
            target_set_sha256="sha256:" + "6" * 64,
        ),
        rights_policies=(
            ImageTrainingRightsPolicy(
                rights_policy_id="rightspolicy_" + "7" * 32,
                rights_policy_revision_id="rightspolicyrev_" + "8" * 32,
                rights_policy_sha256="sha256:" + "9" * 64,
            ),
        ),
        approved_at=datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
        approved_by="owner_explicit_chat",
    )


def test_authorization_uses_orchestrator_control_artifact_boundary() -> None:
    publisher = _Publisher()
    authorization = _authorization()
    adapter = LocalImageTrainingControlArtifactPublisher(
        publisher,  # type: ignore[arg-type]
        source_commit="a" * 40,
    )
    pointer = adapter.commit_authorization(authorization)
    payload = canonical_json_bytes(authorization.model_dump(mode="json"))
    assert publisher.arguments["payload"] == payload
    assert publisher.arguments["artifact_type"] == AUTHORIZATION_ARTIFACT_TYPE
    assert publisher.arguments["idempotency_key"] == (
        "local-image-training-authorization:"
        + authorization.authorization_sha256.removeprefix("sha256:")
    )
    assert pointer.sha256 == sha256_bytes(payload)
