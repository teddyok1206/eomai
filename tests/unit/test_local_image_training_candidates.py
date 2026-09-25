from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_contracts import KnowledgeAnalysisResultV9, LegacyItemExtractionResult
from eom_catalog_service.local_image_training_candidates import (
    AcceptedVisualTrainingSource,
    TrainingCandidateProjectionError,
    build_training_candidate_inventory,
    project_training_eligibility_draft,
    select_training_visual_crop_sources,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    LocalImageTrainingEligibilityEntry,
    LocalImageTrainingEligibilityReview,
    content_sha256,
    text_sha256,
)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(serial: int, *, media_type: str = "application/json") -> ImageEvaluationArtifactMember:
    suffix = "png" if media_type == "image/png" else "json"
    return ImageEvaluationArtifactMember.model_validate(
        {
            "artifact_id": "artifact_" + f"{serial:032x}",
            "artifact_revision_id": "rev_" + f"{serial + 100:032x}",
            "member_path": f"source/member-{serial}.{suffix}",
            "schema_ref": f"eom://schemas/test/member/{serial}.0",
            "media_type": media_type,
            "sha256": "sha256:" + f"{serial:064x}"[-64:],
        }
    )


def _snapshot() -> ImageEvaluationSourceSnapshot:
    return ImageEvaluationSourceSnapshot.model_validate(
        {
            "graph_revision_id": "graphrev_" + "1" * 32,
            "graph_snapshot_sha256": _sha("2"),
            "graph_manifest_sha256": _sha("3"),
            "target_count": 1,
            "target_set_sha256": _sha("4"),
        }
    )


def _holdout_pointer() -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember.model_validate(
        {
            "artifact_id": "artifact_" + "e" * 32,
            "artifact_revision_id": "rev_" + "f" * 32,
            "member_path": "manifests/evaluation-plan.json",
            "schema_ref": ("eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"),
            "media_type": "application/json",
            "sha256": _sha("1"),
        }
    )


def _holdout_anchors(*, include_candidate: bool = False) -> tuple[str, ...]:
    anchors = ["assessmentanchor_" + f"{index + 9000:032x}" for index in range(12)]
    if include_candidate:
        anchors[0] = "assessmentanchor_" + "5" * 32
    return tuple(sorted(anchors))


def _source(
    *,
    extraction_hash: str = _sha("6"),
    include_bounding_box: bool = True,
    item_revision_character: str = "a",
    page_pointer_serial: int = 11,
) -> AcceptedVisualTrainingSource:
    extraction_pointer = _pointer(10)
    extraction_pointer = extraction_pointer.model_copy(update={"sha256": extraction_hash})
    page_pointer = _pointer(page_pointer_serial, media_type="image/png")
    bounding_box = ImageEvaluationBoundingBox(left=1000, top=2000, right=8000, bottom=7000)
    source_anchor = SimpleNamespace(
        anchor_id="assessmentanchor_" + "5" * 32,
        source_role="PROBLEM_DOCUMENT",
        physical_page=3,
        bounding_box=bounding_box if include_bounding_box else None,
    )
    pattern = SimpleNamespace(
        pattern_id="visualpattern_" + "7" * 32,
        representation_kind="PHOTOGRAPH",
        rendering_mode="RASTER",
        features=(),
        source_anchor_ids=(source_anchor.anchor_id,),
    )
    proposal = SimpleNamespace(
        item_proposal_id="itemproposal_" + "8" * 32,
        item_number=4,
        source_anchors=(source_anchor,),
        visual_patterns=(pattern,),
    )
    extraction = SimpleNamespace(
        extraction_result_id="itemextractresult_" + "9" * 32,
        result_sha256=extraction_hash,
        items=(proposal,),
    )
    page = SimpleNamespace(
        source_role="PROBLEM_DOCUMENT",
        physical_page=3,
        image=page_pointer,
    )
    accepted_source = SimpleNamespace(
        item_revision_id="itemrev_" + item_revision_character * 32,
        extraction_result_id=extraction.extraction_result_id,
        extraction_result_sha256=extraction_hash,
        extraction_result_artifact=extraction_pointer,
        item_proposal_id=proposal.item_proposal_id,
        item_number=proposal.item_number,
        page_inputs=(page,),
    )
    accepted = SimpleNamespace(source=accepted_source)
    rights = ImageTrainingRightsPolicy(
        rights_policy_id="rightspolicy_" + "b" * 32,
        rights_policy_revision_id="rightspolicyrev_" + "c" * 32,
        rights_policy_sha256=_sha("d"),
    )
    return AcceptedVisualTrainingSource(
        accepted=cast(KnowledgeAnalysisResultV9, accepted),
        extraction=cast(LegacyItemExtractionResult, extraction),
        rights_policy=rights,
    )


def _project(*, include_candidate_in_holdout: bool = False) -> LocalImageTrainingEligibilityReview:
    return project_training_eligibility_draft(
        sources=(_source(),),
        source_snapshot=_snapshot(),
        holdout_evaluation_plan=_holdout_pointer(),
        holdout_sample_ids=tuple("imgsample_" + f"{index + 10000:032x}" for index in range(12)),
        holdout_source_anchor_ids=_holdout_anchors(include_candidate=include_candidate_in_holdout),
        created_at=datetime(2026, 9, 25, 5, 0, tzinfo=UTC),
        created_by="operator_test",
    )


def test_projection_creates_only_pending_human_review_entries() -> None:
    review = _project()
    assert review.review_state == "DRAFT"
    assert len(review.entries) == 1
    entry = review.entries[0]
    assert entry.decision == "PENDING"
    assert entry.exclusion_reasons == ()
    assert entry.caption_en is None
    assert entry.visual_pattern_ids == ("visualpattern_" + "7" * 32,)
    assert review.eligible_candidate_set_sha256 == content_sha256([])


def test_projection_marks_holdout_anchor_excluded() -> None:
    review = _project(include_candidate_in_holdout=True)
    assert review.entries[0].decision == "EXCLUDED"
    assert review.entries[0].exclusion_reasons == ("HOLDOUT_OR_NEAR_DUPLICATE",)


def test_crop_source_selection_keeps_pending_raster_pointer_without_pixel_decision() -> None:
    selected, omissions = select_training_visual_crop_sources(
        sources=(_source(),),
        holdout_source_anchor_ids=_holdout_anchors(),
    )
    assert len(selected) == 1
    assert omissions == ()
    source = selected[0]
    assert source.source_anchor_id == "assessmentanchor_" + "5" * 32
    assert source.representation_kind == "PHOTOGRAPH"
    assert source.rendering_mode == "RASTER"
    assert source.context_bounding_box is not None


def test_crop_source_selection_records_holdout_as_omission() -> None:
    selected, omissions = select_training_visual_crop_sources(
        sources=(_source(),),
        holdout_source_anchor_ids=_holdout_anchors(include_candidate=True),
    )
    assert selected == ()
    assert len(omissions) == 1
    assert omissions[0].reason == "HOLDOUT_SOURCE"


def test_crop_source_selection_quarantines_globally_ambiguous_legacy_anchor() -> None:
    first = _source()
    second = _source(item_revision_character="d", page_pointer_serial=12)

    selected, omissions = select_training_visual_crop_sources(
        sources=(first, second),
        holdout_source_anchor_ids=_holdout_anchors(include_candidate=True),
    )

    assert selected == ()
    assert tuple(value.item_revision_id for value in omissions) == (
        "itemrev_" + "a" * 32,
        "itemrev_" + "d" * 32,
    )
    assert {value.source_anchor_id for value in omissions} == {"assessmentanchor_" + "5" * 32}
    assert {value.reason for value in omissions} == {"SOURCE_POINTER_INVALID"}


def test_projection_records_unbounded_anchor_as_explicit_omission() -> None:
    review = project_training_eligibility_draft(
        sources=(_source(include_bounding_box=False),),
        source_snapshot=_snapshot(),
        holdout_evaluation_plan=_holdout_pointer(),
        holdout_sample_ids=tuple("imgsample_" + f"{index + 10000:032x}" for index in range(12)),
        holdout_source_anchor_ids=_holdout_anchors(),
        created_at=datetime(2026, 9, 25, 5, 0, tzinfo=UTC),
        created_by="operator_test",
    )
    assert review.entries == ()
    assert len(review.projection_omissions) == 1
    assert review.projection_omissions[0].exclusion_reasons == ("AMBIGUOUS_CROP",)


def test_projection_rejects_extraction_hash_drift() -> None:
    source = _source()
    mismatched = AcceptedVisualTrainingSource(
        accepted=source.accepted,
        extraction=cast(
            LegacyItemExtractionResult,
            SimpleNamespace(
                extraction_result_id=source.extraction.extraction_result_id,
                result_sha256=_sha("e"),
                items=source.extraction.items,
            ),
        ),
        rights_policy=source.rights_policy,
    )
    with pytest.raises(
        TrainingCandidateProjectionError,
        match="IMAGE_TRAINING_EXTRACTION_POINTER_MISMATCH",
    ):
        project_training_eligibility_draft(
            sources=(mismatched,),
            source_snapshot=_snapshot(),
            holdout_evaluation_plan=_holdout_pointer(),
            holdout_sample_ids=tuple("imgsample_" + f"{index + 10000:032x}" for index in range(12)),
            holdout_source_anchor_ids=_holdout_anchors(),
            created_at=datetime(2026, 9, 25, 5, 0, tzinfo=UTC),
            created_by="operator_test",
        )


def test_final_review_derives_exact_candidate_inventory() -> None:
    draft = _project()
    pending = draft.entries[0]
    caption = "Side view of one nonhuman natural specimen."
    eligible = LocalImageTrainingEligibilityEntry.model_validate(
        {
            **pending.model_dump(mode="json"),
            "decision": "ELIGIBLE",
            "caption_en": caption,
            "caption_sha256": text_sha256(caption),
        }
    )
    body = {
        **draft.model_dump(mode="json", exclude={"review_sha256"}),
        "review_state": "FINAL",
        "entries": [eligible.model_dump(mode="json")],
        "eligible_candidate_set_sha256": content_sha256(
            [eligible.candidate().model_dump(mode="json")]
        ),
        "reviewed_at": "2026-09-25T05:01:00Z",
        "reviewed_by": "operator_reviewer",
    }
    review = LocalImageTrainingEligibilityReview.model_validate(
        {**body, "review_sha256": content_sha256(body)}
    )
    inventory = build_training_candidate_inventory(
        review=review,
        created_at=datetime(2026, 9, 25, 5, 2, tzinfo=UTC),
        created_by="operator_reviewer",
    )
    assert inventory.candidates == (eligible.candidate(),)
    assert inventory.source_snapshot == review.source_snapshot


def test_inventory_rejects_draft_review() -> None:
    with pytest.raises(
        TrainingCandidateProjectionError,
        match="IMAGE_TRAINING_ELIGIBILITY_REVIEW_NOT_FINAL",
    ):
        build_training_candidate_inventory(
            review=_project(),
            created_at=datetime(2026, 9, 25, 5, 2, tzinfo=UTC),
            created_by="operator_reviewer",
        )
