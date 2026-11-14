"""Signed diagonal native scale preserves crop, local reflection and rotation."""

from __future__ import annotations

import io
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from eom_image_provider.office_picture_records import _shape_geometry
from eom_image_provider.office_picture_uses import extract_office_picture_uses
from eom_image_provider.office_picture_xml import _geometry
from PIL import Image

from tests.unit.test_office_embedded_images import hwpx, raster, sha
from tests.unit.test_office_picture_uses import HC, HP, OPF, hwp_picture, hwp_shape, picture

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 0, 1, 0)
SCALES: tuple[Matrix, ...] = (
    (0.10837200284004211, 0, 19150, 0, -0.1083730012178421, -4365),
    (-0.07789599895477295, 0, 71948, 0, 0.07790300250053406, 79913),
    (-0.25, 0, 19, 0, -0.5, 13),
)
ROTATIONS: tuple[Matrix, ...] = (
    IDENTITY,
    (0, -1, 0, 1, 0, 0),
    (-1, 0, 0, 0, -1, 0),
    (0, 1, 0, -1, 0, 0),
)


def xml_picture(scale: Matrix, *, angle: int = 0, flags: int = 0) -> ET.Element:
    value = ET.fromstring(
        f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">{picture(angle=angle)}</hp:sec>'
    )[0]
    rendering = value.find(f"{{{HP}}}renderingInfo")
    assert rendering is not None
    scaling = rendering.find(f"{{{HC}}}scaMatrix")
    assert scaling is not None
    scaling.attrib.update({f"e{i}": str(number) for i, number in enumerate(scale, 1)})
    flips = value.find(f"{{{HP}}}flip")
    assert flips is not None
    flips.set("horizontal", str(flags & 1))
    flips.set("vertical", str((flags >> 1) & 1))
    return value


def binary_shape(scale: Matrix, *, angle: int = 0, flags: int = 0) -> bytes:
    value = bytearray(hwp_shape())
    struct.pack_into("<I", value, 8 + 28, flags)
    struct.pack_into("<H", value, 8 + 32, angle)
    struct.pack_into("<6d", value, 8 + 44 + 48, *scale)
    struct.pack_into("<6d", value, 8 + 44 + 96, *ROTATIONS[(angle // 90) % 4])
    return bytes(value)


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("angle", (0, 90, 180, 270))
def test_hwp_and_hwpx_resolve_same_signed_local_reflection(scale: Matrix, angle: int) -> None:
    xml = _geometry(xml_picture(scale, angle=angle))
    binary = _shape_geometry(binary_shape(scale, angle=angle), hwp_picture())
    assert xml is not None and binary == xml
    assert (xml.flip_horizontal, xml.flip_vertical) == (scale[0] < 0, scale[4] < 0)
    assert xml.clockwise_quarter_turns == angle // 90
    assert xml.viewport == (0, 0, 1900, 1300)


@pytest.mark.parametrize("flags", (0, 1, 2, 3))
def test_positive_scale_keeps_existing_declared_flags(flags: int) -> None:
    scale: Matrix = (0.25, 0, -321, 0, 0.5, 456)
    xml = _geometry(xml_picture(scale, flags=flags))
    assert xml is not None
    assert _shape_geometry(binary_shape(scale, flags=flags), hwp_picture()) == xml
    assert (xml.flip_horizontal, xml.flip_vertical) == (bool(flags & 1), bool(flags & 2))


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("flags", (1, 2, 3))
def test_negative_scale_with_any_declared_flip_stays_unresolved(scale: Matrix, flags: int) -> None:
    assert _geometry(xml_picture(scale, flags=flags)) is None
    assert _shape_geometry(binary_shape(scale, flags=flags), hwp_picture()) is None


@pytest.mark.parametrize(
    "scale",
    (
        (0, 0, 0, 0, 1, 0),
        (-0.0, 0, 0, 0, -1, 0),
        (1, 0, 0, 0, 0, 0),
        (-1, 0.01, 0, 0, 1, 0),
        (-1, 0, 0, 0.01, 1, 0),
        (float("nan"), 0, 0, 0, 1, 0),
        (-1, 0, 0, 0, float("inf"), 0),
        (-1, 0, 0, 0, 1_000_000_001, 0),
    ),
)
def test_invalid_affine_is_not_admitted_by_signed_scale(scale: Matrix) -> None:
    assert _geometry(xml_picture(scale)) is None
    assert _shape_geometry(binary_shape(scale), hwp_picture()) is None


@pytest.mark.parametrize("scale", SCALES[:2])
def test_multiple_transform_pairs_and_nonquarter_rotation_stay_unresolved(scale: Matrix) -> None:
    element = xml_picture(scale)
    rendering = element.find(f"{{{HP}}}renderingInfo")
    assert rendering is not None
    ET.SubElement(
        rendering, f"{{{HC}}}scaMatrix", {f"e{i}": str(v) for i, v in enumerate(scale, 1)}
    )
    assert _geometry(element) is None
    shape = bytearray(binary_shape(scale))
    struct.pack_into("<H", shape, 8 + 42, 2)
    shape.extend(struct.pack("<12d", *scale, *IDENTITY))
    assert _shape_geometry(bytes(shape), hwp_picture()) is None
    assert _geometry(xml_picture(scale, angle=13)) is None
    assert _shape_geometry(binary_shape(scale, angle=13), hwp_picture()) is None


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("angle", (0, 90, 180, 270))
@pytest.mark.parametrize("cropped", (False, True))
def test_signed_views_crop_then_reflect_then_rotate_without_lost_corners(
    tmp_path: Path, scale: Matrix, angle: int, cropped: bool
) -> None:
    element = xml_picture(scale, angle=angle)
    if cropped:
        clip = element.find(f"{{{HP}}}imgClip")
        assert clip is not None
        clip.attrib.update(left="101", top="201", right="1801", bottom="1201")
    section = f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">'.encode()
    section += ET.tostring(element) + b"</hp:sec>"
    manifest = (
        f'<opf:package xmlns:opf="{OPF}"><opf:item id="image1" '
        'href="../BinData/picture.png"/></opf:package>'
    ).encode()
    path = hwpx(
        tmp_path,
        (
            ("Contents/content.hpf", manifest),
            ("Contents/section0.xml", section),
            ("BinData/picture.png", raster()),
        ),
    )
    result = extract_office_picture_uses(
        path, expected_sha256=sha(path), workspace=tmp_path / "output"
    )
    assert result.picture_uses[0].unresolved_reasons == ()
    assert len(result.rendered_uses) == 1
    view = result.rendered_uses[0]
    with Image.open(io.BytesIO(raster())) as original:
        expected = original.crop((1, 2, 19, 13)) if cropped else original.copy()
        if scale[0] < 0:
            expected = expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if scale[4] < 0:
            expected = expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        for _ in range(angle // 90):
            expected = expected.transpose(Image.Transpose.ROTATE_270)
        with Image.open(tmp_path / "output" / view.member_path) as actual:
            assert actual.size == expected.size
            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
        source_member = tmp_path / "output" / result.embedded_images.images[0].member_path
        assert source_member.read_bytes() == raster()
