from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import eom_orchestrator.local_image_training_control_artifacts as control_artifacts
from eom_catalog_service.local_image_training_authorization import build_training_authorization
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    content_json_bytes,
)
from eom_orchestrator.local_image_training_control_artifacts import (
    AUTHORIZATION_ARTIFACT_TYPE,
    SCIENCE_CAMPAIGN_RASTER_REFINEMENT_PLAN_ARTIFACT_TYPE,
    SCIENCE_CAMPAIGN_RASTER_REFINEMENT_PLAN_MEMBER,
    SCIENCE_CAMPAIGN_RASTER_SUITABILITY_REVIEW_ARTIFACT_TYPE,
    SCIENCE_CAMPAIGN_RASTER_SUITABILITY_REVIEW_MEMBER,
    SCIENCE_CORPUS_AUTHORIZATION_ARTIFACT_TYPE,
    SCIENCE_CORPUS_AUTHORIZATION_MEMBER,
    SCIENCE_MICRO_PROBE_PLAN_ARTIFACT_TYPE,
    SCIENCE_MICRO_PROBE_PLAN_MEMBER,
    SCIENCE_RASTER_REFINEMENT_PLAN_ARTIFACT_TYPE,
    SCIENCE_RASTER_REFINEMENT_PLAN_MEMBER,
    SCIENCE_RASTER_SUITABILITY_REVIEW_ARTIFACT_TYPE,
    SCIENCE_RASTER_SUITABILITY_REVIEW_MEMBER,
    SCIENCE_VISUAL_CAMPAIGN_PATTERN_INVENTORY_ARTIFACT_TYPE,
    SCIENCE_VISUAL_CAMPAIGN_PATTERN_INVENTORY_MEMBER,
    SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_COMMAND_ARTIFACT_TYPE,
    SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_COMMAND_MEMBER,
    SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_RESULT_ARTIFACT_TYPE,
    SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_RESULT_MEMBER,
    SCIENCE_VISUAL_PATTERN_INVENTORY_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PATTERN_INVENTORY_MEMBER,
    SCIENCE_VISUAL_PATTERN_INVENTORY_V2_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PILOT_PLAN_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PILOT_PLAN_MEMBER,
    SCIENCE_VISUAL_PILOT_PLAN_V2_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PILOT_PLAN_V3_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PILOT_RESULT_ARTIFACT_TYPE,
    SCIENCE_VISUAL_PILOT_RESULT_MEMBER,
    LocalImageTrainingControlArtifactPublisher,
)
from eom_workflow import ControlArtifactPointer
from pydantic import BaseModel


class _Publisher:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def publish_bytes(self, **kwargs: object) -> object:
        self.arguments = kwargs
        payload = kwargs["payload"]
        assert isinstance(payload, bytes)
        schema_ref = kwargs["schema_ref"]
        logical_name = kwargs["logical_name"]
        assert isinstance(schema_ref, str)
        assert isinstance(logical_name, str)
        return SimpleNamespace(
            pointer=ControlArtifactPointer(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                sha256=sha256_bytes(payload),
                schema_ref=schema_ref,
                media_type="application/json",
                logical_name=logical_name,
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
    payload = content_json_bytes(authorization.model_dump(mode="json"))
    assert publisher.arguments["payload"] == payload
    assert publisher.arguments["artifact_type"] == AUTHORIZATION_ARTIFACT_TYPE
    assert publisher.arguments["idempotency_key"] == (
        "local-image-training-authorization:"
        + authorization.authorization_sha256.removeprefix("sha256:")
    )
    assert pointer.sha256 == sha256_bytes(payload)


def test_image_control_artifact_uses_image_contract_number_encoding(monkeypatch) -> None:
    class _FloatControl(BaseModel):
        guidance_scale: float

    monkeypatch.setattr(control_artifacts, "validate_contract", lambda *_args: None)
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(
        publisher,  # type: ignore[arg-type]
        source_commit="a" * 40,
    )
    value = _FloatControl(guidance_scale=7.5)

    pointer = adapter._commit_document(
        value=value,
        contract_name="quality-evaluation-plan",
        member="manifests/test-float.json",
        schema_ref="eom://schemas/image-provider/test-float/1.0",
        artifact_type="control_local_image_test_float",
        idempotency_prefix="local-image-test-float",
        identity_sha256="sha256:" + "f" * 64,
        created_at=datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
    )

    expected = content_json_bytes({"guidance_scale": 7.5})
    assert publisher.arguments["payload"] == expected
    assert pointer.sha256 == sha256_bytes(expected)


def test_science_visual_controls_use_orchestrator_publication_boundary(monkeypatch) -> None:
    class _ScienceAuthorization(BaseModel):
        authorization_sha256: str
        approved_at: datetime

    class _SciencePlan(BaseModel):
        plan_sha256: str
        created_at: datetime

    class _ScienceResult(BaseModel):
        result_sha256: str
        completed_at: datetime

    class _ScienceCampaignBatchCommand(BaseModel):
        command_sha256: str
        created_at: datetime

    class _ScienceInventory(BaseModel):
        inventory_sha256: str
        created_at: datetime

    class _ScienceRasterSuitabilityReview(BaseModel):
        review_sha256: str
        reviewed_at: datetime

    class _ScienceRasterRefinementPlan(BaseModel):
        plan_sha256: str
        created_at: datetime

    monkeypatch.setattr(control_artifacts, "validate_contract", lambda *_args: None)
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(
        publisher,  # type: ignore[arg-type]
        source_commit="a" * 40,
    )
    authorization = _ScienceAuthorization(
        authorization_sha256="sha256:" + "b" * 64,
        approved_at=datetime(2026, 9, 25, 18, 0, tzinfo=UTC),
    )
    authorization_pointer = adapter.commit_science_corpus_authorization(
        authorization  # type: ignore[arg-type]
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_CORPUS_AUTHORIZATION_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_CORPUS_AUTHORIZATION_MEMBER
    assert authorization_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    plan = _SciencePlan(
        plan_sha256="sha256:" + "c" * 64,
        created_at=datetime(2026, 9, 25, 18, 5, tzinfo=UTC),
    )
    plan_pointer = adapter.commit_science_visual_pilot_plan(plan)  # type: ignore[arg-type]
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PILOT_PLAN_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PILOT_PLAN_MEMBER
    assert plan_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    plan_v2_pointer = adapter.commit_science_visual_pilot_plan_v2(  # type: ignore[arg-type]
        plan
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PILOT_PLAN_V2_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PILOT_PLAN_MEMBER
    assert plan_v2_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    plan_v3_pointer = adapter.commit_science_visual_pilot_plan_v3(  # type: ignore[arg-type]
        plan
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PILOT_PLAN_V3_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PILOT_PLAN_MEMBER
    assert plan_v3_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    science_micro_pointer = adapter.commit_science_micro_probe_plan(  # type: ignore[arg-type]
        plan
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_MICRO_PROBE_PLAN_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_MICRO_PROBE_PLAN_MEMBER
    assert science_micro_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    result = _ScienceResult(
        result_sha256="sha256:" + "d" * 64,
        completed_at=datetime(2026, 9, 25, 18, 10, tzinfo=UTC),
    )
    result_pointer = adapter.commit_science_visual_pilot_result(  # type: ignore[arg-type]
        result
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PILOT_RESULT_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PILOT_RESULT_MEMBER
    assert result_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    inventory = _ScienceInventory(
        inventory_sha256="sha256:" + "e" * 64,
        created_at=datetime(2026, 9, 25, 18, 15, tzinfo=UTC),
    )
    inventory_pointer = adapter.commit_science_visual_pattern_inventory(
        inventory  # type: ignore[arg-type]
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PATTERN_INVENTORY_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PATTERN_INVENTORY_MEMBER
    assert inventory_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    inventory_v2_pointer = adapter.commit_science_visual_pattern_inventory_v2(
        inventory  # type: ignore[arg-type]
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_VISUAL_PATTERN_INVENTORY_V2_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_PATTERN_INVENTORY_MEMBER
    assert inventory_v2_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    campaign_inventory_pointer = adapter.commit_science_visual_campaign_pattern_inventory(
        inventory  # type: ignore[arg-type]
    )
    assert (
        publisher.arguments["artifact_type"]
        == SCIENCE_VISUAL_CAMPAIGN_PATTERN_INVENTORY_ARTIFACT_TYPE
    )
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_CAMPAIGN_PATTERN_INVENTORY_MEMBER
    assert campaign_inventory_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    campaign_batch_command = _ScienceCampaignBatchCommand(
        command_sha256="sha256:" + "d" * 64,
        created_at=datetime(2026, 9, 25, 18, 11, tzinfo=UTC),
    )
    campaign_batch_command_pointer = adapter.commit_science_visual_campaign_review_batch_command(
        campaign_batch_command  # type: ignore[arg-type]
    )
    assert (
        publisher.arguments["artifact_type"]
        == SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_COMMAND_ARTIFACT_TYPE
    )
    assert (
        publisher.arguments["logical_name"] == SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_COMMAND_MEMBER
    )
    assert campaign_batch_command_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    campaign_batch_result_pointer = adapter.commit_science_visual_campaign_review_batch_result(
        result  # type: ignore[arg-type]
    )
    assert (
        publisher.arguments["artifact_type"]
        == SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_RESULT_ARTIFACT_TYPE
    )
    assert publisher.arguments["logical_name"] == SCIENCE_VISUAL_CAMPAIGN_REVIEW_BATCH_RESULT_MEMBER
    assert campaign_batch_result_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    raster_review = _ScienceRasterSuitabilityReview(
        review_sha256="sha256:" + "f" * 64,
        reviewed_at=datetime(2026, 9, 26, 6, 0, tzinfo=UTC),
    )
    raster_review_pointer = adapter.commit_science_raster_suitability_review(
        raster_review  # type: ignore[arg-type]
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_RASTER_SUITABILITY_REVIEW_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_RASTER_SUITABILITY_REVIEW_MEMBER
    assert raster_review_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    campaign_raster_review_pointer = adapter.commit_science_campaign_raster_suitability_review(
        raster_review  # type: ignore[arg-type]
    )
    assert (
        publisher.arguments["artifact_type"]
        == SCIENCE_CAMPAIGN_RASTER_SUITABILITY_REVIEW_ARTIFACT_TYPE
    )
    assert publisher.arguments["logical_name"] == SCIENCE_CAMPAIGN_RASTER_SUITABILITY_REVIEW_MEMBER
    assert campaign_raster_review_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    refinement_plan = _ScienceRasterRefinementPlan(
        plan_sha256="sha256:" + "0" * 64,
        created_at=datetime(2026, 9, 26, 7, 0, tzinfo=UTC),
    )
    refinement_pointer = adapter.commit_science_raster_refinement_plan(
        refinement_plan  # type: ignore[arg-type]
    )
    assert publisher.arguments["artifact_type"] == SCIENCE_RASTER_REFINEMENT_PLAN_ARTIFACT_TYPE
    assert publisher.arguments["logical_name"] == SCIENCE_RASTER_REFINEMENT_PLAN_MEMBER
    assert refinement_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])

    campaign_refinement_pointer = adapter.commit_science_campaign_raster_refinement_plan(
        refinement_plan  # type: ignore[arg-type]
    )
    assert (
        publisher.arguments["artifact_type"]
        == SCIENCE_CAMPAIGN_RASTER_REFINEMENT_PLAN_ARTIFACT_TYPE
    )
    assert publisher.arguments["logical_name"] == SCIENCE_CAMPAIGN_RASTER_REFINEMENT_PLAN_MEMBER
    assert campaign_refinement_pointer.sha256 == sha256_bytes(publisher.arguments["payload"])
