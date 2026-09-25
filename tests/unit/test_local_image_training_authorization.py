from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_service.local_image_training_authorization import (
    LocalImageTrainingAuthorizationError,
    build_training_authorization,
)
from eom_image_contracts import ImageEvaluationSourceSnapshot, ImageTrainingRightsPolicy


def _snapshot() -> ImageEvaluationSourceSnapshot:
    return ImageEvaluationSourceSnapshot(
        graph_revision_id="graphrev_" + "1" * 32,
        graph_snapshot_sha256="sha256:" + "2" * 64,
        graph_manifest_sha256="sha256:" + "3" * 64,
        target_count=520,
        target_set_sha256="sha256:" + "4" * 64,
    )


def _rights(index: int) -> ImageTrainingRightsPolicy:
    return ImageTrainingRightsPolicy(
        rights_policy_id="rightspolicy_" + f"{index:032x}",
        rights_policy_revision_id="rightspolicyrev_" + f"{index:032x}",
        rights_policy_sha256="sha256:" + f"{index:064x}",
    )


def test_build_authorization_is_deterministic_and_bounded() -> None:
    approved_at = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    authorization = build_training_authorization(
        source_snapshot=_snapshot(),
        rights_policies=(_rights(1), _rights(2)),
        approved_at=approved_at,
        approved_by="owner_explicit_chat",
    )
    replay = build_training_authorization(
        source_snapshot=_snapshot(),
        rights_policies=(_rights(1), _rights(2)),
        approved_at=approved_at,
        approved_by="owner_explicit_chat",
    )
    assert replay == authorization
    assert authorization.permitted_use == "INTERNAL_LORA_TRAINING"
    assert authorization.derivative_output == "LORA_ADAPTER_ONLY"
    assert authorization.source_snapshot.target_count == 520


def test_build_authorization_rejects_non_utc_approval() -> None:
    with pytest.raises(
        LocalImageTrainingAuthorizationError,
        match="IMAGE_TRAINING_AUTHORIZATION_INVALID",
    ):
        build_training_authorization(
            source_snapshot=_snapshot(),
            rights_policies=(_rights(1),),
            approved_at=datetime(2026, 9, 25, 8, 0),
            approved_by="owner_explicit_chat",
        )
