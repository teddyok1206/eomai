from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest
from eom_catalog_contracts import AssessmentItemContent
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import parse_native_document
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_item_renderer import (
    render_native_item_document,
    render_native_item_workspace,
)
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.native_item import NativeItemImage, NativeItemRenderRequest
from eom_hwpx_contracts.native_item_semantics import (
    expected_native_item_events,
    native_item_section_events,
)
from eom_hwpx_contracts.validation import validate_contract
from eom_hwpx_manager.native_item_projection import project_native_item
from jsonschema import ValidationError as SchemaError
from PIL import Image, ImageDraw
from pydantic import ValidationError

from tests.hwpx.helpers import synthetic_parts, write_hwpx
from tests.hwpx.test_curated_native_merge import header
from tests.unit.test_assessment_item_content import item_content

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def image_bytes(size=(321, 189), *, jpeg=False):
    output = io.BytesIO()
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline="black", width=4)
    draw.line((5, 5, size[0] - 6, size[1] - 6), fill="black", width=3)
    draw.ellipse(
        (size[0] // 3, size[1] // 3, size[0] * 2 // 3, size[1] * 2 // 3), outline="black", width=3
    )
    image.save(output, format="JPEG" if jpeg else "PNG")
    return output.getvalue()


def content_and_projection(*, body=None, repeated_image=False):
    value = item_content()
    data = image_bytes()
    value["body"][2].update(
        width_px=321, height_px=189, alt_text="INTERNAL IMAGE DESCRIPTION MUST NEVER BE VISIBLE"
    )
    value["body"][2]["artifact"]["sha256"] = sha256_bytes(data)
    value["body"][0]["text"] = "물체의 처음 속력은 $v_0$이다.\n다음 정보를 확인한다."
    value["solution"]["explanation"] = "속력 $v_0$를 비교한다."
    if repeated_image:
        extra = copy.deepcopy(value["body"][2])
        extra["block_id"] = "block_second_image"
        value["body"].insert(3, extra)
    if body is not None:
        value["body"] = [value["body"][index] for index in body]
        value["solution"]["statement_explanations"] = []
    content = AssessmentItemContent.model_validate(value)
    projection = project_native_item(
        content,
        build_id="hwpxbuild_" + "a" * 32,
        item_revision_id="itemrev_" + "b" * 32,
        source_sha256="sha256:" + "c" * 64,
        effective_content_sha256="sha256:" + "d" * 64,
        item_number=8,
    )
    return content, projection, data


def synthetic_template(workspace):
    from eom_hwpx_builder.xmlsafe import parse_xml
    from lxml import etree

    marker_paragraphs = "".join(
        f'<hp:p id="{index}" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{marker}</hp:t></hp:run></hp:p>'
        for index, marker in enumerate(
            ("[[Q_STEM]]", "[[Q_BOTTOM]]", "[[CHOICE_1]]", "[[SOLUTION]]"), 10
        )
    )
    section = f'''<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{HP}">
    <hp:p id="1" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:secPr/>
      <hp:ctrl><hp:colPr colCount="1"/></hp:ctrl></hp:run></hp:p>{marker_paragraphs}
    <hp:p id="20" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">
    <hp:equation id="21" zOrder="0" numberingType="EQUATION"><hp:sz width="1000" height="2300"/>
    <hp:pos treatAsChar="1"/><hp:script>x</hp:script></hp:equation></hp:run></hp:p>
    </hs:sec>'''.encode()
    head = header().replace(
        b'itemCnt="1"><hh:borderFill id="1"/>',
        b'itemCnt="2"><hh:borderFill id="1"/><hh:borderFill id="3"/>',
    )
    head = head.replace(b"urn:synthetic:header", b"http://www.hancom.co.kr/hwpml/2011/head")
    parts = []
    for name, data, method in synthetic_parts():
        if name.startswith("BinData/") or name == "Extra/unknown.dat":
            continue
        if name == "Contents/header.xml":
            data = head
        elif name == "Contents/section0.xml":
            data = section
        elif name == "Contents/content.hpf":
            root = parse_xml(data, name).root
            for node in tuple(root.iter()):
                if node.get("id") == "image1":
                    node.getparent().remove(node)
            data = etree.tostring(root)
        parts.append((name, data, method))
    return write_hwpx(workspace / "template.hwpx", parts)


def local_render(tmp_path, *, body=None, repeated_image=False):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    content, projection, data = content_and_projection(body=body, repeated_image=repeated_image)
    template = synthetic_template(workspace)
    # Pure renderer fixture only. The public wire contract rejects this synthetic
    # template hash; the immutable real template is covered by the installed probe.
    plan = projection.document.model_copy(update={"template_sha256": sha256_file(template)})
    for binding in projection.images:
        target = workspace / binding.image.local_file
        target.parent.mkdir(mode=0o700, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    output = workspace / "item.hwpx"
    return workspace, content, projection, plan, output


def test_projection_preserves_variable_order_and_does_not_publish_alt_text():
    content, projection, _data = content_and_projection()
    request = projection.document
    assert [block.block_id for block in request.body] == [block.block_id for block in content.body]
    assert request.source_sha256 != request.effective_content_sha256
    assert request.item_number == 8 and request.points == content.score.points
    assert "INTERNAL IMAGE DESCRIPTION" not in request.model_dump_json()
    assert projection.images[0].source == content.body[2].artifact
    validate_contract("native-item-render-request", request.model_dump(mode="json"))


def test_native_renderer_preserves_order_text_equations_tables_and_uncropped_nonstandard_png(
    tmp_path,
):
    workspace, _content, projection, plan, output = local_render(tmp_path)
    original = (workspace / "template.hwpx").read_bytes()
    equations, tables, images = render_native_item_document(workspace, plan, output)
    assert (equations, tables, images) == (3, 1, 1)
    doc = parse_native_document(read_package(output))
    entries = doc.package.by_name()
    section = entries["Contents/section0.xml"].data
    hashes = {
        key: sha256_bytes(entries[member].data) for key, (member, _media) in doc.binaries.items()
    }
    assert native_item_section_events(section, hashes) == expected_native_item_events(plan)
    assert b"<hp:tbl" in section and b"<hp:equation" in section
    assert b"INTERNAL IMAGE DESCRIPTION" not in section and b"[[" not in section
    assert "<자료>" not in "".join(
        value for kind, value in expected_native_item_events(plan) if kind == "text"
    )
    assert original == (workspace / "template.hwpx").read_bytes()
    assert len(doc.binaries) == 1
    assert next(iter(hashes.values())) == projection.images[0].source.sha256


def test_table_only_is_native_and_has_no_image_binary_or_empty_visual_frame(tmp_path):
    workspace, _content, _projection, plan, output = local_render(tmp_path, body=(0, 1, 4))
    assert render_native_item_document(workspace, plan, output)[1:] == (1, 0)
    doc = parse_native_document(read_package(output))
    assert not doc.binaries
    events = native_item_section_events(doc.package.by_name()["Contents/section0.xml"].data, {})
    assert [value for kind, value in events if kind == "table"] == ["2,3"]
    assert not any(kind == "image" for kind, _value in events)


def test_repeated_image_uses_preserve_order_but_share_one_embedded_binary(tmp_path):
    workspace, _content, projection, plan, output = local_render(tmp_path, repeated_image=True)
    assert len(projection.images) == 2
    assert projection.images[0].image.local_file == projection.images[1].image.local_file
    assert render_native_item_document(workspace, plan, output)[2] == 2
    doc = parse_native_document(read_package(output))
    assert len(doc.binaries) == 1
    section = doc.package.by_name()["Contents/section0.xml"].data
    hashes = {
        key: sha256_bytes(doc.package.by_name()[member].data)
        for key, (member, _media) in doc.binaries.items()
    }
    assert sum(kind == "image" for kind, _ in native_item_section_events(section, hashes)) == 2


def test_changed_image_is_not_replaced_with_placeholder_or_published(tmp_path):
    workspace, _content, projection, plan, output = local_render(tmp_path)
    (workspace / projection.images[0].image.local_file).write_bytes(b"wrong bytes")
    with pytest.raises(HwpxError, match="hash differs"):
        render_native_item_document(workspace, plan, output)
    assert not output.exists()


def test_public_contract_rejects_a_synthetic_template_and_unsafe_image_filename():
    _content, projection, _data = content_and_projection()
    value = projection.document.model_dump(mode="json")
    value["template_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(SchemaError):
        validate_contract("native-item-render-request", value)
    with pytest.raises(ValidationError):
        NativeItemRenderRequest.model_validate(value)
    image = next(row for row in projection.document.body if isinstance(row, NativeItemImage))
    with pytest.raises(ValidationError):
        NativeItemImage.model_validate(
            {**image.model_dump(), "local_file": "images/../outside.png"}
        )


@pytest.mark.parametrize(
    "name",
    [
        "hwpx-native-item-render-request-v1.schema.json",
        "hwpx-native-item-render-result-v1.schema.json",
    ],
)
def test_publication_schema_mirrors(name):
    root = Path(__file__).resolve().parents[2]
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE sec [<!ENTITY x "expanded">]><sec>&x;</sec>',
        '<!DOCTYPE sec [<!ENTITY x "expanded">]><sec>&x;</sec>'.encode("utf-16"),
        b'<wrong xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p/></wrong>',
    ],
)
def test_semantic_reader_rejects_dtd_utf16_and_wrong_root(payload):
    with pytest.raises(ValueError):
        native_item_section_events(payload, {})


def test_semantic_reader_rejects_clipped_picture_even_with_correct_binary(tmp_path):
    from xml.etree import ElementTree as ET

    workspace, _content, _projection, plan, output = local_render(tmp_path)
    render_native_item_document(workspace, plan, output)
    doc = parse_native_document(read_package(output))
    entries = doc.package.by_name()
    section = ET.fromstring(entries["Contents/section0.xml"].data)
    clip = next(section.iter("{" + HP + "}imgClip"))
    clip.set("right", str(int(clip.get("right")) - 100))
    hashes = {
        key: sha256_bytes(entries[member].data) for key, (member, _media) in doc.binaries.items()
    }
    with pytest.raises(ValueError, match="cropped"):
        native_item_section_events(ET.tostring(section), hashes)


def test_workspace_result_handoff_and_replay_guard_are_not_a_second_render(tmp_path, monkeypatch):
    from eom_hwpx_builder import native_item_renderer

    _content, projection, _data = content_and_projection()
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    request = root / "request.json"
    request.write_bytes(canonical_json_bytes(projection.document.model_dump(mode="json")))
    calls = []

    def already_validated_segment(workspace, plan, output):
        calls.append(plan.item_revision_id)
        output.write_bytes(b"opaque already-validated segment fixture")
        output.chmod(0o600)
        return (3, 1, 1)

    monkeypatch.setattr(
        native_item_renderer, "render_native_item_document", already_validated_segment
    )
    result = render_native_item_workspace(request, root / "result.json")
    validate_contract("native-item-render-result", result.model_dump(mode="json"))
    assert (
        result.status == "SUCCEEDED" and result.source_sha256 == projection.document.source_sha256
    )
    output = root / "output/item.hwpx"
    assert output.stat().st_mode & 0o777 == 0o640
    assert output.parent.stat().st_mode & 0o777 == 0o750
    with pytest.raises(HwpxError):
        render_native_item_workspace(request, root / "result.json")
    assert calls == [projection.document.item_revision_id]


def test_workspace_preservation_failure_has_no_published_output(tmp_path, monkeypatch):
    from eom_hwpx_builder import native_item_renderer

    _content, projection, _data = content_and_projection()
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    request = root / "request.json"
    request.write_bytes(canonical_json_bytes(projection.document.model_dump(mode="json")))

    def corrupt_segment(workspace, plan, output):
        output.write_bytes(b"unvalidated partial candidate")
        raise ValueError("preservation mismatch")

    monkeypatch.setattr(native_item_renderer, "render_native_item_document", corrupt_segment)
    result = render_native_item_workspace(request, root / "result.json")
    assert (
        result.status == "FAILED" and result.failure_code == "HWPX_NATIVE_ITEM_PRESERVATION_FAILED"
    )
    assert result.output_sha256 is None and result.image_count == 0
    assert not (root / "output/item.hwpx").exists()
    validate_contract("native-item-render-result", result.model_dump(mode="json"))


def test_request_symlink_and_duplicate_keys_do_not_start_a_renderer(tmp_path):
    _content, projection, _data = content_and_projection()
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    data = canonical_json_bytes(projection.document.model_dump(mode="json"))
    outside.write_bytes(data)
    request = root / "request.json"
    request.symlink_to(outside)
    with pytest.raises(OSError):
        render_native_item_workspace(request, root / "result.json")
    assert not (root / "output").exists() and outside.read_bytes() == data
    request.unlink()
    request.write_bytes(data.replace(b'"item_number":8', b'"item_number":8,"item_number":9'))
    with pytest.raises(ValueError, match="duplicate JSON key"):
        render_native_item_workspace(request, root / "result.json")
    assert not (root / "output").exists()
