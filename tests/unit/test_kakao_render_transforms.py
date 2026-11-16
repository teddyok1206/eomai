"""Explicit human transforms and ordered flow; synthetic pixels, no private image edits."""

from __future__ import annotations

import io
import json

import pymupdf
import pytest
from eom_kakao_archive_contracts import RenderManifest, sha256
from eom_kakao_archive_contracts.layout import RenderLayoutReceipt, check_layout_receipt
from eom_kakao_archive_contracts.validation import validate_contract
from eom_kakao_archive_worker.question_pdf import render_questions
from PIL import Image

from tests.unit.test_kakao_question_render import RELEASE, identity, local_file
from tests.unit.test_kakao_question_render import prepared as prepared


def photo(root, *, exif=False):
    with Image.new("RGB", (80, 120), "red") as original:
        original.paste("green", (40, 0, 80, 60))
        original.paste("blue", (0, 60, 40, 120))
        original.paste("yellow", (40, 60, 80, 120))
        raw = io.BytesIO()
        metadata = Image.Exif()
        if exif:
            metadata[274] = 6
        original.save(raw, format="PNG", exif=metadata)
    member = local_file(root, "quadrants.png", raw.getvalue(), "image/png")
    return {
        "attachment_occurrence_id": identity("attachment"),
        "attachment_revision_id": identity("attachmentrev"),
        "member": member,
        "availability": "AVAILABLE",
        "quality_accepted": True,
    }


def transform(rotation=90, crop=None):
    return {
        "transform_revision_id": identity("transformrev"),
        "operation_order": "EXIF_THEN_ROTATE_THEN_CROP",
        "rotate_clockwise": rotation,
        "crop": crop,
    }


def actual(prepared, change):
    source, output, prepare = prepared
    command = prepare(change)
    result = render_questions(
        command, input_root=source, output_root=output, renderer_release_sha256=RELEASE
    )
    assert result.status == "COMPLETED", result.error_code
    layout = json.loads((output / "layout.json").read_bytes())
    return command, result, layout


def test_rotate_then_explicit_crop_preserves_source_and_expected_pdf_pixels(prepared):
    source, output, _ = prepared
    image = photo(source)
    original = (source / "quadrants.png").read_bytes()
    image["transform"] = transform(
        crop={"left_ppm": 0, "top_ppm": 0, "right_ppm": 500000, "bottom_ppm": 1000000}
    )
    _, _, layout = actual(prepared, lambda value: value["questions"][0].update(images=[image]))
    receipt = layout["pages"][0]["image_blocks"][0]
    assert receipt["source_sha256"] == sha256(original)
    assert (
        receipt["transform"] == image["transform"] and receipt["crop"] == image["transform"]["crop"]
    )
    assert (receipt["display_width_px"], receipt["display_height_px"]) == (60, 80)
    assert (source / "quadrants.png").read_bytes() == original
    with pymupdf.open(output / "report.pdf") as pdf:
        embedded = pdf.extract_image(pdf[0].get_images()[0][0])["image"]
    with Image.open(io.BytesIO(embedded)) as actual_image:
        assert actual_image.size == (60, 80)
        assert actual_image.getpixel((30, 10)) == (0, 0, 255)
        assert actual_image.getpixel((30, 70)) == (255, 255, 0)
    with Image.new("RGB", (60, 80), "blue") as expected:
        expected.paste("yellow", (0, 40, 60, 80))
        raw = io.BytesIO()
        expected.save(raw, format="PNG")
        assert receipt["display_sha256"] == sha256(raw.getvalue())
        assert receipt["display_size_bytes"] == len(raw.getvalue())


def test_exif_is_applied_before_explicit_inverse_rotation(prepared):
    source, output, _ = prepared
    image = photo(source, exif=True)
    original = (source / "quadrants.png").read_bytes()
    image["transform"] = transform(rotation=270)
    _, _, layout = actual(prepared, lambda value: value["questions"][0].update(images=[image]))
    receipt = layout["pages"][0]["image_blocks"][0]
    assert (receipt["display_width_px"], receipt["display_height_px"]) == (80, 120)
    with pymupdf.open(output / "report.pdf") as pdf:
        embedded = pdf.extract_image(pdf[0].get_images()[0][0])["image"]
    with Image.open(io.BytesIO(embedded)) as pixels:
        assert pixels.getpixel((10, 10)) == (255, 0, 0)
        assert pixels.getpixel((70, 110)) == (255, 255, 0)
    assert (source / "quadrants.png").read_bytes() == original


def test_text_image_text_remains_interleaved_without_clipping_and_is_deterministic(
    prepared, tmp_path
):
    source, output, _ = prepared
    image = photo(source)

    def change(value):
        value["questions"][0].update(
            text_blocks=[
                {"span_id": "before", "text": "위쪽 설명입니다."},
                {"span_id": "after", "text": "아래쪽 질문입니다."},
            ],
            images=[image],
            ordered_blocks=[
                {"kind": "TEXT", "span_id": "before"},
                {"kind": "IMAGE", "attachment_occurrence_id": image["attachment_occurrence_id"]},
                {"kind": "TEXT", "span_id": "after"},
            ],
        )

    command, first, layout = actual(prepared, change)
    page = layout["pages"][0]
    before, after = page["text_blocks"]
    figure = page["image_blocks"][0]
    assert (
        before["bounds_pt"][3]
        < figure["bounds_pt"][1]
        < figure["bounds_pt"][3]
        < after["bounds_pt"][1]
    )
    with pymupdf.open(output / "report.pdf") as pdf:
        upper = pdf[0].search_for("위쪽 설명입니다.")[0]
        lower = pdf[0].search_for("아래쪽 질문입니다.")[0]
        image_bounds = pdf[0].get_image_info()[0]["bbox"]
        assert upper.y1 < image_bounds[1] < image_bounds[3] < lower.y0
        # Physical content-stream block order matches visual interleaving as well.
        blocks = pdf[0].get_text("dict")["blocks"]
        body = [
            block["type"]
            for block in blocks
            if block["bbox"][1] >= 86 and block["bbox"][3] <= 790.01
        ]
        assert body == [0, 1, 0]
    second_output = tmp_path / "second-output"
    second_output.mkdir()
    second = render_questions(
        command, input_root=source, output_root=second_output, renderer_release_sha256=RELEASE
    )
    assert first == second
    assert {member.relative_path: member.sha256 for member in first.outputs} == {
        member.relative_path: member.sha256 for member in second.outputs
    }


def test_same_source_different_transforms_never_share_wrong_cached_display(prepared):
    source, output, _ = prepared
    original = photo(source)
    second = {
        **original,
        "attachment_occurrence_id": identity("attachment", 2),
        "transform": transform(rotation=90),
    }
    _, _, layout = actual(
        prepared, lambda value: value["questions"][0].update(images=[original, second])
    )
    a, b = layout["pages"][0]["image_blocks"]
    assert a["source_sha256"] == b["source_sha256"]
    assert a["display_sha256"] != b["display_sha256"]
    assert (a["display_width_px"], a["display_height_px"]) == (80, 120)
    assert (b["display_width_px"], b["display_height_px"]) == (120, 80)
    with pymupdf.open(output / "report.pdf") as pdf:
        assert len(pdf[0].get_image_info()) == 2


@pytest.mark.parametrize("rotation", [True, "90", 45, 360, -90])
def test_invalid_transform_does_not_reinterpret_rotation(prepared, rotation):
    source, _, prepare = prepared
    image = photo(source)
    image["transform"] = transform(rotation=rotation)
    command = prepare(lambda value: value["questions"][0].update(images=[image]))
    raw = json.loads((source / command.manifest.relative_path).read_bytes())
    with pytest.raises(ValueError):
        validate_contract("manifest", raw)


@pytest.mark.parametrize(
    "ordering",
    [
        [],
        [{"kind": "TEXT", "span_id": "missing"}],
        [{"kind": "TEXT", "span_id": "span-one"}, {"kind": "TEXT", "span_id": "span-one"}],
    ],
)
def test_missing_or_duplicate_order_reference_fails_explicitly(prepared, ordering):
    source, output, prepare = prepared
    command = prepare(lambda value: value["questions"][0].update(ordered_blocks=ordering))
    result = render_questions(
        command, input_root=source, output_root=output, renderer_release_sha256=RELEASE
    )
    assert result.status == "INVALID_INPUT" and not result.outputs


def test_owner_rejects_receipt_moving_later_text_above_picture(prepared):
    source, _, _ = prepared
    image = photo(source)

    def change(value):
        value["questions"][0].update(
            text_blocks=[
                {"span_id": "before", "text": "설명"},
                {"span_id": "after", "text": "질문"},
            ],
            images=[image],
            ordered_blocks=[
                {"kind": "TEXT", "span_id": "before"},
                {"kind": "IMAGE", "attachment_occurrence_id": image["attachment_occurrence_id"]},
                {"kind": "TEXT", "span_id": "after"},
            ],
        )

    command, _, layout = actual(prepared, change)
    layout["pages"][0]["text_blocks"][1]["bounds_pt"] = [34.016, 120, 60, 134]
    manifest = RenderManifest.model_validate(json.loads((source / "manifest.json").read_bytes()))
    with pytest.raises(ValueError, match="ORDER_INVALID"):
        check_layout_receipt(command, manifest, RenderLayoutReceipt.model_validate(layout))


def test_crop_fraction_rounding_is_explicit_and_source_crop_area_must_be_positive(prepared):
    source, _, prepare = prepared
    image = photo(source)
    image["transform"] = transform(
        rotation=0,
        crop={"left_ppm": 100001, "top_ppm": 100001, "right_ppm": 900001, "bottom_ppm": 900001},
    )
    _, _, layout = actual(prepared, lambda value: value["questions"][0].update(images=[image]))
    receipt = layout["pages"][0]["image_blocks"][0]
    assert (receipt["display_width_px"], receipt["display_height_px"]) == (65, 97)
    image["transform"]["crop"]["right_ppm"] = 0
    command = prepare(lambda value: value["questions"][0].update(images=[image]))
    with pytest.raises(ValueError, match="CROP_INVALID"):
        RenderManifest.model_validate(
            json.loads((source / command.manifest.relative_path).read_bytes())
        )


def test_draft_missing_photo_placeholder_preserves_interleaved_text_order(prepared):
    _, output, _ = prepared

    def change(value):
        value["mode"] = "DRAFT"
        value["questions"][0].update(
            text_blocks=[
                {"span_id": "before", "text": "앞 문장"},
                {"span_id": "after", "text": "뒤 문장"},
            ],
            images=[
                {
                    "attachment_occurrence_id": identity("attachment"),
                    "attachment_revision_id": identity("attachmentrev"),
                    "member": None,
                    "availability": "MISSING",
                    "quality_accepted": False,
                }
            ],
            ordered_blocks=[
                {"kind": "TEXT", "span_id": "before"},
                {"kind": "IMAGE", "attachment_occurrence_id": identity("attachment")},
                {"kind": "TEXT", "span_id": "after"},
            ],
        )

    actual(prepared, change)
    with pymupdf.open(output / "report.pdf") as pdf:
        text = pdf[0].get_text()
        assert text.index("앞 문장") < text.index("미확보 사진") < text.index("뒤 문장")


def test_interleaved_three_text_spans_with_multiline_reply_freeze_exact_bottom(prepared):
    source, _, _ = prepared
    image = photo(source)

    def change(value):
        value["questions"][0].update(
            text_blocks=[
                {"span_id": "first", "text": "첫 질문"},
                {"span_id": "second", "text": "추가 질문"},
                {"span_id": "reply", "text": "답변\n답변"},
            ],
            images=[image],
            ordered_blocks=[
                {"kind": "TEXT", "span_id": "first"},
                {"kind": "IMAGE", "attachment_occurrence_id": image["attachment_occurrence_id"]},
                {"kind": "TEXT", "span_id": "second"},
                {"kind": "TEXT", "span_id": "reply"},
            ],
        )

    _, _, layout = actual(prepared, change)
    page = layout["pages"][0]
    assert page["text_blocks"][-1]["bounds_pt"][3] == 790.0
    assert all(block["bounds_pt"][3] <= 790 for block in page["text_blocks"] + page["image_blocks"])
