from __future__ import annotations

import pytest
from eom_image_contracts import ImageEvaluationBoundingBox
from eom_image_trainer.crop_locator import (
    CropLocatorError,
    locate_visual_regions,
    parse_tesseract_tsv,
)
from PIL import Image, ImageDraw


def _tsv() -> bytes:
    return (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\t"
        b"height\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t40\t50\t300\t50\t95.0\tquestion\n"
        b"5\t1\t2\t1\t1\t1\t650\t300\t80\t40\t88.0\tA\n"
    )


def test_parse_tesseract_tsv_returns_only_bounded_confident_boxes() -> None:
    boxes = parse_tesseract_tsv(_tsv(), width=1000, height=1000)
    assert len(boxes) == 2
    assert boxes == tuple(sorted(boxes, key=lambda value: (value.top, value.left)))


def test_parse_tesseract_tsv_rejects_out_of_bounds_box() -> None:
    payload = _tsv().replace(b"650\t300\t80\t40", b"980\t300\t80\t40")
    with pytest.raises(CropLocatorError, match="IMAGE_TRAINING_OCR_RESULT_INVALID"):
        parse_tesseract_tsv(payload, width=1000, height=1000)


def test_locator_proposes_visual_region_and_exact_embedded_redaction() -> None:
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for offset in range(0, 180, 30):
        draw.line((600 + offset, 300, 600 + offset, 700), fill=0, width=8)
    draw.ellipse((560, 260, 820, 740), outline=0, width=12)
    draw.rectangle((650, 300, 730, 340), fill=0)
    ocr_boxes = parse_tesseract_tsv(_tsv(), width=1000, height=1000)
    result = locate_visual_regions(
        image,
        context_bounding_box=ImageEvaluationBoundingBox(
            left=0,
            top=0,
            right=10_000,
            bottom=10_000,
        ),
        ocr_boxes=ocr_boxes,
    )
    assert result
    first = result[0]
    assert first.candidate_rank == 1
    assert first.crop_bounding_box.left >= 5000
    assert first.crop_bounding_box.right <= 9000
    assert first.redaction_boxes
    assert first.ink_fraction_milli > 0


def test_locator_is_deterministic_and_never_decides_eligibility() -> None:
    image = Image.new("L", (400, 400), 255)
    ImageDraw.Draw(image).rectangle((100, 100, 300, 300), outline=0, width=10)
    first = locate_visual_regions(image, context_bounding_box=None, ocr_boxes=())
    second = locate_visual_regions(image, context_bounding_box=None, ocr_boxes=())
    assert first == second
    assert all(not hasattr(value, "decision") for value in first)
