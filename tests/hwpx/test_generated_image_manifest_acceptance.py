from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from eom_hwpx_manager.content_team_output_acceptance import verify_content_team_output
from eom_hwpx_manager.errors import HwpxManagerError

from tests.hwpx.test_content_team_output_acceptance import (
    HANDOFF,
    _render_paired_images,
    _render_table_image,
    _render_table_only,
    _rewrite_member,
    _sha256,
)

pytestmark = pytest.mark.skipif(
    not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable"
)


def _image_manifest_items(payload: bytes) -> tuple[ElementTree.Element, ...]:
    root = ElementTree.fromstring(payload)
    return tuple(
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "item" and node.attrib.get("media-type") == "image/png"
    )


@pytest.mark.parametrize("image_count", (1, 2))
def test_manager_accepts_literal_embedded_png_manifest(tmp_path: Path, image_count: int) -> None:
    output, output_sha256, expectation = _render_paired_images(tmp_path, image_count)
    with zipfile.ZipFile(output) as archive:
        image_items = _image_manifest_items(archive.read("Contents/content.hpf"))
        assert len(image_items) == image_count
        for image_item, image in zip(image_items, expectation.images, strict=True):
            member = image_item.attrib["href"]
            assert member.startswith("BinData/")
            assert member in archive.namelist()
            assert image_item.attrib["isEmbeded"] == "1"
            assert _sha256(archive.read(member)) == image.sha256

    receipt = verify_content_team_output(
        output, expected_sha256=output_sha256, expectations=(expectation,)
    )

    assert len(receipt.items[0].images) == image_count


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    (
        ("href", "../{member}"),
        ("href", ".././{member}"),
        ("href", "./../{member}"),
        ("href", "BinData/./{filename}"),
        ("href", "BinData/subdir/../{filename}"),
        ("href", "BinData//{filename}"),
        ("isEmbeded", None),
        ("isEmbeded", "0"),
        ("isEmbeded", "false"),
        ("isEmbeded", "true"),
        ("media-type", None),
        ("media-type", "application/octet-stream"),
    ),
)
def test_manager_rejects_normalized_or_nonembedded_generated_png(
    tmp_path: Path, attribute: str, replacement: str | None
) -> None:
    output, _, expectation = _render_paired_images(tmp_path, image_count=2)
    tampered = tmp_path / "tampered.hwpx"

    def change_manifest(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        image_items = tuple(
            node
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "item"
            and node.attrib.get("media-type") == "image/png"
        )
        assert len(image_items) == 2
        image = image_items[1]
        member = image.attrib["href"]
        if replacement is None:
            del image.attrib[attribute]
        else:
            image.attrib[attribute] = replacement.format(
                member=member, filename=member.rsplit("/", 1)[-1]
            )
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))

    _rewrite_member(output, tampered, "Contents/content.hpf", change_manifest)

    with pytest.raises(HwpxManagerError, match="generated image manifest"):
        verify_content_team_output(
            tampered,
            expected_sha256=_sha256(tampered.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.parametrize(
    ("attribute", "replacement_name"),
    (
        ("href", "{urn:eom-test-foreign}href"),
        ("media-type", "{urn:eom-test-foreign}media-type"),
        ("isEmbeded", "{urn:eom-test-foreign}isEmbeded"),
        ("id", "{urn:eom-test-foreign}id"),
        ("href", "HREF"),
        ("media-type", "MEDIA-TYPE"),
        ("isEmbeded", "isembeded"),
        ("id", "ID"),
    ),
)
def test_manager_rejects_non_native_generated_image_attribute_names(
    tmp_path: Path, attribute: str, replacement_name: str
) -> None:
    output, _, expectation = _render_paired_images(tmp_path, image_count=1)
    tampered = tmp_path / "non-native-attribute.hwpx"

    def change_manifest(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        image = next(
            node
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "item"
            and node.attrib.get("media-type") == "image/png"
        )
        image.attrib[replacement_name] = image.attrib.pop(attribute)
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))

    _rewrite_member(output, tampered, "Contents/content.hpf", change_manifest)

    with pytest.raises(HwpxManagerError, match="generated image manifest"):
        verify_content_team_output(
            tampered,
            expected_sha256=_sha256(tampered.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.parametrize(
    "replacement_tag",
    (
        "{urn:eom-test-foreign}item",
        "item",
        "{http://www.idpf.org/2007/opf/}ITEM",
    ),
)
def test_manager_rejects_non_native_generated_image_element_names(
    tmp_path: Path, replacement_tag: str
) -> None:
    output, _, expectation = _render_paired_images(tmp_path, image_count=1)
    tampered = tmp_path / "non-native-element.hwpx"

    def change_manifest(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        image = next(
            node
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "item"
            and node.attrib.get("media-type") == "image/png"
        )
        image.tag = replacement_tag
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))

    _rewrite_member(output, tampered, "Contents/content.hpf", change_manifest)

    with pytest.raises(HwpxManagerError, match="generated image manifest"):
        verify_content_team_output(
            tampered,
            expected_sha256=_sha256(tampered.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.parametrize(
    ("field", "replacement_name"),
    (
        ("tag", "{urn:eom-test-foreign}img"),
        ("tag", "img"),
        ("tag", "{http://www.hancom.co.kr/hwpml/2011/core}IMG"),
        ("attribute", "{urn:eom-test-foreign}binaryItemIDRef"),
        ("attribute", "binaryitemidref"),
    ),
)
def test_manager_rejects_non_native_section_image_references(
    tmp_path: Path, field: str, replacement_name: str
) -> None:
    output, _, expectation = _render_paired_images(tmp_path, image_count=1)
    tampered = tmp_path / "non-native-section-reference.hwpx"

    def change_section(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        image = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "img")
        if field == "tag":
            image.tag = replacement_name
        else:
            image.attrib[replacement_name] = image.attrib.pop("binaryItemIDRef")
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))

    _rewrite_member(output, tampered, "Contents/section0.xml", change_section)

    with pytest.raises(HwpxManagerError, match="generated image reference is not native"):
        verify_content_team_output(
            tampered,
            expected_sha256=_sha256(tampered.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.parametrize("reference", (None, ""))
def test_manager_rejects_missing_or_empty_section_image_reference(
    tmp_path: Path, reference: str | None
) -> None:
    output, _, expectation = _render_paired_images(tmp_path, image_count=1)
    tampered = tmp_path / "missing-section-reference.hwpx"

    def change_section(payload: bytes) -> bytes:
        root = ElementTree.fromstring(payload)
        image = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "img")
        if reference is None:
            del image.attrib["binaryItemIDRef"]
        else:
            image.attrib["binaryItemIDRef"] = reference
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))

    _rewrite_member(output, tampered, "Contents/section0.xml", change_section)

    with pytest.raises(HwpxManagerError, match="generated image reference is not native"):
        verify_content_team_output(
            tampered,
            expected_sha256=_sha256(tampered.read_bytes()),
            expectations=(expectation,),
        )


def test_manager_accepts_table_only_without_image_manifest(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_table_only(tmp_path)

    receipt = verify_content_team_output(
        output, expected_sha256=output_sha256, expectations=(expectation,)
    )

    assert receipt.items[0].images == ()
    assert len(receipt.items[0].tables) == 1


def test_manager_accepts_table_image_without_changing_ordinal(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_table_image(tmp_path)

    receipt = verify_content_team_output(
        output, expected_sha256=output_sha256, expectations=(expectation,)
    )

    assert tuple(image.visual_ordinal for image in receipt.items[0].images) == (1,)
    assert tuple(table.visual_ordinal for table in receipt.items[0].tables) == (0,)
