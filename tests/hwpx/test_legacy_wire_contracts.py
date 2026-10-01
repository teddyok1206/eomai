from __future__ import annotations

import hashlib
import json

import pytest
from eom_hwpx_contracts import (
    HwpxRenderRequest,
    HwpxTemplateBindingManifest,
    KordocBridgeReport,
    parse_contract_json,
    validate_contract,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_render_request_and_binding_manifest_are_shared_closed_contracts() -> None:
    request = {
        "request_version": "1.0",
        "build_id": "hwpxbuild_" + "1" * 32,
        "template_id": "hwpxtpl_" + "2" * 32,
        "template_revision_id": "hwpxrev_" + "3" * 32,
        "template_sha256": "sha256:" + "4" * 64,
        "template_file": "template.hwpx",
        "bindings_file": "template-bindings.json",
        "document_file": "input/document.json",
        "image_file": "input/eom-placeholder-image-output.png",
        "output_directory": "output",
    }
    validate_contract("render-request", request)
    assert HwpxRenderRequest.model_validate(request).build_id == request["build_id"]

    manifest = {
        "manifest_version": "1.0",
        "template_id": request["template_id"],
        "template_revision_id": request["template_revision_id"],
        "template_sha256": request["template_sha256"],
        "bindings": [],
        "warnings": [],
    }
    manifest["binding_manifest_sha256"] = _sha(manifest)
    validate_contract("template-binding-manifest", manifest)
    HwpxTemplateBindingManifest.model_validate(manifest)

    with pytest.raises(ValidationError, match="SHA-256 does not match"):
        HwpxTemplateBindingManifest.model_validate(
            manifest | {"binding_manifest_sha256": "sha256:" + "f" * 64}
        )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_contract_json("render-request", '{"request_version":"1.0","request_version":"1.0"}')


def test_kordoc_bridge_report_is_schema_first_and_semantically_coherent() -> None:
    value = {
        "schema_version": "1.0",
        "kordoc_version": "4.9.0",
        "source_sha256": "sha256:" + "1" * 64,
        "output_sha256": "sha256:" + "2" * 64,
        "validation_ok": True,
        "validation_issue_count": 0,
        "parse_success": True,
        "parsed_markdown_sha256": "sha256:" + "3" * 64,
        "parse_warning_count": 0,
        "parsed_table_count": 1,
    }
    validate_contract("kordoc-bridge-report", value)
    assert KordocBridgeReport.model_validate(value).parse_success is True

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("kordoc-bridge-report", value | {"kordoc_version": "latest"})
    with pytest.raises(ValidationError, match="status and Markdown hash"):
        KordocBridgeReport.model_validate(value | {"parsed_markdown_sha256": None})
