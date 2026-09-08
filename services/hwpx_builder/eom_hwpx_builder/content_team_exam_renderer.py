"""Deterministic whole-exam renderer built from reviewed content-team item layouts."""

from __future__ import annotations

import copy
import json
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import (
    ContentTeamExamBuildResult,
    ContentTeamExamBuildResultContract,
    ContentTeamExamBuildResultV2,
    ContentTeamExamBuildResultV3,
    ContentTeamExamImageSource,
    ContentTeamExamItemSourceV2,
    ContentTeamExamItemSourceV3,
    ContentTeamExamRenderRequest,
    ContentTeamExamRenderRequestContract,
    ContentTeamExamRenderRequestV2,
    ContentTeamExamRenderRequestV3,
    ContentTeamImageSource,
    content_team_exam_item_set_projection,
    content_team_exam_render_plan_projection,
    parse_content_team_markdown,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
    validate_contract,
)
from lxml import etree  # type: ignore[import-untyped]
from pydantic import ValidationError

from eom_hwpx_builder.analyzer import analyze_package, resolve_part
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, SafePackage, read_package
from eom_hwpx_builder.content_team_handoff import (
    EXPECTED_MEMBER_HASHES,
    inspect_content_team_handoff,
)
from eom_hwpx_builder.content_team_images import inject_content_team_images
from eom_hwpx_builder.content_team_renderer import (
    MAX_IMAGE_BYTES,
    MAX_JSON_BYTES,
    MAX_MARKDOWN_BYTES,
    _external_render,
    _extract_runtime,
    _load_draft,
    _read_regular,
    _workspace_path,
)
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.handoff import (
    finalize_failure_result,
    finalize_success_handoff,
    prepare_private_handoff_file,
    write_private_json,
)
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_builder.xmlsafe import ParsedXml, local_name, parse_xml, serialize_xml

EXAM_RENDERER_VERSION = "1.0.0"
EXAM_RENDERER_VERSION_V2 = "2.0.0"
EXAM_RENDERER_VERSION_V3 = "3.0.0"
MAX_EXAM_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_HANDOFF_BYTES = 64 * 1024 * 1024

_PLANNED_SCORE_DISPLAY = {1500: "1.5", 2000: "2", 2500: "2.5", 3000: "3"}


def _load_exam_request(raw: dict[str, Any]) -> ContentTeamExamRenderRequestContract:
    if raw.get("schema_version") == "content-team-exam-render-request/3.0":
        validate_contract("content-team-exam-render-request-v3", raw)
        return ContentTeamExamRenderRequestV3.model_validate(raw)
    if raw.get("schema_version") == "content-team-exam-render-request/2.0":
        validate_contract("content-team-exam-render-request-v2", raw)
        return ContentTeamExamRenderRequestV2.model_validate(raw)
    validate_contract("content-team-exam-render-request", raw)
    return ContentTeamExamRenderRequest.model_validate(raw)


def _item_set_sha256(request: ContentTeamExamRenderRequestContract) -> str:
    return sha256_bytes(canonical_json_bytes(content_team_exam_item_set_projection(request)))


def _render_plan_sha256(
    request: ContentTeamExamRenderRequestV2 | ContentTeamExamRenderRequestV3,
) -> str:
    return sha256_bytes(canonical_json_bytes(content_team_exam_render_plan_projection(request)))


def _read_request(path: Path) -> bytes:
    """Capture one bounded regular request through a stable no-follow descriptor."""

    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request cannot be opened") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 4 * 1024 * 1024:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request metadata is unsafe")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(before.st_size - len(payload), 1024 * 1024))
            if not chunk:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request was truncated")
            payload.extend(chunk)
        if os.read(descriptor, 1):
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request grew while reading")
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_identity != after_identity:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request changed while reading")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _attribute(element: etree._Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if local_name(key).casefold() == name.casefold():
            return str(value)
    return None


def _set_attribute(element: etree._Element, name: str, value: str) -> None:
    for key in element.attrib:
        if local_name(key).casefold() == name.casefold():
            element.attrib[key] = value
            return
    element.attrib[name] = value


def _serialize_like(original: bytes, part_name: str, root: etree._Element) -> bytes:
    parsed = parse_xml(original, part_name)
    return serialize_xml(
        ParsedXml(
            root=root,
            declaration=parsed.declaration,
            newline=parsed.newline,
            bom=parsed.bom,
        )
    )


def _manifest_parts(
    package: SafePackage,
) -> tuple[etree._Element, etree._Element, etree._Element, etree._Element]:
    entries = package.by_name()
    try:
        content = parse_xml(entries["Contents/content.hpf"].data, "Contents/content.hpf").root
    except KeyError as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item has no package manifest",
        ) from exc
    manifest = next(
        (element for element in content.iter() if local_name(element.tag) == "manifest"), None
    )
    spine = next(
        (element for element in content.iter() if local_name(element.tag) == "spine"), None
    )
    if manifest is None or spine is None:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item manifest is incomplete",
        )
    items = [element for element in manifest if local_name(element.tag) == "item"]
    section_items = [
        element
        for element in items
        if (_attribute(element, "href") or "").rsplit("/", 1)[-1].startswith("section")
    ]
    if len(section_items) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item must expose exactly one section",
        )
    return content, manifest, spine, section_items[0]


def _binary_manifest_items(
    package: SafePackage, manifest: etree._Element
) -> tuple[tuple[etree._Element, str], ...]:
    names = package.by_name()
    result: list[tuple[etree._Element, str]] = []
    for element in manifest:
        if local_name(element.tag) != "item":
            continue
        href = _attribute(element, "href")
        if href is None:
            continue
        resolved = resolve_part("Contents/content.hpf", href)
        if resolved.startswith("BinData/"):
            if resolved not in names:
                raise HwpxError(
                    HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                    "content-team item binary manifest target is missing",
                )
            result.append((element, resolved))
    return tuple(result)


def _merge_item_packages(items: tuple[Path, ...], output: Path) -> dict[str, Any]:
    if not items or len(items) > 200:
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "exam item set is invalid")
    packages = tuple(read_package(path) for path in items)
    first = packages[0]
    first_entries = first.by_name()
    first_content, first_manifest, first_spine, first_section_item = _manifest_parts(first)
    first_header = first_entries.get("Contents/header.xml")
    if first_header is None:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item has no shared header",
        )

    for child in tuple(first_spine):
        if local_name(child.tag) == "itemref":
            first_spine.remove(child)
    for child in tuple(first_manifest):
        href = _attribute(child, "href") if local_name(child.tag) == "item" else None
        if href is not None and (
            resolve_part("Contents/content.hpf", href).startswith("BinData/")
            or (href.rsplit("/", 1)[-1].startswith("section"))
        ):
            first_manifest.remove(child)

    shared_payloads: dict[str, tuple[bytes, int]] = {}
    for entry in first.entries:
        name = entry.info.filename
        if (
            name == "Contents/content.hpf"
            or name.startswith("Contents/section")
            or name.startswith("BinData/")
            or name.startswith("Preview/")
        ):
            continue
        shared_payloads[name] = (entry.data, entry.info.compress_type)
    payloads = dict(shared_payloads)

    item_reports: list[dict[str, Any]] = []
    for index, (path, package) in enumerate(zip(items, packages, strict=True)):
        actual_shared = {
            entry.info.filename: (entry.data, entry.info.compress_type)
            for entry in package.entries
            if entry.info.filename != "Contents/content.hpf"
            and not entry.info.filename.startswith("Contents/section")
            and not entry.info.filename.startswith("BinData/")
            and not entry.info.filename.startswith("Preview/")
        }
        if actual_shared != shared_payloads:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "exam item package has a different reviewed template runtime",
            )
        _content, manifest, _spine, section_item = _manifest_parts(package)
        entries = package.by_name()
        header = entries.get("Contents/header.xml")
        if header is None or header.data != first_header.data:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "exam item headers do not share the reviewed template identity",
            )
        section_href = _attribute(section_item, "href")
        section_id = _attribute(section_item, "id")
        if section_href is None or section_id is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "exam item section manifest is incomplete",
            )
        section_name = resolve_part("Contents/content.hpf", section_href)
        section_entry = entries.get(section_name)
        if section_entry is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                "exam item section target is missing",
            )
        section = parse_xml(section_entry.data, section_name).root
        binary_items = _binary_manifest_items(package, manifest)
        binary_id_map: dict[str, str] = {}
        for binary_number, (binary_item, binary_name) in enumerate(binary_items):
            old_id = _attribute(binary_item, "id")
            if old_id is None:
                raise HwpxError(
                    HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                    "exam item binary identity is missing",
                )
            new_id = f"eomExam{index + 1:03d}Binary{binary_number:03d}"
            suffix = Path(binary_name).suffix.lower()
            new_name = f"BinData/item-{index + 1:03d}-{binary_number:03d}{suffix}"
            binary_id_map[old_id] = new_id
            cloned_binary = copy.deepcopy(binary_item)
            _set_attribute(cloned_binary, "id", new_id)
            _set_attribute(cloned_binary, "href", f"../{new_name}")
            first_manifest.append(cloned_binary)
            payloads[new_name] = (
                entries[binary_name].data,
                entries[binary_name].info.compress_type,
            )
        for element in section.iter():
            for key, value in tuple(element.attrib.items()):
                if local_name(key).casefold() == "binaryitemidref":
                    replacement = binary_id_map.get(str(value))
                    if replacement is None:
                        raise HwpxError(
                            HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                            "section references an undeclared binary item",
                        )
                    element.attrib[key] = replacement
        new_section_id = f"section{index}"
        new_section_name = f"Contents/section{index}.xml"
        cloned_section = copy.deepcopy(first_section_item if index == 0 else section_item)
        _set_attribute(cloned_section, "id", new_section_id)
        _set_attribute(cloned_section, "href", f"section{index}.xml")
        first_manifest.append(cloned_section)
        itemref = etree.Element(first_spine[0].tag if len(first_spine) else cloned_section.tag)
        if local_name(itemref.tag) != "itemref":
            namespace = etree.QName(first_spine).namespace
            itemref = etree.Element(f"{{{namespace}}}itemref" if namespace else "itemref")
        _set_attribute(itemref, "idref", new_section_id)
        first_spine.append(itemref)
        payloads[new_section_name] = (
            _serialize_like(section_entry.data, section_name, section),
            section_entry.info.compress_type,
        )
        item_reports.append(
            {
                "position": index + 1,
                "source_file": path.name,
                "section": new_section_name,
                "binary_count": len(binary_items),
            }
        )

    header = parse_xml(first_header.data, "Contents/header.xml").root
    _set_attribute(header, "secCnt", str(len(items)))
    payloads["Contents/header.xml"] = (
        _serialize_like(first_header.data, "Contents/header.xml", header),
        first_header.info.compress_type,
    )
    content_entry = first_entries["Contents/content.hpf"]
    payloads["Contents/content.hpf"] = (
        _serialize_like(content_entry.data, "Contents/content.hpf", first_content),
        content_entry.info.compress_type,
    )
    payloads["Preview/PrvText.txt"] = (
        f"EOM 통합과학 모의고사 · {len(items)}문항\n".encode(),
        zipfile.ZIP_DEFLATED,
    )

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    temporary = output.with_name(f".{output.name}.tmp")
    total = 0
    try:
        with zipfile.ZipFile(temporary, "x", allowZip64=False) as archive:
            ordered_names = [
                "mimetype",
                *sorted(name for name in payloads if name != "mimetype"),
            ]
            for name in ordered_names:
                data, compression = payloads[name]
                total += len(data)
                if total > MAX_EXAM_PACKAGE_BYTES:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED,
                        "assembled exam exceeds its package limit",
                    )
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else compression
                info.external_attr = 0o100600 << 16
                archive.writestr(info, data)
        temporary.chmod(0o600)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    analysis = analyze_package(output)
    if (
        analysis.mimetype != "application/hwp+zip"
        or analysis.active_content
        or analysis.external_links
        or analysis.sections != tuple(f"Contents/section{i}.xml" for i in range(len(items)))
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "assembled exam package failed structural validation",
        )
    return {
        "status": "PASS",
        "section_count": len(analysis.sections),
        "binary_count": len(analysis.bindata),
        "items": item_reports,
        "entries": [entry.model_dump(mode="json") for entry in analysis.entries],
        "warnings": list(analysis.warnings),
    }


def _as_item_image(value: ContentTeamExamImageSource) -> ContentTeamImageSource:
    return ContentTeamImageSource(
        visual_ordinal=value.visual_ordinal,
        label=value.label,
        artifact_id=value.artifact_id,
        artifact_revision_id=value.artifact_revision_id,
        artifact_member=value.artifact_member,
        sha256=value.sha256,
        schema_ref=value.schema_ref,
        media_type=value.media_type,
        width_px=value.width_px,
        height_px=value.height_px,
        alt_text=value.alt_text,
        file_name=f"input/visual-{value.visual_ordinal}.png",
    )


def render_content_team_exam_workspace(
    request_path: Path, result_path: Path
) -> ContentTeamExamBuildResultContract:
    started = datetime.now(UTC)
    workspace = request_path.parent.resolve(strict=True)
    if result_path.resolve(strict=False).parent != workspace or result_path.name != "result.json":
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "result path escaped workspace")
    try:
        request_bytes = _read_request(request_path)
        request_raw: object = json.loads(request_bytes.decode("utf-8"))
        if not isinstance(request_raw, dict):
            raise ValueError("request is not an object")
        request = _load_exam_request(request_raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
            "exam render request is invalid",
        ) from exc

    handoff_archive = _workspace_path(workspace, request.handoff.archive_file)
    _read_regular(
        handoff_archive,
        max_bytes=MAX_HANDOFF_BYTES,
        expected_sha256=request.handoff.archive_sha256,
    )
    evidence = inspect_content_team_handoff(handoff_archive)
    if (
        evidence.entry_count != request.handoff.entry_count
        or evidence.uncompressed_bytes != request.handoff.uncompressed_bytes
        or tuple((row.purpose, row.sha256, row.size) for row in evidence.members)
        != tuple((row.purpose, row.sha256, row.size) for row in request.handoff.members)
        or {row.purpose: row.sha256 for row in evidence.members} != dict(EXPECTED_MEMBER_HASHES)
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
            "content-team handoff evidence differs from the exam request",
        )
    runtime = _workspace_path(workspace, "runtime", must_exist=False)
    template = _extract_runtime(handoff_archive, evidence, runtime)
    item_output_root = _workspace_path(workspace, "item-output", must_exist=False)
    item_output_root.mkdir(mode=0o700)
    item_outputs: list[Path] = []
    total_equations = 0
    total_tables = 0
    total_visuals = 0
    item_reports: list[dict[str, Any]] = []
    for item in request.items:
        json_bytes = _read_regular(
            _workspace_path(workspace, item.json_file),
            max_bytes=MAX_JSON_BYTES,
            expected_sha256=item.source_json_sha256,
        )
        markdown_bytes = _read_regular(
            _workspace_path(workspace, item.markdown_file),
            max_bytes=MAX_MARKDOWN_BYTES,
            expected_sha256=item.source_markdown_sha256,
        )
        source_schema_ref = (
            item.source_schema_ref
            if isinstance(item, ContentTeamExamItemSourceV3)
            else "eom.assessment.item-content/2.0"
        )
        draft = _load_draft(json_bytes, source_schema_ref=source_schema_ref)
        if serialize_content_team_markdown(draft) != markdown_bytes:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "exam item JSON and Markdown differ",
            )
        parsed = (
            parse_content_team_markdown_v2(markdown_bytes)
            if isinstance(item, ContentTeamExamItemSourceV3)
            else parse_content_team_markdown(markdown_bytes)
        )
        if parsed.source_sha256 != item.source_markdown_sha256:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "exam item Markdown identity differs",
            )
        rendered_score_display: str = draft.score_display
        if isinstance(item, ContentTeamExamItemSourceV3):
            if draft.score_display != _PLANNED_SCORE_DISPLAY[item.points_milli]:
                raise HwpxError(
                    HwpxErrorCode.HWPX_SEMANTIC_MISMATCH,
                    "V3 exam item source score differs from its exact placement score",
                )
        elif isinstance(item, ContentTeamExamItemSourceV2):
            rendered_score_display = _PLANNED_SCORE_DISPLAY[item.points_milli]
        output = item_output_root / f"item-{item.position:03d}.hwpx"
        report = _external_render(
            runtime,
            template,
            markdown_bytes,
            output,
            draft,
            item_number_override=item.position,
            score_display_override=rendered_score_display,
        )
        expected_slots = tuple(
            (ordinal, visual.label)
            for ordinal, visual in enumerate(draft.visuals)
            if visual.kind == "IMAGE"
        )
        actual_slots = tuple((image.visual_ordinal, image.label) for image in item.images)
        if actual_slots != expected_slots:
            raise HwpxError(
                HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
                "exam item image pointers differ from its editorial visual slots",
            )
        images = tuple(
            (
                _as_item_image(image),
                _read_regular(
                    _workspace_path(workspace, image.file_name),
                    max_bytes=MAX_IMAGE_BYTES,
                    expected_sha256=image.sha256,
                ),
            )
            for image in item.images
        )
        inject_content_team_images(output, images)
        item_outputs.append(output)
        total_equations += int(report["equation_count"])
        total_tables += int(report["table_count"])
        total_visuals += int(report["visual_count"])
        item_report: dict[str, Any] = {
            "position": item.position,
            "placement_id": item.placement_id,
            "item_id": item.item_id,
            "item_revision_id": item.item_revision_id,
            "item_manifest_sha256": item.item_manifest_sha256,
            "source_artifact_revision_id": item.source_artifact_revision_id,
            "source_json_sha256": item.source_json_sha256,
            "source_markdown_sha256": item.source_markdown_sha256,
            "source_item_number": draft.item_number,
            "rendered_item_number": int(report["rendered_item_number"]),
            "equation_count": int(report["equation_count"]),
            "table_count": int(report["table_count"]),
            "visual_count": int(report["visual_count"]),
        }
        if isinstance(item, ContentTeamExamItemSourceV2):
            item_report.update(
                display_number=item.display_number,
                points_milli=item.points_milli,
                source_score_display=draft.score_display,
                rendered_score_display=str(report["rendered_score_display"]),
            )
        item_reports.append(item_report)

    output = _workspace_path(workspace, "output/content-team-exam.hwpx", must_exist=False)
    merge_report = _merge_item_packages(tuple(item_outputs), output)
    item_set_sha256 = _item_set_sha256(request)
    render_plan_sha256 = (
        _render_plan_sha256(request)
        if isinstance(request, (ContentTeamExamRenderRequestV2, ContentTeamExamRenderRequestV3))
        else None
    )
    renderer_version = (
        EXAM_RENDERER_VERSION_V3
        if isinstance(request, ContentTeamExamRenderRequestV3)
        else (
            EXAM_RENDERER_VERSION_V2
            if isinstance(request, ContentTeamExamRenderRequestV2)
            else EXAM_RENDERER_VERSION
        )
    )
    report = {
        "status": "PASS",
        "renderer_profile": request.renderer_profile,
        "renderer_version": renderer_version,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": item_set_sha256,
        "item_count": len(request.items),
        "equation_count": total_equations,
        "table_count": total_tables,
        "visual_count": total_visuals,
        "items": item_reports,
        "package": merge_report,
    }
    if render_plan_sha256 is not None:
        report["render_plan_sha256"] = render_plan_sha256
    output_dir = output.parent
    write_private_json(output_dir / "content-team-exam-validation.json", report)
    package_manifest: dict[str, Any] = {
        "manifest_version": (
            "content-team-exam-hwpx/3.0"
            if isinstance(request, ContentTeamExamRenderRequestV3)
            else (
                "content-team-exam-hwpx/2.0"
                if isinstance(request, ContentTeamExamRenderRequestV2)
                else "content-team-exam-hwpx/1.0"
            )
        ),
        "renderer_profile": request.renderer_profile,
        "renderer_version": renderer_version,
        "assembly": request.assembly.model_dump(mode="json"),
        "handoff": request.handoff.model_dump(mode="json"),
        "item_set_sha256": item_set_sha256,
        "file_name": output.name,
        "media_type": "application/hwp+zip",
        "package_sha256": sha256_file(output),
        "renderer_report": report,
    }
    if render_plan_sha256 is not None:
        package_manifest["render_plan_sha256"] = render_plan_sha256
    write_private_json(output_dir / "package-manifest.json", package_manifest)
    prepare_private_handoff_file(output)
    result_values: dict[str, Any] = {
        "build_id": request.build_id,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": item_set_sha256,
        "handoff_archive_sha256": request.handoff.archive_sha256,
        "status": "SUCCEEDED",
        "output_file": "output/content-team-exam.hwpx",
        "output_sha256": sha256_file(output),
        "package_manifest_file": "output/package-manifest.json",
        "renderer_report_file": "output/content-team-exam-validation.json",
        "item_count": len(request.items),
        "section_count": int(merge_report["section_count"]),
        "equation_count": total_equations,
        "table_count": total_tables,
        "visual_count": total_visuals,
        "warnings": (),
        "errors": (),
        "started_at": started,
        "completed_at": datetime.now(UTC),
    }
    result: ContentTeamExamBuildResultContract
    if isinstance(request, ContentTeamExamRenderRequestV3):
        assert render_plan_sha256 is not None
        result = ContentTeamExamBuildResultV3(
            **result_values,
            render_plan_sha256=render_plan_sha256,
        )
        result_contract = "content-team-exam-build-result-v3"
    elif isinstance(request, ContentTeamExamRenderRequestV2):
        assert render_plan_sha256 is not None
        result = ContentTeamExamBuildResultV2(
            **result_values,
            render_plan_sha256=render_plan_sha256,
        )
        result_contract = "content-team-exam-build-result-v2"
    else:
        result = ContentTeamExamBuildResult(**result_values)
        result_contract = "content-team-exam-build-result"
    validate_contract(result_contract, result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_success_handoff(
        workspace,
        result_path,
        output_file_names=(
            "content-team-exam.hwpx",
            "content-team-exam-validation.json",
            "package-manifest.json",
        ),
    )
    return result


def failed_content_team_exam_result(
    request_path: Path, result_path: Path, started: datetime, error: Exception
) -> ContentTeamExamBuildResultContract | None:
    try:
        raw: object = json.loads(_read_request(request_path).decode("utf-8"))
        if not isinstance(raw, dict):
            return None
        request = _load_exam_request(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        return None
    code = (
        error.code.value if isinstance(error, HwpxError) else "HWPX_CONTENT_TEAM_EXAM_RENDER_FAILED"
    )
    result_values: dict[str, Any] = {
        "build_id": request.build_id,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": _item_set_sha256(request),
        "handoff_archive_sha256": request.handoff.archive_sha256,
        "status": "FAILED",
        "output_file": None,
        "output_sha256": None,
        "package_manifest_file": None,
        "renderer_report_file": None,
        "item_count": 0,
        "section_count": 0,
        "equation_count": 0,
        "table_count": 0,
        "visual_count": 0,
        "warnings": (),
        "errors": (code,),
        "started_at": started,
        "completed_at": datetime.now(UTC),
    }
    result: ContentTeamExamBuildResultContract
    if isinstance(request, ContentTeamExamRenderRequestV3):
        result = ContentTeamExamBuildResultV3(
            **result_values,
            render_plan_sha256=_render_plan_sha256(request),
        )
        result_contract = "content-team-exam-build-result-v3"
    elif isinstance(request, ContentTeamExamRenderRequestV2):
        result = ContentTeamExamBuildResultV2(
            **result_values,
            render_plan_sha256=_render_plan_sha256(request),
        )
        result_contract = "content-team-exam-build-result-v2"
    else:
        result = ContentTeamExamBuildResult(**result_values)
        result_contract = "content-team-exam-build-result"
    validate_contract(result_contract, result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_failure_result(request_path.parent.resolve(strict=True), result_path)
    return result
