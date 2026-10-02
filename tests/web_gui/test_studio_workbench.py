from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from eom_web_gui.contracts import StudioWorkbenchItem
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as PydanticValidationError

from tests.web_gui.helpers import login, make_client
from tests.web_gui.test_gateway import _hwpx_build_data, _list, _session, _single

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _schema() -> dict[str, object]:
    value = json.loads(
        (ROOT / "schemas/web-gui/studio-workbench-overview-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(value, dict)
    Draft202012Validator.check_schema(value)
    return value


def test_workbench_contract_schema_and_pydantic_reject_missing_action_pointer() -> None:
    schema = _schema()
    invalid = {
        "kind": "WORKFLOW",
        "title": "진행 중인 문항 제작",
        "state": "RUNNING",
        "next_action": "OPEN_WORKFLOW",
        "approval_mode": "NONE",
        "workflow_id": None,
        "item_id": None,
        "item_revision_id": None,
        "hwpx_build_id": None,
        "human_reference_code": None,
        "created_at": NOW.isoformat(),
    }
    invalid_overview = {
        "schema_version": "studio-workbench-overview/1.0",
        "generated_at": NOW.isoformat(),
        "source_truncated": False,
        "counts": {
            "in_progress": 1,
            "approval_waiting": 0,
            "hwpx_attention": 0,
            "recent_completed": 0,
        },
        "items": [invalid],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(invalid_overview)
    with pytest.raises(PydanticValidationError):
        StudioWorkbenchItem.model_validate(invalid)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        (
            {"kind": "WORKFLOW", "next_action": "OPEN_ITEM"},
            "resource kind and action",
        ),
        (
            {
                "kind": "WORKFLOW",
                "next_action": "REVIEW_LEGACY_WORKFLOW",
                "approval_mode": "NONE",
                "workflow_id": "workflow_" + "3" * 32,
                "item_id": None,
                "item_revision_id": None,
            },
            "legacy Workflow action",
        ),
    ),
)
def test_workbench_contract_rejects_semantically_incoherent_items(
    changes: dict[str, object], message: str
) -> None:
    value = {
        "kind": "ITEM_APPROVAL",
        "title": "완성 문항",
        "state": "APPROVED",
        "next_action": "OPEN_ITEM",
        "approval_mode": "NONE",
        "workflow_id": None,
        "item_id": "item_" + "1" * 32,
        "item_revision_id": "itemrev_" + "2" * 32,
        "hwpx_build_id": None,
        "human_reference_code": None,
        "created_at": NOW.isoformat(),
    }
    value.update(changes)
    overview = {
        "schema_version": "studio-workbench-overview/1.0",
        "generated_at": NOW.isoformat(),
        "source_truncated": False,
        "counts": {
            "in_progress": 0,
            "approval_waiting": 0,
            "hwpx_attention": 0,
            "recent_completed": 1,
        },
        "items": [value],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(overview)
    with pytest.raises(PydanticValidationError, match=message):
        StudioWorkbenchItem.model_validate(value)


@pytest.mark.anyio
async def test_workbench_gateway_composes_bounded_current_and_legacy_actions() -> None:
    workflow_id = "workflow_" + "1" * 32
    item_id = "item_" + "2" * 32
    revision_id = "itemrev_" + "3" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            assert request.url.params["limit"] == "50"
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "workflow_id": workflow_id,
                            "definition_key": "generic-item-development",
                            "definition_version": "1.15.0",
                            "state": "AWAITING_HUMAN_APPROVAL",
                            "stage": "human_approval",
                            "current_step_key": "human_approval",
                            "resource_version": 8,
                            "rework_cycle_count": 0,
                            "created_at": NOW.isoformat(),
                            "updated_at": NOW.isoformat(),
                            "completed_at": None,
                            "failure_code": None,
                            "accepted_resolution": None,
                            "knowledge_provenance": None,
                            "item_registration": None,
                        }
                    ]
                ),
            )
        if request.url.path == "/api/v1/items":
            assert request.url.params["state"] == "ACTIVE"
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "item_id": item_id,
                            "human_reference_code": "EOM-2026-001",
                            "lifecycle_state": "ACTIVE",
                            "current_revision_id": revision_id,
                            "resource_version": 1,
                            "created_at": NOW.isoformat(),
                            "approval": {
                                "schema_version": "item-approval-view/1.0",
                                "status": "PENDING",
                                "human_review_required": True,
                                "approved_at": None,
                                "approved_by": None,
                                "approval_receipt_sha256": None,
                                "hwpx_build_id": None,
                            },
                        }
                    ]
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    overview = await gateway.studio_workbench_overview(_session())
    assert overview.counts.approval_waiting == 2
    assert overview.counts.hwpx_attention == 1
    assert {item.next_action for item in overview.items} == {
        "REVIEW_LEGACY_WORKFLOW",
        "BUILD_REVIEW_HWPX",
    }
    Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(
        overview.model_dump(mode="json")
    )
    await gateway.close()


@pytest.mark.anyio
async def test_latest_hwpx_lookup_preserves_exact_revision_pointer() -> None:
    revision_id = "itemrev_" + "3" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/item-revisions/{revision_id}/hwpx-builds/latest"
        return httpx.Response(200, json=_single(_hwpx_build_data("hwpxbuild_" + "1" * 32)))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    value = await gateway.latest_valid_hwpx_build(_session(), revision_id)
    assert value is not None
    assert value.item_revision_id == revision_id
    await gateway.close()


@pytest.mark.anyio
async def test_latest_hwpx_lookup_rejects_a_different_revision_pointer() -> None:
    requested_revision_id = "itemrev_" + "4" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{requested_revision_id}/hwpx-builds/latest")
        return httpx.Response(200, json=_single(_hwpx_build_data("hwpxbuild_" + "1" * 32)))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
        await gateway.latest_valid_hwpx_build(_session(), requested_revision_id)
    await gateway.close()


def test_authenticated_workbench_route_uses_typed_projection() -> None:
    client, _ = make_client()
    login(client)
    response = client.get("/studio/api/v1/workbench/overview")
    assert response.status_code == 200
    value = response.json()
    assert value["schema_version"] == "studio-workbench-overview/1.0"
    assert value["counts"]["approval_waiting"] == 1
    Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(value)
    latest = client.get(
        "/studio/api/v1/items/revisions/" + "itemrev_" + "3" * 32 + "/latest-hwpx-build"
    )
    assert latest.status_code == 200
    assert latest.json() is None


def test_studio_assets_expose_deep_link_permissions_mobile_and_full_scorecard() -> None:
    html = (ROOT / "apps/web_gui/eom_web_gui/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    route_module = (ROOT / "apps/web_gui/eom_web_gui/static/studio-route.js").read_text(
        encoding="utf-8"
    )
    assert 'aria-controls="studio-sidebar"' in html
    assert 'id="mobile-logout"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="quality-scorecard-evidence"' in html
    assert 'id="quality-scorecard-authoring"' in html
    assert 'id="quality-scorecard-explanation"' in html
    assert 'id="quality-scorecard-mean-edit-time"' in html
    assert 'id="quality-open-hwpx"' in html
    assert 'id="quality-open-evidence"' in html
    assert 'data-required-permission="workflow:start"' in html
    assert "applyPermissionVisibility" in javascript
    assert "installPermissionRequirements(document)" in javascript
    assert "ADMIN_VIEW_NAMES.has(name)" in javascript
    assert 'window.addEventListener("popstate"' in javascript
    assert "hwpxBuildRequestSequence" in javascript
    assert 'url.searchParams.set("hwpx_build_id"' not in javascript
    assert 'state.currentView !== "hwpx"' in javascript
    assert 'hasPermission(state.operator, "hwpx:build_create")' in javascript
    assert 'setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기")' in javascript
    assert "URLSearchParams" in route_module
    assert "supportContextRoute" in route_module


def test_route_and_permission_modules_fail_closed_and_round_trip(tmp_path: Path) -> None:
    route_module = tmp_path / "studio-route.mjs"
    permission_module = tmp_path / "studio-permissions.mjs"
    route_module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/studio-route.js").read_bytes()
    )
    permission_module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/studio-permissions.js").read_bytes()
    )
    route_uri = json.dumps(route_module.as_uri())
    permission_uri = json.dumps(permission_module.as_uri())
    script = f"""
      import {{
        studioRouteFromLocation, studioRouteUrl, supportContextFromHistory, supportContextRoute,
      }} from {route_uri};
      import {{hasPermission, installPermissionRequirements}} from {permission_uri};
      const item = "item_" + "1".repeat(32);
      const revision = "itemrev_" + "2".repeat(32);
      const search = `?view=item&item_id=${{item}}`
        + `&item_revision_id=${{revision}}`;
      const route = studioRouteFromLocation({{search}});
      if (route.view !== "item"
        || route.item_id !== item
        || route.item_revision_id !== revision) process.exit(1);
      const url = studioRouteUrl(route);
      if (!url.includes("view=item") || !url.includes("item_revision_id=")) process.exit(2);
      if (/[?#]/.test(supportContextRoute(route))) process.exit(3);
      const invalid = studioRouteFromLocation({{search: "?view=unknown&workflow_id=../../secret"}});
      if (invalid.view !== "dashboard" || invalid.workflow_id !== undefined) process.exit(4);
      const context = supportContextRoute(route);
      if (supportContextFromHistory({{support_origin_route: context}}) !== context) process.exit(5);
      const invalidContext = {{support_origin_route: "/studio/../../secret"}};
      if (supportContextFromHistory(invalidContext) !== "/studio/") process.exit(6);
      const operator = {{effective_permissions: ["WORKFLOW:APPROVE"]}};
      if (!hasPermission(operator, "workflow:approve")) process.exit(7);
      if (hasPermission({{effective_permissions: []}}, "workflow:approve")) process.exit(8);
      const elements = new Map([["hwpx-build-submit", {{dataset: {{}}}}]]);
      installPermissionRequirements({{getElementById: (id) => elements.get(id) || null}});
      if (elements.get("hwpx-build-submit").dataset.requiredPermission
        !== "hwpx:build_create") process.exit(9);
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
