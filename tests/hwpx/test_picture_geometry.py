"""Full-image clipping coordinates, independent of renderer/package membership success."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from eom_hwpx_builder.content_team_images import _picture
from eom_hwpx_builder.reference import HP, _image_paragraph
from eom_hwpx_contracts import uncropped_image_bounds
from eom_hwpx_manager.content_team_output_acceptance import verify_content_team_output
from eom_hwpx_manager.errors import HwpxManagerError
from lxml import etree  # type: ignore[import-untyped]

from tests.hwpx.helpers import png_bytes
from tests.hwpx.test_content_team_output_acceptance import (
    HANDOFF,
    _render_paired_images,
    _render_table_image,
    _rewrite_member,
    _sha256,
)


@pytest.mark.parametrize("dimensions", [(800, 500), (22400, 14000), (1, 1)])
def test_uncropped_bounds_use_original_coordinates_not_four_zero_margins(
    dimensions: tuple[int, int],
) -> None:
    assert uncropped_image_bounds(*dimensions) == (0, 0, *dimensions)


@pytest.mark.parametrize("dimensions", [(0, 1), (1, 0), (-1, 2), (True, 1), (1, 1.5)])
def test_uncropped_bounds_reject_nonpositive_or_noninteger_dimensions(
    dimensions: tuple[Any, Any],
) -> None:
    with pytest.raises(ValueError):
        uncropped_image_bounds(*dimensions)


@pytest.mark.parametrize("writer", ["content-team", "reference"])
def test_both_picture_writers_keep_full_intrinsic_extent_and_existing_display_size(
    writer: str,
) -> None:
    image = png_bytes(output=True)
    if writer == "content-team":
        picture = _picture(binary_id="testImage", object_id=123, image=image)
        expected_display = {"width": "12600", "height": "7875"}
    else:
        paragraph = etree.Element(HP + "p")
        etree.SubElement(paragraph, HP + "run", {"charPrIDRef": "2"})
        rendered = _image_paragraph(paragraph, image)
        picture = rendered.find(".//" + HP + "pic")
        assert picture is not None
        expected_display = {"width": "25985", "height": "16241"}
    clip = picture.find(HP + "imgClip")
    assert clip is not None
    assert dict(clip.attrib) == {"left": "0", "top": "0", "right": "22400", "bottom": "14000"}
    display = picture.find(HP + "curSz")
    assert display is not None and dict(display.attrib) == expected_display


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
@pytest.mark.parametrize(
    "fault",
    [
        "zero-area",
        "missing-clip",
        "duplicate-clip",
        "partial-crop",
        "negative-crop",
        "original-drift",
        "zero-display",
        "current-drift",
        "invalid-number",
    ],
)
def test_manager_rejects_invisible_geometry_even_with_exact_embedded_png_bytes(
    tmp_path: Path, fault: str
) -> None:
    output, _hash, expectation = _render_paired_images(tmp_path, image_count=1)
    damaged = tmp_path / f"bad-{fault}.hwpx"

    def change_geometry(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        picture = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "pic")
        children = {node.tag.rsplit("}", 1)[-1]: node for node in picture}
        clip = children["imgClip"]
        if fault == "zero-area":
            clip.set("right", "0")
            clip.set("bottom", "0")
        elif fault == "missing-clip":
            picture.remove(clip)
        elif fault == "duplicate-clip":
            ElementTree.SubElement(picture, clip.tag, dict(clip.attrib))
        elif fault == "partial-crop":
            clip.set("right", "100")
        elif fault == "negative-crop":
            clip.set("left", "-1")
        elif fault == "original-drift":
            children["orgSz"].set("width", "1")
        elif fault == "zero-display":
            children["sz"].set("width", "0")
        elif fault == "current-drift":
            children["curSz"].set("height", "1")
        else:
            clip.set("right", "nan")
        serialized = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
        assert isinstance(serialized, bytes)
        return serialized

    _rewrite_member(output, damaged, "Contents/section0.xml", change_geometry)
    with pytest.raises(HwpxManagerError, match=r"image (geometry|clipping|display)"):
        verify_content_team_output(
            damaged,
            expected_sha256=_sha256(damaged.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
@pytest.mark.parametrize("layout", ["single", "paired", "table-image"])
def test_manager_accepts_full_extent_in_single_paired_and_mixed_visuals(
    tmp_path: Path, layout: str
) -> None:
    output, output_sha256, expectation = (
        _render_table_image(tmp_path)
        if layout == "table-image"
        else _render_paired_images(tmp_path, image_count=2 if layout == "paired" else 1)
    )
    receipt = verify_content_team_output(
        output, expected_sha256=output_sha256, expectations=(expectation,)
    )
    assert tuple(image.sha256 for image in receipt.items[0].images) == tuple(
        image.sha256 for image in expectation.images
    )
