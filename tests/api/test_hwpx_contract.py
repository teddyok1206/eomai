from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from eom_api.app import create_app
from eom_api.services.hwpx_projection import project_hwpx_build
from eom_api_contracts.hwpx import CreateHwpxBuildRequest, HwpxDeliveryProfile
from eom_operator_identity import ROLE_PERMISSIONS, PermissionKey, RoleKey
from jsonschema import Draft202012Validator

from tests.api.helpers import disconnected_services

BUILD_ID = "hwpxbuild_" + "a" * 32


def test_hwpx_protocol_schema_is_draft_2020_12_and_rejects_commands() -> None:
    schema = json.loads(Path("schemas/api/v1/hwpx.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema["$defs"]["buildRequest"])
    assert not list(
        validator.iter_errors(
            {
                "renderer": "kordoc",
                "options": {"require_native_equations": True},
            }
        )
    )
    template_request = {
        "renderer": "eom-template",
        "options": {"document_profile": "eom-question-template-v1", "item_number": 7},
    }
    assert not list(validator.iter_errors(template_request))
    assert CreateHwpxBuildRequest.model_validate(template_request).options.item_number == 7
    content_team_request = {
        "renderer": "content-team",
        "options": {"document_profile": "content-team-hwp-question-editor-v2"},
    }
    assert not list(validator.iter_errors(content_team_request))
    assert CreateHwpxBuildRequest.model_validate(content_team_request).renderer == "content-team"
    assert (
        HwpxDeliveryProfile(
            renderer="content-team",
            renderer_version="2.0.0",
            document_profile="content-team-hwp-question-editor-v2",
            source_schema_ref="eom.assessment.item-content/2.0",
        ).renderer_version
        == "2.0.0"
    )
    automatic_request = {
        "renderer": "auto",
        "options": {"document_profile": "item-revision-auto", "item_number": 7},
    }
    assert not list(validator.iter_errors(automatic_request))
    assert CreateHwpxBuildRequest.model_validate(automatic_request).renderer == "auto"
    assert list(
        validator.iter_errors(
            {
                "renderer": "eom-template",
                "options": {"document_profile": "kordoc-report"},
            }
        )
    )
    assert list(
        validator.iter_errors(
            {
                "renderer": "content-team",
                "options": {"document_profile": "eom-question-template-v1"},
            }
        )
    )
    assert list(
        validator.iter_errors(
            {
                "renderer": "auto",
                "options": {"document_profile": "eom-question-template-v1"},
            }
        )
    )
    assert list(
        validator.iter_errors(
            {
                "renderer": "kordoc",
                "options": {},
                "command": "npm install attacker-package",
            }
        )
    )

    manager_schema = json.loads(
        Path(
            "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
            "hwpx-manager-download-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(manager_schema)
    request_validator = Draft202012Validator(manager_schema["$defs"]["request"])
    assert not list(
        request_validator.iter_errors(
            {"schema_version": "1.0", "operation": "download", "build_id": BUILD_ID}
        )
    )
    assert list(
        request_validator.iter_errors(
            {
                "schema_version": "1.0",
                "operation": "download",
                "build_id": BUILD_ID,
                "path": "/mnt/nas/private.hwpx",
            }
        )
    )


def test_hwpx_openapi_routes_are_additive_and_permissioned() -> None:
    services = disconnected_services()
    try:
        schema = create_app(services).openapi()
    finally:
        services.engine.dispose()
    paths = schema["paths"]
    assert paths["/api/v1/capabilities/hwpx"]["get"]["x-eom-permission"] == "hwpx:read"
    create = paths["/api/v1/item-revisions/{item_revision_id}/hwpx-builds"]["post"]
    assert create["x-eom-permission"] == "hwpx:build_create"
    assert paths["/api/v1/hwpx-builds/{build_id}"]["get"]["x-eom-permission"] == "hwpx:read"
    assert (
        paths["/api/v1/hwpx-builds/{build_id}/download"]["get"]["x-eom-permission"] == "hwpx:read"
    )
    assert PermissionKey.HWPX_READ in ROLE_PERMISSIONS[RoleKey.VIEWER]
    assert PermissionKey.HWPX_BUILD_CREATE not in ROLE_PERMISSIONS[RoleKey.AUTHOR]
    assert PermissionKey.HWPX_BUILD_CREATE in ROLE_PERMISSIONS[RoleKey.EDITOR]


def test_hwpx_build_projection_never_exposes_path_or_command() -> None:
    record = SimpleNamespace(
        build_id="hwpxbuild_" + "a" * 32,
        item_id="item_" + "b" * 32,
        item_revision_id="itemrev_" + "c" * 32,
        source_artifact_revision_id="rev_" + "d" * 32,
        source_sha256="sha256:" + "e" * 64,
        renderer="eom-template",
        renderer_version="1.0.0",
        state="SUCCEEDED",
        validation_state="PASS",
        native_equation_count=5,
        native_table_count=2,
        output_artifact_id="artifact_" + "f" * 32,
        output_artifact_revision_id="rev_" + "1" * 32,
        output_sha256="sha256:" + "2" * 64,
        failure_code=None,
        failure_detail_sanitized=None,
        created_by_operator_id="operator_" + "3" * 32,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        started_at=datetime(2026, 8, 21, tzinfo=UTC),
        completed_at=datetime(2026, 8, 21, tzinfo=UTC),
        resource_version=2,
    )
    payload = project_hwpx_build(record).model_dump(mode="json")  # type: ignore[arg-type]
    assert payload["download_available"] is True
    assert not ({"path", "nas_uri", "command", "environment", "workspace"} & payload.keys())
