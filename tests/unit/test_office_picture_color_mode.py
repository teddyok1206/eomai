"""Native raster MONO math, alpha and use-level source preservation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from eom_image_provider import office_picture_views
from eom_image_provider.office_embedded_images import OfficeEmbeddedImageError
from eom_image_provider.office_picture_color_mode import (
    OfficePictureColorMode,
    apply_office_picture_color_mode,
)
from eom_image_provider.office_picture_records import _section_objects
from eom_image_provider.office_picture_uses import extract_office_picture_uses
from eom_image_provider.office_picture_xml import read_hwpx_picture_uses
from PIL import Image, ImageOps

from tests.unit.test_office_embedded_images import hwpx, sha
from tests.unit.test_office_picture_uses import HC, HP, OPF, hwp_picture, hwp_shape, picture, record


def _source(
    tmp_path: Path, raw: bytes, modes: tuple[str, ...], *, template: str | None = None
) -> Path:
    template = picture() if template is None else template
    body = "".join(template.replace('effect="REAL_PIC"', f'effect="{mode}"') for mode in modes)
    manifest = (
        f'<opf:package xmlns:opf="{OPF}"><opf:manifest>'
        '<opf:item id="image1" href="../BinData/source.png"/>'
        "</opf:manifest></opf:package>"
    )
    section = f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">{body}</hp:sec>'
    return hwpx(
        tmp_path,
        (
            ("Contents/content.hpf", manifest.encode()),
            ("Contents/section0.xml", section.encode()),
            ("BinData/source.png", raw),
        ),
    )


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _expected_monochrome(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    expected = Image.new("RGBA", image.size)
    expected.putdata(
        [
            (value, value, value, alpha)
            for red, green, blue, alpha in rgba.getdata()
            for value in (255 if (76 * red + 151 * green + 29 * blue) >> 8 >= 128 else 0,)
        ]
    )
    return expected


def test_black_white_uses_exact_integer_luminance_not_601_or_rounded_gray() -> None:
    image = Image.new("RGBA", (5, 1))
    image.putdata(
        [
            (0, 188, 151, 0),  # weighted sum 32767: one below the threshold
            (0, 193, 125, 1),  # weighted sum 32768: exact threshold
            (0, 169, 250, 127),  # integer MONO white, unrounded BT.601 black
            (255, 88, 0, 254),  # Pillow rounded grayscale white, MONO black
            (255, 255, 255, 255),
        ]
    )
    actual = apply_office_picture_color_mode(image, OfficePictureColorMode.BLACK_WHITE)
    assert list(actual.getdata()) == [
        (0, 0, 0, 0),
        (255, 255, 255, 1),
        (255, 255, 255, 127),
        (0, 0, 0, 254),
        (255, 255, 255, 255),
    ]
    assert list(ImageOps.grayscale(image.convert("RGB")).getdata())[3] == 128


@pytest.mark.parametrize("mode", ["RGBA", "P"])
def test_palette_transparency_and_original_png_are_unchanged(tmp_path: Path, mode: str) -> None:
    image = Image.new(mode, (3, 2))
    if mode == "P":
        image.putpalette([0, 169, 250, 255, 88, 0, 255, 255, 255] + [0] * (768 - 9))
        image.putdata([0, 1, 2, 2, 1, 0])
        image.info["transparency"] = bytes([0, 127, 255])
    else:
        image.putdata([(0, 169, 250, 0), (255, 88, 0, 127), (255, 255, 255, 255)] * 2)
    raw = _png(image)
    source = _source(tmp_path, raw, ("BLACK_WHITE", "REAL_PIC"))
    result = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    transformed, untouched = result.rendered_uses
    assert all(not use.unresolved_reasons for use in result.picture_uses)
    original = result.embedded_images.images[0]
    assert (tmp_path / "output" / original.member_path).read_bytes() == raw
    assert untouched.member_path == original.member_path
    assert untouched.sha256 == original.sha256
    assert transformed.member_path.startswith("uses/")
    assert transformed.sha256 != original.sha256
    with Image.open(tmp_path / "output" / transformed.member_path) as actual:
        assert actual.convert("RGBA").tobytes() == _expected_monochrome(image).tobytes()
    assert source.read_bytes().startswith(b"PK")


def test_color_mode_is_part_of_render_recipe_and_duplicate_uses_reuse_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 88, 0, 31), (0, 169, 250, 255)])
    raw = _png(image)
    source = _source(
        tmp_path, raw, ("REAL_PIC", "GRAY_SCALE", "BLACK_WHITE", "BLACK_WHITE", "GRAY_SCALE")
    )
    calls: list[OfficePictureColorMode] = []

    def render(image: Image.Image, mode: OfficePictureColorMode) -> Image.Image:
        calls.append(mode)
        return apply_office_picture_color_mode(image, mode)

    monkeypatch.setattr(office_picture_views, "apply_office_picture_color_mode", render)
    result = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    normal, gray, mono, mono_again, gray_again = result.rendered_uses
    assert calls == [OfficePictureColorMode.GRAY_SCALE, OfficePictureColorMode.BLACK_WHITE]
    assert len({normal.sha256, gray.sha256, mono.sha256}) == 3
    assert mono.sha256 == mono_again.sha256 and mono.use_id != mono_again.use_id
    assert gray.sha256 == gray_again.sha256
    assert len(list((tmp_path / "output/uses").iterdir())) == 2
    with Image.open(tmp_path / "output" / gray.member_path) as actual:
        expected = ImageOps.grayscale(image.convert("RGB")).convert("RGBA")
        expected.putalpha(image.getchannel("A"))
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
@pytest.mark.parametrize("flip", [False, True])
def test_monochrome_preserves_native_crop_flip_then_quarter_turn(
    tmp_path: Path, angle: int, flip: bool
) -> None:
    image = Image.new("RGBA", (4, 2))
    image.putdata([(0, 169, 250, 31), (255, 88, 0, 255), (255, 255, 255, 0), (0, 0, 0, 127)] * 2)
    template = picture(angle=angle, clip='left="0" top="0" right="950" bottom="1300"')
    if flip:
        template = template.replace('horizontal="0"', 'horizontal="1"')
    source = _source(tmp_path, _png(image), ("BLACK_WHITE",), template=template)
    result = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert not result.picture_uses[0].unresolved_reasons
    expected = image.crop((0, 0, 2, 2))
    if flip:
        expected = expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    for _ in range(angle // 90):
        expected = expected.transpose(Image.Transpose.ROTATE_270)
    with Image.open(tmp_path / "output" / result.rendered_uses[0].member_path) as actual:
        assert actual.size == expected.size
        assert actual.tobytes() == _expected_monochrome(expected).tobytes()


@pytest.mark.parametrize("tone", [0, 1, 2, 3, 255])
@pytest.mark.parametrize("collect", [False, True])
def test_hwp_modes_are_closed_and_effects_need_the_paired_renderer(
    tone: int, collect: bool
) -> None:
    modes: dict[str, OfficePictureColorMode] | None = {} if collect else None
    uses, _ = _section_objects(
        record(76, 2, hwp_shape()) + record(85, 3, hwp_picture(tone=tone)),
        member="BodyText/Section0",
        source_sha256="sha256:" + "1" * 64,
        bindings=("BinData/BIN0001.png",),
        color_modes=modes,
    )
    assert ("IMAGE_EFFECT_UNSUPPORTED" in uses[0].unresolved_reasons) == (
        tone not in (0, 1, 2) or (tone != 0 and not collect)
    )
    if collect and tone in (0, 1, 2):
        assert modes == {uses[0].use_id: tuple(OfficePictureColorMode)[tone]}
    elif collect:
        assert modes == {}


@pytest.mark.parametrize("mode", ["REAL_PIC", "GRAY_SCALE", "BLACK_WHITE", "SEPIA", ""])
@pytest.mark.parametrize("collect", [False, True])
def test_hwpx_modes_are_closed_and_effects_need_the_paired_renderer(
    tmp_path: Path, mode: str, collect: bool
) -> None:
    modes: dict[str, OfficePictureColorMode] | None = {} if collect else None
    path = _source(tmp_path, _png(Image.new("RGB", (2, 1))), (mode,))
    uses, _ = read_hwpx_picture_uses(path.read_bytes(), source_sha256=sha(path), color_modes=modes)
    assert ("IMAGE_EFFECT_UNSUPPORTED" in uses[0].unresolved_reasons) == (
        mode not in {value.value for value in OfficePictureColorMode}
        or (mode != "REAL_PIC" and not collect)
    )


@pytest.mark.parametrize("replacement", ['bright="1"', 'contrast="-1"', 'alpha="100"', "shadow"])
def test_monochrome_does_not_allow_other_effects(tmp_path: Path, replacement: str) -> None:
    source = _source(tmp_path, _png(Image.new("RGB", (2, 1))), ("BLACK_WHITE",))
    # Synthetic source rebuild, not modification of a received artifact.
    body = picture().replace('effect="REAL_PIC"', 'effect="BLACK_WHITE"')
    if replacement == "shadow":
        body = body.replace("</hp:pic>", "<hp:effects><hp:shadow/></hp:effects></hp:pic>")
    elif replacement.startswith("alpha"):
        body = body.replace('effect="BLACK_WHITE"', 'effect="BLACK_WHITE" ' + replacement)
    else:
        key = replacement.split("=")[0]
        body = body.replace(key + '="0"', replacement)
    section = f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">{body}</hp:sec>'
    import zipfile

    with zipfile.ZipFile(source) as package:
        members = tuple(
            (name, section.encode() if name == "Contents/section0.xml" else package.read(name))
            for name in package.namelist()
            if name != "mimetype"
        )
    source = hwpx(tmp_path, members)
    result = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert result.picture_uses[0].unresolved_reasons == ("IMAGE_EFFECT_UNSUPPORTED",)
    assert not result.rendered_uses


def test_renderer_rejects_untyped_color_mode(tmp_path: Path) -> None:
    source = _source(tmp_path, _png(Image.new("RGB", (2, 1))), ("REAL_PIC",))
    result = extract_office_picture_uses(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    with pytest.raises(OfficeEmbeddedImageError, match="MODE_INVALID"):
        office_picture_views.render_office_picture_views(
            result.embedded_images,
            result.picture_uses,
            workspace=tmp_path / "output",
            color_modes={result.picture_uses[0].use_id: "BLACK_WHITE"},  # type: ignore[dict-item]
        )
