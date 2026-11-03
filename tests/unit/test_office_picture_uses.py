"""Native-use identity and geometry, independent of a PDF renderer or a worker."""

from __future__ import annotations

import io
import json
import struct
import sys
import types
from pathlib import Path

import pytest
from eom_image_contracts.models import content_sha256
from eom_image_contracts.office_picture_uses import (
    OfficePictureUseCatalog,
    office_object_id,
)
from eom_image_contracts.validation import load_schema
from eom_image_provider.office_embedded_images import OfficeEmbeddedImageError
from eom_image_provider.office_picture_uses import extract_office_picture_uses
from PIL import Image

from tests.unit.test_office_embedded_images import hwpx, raster, sha

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"


def picture(
    *,
    reference: str = "image1",
    clip: str = 'left="0" top="0" right="1900" bottom="1300"',
    angle: int = 0,
) -> str:
    matrices = ((1, 0, 0, 1), (0, -1, 1, 0), (-1, 0, 0, -1), (0, 1, -1, 0))
    a, b, c, d = matrices[(angle // 90) % 4]
    return f'''<hp:pic>
        <hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="1900" y="0"/>
          <hc:pt2 x="1900" y="1300"/><hc:pt3 x="0" y="1300"/></hp:imgRect>
        <hp:imgClip {clip}/><hp:rotationInfo angle="{angle}"/>
        <hp:flip horizontal="0" vertical="0"/>
        <hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:rotMatrix e1="{a}" e2="{b}" e3="0" e4="{c}" e5="{d}" e6="0"/></hp:renderingInfo>
        <hc:img binaryItemIDRef="{reference}" bright="0" contrast="0" effect="REAL_PIC"/>
      </hp:pic>'''


def source(
    tmp_path: Path, body: str, *, manifest: str | None = None, raw_section: bytes | None = None
) -> Path:
    header = (
        manifest
        or f'''<opf:package xmlns:opf="{OPF}"><opf:manifest>
      <opf:item id="image1" href="../BinData/a.png"/>
      <opf:item id="image2" href="../BinData/b.png"/>
      </opf:manifest></opf:package>'''
    )
    section = raw_section or f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">{body}</hp:sec>'.encode()
    return hwpx(
        tmp_path,
        (
            ("Contents/content.hpf", header.encode()),
            ("Contents/section0.xml", section),
            ("BinData/a.png", raster()),
            ("BinData/b.png", raster("BMP")),
        ),
    )


def extracted(tmp_path: Path, path: Path) -> OfficePictureUseCatalog:
    return extract_office_picture_uses(
        path, expected_sha256=sha(path), workspace=tmp_path / "output"
    )


def rehash(value: dict) -> dict:
    return {
        **value,
        "manifest_sha256": content_sha256(
            {k: v for k, v in value.items() if k != "manifest_sha256"}
        ),
    }


def test_same_member_has_distinct_main_and_reference_use_ids(tmp_path: Path) -> None:
    result = extracted(tmp_path, source(tmp_path, picture() + picture()))
    first, second = result.picture_uses
    assert first.source_member == second.source_member == "BinData/a.png"
    assert first.use_id != second.use_id
    assert first.use_id == office_object_id(result.embedded_images.source_sha256, first.locator)
    # Inventory does not approve a main/reference role from pixel shape or x/y.
    assert "role" not in first.model_dump()
    assert first.unresolved_reasons == second.unresolved_reasons == ()
    assert result.rendered_uses[0].member_path == result.rendered_uses[1].member_path
    assert result.rendered_uses[0].member_path.startswith("images/")
    assert list((tmp_path / "output/uses").iterdir()) == []
    assert (
        OfficePictureUseCatalog.model_validate_json(
            (tmp_path / "output/picture-use-catalog.json").read_bytes()
        )
        == result
    )


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_native_crop_and_rotation_never_use_a_pdf_rectangle(tmp_path: Path, angle: int) -> None:
    result = extracted(
        tmp_path,
        source(
            tmp_path, picture(angle=angle, clip='left="101" top="201" right="1801" bottom="1201"')
        ),
    )
    geometry = result.picture_uses[0].geometry
    assert geometry is not None
    assert geometry.pixel_box(width=19, height=13) == (1, 2, 19, 13)
    assert geometry.clockwise_quarter_turns == angle // 90
    assert geometry.original_extent == (1900, 1300)
    view = result.rendered_uses[0]
    with Image.open(io.BytesIO(raster())) as original:
        expected = original.crop((1, 2, 19, 13))
        for _ in range(angle // 90):
            expected = expected.transpose(Image.Transpose.ROTATE_270)
        with Image.open(tmp_path / "output" / view.member_path) as actual:
            assert actual.size == expected.size
            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()


def test_grouped_native_labels_are_explicit_not_dropped(tmp_path: Path) -> None:
    result = extracted(
        tmp_path,
        source(
            tmp_path,
            "<hp:container><hp:rect><hp:drawText><hp:t>A</hp:t></hp:drawText></hp:rect>"
            + picture()
            + "</hp:container>",
        ),
    )
    use = result.picture_uses[0]
    group = next(obj for obj in result.native_objects if obj.kind == "GROUP")
    assert use.group_id == group.object_id
    assert use.unresolved_reasons == ("GROUP_COMPOSITION_REQUIRED",)
    assert any(
        obj.group_id == group.object_id and obj.kind == "DRAWING" for obj in result.native_objects
    )
    assert result.rendered_uses == ()


def test_table_only_and_equation_stay_native_without_rasters(tmp_path: Path) -> None:
    result = extracted(tmp_path, source(tmp_path, "<hp:tbl><hp:equation/></hp:tbl>"))
    assert result.picture_uses == ()
    assert [obj.kind for obj in result.native_objects] == ["TABLE", "EQUATION"]


@pytest.mark.parametrize(
    "case", ["outside-clip", "zero-clip", "missing-geometry", "arbitrary-rotation", "shear", "nan"]
)
def test_unsupported_geometry_is_explicit_without_fallback_crop(tmp_path: Path, case: str) -> None:
    body = picture()
    if case == "outside-clip":
        body = body.replace('right="1900"', 'right="2000"')
    elif case == "zero-clip":
        body = body.replace('right="1900" bottom="1300"', 'right="0" bottom="0"')
    elif case == "missing-geometry":
        body = body.replace('<hp:rotationInfo angle="0"/>', "")
    elif case == "arbitrary-rotation":
        body = body.replace('angle="0"', 'angle="13"')
    elif case == "shear":
        body = body.replace('e2="0"', 'e2="0.5"', 1)
    else:
        body = body.replace('e1="1"', 'e1="nan"', 1)
    result = extracted(tmp_path, source(tmp_path, body))
    assert result.picture_uses[0].geometry is None
    assert "GEOMETRY_UNRESOLVED" in result.picture_uses[0].unresolved_reasons


def test_external_image_is_not_resolved_or_used(tmp_path: Path) -> None:
    manifest = f'<opf:package xmlns:opf="{OPF}"><opf:item id="image1" href="file:///etc/passwd"/></opf:package>'
    result = extracted(tmp_path, source(tmp_path, picture(), manifest=manifest))
    assert result.picture_uses[0].source_member is None
    assert result.picture_uses[0].unresolved_reasons == ("EXTERNAL_IMAGE",)
    assert "/etc" not in result.model_dump_json()


@pytest.mark.parametrize(
    "raw",
    [
        b'<!DOCTYPE x [<!ENTITY x "unsafe">]><x/>',
        b"<x>\0</x>",
        b'<x><xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="/etc/passwd"/></x>',
    ],
)
def test_untrusted_xml_rejected(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(OfficeEmbeddedImageError):
        extracted(tmp_path, source(tmp_path, "", raw_section=raw))


@pytest.mark.parametrize(
    "field", ["hash", "identity", "duplicate", "missing-member", "missing-group", "reordered"]
)
def test_manifest_rejects_broken_identities_and_closure(tmp_path: Path, field: str) -> None:
    result = extracted(tmp_path, source(tmp_path, picture() + picture(reference="image2")))
    value = result.model_dump(mode="json")
    if field == "hash":
        value["manifest_sha256"] = "sha256:" + "0" * 64
    elif field == "identity":
        value["picture_uses"][0]["use_id"] = "officeobj_" + "0" * 32
    elif field == "duplicate":
        value["picture_uses"] *= 2
    elif field == "missing-member":
        value["picture_uses"][0]["source_member"] = "BinData/missing.png"
    elif field == "missing-group":
        value["picture_uses"][0]["group_id"] = "officeobj_" + "0" * 32
        value["picture_uses"][0]["unresolved_reasons"] = ["GROUP_COMPOSITION_REQUIRED"]
    else:
        value["picture_uses"].reverse()
    with pytest.raises(ValueError):
        OfficePictureUseCatalog.model_validate(value if field == "hash" else rehash(value))


def record(tag: int, level: int, body: bytes) -> bytes:
    return struct.pack("<I", tag | level << 10 | len(body) << 20) + body


def hwp_picture(*, binding: int = 1) -> bytes:
    raw = bytearray(91)
    struct.pack_into("<8i", raw, 12, 0, 0, 1900, 0, 1900, 1300, 0, 1300)
    struct.pack_into("<4i", raw, 44, 0, 0, 1900, 1300)
    struct.pack_into("<H", raw, 71, binding)
    return bytes(raw)


def hwp_shape() -> bytes:
    matrix = struct.pack("<6d", 1, 0, 0, 0, 1, 0)
    return (
        b"cip$cip$"
        + struct.pack("<iiHH5IHiiH", 0, 0, 0, 0, 1900, 1300, 1900, 1300, 0, 0, 0, 0, 1)
        + matrix * 3
    )


def test_hwp_bindata_index_is_not_the_storage_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The first DocInfo entry names storage 8, not BIN0001. This occurs in real
    # edited Hancom files and must not be inferred from the picture's index.
    header = b"HWP Document File".ljust(32, b"\0") + b"\0\1\0\5" + struct.pack("<I", 0)
    extension = "bmp".encode("utf-16-le")
    bindings = record(18, 0, struct.pack("<HHH", 1, 8, 3) + extension)
    section = (
        record(76, 2, hwp_shape())
        + record(85, 3, hwp_picture())
        + record(76, 2, hwp_shape())
        + record(85, 3, hwp_picture())
        + record(77, 1, b"table")
        + record(88, 1, b"equation")
    )
    streams = {
        "FileHeader": header,
        "DocInfo": bindings,
        "BodyText/Section0": section,
        "BinData/BIN0008.bmp": raster("BMP"),
    }

    class ReadOnlyOle:
        def __init__(self, source: object, *, write_mode: bool, raise_defects: int) -> None:
            assert not write_mode

        def __enter__(self) -> ReadOnlyOle:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def exists(self, name: str) -> bool:
            return name in streams

        def get_size(self, name: str | list[str]) -> int:
            return len(streams[name if isinstance(name, str) else "/".join(name)])

        def openstream(self, name: str | list[str]) -> io.BytesIO:
            return io.BytesIO(streams[name if isinstance(name, str) else "/".join(name)])

        def listdir(self) -> list[list[str]]:
            return [name.split("/") for name in streams]

    monkeypatch.setitem(
        sys.modules, "olefile", types.SimpleNamespace(OleFileIO=ReadOnlyOle, DEFECT_INCORRECT=30)
    )
    path = tmp_path / "source.hwp"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"synthetic native-use test")
    result = extracted(tmp_path, path)
    assert result.embedded_images.source_format == "HWP5"
    assert len(result.picture_uses) == 2
    assert (
        result.picture_uses[0].source_member
        == result.picture_uses[1].source_member
        == "BinData/BIN0008.bmp"
    )
    assert result.picture_uses[0].use_id != result.picture_uses[1].use_id
    assert all(
        use.geometry is not None and use.unresolved_reasons == () for use in result.picture_uses
    )
    assert [obj.kind for obj in result.native_objects] == ["TABLE", "EQUATION"]


@pytest.mark.parametrize(
    "payload",
    [
        b"\0",
        struct.pack("<I", 85 | 3 << 10 | 4095 << 20),
        struct.pack("<II", 85 | 4095 << 20, 1000),
    ],
)
def test_hwp_truncated_and_extended_records_fail_explicitly(payload: bytes) -> None:
    from eom_image_provider.office_picture_records import hwp_records

    with pytest.raises(OfficeEmbeddedImageError, match="RECORD_INVALID"):
        tuple(hwp_records(payload))


def test_schema_resources_and_predecessor_are_unchanged() -> None:
    import hashlib

    root = Path(__file__).resolve().parents[2]
    schema = load_schema("office-picture-use-catalog")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema == json.loads(
        (root / "schemas/image-provider/office-picture-use-catalog-v1.schema.json").read_bytes()
    )
    assert (
        hashlib.sha256(
            (root / "schemas/image-provider/office-embedded-image-set-v1.schema.json").read_bytes()
        ).hexdigest()
        == "f3fd7bd660783fe4c82b5d96d3c3057bb3f041f7261b8ba15734417649bbf27a"
    )
