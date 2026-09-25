from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    build_training_crop_review_draft,
    content_sha256,
)
from eom_image_trainer.proposal_builder import (
    StagedVisualCropSource,
    build_training_crop_proposal_set,
)
from PIL import Image, ImageDraw


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(serial: int, *, role: str) -> ImageEvaluationArtifactMember:
    if role == "authorization":
        member = "manifests/training-authorization.json"
        schema = "eom://schemas/image-provider/local-image-training-authorization/1.0"
        media = "application/json"
    elif role == "holdout":
        member = "manifests/evaluation-plan.json"
        schema = "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"
        media = "application/json"
    elif role == "page":
        member = "pages/problem-1.png"
        schema = "eom://schemas/legacy-assessment/page-image/1.0"
        media = "image/png"
    else:
        member = "results/result.json"
        schema = "eom://schemas/legacy-assessment/item-extraction-result/1.0"
        media = "application/json"
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + f"{serial:032x}",
        artifact_revision_id="rev_" + f"{serial + 100:032x}",
        member_path=member,
        schema_ref=schema,
        media_type=media,
        sha256="sha256:" + f"{serial:064x}"[-64:],
    )


def _source() -> StagedVisualCropSource:
    image = Image.new("L", (1000, 1000), 255)
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((550, 220, 850, 760), outline=0, width=14)
    for offset in range(0, 180, 36):
        drawing.line((610 + offset, 300, 610 + offset, 680), fill=0, width=8)
    return StagedVisualCropSource(
        item_revision_id="itemrev_" + "1" * 32,
        extraction_result=_pointer(1, role="extraction"),
        source_anchor_id="assessmentanchor_" + "2" * 32,
        visual_pattern_ids=("visualpattern_" + "3" * 32,),
        source_page_image=_pointer(2, role="page"),
        physical_page=1,
        context_bounding_box=ImageEvaluationBoundingBox(
            left=0,
            top=0,
            right=10_000,
            bottom=10_000,
        ),
        rights_policy=ImageTrainingRightsPolicy(
            rights_policy_id="rightspolicy_" + "4" * 32,
            rights_policy_revision_id="rightspolicyrev_" + "5" * 32,
            rights_policy_sha256=_sha("6"),
        ),
        representation_kind="COMPOSITE",
        rendering_mode="RASTER",
        visual_features=(),
        page_image=image,
    )


def test_proposal_builder_emits_immutable_pending_population() -> None:
    holdout_samples = tuple("imgsample_" + f"{index + 100:032x}" for index in range(12))
    holdout_anchors = tuple("assessmentanchor_" + f"{index + 1000:032x}" for index in range(12))
    value = build_training_crop_proposal_set(
        sources=(_source(),),
        preliminary_omissions=(),
        source_snapshot=ImageEvaluationSourceSnapshot(
            graph_revision_id="graphrev_" + "7" * 32,
            graph_snapshot_sha256=_sha("8"),
            graph_manifest_sha256=_sha("9"),
            target_count=520,
            target_set_sha256=_sha("a"),
        ),
        training_authorization=_pointer(3, role="authorization"),
        holdout_evaluation_plan=_pointer(4, role="holdout"),
        holdout_sample_ids=holdout_samples,
        holdout_source_anchor_ids=holdout_anchors,
        created_at=datetime(2026, 9, 25, 13, 0, tzinfo=UTC),
        created_by="operator_test",
        ocr_locator=lambda _image: (),
    )
    assert value.proposals
    assert value.omissions == ()
    assert value.proposals[0].candidate_rank == 1
    assert not hasattr(value.proposals[0], "decision")
    assert value.proposal_set_id.startswith("imgcropproposalset_")
    proposal_pointer = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "f" * 32,
        member_path="manifests/crop-proposals.json",
        schema_ref=("eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0"),
        media_type="application/json",
        sha256=content_sha256(value.model_dump(mode="json")),
    )
    review = build_training_crop_review_draft(
        proposal_set=value,
        proposal_set_pointer=proposal_pointer,
        reviewed_at=datetime(2026, 9, 25, 13, 1, tzinfo=UTC),
        reviewed_by="operator_test",
    )
    assert review.review_state == "DRAFT"
    assert all(entry.decision == "PENDING" for entry in review.entries)
    assert review.proposal_set_sha256 == value.proposal_set_sha256


def test_proposal_builder_records_no_visual_region_without_eligibility_fallback() -> None:
    source = replace(_source(), page_image=Image.new("L", (1000, 1000), 255))
    holdout_samples = tuple("imgsample_" + f"{index + 100:032x}" for index in range(12))
    holdout_anchors = tuple("assessmentanchor_" + f"{index + 1000:032x}" for index in range(12))
    try:
        build_training_crop_proposal_set(
            sources=(source,),
            preliminary_omissions=(),
            source_snapshot=ImageEvaluationSourceSnapshot(
                graph_revision_id="graphrev_" + "7" * 32,
                graph_snapshot_sha256=_sha("8"),
                graph_manifest_sha256=_sha("9"),
                target_count=520,
                target_set_sha256=_sha("a"),
            ),
            training_authorization=_pointer(3, role="authorization"),
            holdout_evaluation_plan=_pointer(4, role="holdout"),
            holdout_sample_ids=holdout_samples,
            holdout_source_anchor_ids=holdout_anchors,
            created_at=datetime(2026, 9, 25, 13, 0, tzinfo=UTC),
            created_by="operator_test",
            ocr_locator=lambda _image: (),
        )
    except RuntimeError as exc:
        assert str(exc) == "IMAGE_TRAINING_CROP_PROPOSAL_SET_EMPTY"
    else:
        raise AssertionError("an empty crop proposal population was accepted")
