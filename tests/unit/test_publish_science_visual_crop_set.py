from __future__ import annotations

from pathlib import Path

import pytest
from eom_image_contracts import ScienceVisualReviewedCropMember, text_sha256

from scripts.image_trainer.publish_science_visual_crop_set import (
    ScienceVisualCropSetPublicationError,
    _InspectedCandidate,
    _safe_read,
    _select_group_representatives,
)


def _candidate(
    index: int,
    *,
    group: str,
    partition: str,
    perceptual_value: int,
) -> _InspectedCandidate:
    candidate_id = f"imgsciviscandidate_{index:032x}"
    caption = f"Science raster example {index}"
    return _InspectedCandidate(
        member=ScienceVisualReviewedCropMember.model_validate(
            {
                "candidate_id": candidate_id,
                "document_id": f"sciencedoc_{index:032x}",
                "physical_page": 1,
                "exam_group_sha256": group,
                "partition": partition,
                "pattern_family": "NATURAL_TEXTURE",
                "member_path": f"crops/{candidate_id}.png",
                "media_type": "image/png",
                "width_px": 320,
                "height_px": 240,
                "size_bytes": 128,
                "sha256": f"sha256:{index:064x}",
                "caption_en": caption,
                "caption_sha256": text_sha256(caption),
                "perceptual_hash": f"{perceptual_value:016x}",
            }
        ),
        source=Path(f"/tmp/{candidate_id}.png"),
        perceptual_value=perceptual_value,
    )


def test_group_selection_is_partition_ordered_unique_and_deterministic() -> None:
    train_group = "sha256:" + "1" * 64
    validation_group = "sha256:" + "2" * 64
    holdout_group = "sha256:" + "3" * 64
    values = (
        _candidate(30, group=holdout_group, partition="HOLDOUT", perceptual_value=0xF0F0),
        _candidate(20, group=validation_group, partition="VALIDATION", perceptual_value=0x00F0),
        _candidate(11, group=train_group, partition="TRAIN", perceptual_value=0x0001),
        _candidate(10, group=train_group, partition="TRAIN", perceptual_value=0x0000),
    )

    selected = _select_group_representatives(values)

    assert [value.member.candidate_id for value in selected] == sorted(
        [
            f"imgsciviscandidate_{10:032x}",
            f"imgsciviscandidate_{20:032x}",
            f"imgsciviscandidate_{30:032x}",
        ]
    )
    assert len({value.member.exam_group_sha256 for value in selected}) == 3


def test_group_selection_uses_later_candidate_when_first_is_near_duplicate() -> None:
    first_group = "sha256:" + "1" * 64
    second_group = "sha256:" + "2" * 64
    values = (
        _candidate(1, group=first_group, partition="TRAIN", perceptual_value=0),
        _candidate(2, group=second_group, partition="TRAIN", perceptual_value=1),
        _candidate(3, group=second_group, partition="TRAIN", perceptual_value=0xFFFF),
    )

    selected = _select_group_representatives(values)

    assert {value.member.candidate_id for value in selected} == {
        f"imgsciviscandidate_{1:032x}",
        f"imgsciviscandidate_{3:032x}",
    }


def test_group_selection_rejects_near_duplicate_only_group() -> None:
    values = (
        _candidate(
            1,
            group="sha256:" + "1" * 64,
            partition="TRAIN",
            perceptual_value=0,
        ),
        _candidate(
            2,
            group="sha256:" + "2" * 64,
            partition="TRAIN",
            perceptual_value=1,
        ),
    )

    with pytest.raises(ScienceVisualCropSetPublicationError, match="NEAR_DUPLICATE"):
        _select_group_representatives(values)


def test_group_selection_rejects_cross_partition_group() -> None:
    group = "sha256:" + "1" * 64
    values = (
        _candidate(1, group=group, partition="TRAIN", perceptual_value=0),
        _candidate(2, group=group, partition="HOLDOUT", perceptual_value=0xFFFF),
    )

    with pytest.raises(ScienceVisualCropSetPublicationError, match="GROUP_PARTITION_INVALID"):
        _select_group_representatives(values)


def test_safe_read_rejects_group_writable_and_accepts_frozen_file(tmp_path: Path) -> None:
    source = tmp_path / "crop.png"
    source.write_bytes(b"not-a-real-png")
    source.chmod(0o620)
    with pytest.raises(ScienceVisualCropSetPublicationError, match="MEMBER_INVALID"):
        _safe_read(source, maximum_bytes=1024)

    source.chmod(0o600)
    assert _safe_read(source, maximum_bytes=1024) == b"not-a-real-png"
