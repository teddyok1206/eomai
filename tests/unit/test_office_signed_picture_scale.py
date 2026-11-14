"""Signed resize-box scale is not bitmap mirroring; explicit flips preserve pixels."""

from __future__ import annotations

import hashlib
import io
import math
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

# Two exact geometry-only record pairs from the bounded, hash-verified MAIN HWP.
# No question text or image bytes are fixtures. Independent native HWPX geometry
# observations pin their image extents/viewports; observed signed-size axes are
# NOT bitmap flips. These records explicitly declare no horizontal/vertical flip.
REFLECTED_SIZE_RECORDS = (
    (
        "636970246369702432b5ffff9726000000000100a0980300c0c60000c5630000"
        "76eaffff000008240000e2310000c50a00000100000000000000f03f00000000"
        "000000000000000080b3d2c00000000000000000000000000000f03f00000000"
        "804bc3400000008044bebb3f00000000000000000000000080b3d24000000000"
        "000000000000004055bebbbf00000000000db1c0000000000000f03f00000000"
        "0000000000000000000000000000000000000000000000000000f03f00000000"
        "00000000",
        "0000000000000000000000000000000000000000a098030000000000a0980300c0c60000"
        "00000000c0c6000000000000000000001c4a030094d40000000000000000000000000109"
        "000099ea0038000000001c4a030094d4000000",
        "f2a5b6da92b8da02101a308442381c624e0bf29438bdcc34ce463554be2253cc",
        "af6461442dd2ff1d98c416602c14e9979bad0745fc6d201cd479d3c519491391",
        (215580, 54420),
        (False, True),
    ),
    (
        "63697024636970246e02ffffd7c7feff00000100bc6001009c8e020086e4ffff"
        "ff320000000008240000bd0d00007f1900000100000000000000f03f00000000"
        "000000000000000040b2efc00000000000000000000000000000f03f00000000"
        "9082f3c000000000fef0b3bf000000000000000000000000c090f14000000000"
        "000000000000008073f1b33f000000009082f340000000000000f03f00000000"
        "0000000000000000000000000000000000000000000000000000f03f00000000"
        "00000000",
        "0000000000000000000000000000000000000000bc60010000000000bc6001009c8e0200"
        "000000009c8e020000000000000000009c080100c8ea010000000000000000000000000a"
        "000087dd6638000000009c080100c8ea010000",
        "06eee4d7d21c536df13ba381cf6a82f0eef08a6c787943e9247bb91ffa093d09",
        "ed0d170814038c12539847f3c08ea2201ad13f79529c1d7d177f80a94b776007",
        (67740, 125640),
        (True, False),
    ),
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
    ET.SubElement(value, f"{{{HP}}}orgSz", width="1900", height="1300")
    current = resized_dimensions(scale)
    ET.SubElement(value, f"{{{HP}}}curSz", width=str(current[0]), height=str(current[1]))
    return value


def resized_dimensions(scale: Matrix) -> tuple[int, int]:
    values = tuple(
        round(initial * factor)
        if math.isfinite(factor) and abs(initial * factor) <= 1_000_000_000
        else initial
        for initial, factor in zip((1900, 1300), (scale[0], scale[4]), strict=True)
    )
    return values[0], values[1]


def binary_shape(scale: Matrix, *, angle: int = 0, flags: int = 0) -> bytes:
    value = bytearray(hwp_shape())
    struct.pack_into("<I", value, 8 + 28, flags)
    struct.pack_into("<H", value, 8 + 32, angle)
    struct.pack_into("<6d", value, 8 + 44 + 48, *scale)
    struct.pack_into("<6d", value, 8 + 44 + 96, *ROTATIONS[(angle // 90) % 4])
    if scale[0] < 0 or scale[4] < 0:
        struct.pack_into("<2i", value, 8 + 20, *resized_dimensions(scale))
    return bytes(value)


@pytest.mark.parametrize(
    "shape_hex,picture_hex,shape_sha,picture_sha,extent,flips", REFLECTED_SIZE_RECORDS
)
def test_actual_signed_hwp_size_records_keep_bitmap_unmirrored_in_native_hwpx(
    tmp_path, shape_hex, picture_hex, shape_sha, picture_sha, extent, flips
) -> None:
    shape, image = bytes.fromhex(shape_hex), bytes.fromhex(picture_hex)
    assert hashlib.sha256(shape).hexdigest() == shape_sha
    assert hashlib.sha256(image).hexdigest() == picture_sha
    assert len(shape) == 196 and len(image) == 91
    initial_x, initial_y, current_x, current_y, flags = struct.unpack_from("<4iI", shape, 20)
    assert initial_x > 0 and initial_y > 0 and flags == 604504064
    assert (current_x < 0, current_y < 0) == flips
    scale = struct.unpack_from("<6d", shape, 100)
    xml = xml_picture(scale)
    original = xml.find(f"{{{HP}}}orgSz")
    current = xml.find(f"{{{HP}}}curSz")
    assert original is not None and current is not None
    original.attrib.update(width=str(initial_x), height=str(initial_y))
    current.attrib.update(width=str(current_x), height=str(current_y))
    rectangle = xml.find(f"{{{HP}}}imgRect")
    dimensions = xml.find(f"{{{HP}}}imgDim")
    clip = xml.find(f"{{{HP}}}imgClip")
    assert rectangle is not None and dimensions is not None and clip is not None
    points = struct.unpack_from("<8i", image, 12)
    for number in range(4):
        point = rectangle.find(f"{{{HC}}}pt{number}")
        assert point is not None
        point.attrib.update(x=str(points[number * 2]), y=str(points[number * 2 + 1]))
    dimensions.attrib.update(dimwidth=str(extent[0]), dimheight=str(extent[1]))
    clip.attrib.update(left="0", top="0", right=str(extent[0]), bottom=str(extent[1]))
    observed = _shape_geometry(shape, image)
    assert observed is not None and observed == _geometry(xml)
    assert observed.original_extent == extent
    assert observed.viewport == (0, 0, *extent)
    assert (observed.flip_horizontal, observed.flip_vertical) == (False, False)
    assert observed.clockwise_quarter_turns == 0
    # Exact signed-size metadata must not mirror independently known corner
    # pixels. A full, zero-flip view reuses the original PNG byte-for-byte.
    section = f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">'.encode()
    section += ET.tostring(xml) + b"</hp:sec>"
    manifest = (
        f'<opf:package xmlns:opf="{OPF}"><opf:item id="image1" '
        'href="../BinData/picture.png"/></opf:package>'
    ).encode()
    source = hwpx(
        tmp_path,
        (
            ("Contents/content.hpf", manifest),
            ("Contents/section0.xml", section),
            ("BinData/picture.png", raster()),
        ),
    )
    extracted = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert extracted.picture_uses[0].geometry == observed
    assert extracted.rendered_uses[0].sha256 == extracted.embedded_images.images[0].sha256
    assert (tmp_path / "output" / extracted.rendered_uses[0].member_path).read_bytes() == raster()


@pytest.mark.parametrize("axis", (0, 1))
def test_negative_current_size_without_matching_scale_sign_remains_unresolved(axis: int) -> None:
    shape = bytearray(binary_shape(IDENTITY))
    struct.pack_into("<i", shape, 8 + 20 + axis * 4, -100)
    assert _shape_geometry(bytes(shape), hwp_picture()) is None


@pytest.mark.parametrize("offset", (12, 16, 20, 24))
@pytest.mark.parametrize("value", (0, -1_000_000_001, 1_000_000_001, -(2**31)))
def test_signed_dimensions_keep_nonzero_magnitude_bounds(offset: int, value: int) -> None:
    shape = bytearray(binary_shape(SCALES[2]))
    struct.pack_into("<i", shape, 8 + offset, value)
    assert _shape_geometry(bytes(shape), hwp_picture()) is None


@pytest.mark.parametrize("offset", (12, 16))
def test_negative_initial_extent_is_not_a_reflected_current_size(offset: int) -> None:
    shape = bytearray(binary_shape(SCALES[2]))
    struct.pack_into("<i", shape, 8 + offset, -100)
    assert _shape_geometry(bytes(shape), hwp_picture()) is None


def test_reflected_current_sizes_do_not_relax_viewport_or_picture_rectangle_checks() -> None:
    shape_hex, picture_hex, *_ = REFLECTED_SIZE_RECORDS[0]
    shape, image = bytes.fromhex(shape_hex), bytearray.fromhex(picture_hex)
    struct.pack_into("<i", image, 52, 1_000_000_000)
    assert _shape_geometry(shape, bytes(image)) is None
    image = bytearray.fromhex(picture_hex)
    struct.pack_into("<i", image, 24, 1)
    assert _shape_geometry(shape, bytes(image)) is None


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("angle", (0, 90, 180, 270))
def test_hwp_and_hwpx_resolve_signed_resize_without_inventing_reflection(
    scale: Matrix, angle: int
) -> None:
    xml = _geometry(xml_picture(scale, angle=angle))
    binary = _shape_geometry(binary_shape(scale, angle=angle), hwp_picture())
    assert xml is not None and binary == xml
    assert (xml.flip_horizontal, xml.flip_vertical) == (False, False)
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
def test_closed_signed_resize_respects_only_the_declared_bitmap_flip(
    scale: Matrix, flags: int
) -> None:
    xml = _geometry(xml_picture(scale, flags=flags))
    binary = _shape_geometry(binary_shape(scale, flags=flags), hwp_picture())
    assert xml is not None and binary == xml
    assert (xml.flip_horizontal, xml.flip_vertical) == (bool(flags & 1), bool(flags & 2))


@pytest.mark.parametrize(
    "field", ["missing-current", "positive-current", "wrong-size", "missing-original"]
)
@pytest.mark.parametrize("scale", SCALES)
def test_negative_scale_without_closed_signed_resize_proof_is_unresolved(field, scale):
    element = xml_picture(scale)
    current = element.find(f"{{{HP}}}curSz")
    original = element.find(f"{{{HP}}}orgSz")
    assert current is not None and original is not None
    if field == "missing-current":
        element.remove(current)
    elif field == "missing-original":
        element.remove(original)
    elif field == "positive-current":
        current.attrib.update(
            {name: str(abs(int(value))) for name, value in current.attrib.items()}
        )
    else:
        current.set("width", str(int(current.attrib["width"]) + 10))
    assert _geometry(element) is None
    shape = bytearray(binary_shape(scale))
    x, y = resized_dimensions(scale)
    if field == "positive-current":
        struct.pack_into("<2i", shape, 28, abs(x), abs(y))
    else:
        struct.pack_into("<i", shape, 28, x + 10)
    assert _shape_geometry(bytes(shape), hwp_picture()) is None


@pytest.mark.parametrize("scale", SCALES)
def test_unsigned_wrapped_signed_hwpx_current_size_has_the_same_closed_meaning(scale):
    element = xml_picture(scale)
    current = element.find(f"{{{HP}}}curSz")
    assert current is not None
    expected = _geometry(element)
    current.attrib.update(
        {name: str(int(value) & 0xFFFFFFFF) for name, value in current.attrib.items()}
    )
    assert expected is not None and _geometry(element) == expected


@pytest.mark.parametrize("axis", (0, 1))
def test_negative_scale_rejects_zero_current_extent_even_on_the_other_axis(axis):
    scale = (-1, 0, 0, 0, 1, 0) if axis == 0 else (1, 0, 0, 0, -1, 0)
    element = xml_picture(scale)
    current = element.find(f"{{{HP}}}curSz")
    assert current is not None
    current.set("height" if axis == 0 else "width", "0")
    assert _geometry(element) is None


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
@pytest.mark.parametrize("flags", (0, 1, 2, 3))
def test_signed_resize_views_crop_then_explicit_flip_then_rotate_without_lost_corners(
    tmp_path: Path, scale: Matrix, angle: int, cropped: bool, flags: int
) -> None:
    element = xml_picture(scale, angle=angle, flags=flags)
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
        if flags & 1:
            expected = expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if flags & 2:
            expected = expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        for _ in range(angle // 90):
            expected = expected.transpose(Image.Transpose.ROTATE_270)
        with Image.open(tmp_path / "output" / view.member_path) as actual:
            assert actual.size == expected.size
            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
        source_member = tmp_path / "output" / result.embedded_images.images[0].member_path
        assert source_member.read_bytes() == raster()
