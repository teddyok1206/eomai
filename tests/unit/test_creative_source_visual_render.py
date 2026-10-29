"""Actual Poppler crop geometry over synthetic PDFs; never production sources."""

import shutil
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_learning_pages import ExternalItemLearningPageSet
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.external_item_learning_page_render import (
    render_creative_source_visuals,
    render_external_item_learning_pages,
)

from tests.unit.test_external_item_learning_page_render import (
    _direct_fixture_runner,
    _pdf,
    _source_for_pdf,
)
from tests.unit.test_external_item_learning_result_contract import _rehash
from tests.unit.test_external_item_learning_result_v2 import result_v2

pytestmark = pytest.mark.skipif(
    shutil.which("pdfinfo") is None or shutil.which("pdftoppm") is None,
    reason="synthetic crop tests require Poppler",
)


def visual_result(source, *, repeat=False):
    value = result_v2()
    for field in ("source_id", "source_revision_id", "external_number"):
        value[field] = getattr(source, field)
    value["input_sha256"] = source.input_sha256
    target = value["regions"][0]["region_id"]
    visual = "extregion_" + "a" * 32
    value["regions"].append(
        {
            "region_id": visual,
            "role": "TARGET_ITEM",
            "physical_page": 1,
            "bounding_box": {"left": 200, "top": 300, "right": 800, "bottom": 900},
            "observed_text": "원본 도식",
            "confidence_milli": 990,
        }
    )
    for index in range(2 if repeat else 1):
        offset = len(value["proposal"]["content"]["body"])
        value["proposal"]["content"]["body"].append(
            {
                "type": "source_image",
                "block_id": f"block_source_visual_{index}",
                "purpose": "stimulus",
                "source_region_id": visual,
                "target_region_id": target,
                "alt_text": "원문 도식",
            }
        )
        value["proposal"]["content_region_map"].append(
            {
                "content_path": f"body[{offset}]",
                "region_ids": [visual],
            }
        )
    _rehash(value)
    return ExternalItemLearningResultV2.model_validate(value)


def fixture_source(tmp_path):
    payload = _pdf()
    source = _source_for_pdf(payload)
    rendered = render_external_item_learning_pages(
        source, payload, workspace=tmp_path / "pages", run=_direct_fixture_runner
    )
    return source, payload, rendered.manifest


def test_real_crop_uses_normalized_box_in_the_exact_delivered_page_frame(tmp_path):
    source, payload, pages = fixture_source(tmp_path)
    result = visual_result(source)
    outputs = render_creative_source_visuals(
        source, pages, result, payload, workspace=tmp_path / "crops", run=_direct_fixture_runner
    )
    assert len(outputs) == 1
    image, page = outputs[0], pages.pages[0]
    expected = (
        200 * page.width_px // 10000,
        300 * page.height_px // 10000,
        (800 * page.width_px + 9999) // 10000,
        (900 * page.height_px + 9999) // 10000,
    )
    assert image.pixel_box == expected
    assert (image.width_px, image.height_px) == (
        expected[2] - expected[0],
        expected[3] - expected[1],
    )
    assert image.source_page_sha256 == page.sha256
    assert sha256_bytes(image.path.read_bytes()) == image.sha256
    assert image.content_length == image.path.stat().st_size
    assert image.sha256 != page.sha256


def test_duplicate_references_materialize_one_source_crop_only(tmp_path):
    source, payload, pages = fixture_source(tmp_path)
    run = Mock(side_effect=_direct_fixture_runner)
    outputs = render_creative_source_visuals(
        source,
        pages,
        visual_result(source, repeat=True),
        payload,
        workspace=tmp_path / "crops",
        run=run,
    )
    assert len(outputs) == 1 and run.call_count == 1


def test_pdf_tamper_is_refused_before_render_or_workspace_creation(tmp_path):
    source, payload, pages = fixture_source(tmp_path)
    run = Mock()
    target = tmp_path / "crops"
    with pytest.raises(ValueError, match="CROP_INPUT_INVALID"):
        render_creative_source_visuals(
            source, pages, visual_result(source), payload + b"tampered", workspace=target, run=run
        )
    assert not target.exists()
    run.assert_not_called()


def test_changed_renderer_is_not_silently_used_against_a_pinned_page(tmp_path):
    source, payload, pages = fixture_source(tmp_path)
    value = pages.model_dump(mode="json")
    value["renderer"]["pdftoppm_sha256"] = "sha256:" + "0" * 64
    value["manifest_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "manifest_sha256"}
    )
    changed = ExternalItemLearningPageSet.model_validate(value)
    run = Mock()
    with pytest.raises(ValueError, match="RENDERER_CHANGED"):
        render_creative_source_visuals(
            source, changed, visual_result(source), payload, workspace=tmp_path / "crops", run=run
        )
    run.assert_not_called()


def test_empty_visual_set_has_no_render_side_effect(tmp_path):
    source, payload, pages = fixture_source(tmp_path)
    value = visual_result(source).model_dump(mode="json")
    value["proposal"]["content"]["body"].pop()
    value["proposal"]["content_region_map"].pop()
    _rehash(value)
    run = Mock()
    target = tmp_path / "unused"
    assert (
        render_creative_source_visuals(
            source,
            pages,
            ExternalItemLearningResultV2.model_validate(value),
            payload,
            workspace=target,
            run=run,
        )
        == ()
    )
    run.assert_not_called()
    assert not target.exists()
