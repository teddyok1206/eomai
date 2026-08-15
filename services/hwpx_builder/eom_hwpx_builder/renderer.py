"""Reference-template renderer with deterministic package reconstruction."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import (
    BuildResultStatus,
    HwpxBuildResult,
    HwpxItemDocument,
    validate_contract,
)
from PIL import Image
from pydantic import ValidationError

from eom_hwpx_builder import RENDERER_VERSION
from eom_hwpx_builder.archive import extract_package, read_package
from eom_hwpx_builder.bindings import replace_text_binding
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import (
    BindingKind,
    BindingManifest,
    RenderRequest,
)
from eom_hwpx_builder.semantic import compare_semantic
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file, write_json
from eom_hwpx_builder.validation import validate_structure
from eom_hwpx_builder.xmlsafe import local_name, parse_xml, serialize_xml

FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
EQUATION_PATTERN = re.compile(r"^[A-Za-z0-9+\-*/=() ._^]{1,200}$")


def _resolve_workspace(workspace: Path, relative: str) -> Path:
    root = workspace.resolve(strict=True)
    target = (workspace / relative).resolve(strict=False)
    if not target.is_relative_to(root):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "workspace path escaped root")
    return target


def _field(document: dict[str, Any], field_name: str) -> str:
    value: Any = document
    for component in field_name.split("."):
        value = value[int(component)] if component.isdigit() else value[component]
    if not isinstance(value, str) or not value:
        raise HwpxError(HwpxErrorCode.HWPX_TEXT_REPLACEMENT_FAILED, "replacement is empty")
    return value


def _validate_png(path: Path, document: HwpxItemDocument) -> bytes:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_REPLACEMENT_FAILED, "PNG signature invalid")
    if sha256_bytes(data) != document.item.image.sha256:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_REPLACEMENT_FAILED, "PNG checksum mismatch")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            dimensions = image.size
            mode = image.mode
            file_format = image.format
    except Exception as exc:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_REPLACEMENT_FAILED, "PNG decode failed") from exc
    if (
        dimensions
        != (
            document.item.image.expected_width_px,
            document.item.image.expected_height_px,
        )
        or mode not in {"RGB", "RGBA"}
        or file_format != "PNG"
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_REPLACEMENT_FAILED, "PNG dimensions or color mode mismatch"
        )
    return data


def _update_equation(root: Any, binding: Any, source: str) -> None:
    if not EQUATION_PATTERN.fullmatch(source):
        raise HwpxError(
            HwpxErrorCode.HWPX_EQUATION_REPLACEMENT_FAILED, "equation source is outside POC grammar"
        )
    try:
        element = list(root.iter())[int(binding.locator["element_index"])]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_EQUATION_REPLACEMENT_FAILED,
            "equation locator no longer resolves",
        ) from exc
    if binding.locator.get("value_location") == "text":
        if binding.expected_original_value not in (element.text or ""):
            raise HwpxError(HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "equation marker changed")
        element.text = (element.text or "").replace(binding.expected_original_value, source, 1)
    else:
        attribute_local = binding.locator.get("attribute_local_name")
        attribute_name = next(
            (name for name in element.attrib if local_name(name) == attribute_local), None
        )
        if (
            attribute_name is None
            or binding.expected_original_value not in element.attrib[attribute_name]
        ):
            raise HwpxError(HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "equation marker changed")
        element.attrib[attribute_name] = element.attrib[attribute_name].replace(
            binding.expected_original_value, source, 1
        )
    anchor_locator = binding.constraints.get("anchor_text_locator")
    if anchor_locator:
        anchor_binding = binding.model_copy(
            update={
                "binding_kind": BindingKind.TEXT_MARKER,
                "locator": anchor_locator,
                "expected_original_value": "{{EOM_EQUATION_ANCHOR}}",
                "constraints": {
                    "prefix": anchor_locator.get("prefix", ""),
                    "suffix": anchor_locator.get("suffix", ""),
                },
            }
        )
        replace_text_binding(root, anchor_binding, "")


def _update_metadata(root: Any, document_title: str, build_id: str) -> None:
    for element in root.iter():
        name = local_name(element.tag).casefold()
        if name == "title" and element.text:
            element.text = document_title
        elif name in {"modified", "modifieddate", "date-modified"} and element.text:
            element.text = "1980-01-01T00:00:00Z"
        elif name == "meta" and any(
            local_name(key).casefold() == "name" and value == "eom-build-id"
            for key, value in element.attrib.items()
        ):
            for key in element.attrib:
                if local_name(key).casefold() in {"content", "value"}:
                    element.attrib[key] = build_id


def reconstruct_package(reference: Any, extracted: Path, output: Path) -> None:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=False) as archive:
            for entry in reference.entries:
                info = zipfile.ZipInfo(entry.info.filename, FIXED_ZIP_TIMESTAMP)
                info.compress_type = entry.info.compress_type
                info.comment = entry.info.comment
                info.extra = entry.info.extra
                info.internal_attr = entry.info.internal_attr
                info.external_attr = entry.info.external_attr
                info.create_system = entry.info.create_system
                data = (
                    b"" if entry.info.is_dir() else (extracted / entry.info.filename).read_bytes()
                )
                archive.writestr(info, data)
        temporary.replace(output)
    except (OSError, zipfile.BadZipFile) as exc:
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "package write failed") from exc


def _package_manifest(output: Path, semantic_hash: str, warnings: list[str]) -> dict[str, Any]:
    package = read_package(output)
    return {
        "manifest_version": "1.0",
        "file_name": output.name,
        "media_type": "application/hwp+zip",
        "package_sha256": package.package_sha256,
        "semantic_sha256": semantic_hash,
        "entries": [record.model_dump(mode="json") for record in package.records()],
        "warnings": warnings,
    }


def render_workspace(request_path: Path, result_path: Path) -> HwpxBuildResult:
    started = datetime.now(UTC)
    request_raw: dict[str, Any] = json.loads(request_path.read_text(encoding="utf-8"))
    request = RenderRequest.model_validate(request_raw)
    workspace = request_path.parent.resolve(strict=True)
    if result_path.resolve(strict=False).parent != workspace:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "result path must be in workspace")
    template = _resolve_workspace(workspace, request.template_file)
    bindings_path = _resolve_workspace(workspace, request.bindings_file)
    document_path = _resolve_workspace(workspace, request.document_file)
    image_path = _resolve_workspace(workspace, request.image_file)
    output_dir = _resolve_workspace(workspace, request.output_directory)
    if output_dir.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "output directory must be fresh")
    extracted = workspace / "extracted"
    if extracted.exists():
        raise HwpxError(
            HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "workspace extraction must be fresh"
        )

    document_raw: dict[str, Any] = json.loads(document_path.read_text(encoding="utf-8"))
    validate_contract("item-document", document_raw)
    document = HwpxItemDocument.model_validate(document_raw)
    input_sha256 = sha256_bytes(canonical_json_bytes(document.model_dump(mode="json")))
    bindings = BindingManifest.model_validate_json(bindings_path.read_text(encoding="utf-8"))
    if (
        bindings.template_id != request.template_id
        or bindings.template_revision_id != request.template_revision_id
        or bindings.template_sha256 != request.template_sha256
        or sha256_file(template) != request.template_sha256
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "template revision binding mismatch"
        )
    reference_image = next(
        binding for binding in bindings.bindings if binding.binding_kind == BindingKind.IMAGE_BINARY
    )
    reference_report = validate_structure(
        template,
        bindings=bindings,
        expected_image_sha256=reference_image.expected_original_value,
    )
    if reference_report.status != "PASS":
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "reference validation failed")
    package = read_package(template)
    extract_package(package, extracted)
    image_bytes = _validate_png(image_path, document)
    parsed_parts: dict[str, Any] = {}
    split_fields: list[str] = []
    for binding in bindings.bindings:
        if binding.binding_kind in {BindingKind.TEXT_MARKER, BindingKind.TABLE_CELL_MARKER}:
            if binding.part_name not in parsed_parts:
                part_path = extracted / binding.part_name
                parsed_parts[binding.part_name] = parse_xml(
                    part_path.read_bytes(), binding.part_name
                )
            replacement = _field(document_raw, binding.field_name)
            if replace_text_binding(parsed_parts[binding.part_name].root, binding, replacement):
                split_fields.append(binding.field_name)
        elif binding.binding_kind == BindingKind.IMAGE_BINARY:
            if binding.binary_part is None:
                raise HwpxError(HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "image part missing")
            (extracted / binding.binary_part).write_bytes(image_bytes)
        elif binding.binding_kind in {BindingKind.EQUATION_SCRIPT, BindingKind.EQUATION_ANCHOR}:
            if binding.part_name not in parsed_parts:
                part_path = extracted / binding.part_name
                parsed_parts[binding.part_name] = parse_xml(
                    part_path.read_bytes(), binding.part_name
                )
            _update_equation(
                parsed_parts[binding.part_name].root, binding, document.item.equation.source
            )
    if "Contents/content.hpf" not in parsed_parts:
        content_path = extracted / "Contents/content.hpf"
        parsed_parts["Contents/content.hpf"] = parse_xml(
            content_path.read_bytes(), "Contents/content.hpf"
        )
    _update_metadata(
        parsed_parts["Contents/content.hpf"].root, document.document_title, request.build_id
    )
    for part_name, parsed in parsed_parts.items():
        (extracted / part_name).write_bytes(serialize_xml(parsed))
    output_dir.mkdir(mode=0o700)
    output = output_dir / "placeholder_item_combined.hwpx"
    reconstruct_package(package, extracted, output)
    structural = validate_structure(
        output,
        bindings=bindings,
        expected_image_sha256=document.item.image.sha256,
        expected_equation_source=document.item.equation.source,
        require_markers_removed=True,
    )
    semantic = compare_semantic(document_raw, output, bindings)
    write_json(output_dir / "structural-validation.json", structural.model_dump(mode="json"))
    write_json(output_dir / "semantic-validation.json", semantic.model_dump(mode="json"))
    warnings = list(bindings.warnings)
    if any(entry.info.filename.startswith("Preview/") for entry in package.entries):
        warnings.extend(["PREVIEW_IMAGE_STALE", "PREVIEW_TEXT_STALE"])
    warnings.extend(f"SPLIT_MARKER_NORMALIZED:{field}" for field in split_fields)
    warnings = sorted(set(warnings))
    if structural.status != "PASS":
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED, "structural validation failed"
        )
    if semantic.status != "PASS":
        raise HwpxError(HwpxErrorCode.HWPX_SEMANTIC_MISMATCH, "semantic validation failed")
    write_json(
        output_dir / "package-manifest.json",
        _package_manifest(output, semantic.semantic_hash, warnings),
    )
    result = HwpxBuildResult(
        build_id=request.build_id,
        template_id=request.template_id,
        template_revision_id=request.template_revision_id,
        input_sha256=input_sha256,
        renderer_version=RENDERER_VERSION,
        status=BuildResultStatus.PENDING_MANUAL_HANCOM_VALIDATION,
        output_file="output/placeholder_item_combined.hwpx",
        output_sha256=sha256_file(output),
        package_manifest_file="output/package-manifest.json",
        validation_report_file="output/structural-validation.json",
        semantic_report_file="output/semantic-validation.json",
        warnings=tuple(warnings),
        errors=(),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("build-result", result.model_dump(mode="json"))
    write_json(result_path, result.model_dump(mode="json"))
    return result


def failed_result(
    request_path: Path, result_path: Path, started: datetime, error: Exception
) -> HwpxBuildResult | None:
    try:
        request = RenderRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None
    code = (
        error.code.value
        if isinstance(error, HwpxError)
        else HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED.value
    )
    try:
        document_raw = json.loads(
            _resolve_workspace(request_path.parent, request.document_file).read_text(
                encoding="utf-8"
            )
        )
        input_hash = sha256_bytes(canonical_json_bytes(document_raw))
    except Exception:
        input_hash = sha256_bytes(b"invalid-input")
    result = HwpxBuildResult(
        build_id=request.build_id,
        template_id=request.template_id,
        template_revision_id=request.template_revision_id,
        input_sha256=input_hash,
        renderer_version=RENDERER_VERSION,
        status=BuildResultStatus.FAILED,
        output_file=None,
        output_sha256=None,
        package_manifest_file=None,
        validation_report_file=None,
        semantic_report_file=None,
        warnings=(),
        errors=(code,),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("build-result", result.model_dump(mode="json"))
    write_json(result_path, result.model_dump(mode="json"))
    return result
