#!/usr/bin/env python3
"""Generate immutable contracts for post-registration Item approval."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SHA256 = r"^sha256:[0-9a-f]{64}$"


def _write_pair(
    canonical_root: str,
    package_root: str,
    file_name: str,
    value: dict[str, object],
) -> None:
    Draft202012Validator.check_schema(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for root in (ROOT / canonical_root, ROOT / package_root):
        path = root / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _approval_policy() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["mode", "initial_revision_state", "required_review_artifact"],
        "properties": {
            "mode": {"const": "POST_REGISTRATION_HUMAN_REVIEW"},
            "initial_revision_state": {"const": "IN_REVIEW"},
            "required_review_artifact": {"const": "VALIDATED_HWPX"},
        },
    }


def _item_revision_manifest_v2() -> dict[str, object]:
    source = json.loads(
        (ROOT / "schemas/item-registry/item-revision-manifest-v1.schema.json").read_text()
    )
    value = cast(dict[str, object], deepcopy(source))
    value["$id"] = "eom://schemas/item-registry/item-revision-manifest-v2"
    value["title"] = "Item Revision Manifest V2"
    required = value["required"]
    properties = value["properties"]
    assert isinstance(required, list) and isinstance(properties, dict)
    required.extend(["revision_state", "approval_policy"])
    properties["schema_version"] = {"const": "2.0"}
    properties["revision_state"] = {"const": "IN_REVIEW"}
    properties["approval_policy"] = _approval_policy()
    return value


def _approval_receipt_v1() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/item-registry/item-revision-approval-receipt/1.0",
        "title": "Item Revision Approval Receipt V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "item_id",
            "item_revision_id",
            "item_revision_number",
            "prior_revision_state",
            "approved_revision_state",
            "manifest_artifact_id",
            "manifest_artifact_revision_id",
            "manifest_sha256",
            "workflow_id",
            "registration_step_run_id",
            "hwpx_build_id",
            "hwpx_output_artifact_id",
            "hwpx_output_artifact_revision_id",
            "hwpx_output_sha256",
            "approved_by",
            "approved_at",
            "reason_sha256",
            "idempotency_key",
            "approval_submission_sha256",
            "receipt_sha256",
        ],
        "properties": {
            "schema_version": {"const": "item-revision-approval-receipt/1.0"},
            "item_id": {"type": "string", "pattern": r"^item_[0-9a-f]{32}$"},
            "item_revision_id": {
                "type": "string",
                "pattern": r"^itemrev_[0-9a-f]{32}$",
            },
            "item_revision_number": {"type": "integer", "minimum": 1},
            "prior_revision_state": {"const": "IN_REVIEW"},
            "approved_revision_state": {"const": "APPROVED"},
            "manifest_artifact_id": {
                "type": "string",
                "pattern": r"^artifact_[0-9a-f]{32}$",
            },
            "manifest_artifact_revision_id": {
                "type": "string",
                "pattern": r"^rev_[0-9a-f]{32}$",
            },
            "manifest_sha256": {"type": "string", "pattern": SHA256},
            "workflow_id": {"type": "string", "pattern": r"^workflow_[0-9a-f]{32}$"},
            "registration_step_run_id": {
                "type": "string",
                "pattern": r"^steprun_[0-9a-f]{32}$",
            },
            "hwpx_build_id": {"type": "string", "pattern": r"^hwpxbuild_[0-9a-f]{32}$"},
            "hwpx_output_artifact_id": {
                "type": "string",
                "pattern": r"^artifact_[0-9a-f]{32}$",
            },
            "hwpx_output_artifact_revision_id": {
                "type": "string",
                "pattern": r"^rev_[0-9a-f]{32}$",
            },
            "hwpx_output_sha256": {"type": "string", "pattern": SHA256},
            "approved_by": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
            },
            "approved_at": {"type": "string", "format": "date-time"},
            "reason_sha256": {"type": "string", "pattern": SHA256},
            "idempotency_key": {"type": "string", "minLength": 16, "maxLength": 200},
            "approval_submission_sha256": {"type": "string", "pattern": SHA256},
            "receipt_sha256": {"type": "string", "pattern": SHA256},
        },
    }


def _approval_request_v1() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/api/v1/item-revision-approval-request/1.0",
        "title": "Item Revision Approval Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "hwpx_build_id", "reason"],
        "properties": {
            "schema_version": {"const": "item-revision-approval-request/1.0"},
            "hwpx_build_id": {"type": "string", "pattern": r"^hwpxbuild_[0-9a-f]{32}$"},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    }


def _approval_view_v1() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/api/v1/item-approval-view/1.0",
        "title": "Item Approval View V1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "status", "human_review_required"],
        "properties": {
            "schema_version": {"const": "item-approval-view/1.0"},
            "status": {"enum": ["PENDING", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"]},
            "human_review_required": {"type": "boolean"},
            "approved_at": {"type": ["string", "null"], "format": "date-time"},
            "approved_by": {
                "type": ["string", "null"],
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
            },
            "approval_receipt_sha256": {
                "type": ["string", "null"],
                "pattern": SHA256,
            },
            "hwpx_build_id": {
                "type": ["string", "null"],
                "pattern": r"^hwpxbuild_[0-9a-f]{32}$",
            },
        },
        "allOf": _approval_projection_semantics(),
    }


def _approval_projection_semantics() -> list[dict[str, object]]:
    evidence_fields = [
        "approved_at",
        "approved_by",
        "approval_receipt_sha256",
        "hwpx_build_id",
    ]
    return [
        {
            "if": {
                "properties": {
                    "status": {"enum": ["APPROVED", "SUPERSEDED", "RETIRED"]},
                    "human_review_required": {"const": True},
                },
                "required": ["status", "human_review_required"],
            },
            "then": {
                "required": evidence_fields,
                "properties": {
                    "approved_at": {"type": "string", "format": "date-time"},
                    "approved_by": {
                        "type": "string",
                        "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
                    },
                    "approval_receipt_sha256": {"type": "string", "pattern": SHA256},
                    "hwpx_build_id": {
                        "type": "string",
                        "pattern": r"^hwpxbuild_[0-9a-f]{32}$",
                    },
                },
            },
        },
        {
            "if": {
                "properties": {"status": {"const": "PENDING"}},
                "required": ["status"],
            },
            "then": {
                "properties": {field: {"const": None} for field in evidence_fields},
            },
        },
    ]


def _item_preview_v4() -> dict[str, object]:
    value = cast(
        dict[str, object],
        json.loads(
            (ROOT / "schemas/web-gui/item-preview-v3.schema.json").read_text(encoding="utf-8")
        ),
    )
    value["$id"] = "eom://schemas/web-gui/item-preview/4.0"
    properties = value["properties"]
    required = value["required"]
    assert isinstance(properties, dict) and isinstance(required, list)
    properties["schema_version"] = {"const": "4.0"}
    properties["revision_state"] = {"enum": ["IN_REVIEW", "APPROVED"]}
    properties["approval"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "human_review_required",
            "approved_at",
            "approved_by",
            "approval_receipt_sha256",
            "hwpx_build_id",
        ],
        "properties": {
            "status": {"enum": ["PENDING", "APPROVED"]},
            "human_review_required": {"type": "boolean"},
            "approved_at": {"type": ["string", "null"], "format": "date-time"},
            "approved_by": {"type": ["string", "null"]},
            "approval_receipt_sha256": {
                "type": ["string", "null"],
                "pattern": SHA256,
            },
            "hwpx_build_id": {
                "type": ["string", "null"],
                "pattern": r"^hwpxbuild_[0-9a-f]{32}$",
            },
        },
        "allOf": _approval_projection_semantics(),
    }
    required.append("approval")
    all_of = value.setdefault("allOf", [])
    assert isinstance(all_of, list)
    all_of.extend(
        [
            {
                "if": {
                    "properties": {"revision_state": {"const": "IN_REVIEW"}},
                    "required": ["revision_state"],
                },
                "then": {
                    "properties": {
                        "approval": {
                            "properties": {
                                "status": {"const": "PENDING"},
                                "human_review_required": {"const": True},
                            }
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {"revision_state": {"const": "APPROVED"}},
                    "required": ["revision_state"],
                },
                "then": {
                    "properties": {"approval": {"properties": {"status": {"const": "APPROVED"}}}}
                },
            },
        ]
    )
    return value


def _catalog_request_v18() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog-application/catalog-application-request-v18",
        "title": "EOM Catalog Item Revision Approval Request V18",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "operation",
            "item_revision_id",
            "expected_revision_version",
            "hwpx_build_id",
            "hwpx_output_artifact_id",
            "hwpx_output_artifact_revision_id",
            "hwpx_output_sha256",
            "reason",
            "approved_by",
            "idempotency_key",
            "submission_sha256",
        ],
        "properties": {
            "operation": {"const": "APPROVE_ITEM_REVISION"},
            "item_revision_id": {
                "type": "string",
                "pattern": r"^itemrev_[0-9a-f]{32}$",
            },
            "expected_revision_version": {"type": "integer", "minimum": 1},
            "hwpx_build_id": {"type": "string", "pattern": r"^hwpxbuild_[0-9a-f]{32}$"},
            "hwpx_output_artifact_id": {
                "type": "string",
                "pattern": r"^artifact_[0-9a-f]{32}$",
            },
            "hwpx_output_artifact_revision_id": {
                "type": "string",
                "pattern": r"^rev_[0-9a-f]{32}$",
            },
            "hwpx_output_sha256": {"type": "string", "pattern": SHA256},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
            "approved_by": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
            },
            "idempotency_key": {"type": "string", "minLength": 16, "maxLength": 200},
            "submission_sha256": {"type": "string", "pattern": SHA256},
        },
    }


def _catalog_response_v17() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog-application/catalog-application-response-v17",
        "title": "EOM Catalog Item Revision Approval Response V17",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "operation", "item_approval"],
                "properties": {
                    "status": {"const": "OK"},
                    "operation": {"const": "APPROVE_ITEM_REVISION"},
                    "item_approval": {
                        "$ref": "eom://schemas/item-registry/item-revision-approval-receipt/1.0"
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "operation", "error_code"],
                "properties": {
                    "status": {"const": "ERROR"},
                    "operation": {"const": "APPROVE_ITEM_REVISION"},
                    "error_code": {
                        "type": "string",
                        "pattern": r"^[A-Z][A-Z0-9_]{2,127}$",
                    },
                },
            },
        ],
    }


def _hwpx_review_eligibility_v1() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/item-registry/item-revision-hwpx-eligibility/1.0",
        "title": "Item Revision HWPX Review Eligibility V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "eligible",
            "item_id",
            "item_revision_id",
            "item_revision_number",
            "revision_state",
            "workflow_id",
            "workflow_definition_version",
            "manifest_artifact_id",
            "manifest_artifact_revision_id",
            "manifest_sha256",
            "eligibility_sha256",
        ],
        "properties": {
            "schema_version": {"const": "item-revision-hwpx-eligibility/1.0"},
            "eligible": {"const": True},
            "item_id": {"type": "string", "pattern": r"^item_[0-9a-f]{32}$"},
            "item_revision_id": {
                "type": "string",
                "pattern": r"^itemrev_[0-9a-f]{32}$",
            },
            "item_revision_number": {"type": "integer", "minimum": 1},
            "revision_state": {"const": "IN_REVIEW"},
            "workflow_id": {
                "type": "string",
                "pattern": r"^workflow_[0-9a-f]{32}$",
            },
            "workflow_definition_version": {"const": "1.16.0"},
            "manifest_artifact_id": {
                "type": "string",
                "pattern": r"^artifact_[0-9a-f]{32}$",
            },
            "manifest_artifact_revision_id": {
                "type": "string",
                "pattern": r"^rev_[0-9a-f]{32}$",
            },
            "manifest_sha256": {"type": "string", "pattern": SHA256},
            "eligibility_sha256": {"type": "string", "pattern": SHA256},
        },
    }


def _catalog_request_v19() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog-application/catalog-application-request-v19",
        "title": "EOM Catalog Item Revision HWPX Eligibility Request V19",
        "type": "object",
        "additionalProperties": False,
        "required": ["operation", "item_revision_id"],
        "properties": {
            "operation": {"const": "INSPECT_ITEM_REVISION_HWPX_ELIGIBILITY"},
            "item_revision_id": {
                "type": "string",
                "pattern": r"^itemrev_[0-9a-f]{32}$",
            },
        },
    }


def _catalog_response_v18() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog-application/catalog-application-response-v18",
        "title": "EOM Catalog Item Revision HWPX Eligibility Response V18",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "operation", "hwpx_review_eligibility"],
                "properties": {
                    "status": {"const": "OK"},
                    "operation": {"const": "INSPECT_ITEM_REVISION_HWPX_ELIGIBILITY"},
                    "hwpx_review_eligibility": {
                        "$ref": ("eom://schemas/item-registry/item-revision-hwpx-eligibility/1.0")
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "operation", "error_code"],
                "properties": {
                    "status": {"const": "ERROR"},
                    "operation": {"const": "INSPECT_ITEM_REVISION_HWPX_ELIGIBILITY"},
                    "error_code": {
                        "type": "string",
                        "pattern": r"^[A-Z][A-Z0-9_]{2,127}$",
                    },
                },
            },
        ],
    }


def _workflow_start_v6() -> dict[str, object]:
    source = json.loads((ROOT / "schemas/api/v1/workflow-start-v5.schema.json").read_text())
    value = cast(dict[str, object], deepcopy(source))
    value["$id"] = "eom://schemas/api/v1/workflow-start/6.0"
    value["title"] = "Workflow Start Request V6"
    value["oneOf"] = [
        {"$ref": "eom://schemas/api/v1/workflow-start/5.0"},
        {"$ref": "#/$defs/post_registration_review_start"},
        {"$ref": "#/$defs/post_registration_variation_review_start"},
    ]
    definitions = value["$defs"]
    assert isinstance(definitions, dict)
    general = deepcopy(definitions["content_team_natural_presentation_start"])
    variation = deepcopy(definitions["past_exam_natural_presentation_start"])
    for branch in (general, variation):
        properties = branch["properties"]
        assert isinstance(properties, dict)
        properties["definition_version"] = {"const": "1.16.0"}
        properties["registry_mode"] = {"const": "CREATE_ITEM", "default": "CREATE_ITEM"}
        properties["item_id"] = {"type": "null", "default": None}
        properties["base_revision_id"] = {"type": "null", "default": None}
    definitions["post_registration_review_start"] = general
    definitions["post_registration_variation_review_start"] = variation
    return value


def _resolved_plan(source_version: int, target_version: int) -> dict[str, object]:
    source = json.loads(
        (
            ROOT
            / (
                "schemas/workflow/control-plane/"
                f"resolved-execution-plan-v{source_version}.schema.json"
            )
        ).read_text()
    )
    value = cast(dict[str, object], deepcopy(source))
    value["$id"] = f"eom://schemas/workflow/resolved-execution-plan/{target_version}.0"
    value["title"] = f"Resolved Execution Plan V{target_version}"
    properties = value["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": f"resolved-execution-plan/{target_version}.0"}
    properties["workflow_definition_version"] = {"const": "1.16.0"}
    properties["resolver_version"] = {"const": f"{target_version}.0.0"}
    return value


def main() -> None:
    _write_pair(
        "schemas/item-registry",
        "packages/catalog_contracts/eom_catalog_contracts/resources/item-registry",
        "item-revision-manifest-v2.schema.json",
        _item_revision_manifest_v2(),
    )
    _write_pair(
        "schemas/item-registry",
        "packages/catalog_contracts/eom_catalog_contracts/resources/item-registry",
        "item-revision-approval-receipt-v1.schema.json",
        _approval_receipt_v1(),
    )
    _write_pair(
        "schemas/catalog-application",
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        "catalog-application-request-v18.schema.json",
        _catalog_request_v18(),
    )
    _write_pair(
        "schemas/catalog-application",
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        "catalog-application-response-v17.schema.json",
        _catalog_response_v17(),
    )
    _write_pair(
        "schemas/item-registry",
        "packages/catalog_contracts/eom_catalog_contracts/resources/item-registry",
        "item-revision-hwpx-eligibility-v1.schema.json",
        _hwpx_review_eligibility_v1(),
    )
    _write_pair(
        "schemas/catalog-application",
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        "catalog-application-request-v19.schema.json",
        _catalog_request_v19(),
    )
    _write_pair(
        "schemas/catalog-application",
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        "catalog-application-response-v18.schema.json",
        _catalog_response_v18(),
    )
    _write_pair(
        "schemas/api/v1",
        "packages/api_contracts/eom_api_contracts/schemas",
        "item-revision-approval-request-v1.schema.json",
        _approval_request_v1(),
    )
    _write_pair(
        "schemas/api/v1",
        "packages/api_contracts/eom_api_contracts/schemas",
        "item-approval-view-v1.schema.json",
        _approval_view_v1(),
    )
    web_preview = _item_preview_v4()
    Draft202012Validator.check_schema(web_preview)
    (ROOT / "schemas/web-gui/item-preview-v4.schema.json").write_bytes(
        (json.dumps(web_preview, ensure_ascii=False, indent=2) + "\n").encode()
    )
    _write_pair(
        "schemas/api/v1",
        "packages/api_contracts/eom_api_contracts/schemas",
        "workflow-start-v6.schema.json",
        _workflow_start_v6(),
    )
    _write_pair(
        "schemas/workflow/control-plane",
        "packages/workflow/eom_workflow/resources/control-plane",
        "resolved-execution-plan-v19.schema.json",
        _resolved_plan(17, 19),
    )
    _write_pair(
        "schemas/workflow/control-plane",
        "packages/workflow/eom_workflow/resources/control-plane",
        "resolved-execution-plan-v20.schema.json",
        _resolved_plan(18, 20),
    )


if __name__ == "__main__":
    main()
