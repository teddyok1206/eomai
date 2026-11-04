"""File-only variable Item publication with native text/tables/equations and embedded pictures."""

from __future__ import annotations

import copy
import io
import os
from pathlib import Path

from eom_hwpx_contracts.native_item import (
    NativeItemEquation,
    NativeItemImage,
    NativeItemRenderRequest,
    NativeItemRenderResult,
    NativeItemStatements,
    NativeItemTable,
)
from eom_hwpx_contracts.native_item_format import (
    NativeItemText,
    native_item_equation_script,
    native_item_publication_elements,
)
from eom_hwpx_contracts.native_item_semantics import (
    expected_native_item_events,
    native_item_section_events,
)
from eom_hwpx_contracts.validation import parse_json_object, validate_contract
from lxml import etree  # type: ignore[import-untyped]
from PIL import Image

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import (
    NativeDocument,
    merge_native_hwpx,
    parse_native_document,
    write_native_package,
)
from eom_hwpx_builder.curated_resources import NativeMergeProfile, fail
from eom_hwpx_builder.handoff import finalize_failure_result, finalize_success_handoff
from eom_hwpx_builder.native_item_nodes import HP, NativeItemNodes
from eom_hwpx_builder.util import canonical_json_bytes, read_stable_local_file, sha256_bytes
from eom_hwpx_builder.xmlsafe import local_name

OPF = "{http://www.idpf.org/2007/opf/}"
MAX_OUTPUT = 64 * 1024 * 1024


def _images(
    workspace: Path, request: NativeItemRenderRequest
) -> dict[str, tuple[NativeItemImage, bytes]]:
    result: dict[str, tuple[NativeItemImage, bytes]] = {}
    total = 0
    image_root = workspace / "images"
    for image in (block for block in request.body if isinstance(block, NativeItemImage)):
        if image.local_file in result:
            continue
        if image_root.is_symlink() or not image_root.is_dir():
            fail("native Item image input directory is invalid")
        data = read_stable_local_file(workspace / image.local_file, max_bytes=20 * 1024 * 1024)
        total += len(data)
        if total > 48 * 1024 * 1024 or sha256_bytes(data) != image.sha256:
            fail("native Item image byte budget or hash differs")
        with Image.open(io.BytesIO(data)) as decoded:
            if (
                decoded.size != (image.width_px, image.height_px)
                or decoded.format != ("PNG" if image.media_type == "image/png" else "JPEG")
                or image.width_px * image.height_px > 25000000
            ):
                fail("native Item image format or dimensions differ")
            decoded.verify()
        result[image.local_file] = (image, data)
    return result


def prepare_native_item_template(template: Path, expected_sha256: str) -> NativeDocument:
    """Capture the reviewed immutable template once for a multi-item render."""
    if (
        sha256_bytes(read_stable_local_file(template, max_bytes=50 * 1024 * 1024))
        != expected_sha256
    ):
        fail("native Item template hash differs")
    package = read_package(template)
    if package.package_sha256 != expected_sha256:
        fail("native Item template changed during read")
    document = parse_native_document(package)
    if len(document.sections) != 1 or document.binaries:
        fail("native Item template shape differs from the reviewed release")
    return document


def render_native_item_document(
    workspace: Path,
    request: NativeItemRenderRequest,
    output: Path,
    *,
    prepared_template: NativeDocument | None = None,
) -> tuple[int, int, int]:
    """Materialize one local segment; no registration, DB, source mutation or model work."""
    expected_events = expected_native_item_events(request)
    document = prepared_template or prepare_native_item_template(
        workspace / "template.hwpx",
        request.template_sha256,
    )
    if document.package.package_sha256 != request.template_sha256:
        fail("native Item prepared template identity differs")
    package = document.package
    original_section = document.sections[0][1]
    header = copy.deepcopy(document.header)
    nodes = NativeItemNodes(original_section, header)
    section = etree.Element(original_section.tag, nsmap=original_section.nsmap)
    properties = nodes.paragraph()
    run = properties[0]
    for child in tuple(run):
        run.remove(child)
    section_properties = tuple(original_section.iter(HP + "secPr"))
    columns = tuple(original_section.iter(HP + "colPr"))
    if len(section_properties) != 1 or len(columns) != 1:
        fail("native Item template page/column settings differ")
    run.append(copy.deepcopy(section_properties[0]))
    control = etree.SubElement(run, HP + "ctrl")
    control.append(copy.deepcopy(columns[0]))
    section.append(properties)
    images = _images(workspace, request)
    binary_ids = {
        name: f"nativeImage{image.sha256.removeprefix('sha256:')}"
        for name, (image, _data) in images.items()
    }
    for element in native_item_publication_elements(request):
        if isinstance(element, NativeItemText):
            section.append(
                nodes.paragraph(element.text, role=element.role, page_break=element.page_break)
            )
        elif isinstance(element, NativeItemEquation):
            section.append(
                nodes.object_paragraph(nodes.equation(native_item_equation_script(element)))
            )
        elif isinstance(element, NativeItemImage):
            section.append(
                nodes.object_paragraph(
                    nodes.picture(
                        binary_id=binary_ids[element.local_file],
                        width_px=element.width_px,
                        height_px=element.height_px,
                    )
                )
            )
        elif isinstance(element, NativeItemTable):
            if element.caption:
                section.append(nodes.paragraph(element.caption))
            section.append(nodes.object_paragraph(nodes.table((element.headers, *element.rows))))
        elif isinstance(element, NativeItemStatements):
            section.append(nodes.paragraph("<보기>"))
            lines = tuple(f"{row.label}. {row.text}" for row in element.statements)
            section.append(
                nodes.object_paragraph(nodes.table((("",),), header=False, box_lines=lines))
            )
    content = copy.deepcopy(document.content)
    manifests = tuple(node for node in content.iter() if local_name(node.tag) == "manifest")
    if len(manifests) != 1:
        fail("native Item template manifest differs")
    payloads = {
        entry.info.filename: entry.data
        for entry in package.entries
        if not entry.info.filename.startswith("Preview/")
    }
    for name, (image, data) in images.items():
        member = "BinData/native-" + Path(name).name
        etree.SubElement(
            manifests[0],
            OPF + "item",
            {
                "id": binary_ids[name],
                "href": "../" + member,
                "media-type": image.media_type,
                "isEmbeded": "1",
            },
        )
        payloads[member] = data
    for node in content.iter():
        if local_name(node.tag) == "title":
            node.text = request.title
    payloads["Contents/section0.xml"] = etree.tostring(
        section, encoding="utf-8", xml_declaration=True, standalone=True
    )
    payloads["Contents/content.hpf"] = etree.tostring(
        content, encoding="utf-8", xml_declaration=True, standalone=True
    )
    payloads["Contents/header.xml"] = etree.tostring(
        header, encoding="utf-8", xml_declaration=True, standalone=True
    )
    payloads["Preview/PrvText.txt"] = "\r\n".join(
        value for kind, value in expected_events if kind == "text"
    ).encode()
    candidate = workspace / f"native-item-{request.item_number:03d}.candidate.hwpx"
    write_native_package(payloads, candidate)
    # Reuse the native package/reference/relocation checks, not a parallel ZIP assembler.
    merge_native_hwpx((candidate,), output, profile=NativeMergeProfile.EDITABLE_V2)
    if output.stat().st_size > MAX_OUTPUT:
        fail("native Item output byte budget exceeded")
    delivered = parse_native_document(read_package(output))
    entries = delivered.package.by_name()
    binary_hashes = {
        key: sha256_bytes(entries[member].data)
        for key, (member, _media) in delivered.binaries.items()
    }
    events = native_item_section_events(entries["Contents/section0.xml"].data, binary_hashes)
    if events != expected_events or set(binary_hashes.values()) != {
        image.sha256 for image, _data in images.values()
    }:
        fail("native Item output content/order/picture bytes differ")
    return (
        sum(kind == "equation" for kind, _ in events),
        sum(isinstance(block, NativeItemTable) for block in request.body),
        sum(isinstance(block, NativeItemImage) for block in request.body),
    )


def render_native_item_workspace(request_path: Path, result_path: Path) -> NativeItemRenderResult:
    workspace = request_path.absolute().parent
    if (
        workspace.resolve(strict=True) != workspace
        or request_path.name != "request.json"
        or result_path.absolute() != workspace / "result.json"
        or result_path.exists()
        or result_path.is_symlink()
    ):
        fail("native Item workspace boundary is invalid")
    value = parse_json_object(read_stable_local_file(request_path, max_bytes=2 * 1024 * 1024))
    validate_contract("native-item-render-request", value)
    request = NativeItemRenderRequest.model_validate(value)
    output = workspace / "output/item.hwpx"
    output.parent.mkdir(mode=0o700)
    common = dict(
        build_id=request.build_id,
        item_revision_id=request.item_revision_id,
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        source_sha256=request.source_sha256,
        effective_content_sha256=request.effective_content_sha256,
    )
    try:
        equations, tables, image_count = render_native_item_document(workspace, request, output)
        result = NativeItemRenderResult.model_validate(
            {
                **common,
                "status": "SUCCEEDED",
                "output_sha256": sha256_bytes(read_stable_local_file(output, max_bytes=MAX_OUTPUT)),
                "output_size_bytes": output.stat().st_size,
                "native_equation_count": equations,
                "content_table_count": tables,
                "image_count": image_count,
                "failure_code": None,
            }
        )
    except Exception:
        failure_code = (
            "HWPX_NATIVE_ITEM_PRESERVATION_FAILED"
            if output.exists()
            else "HWPX_NATIVE_ITEM_RENDER_FAILED"
        )
        if output.exists() and not output.is_symlink():
            output.unlink()
        result = NativeItemRenderResult.model_validate(
            {
                **common,
                "status": "FAILED",
                "output_sha256": None,
                "output_size_bytes": None,
                "native_equation_count": 0,
                "content_table_count": 0,
                "image_count": 0,
                "failure_code": failure_code,
            }
        )
    value = result.model_dump(mode="json")
    validate_contract("native-item-render-result", value)
    descriptor = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json_bytes(value))
    if result.status == "SUCCEEDED":
        finalize_success_handoff(workspace, result_path, output_file_names=("item.hwpx",))
    else:
        finalize_failure_result(workspace, result_path)
    return result
