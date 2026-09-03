from __future__ import annotations

from eom_catalog_contracts import LegacyLearnedItemPointer
from eom_catalog_service.legacy_item_learning_service import LegacyItemLearningCoordinator
from eom_catalog_service.legacy_item_promotion_service import LegacyItemPromotion


def _promotion() -> LegacyItemPromotion:
    return LegacyItemPromotion(
        source=LegacyLearnedItemPointer.model_validate(
            {
                "item_id": "item_" + "1" * 32,
                "item_revision_id": "itemrev_" + "2" * 32,
                "item_manifest_sha256": "sha256:" + "3" * 64,
                "item_content": {
                    "artifact_id": "artifact_" + "4" * 32,
                    "artifact_revision_id": "rev_" + "5" * 32,
                    "member_path": "assessment-item-content.json",
                    "schema_ref": "eom://schemas/item-registry/assessment-item-content-v1",
                    "media_type": "application/json",
                    "sha256": "sha256:" + "6" * 64,
                },
                "extraction_acceptance_id": "itemacceptance_" + "7" * 32,
                "extraction_acceptance_sha256": "sha256:" + "8" * 64,
                "item_origin_profile_id": "originprofile_" + "9" * 32,
                "item_origin_profile_sha256": "sha256:" + "a" * 64,
                "lifecycle_state": "APPROVED",
            }
        ),
        item_created=True,
        origin_created=True,
    )


def test_analysis_identity_replays_only_the_same_item_policy_and_preset_revision() -> None:
    promoted = _promotion()
    first = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "c" * 32,
        requested_by="operator_learning",
    )
    replay = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "c" * 32,
        requested_by="operator_learning",
    )
    changed = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "d" * 32,
        requested_by="operator_learning",
    )

    assert first == replay
    assert first.source.source_class == "PAST_EXAM"
    assert first.general_knowledge_mode == "DISABLED"
    assert changed.idempotency_key != first.idempotency_key
