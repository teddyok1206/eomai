from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.idempotency_service import IdempotencyClaim
from eom_api.services.query_adapter import PageResult
from eom_api_contracts.hwpx import HwpxBuildView
from eom_hwpx_manager.application_service import SecureHwpxDownload
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)
BUILD_ID = "hwpxbuild_" + "1" * 32
ITEM_ID = "item_" + "2" * 32
REVISION_ID = "itemrev_" + "3" * 32
ARTIFACT_ID = "artifact_" + "4" * 32
ARTIFACT_REVISION_ID = "rev_" + "5" * 32
OPERATOR_ID = "operator_" + "6" * 32


def _authentication(*, admin: bool = True) -> AccessAuthentication:
    roles = (RoleKey.ADMIN,) if admin else (RoleKey.VIEWER,)
    permissions = frozenset(PermissionKey) if admin else frozenset({PermissionKey.HWPX_READ})
    operator = OperatorProjection(
        operator_id=OPERATOR_ID,
        username="hwpx-admin" if admin else "hwpx-viewer",
        display_name="HWPX Test Operator",
        status="ACTIVE",
        must_change_password=False,
        roles=roles,
        effective_permissions=tuple(sorted(permissions, key=str)),
        resource_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return AccessAuthentication(
        operator=operator,
        session_id="apisession_" + "7" * 32,
        authenticated_at=NOW,
        access_expires_at=NOW + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


def _record(*, state: str = "REQUESTED") -> SimpleNamespace:
    succeeded = state == "SUCCEEDED"
    return SimpleNamespace(
        build_id=BUILD_ID,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
        source_artifact_revision_id=ARTIFACT_REVISION_ID,
        source_sha256="sha256:" + "8" * 64,
        state=state,
        validation_state="PASS" if succeeded else "PENDING",
        native_equation_count=5 if succeeded else None,
        native_table_count=2 if succeeded else None,
        output_artifact_id=ARTIFACT_ID if succeeded else None,
        output_artifact_revision_id=ARTIFACT_REVISION_ID if succeeded else None,
        output_sha256="sha256:" + "9" * 64 if succeeded else None,
        failure_code=None,
        failure_detail_sanitized=None,
        created_by_operator_id=OPERATOR_ID,
        created_at=NOW,
        started_at=NOW if succeeded else None,
        completed_at=NOW if succeeded else None,
        resource_version=2 if succeeded else 1,
    )


@dataclass
class FakeCapability:
    state: str
    native_equations: bool
    native_tables: bool
    manager_registered: bool = True
    detail_code: str = "HWPX_READY"


class FakeCapabilityService:
    def __init__(self, state: str) -> None:
        self.state = state

    def inspect(self) -> FakeCapability:
        ready = self.state == "READY"
        return FakeCapability(
            state=self.state,
            native_equations=ready,
            native_tables=ready,
            detail_code="HWPX_READY" if ready else "HWPX_BUILDER_NOT_DEPLOYED",
        )


class MemoryIdempotency:
    def __init__(self) -> None:
        self.request_sha256: str | None = None
        self.response: dict[str, Any] | None = None

    @staticmethod
    def request_hash(**values: Any) -> str:
        import hashlib
        import json

        return "sha256:" + hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def claim(self, *, request_sha256: str, **_values: Any) -> IdempotencyClaim:
        if self.request_sha256 is not None and self.request_sha256 != request_sha256:
            from eom_api.errors import ApiError

            raise ApiError(409, "API_IDEMPOTENCY_CONFLICT", "Conflict", "Conflict")
        if self.response is not None:
            return IdempotencyClaim("apiidem_" + "a" * 32, self.response, 202)
        self.request_sha256 = request_sha256
        return IdempotencyClaim("apiidem_" + "a" * 32)

    def complete(self, _claim: IdempotencyClaim, *, body: dict[str, Any], **_values: Any) -> None:
        self.response = body

    @staticmethod
    def fail_final(_claim: IdempotencyClaim, _error_code: str) -> None:
        pass

    @staticmethod
    def submission_key(**_values: Any) -> str:
        return "api:" + "b" * 64


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[str] = []

    def append(self, _context: object, *, event_type: str, **_values: Any) -> None:
        self.events.append(event_type)


class FakeHwpxService:
    def __init__(self, download_path: Path) -> None:
        self.request_count = 0
        self.download_path = download_path

    def request_build(self, *_args: Any, **_kwargs: Any) -> tuple[SimpleNamespace, bool]:
        self.request_count += 1
        return _record(), True

    @staticmethod
    def get_build(_build_id: str) -> SimpleNamespace:
        return _record(state="SUCCEEDED")

    def secure_download(self, _build_id: str) -> SecureHwpxDownload:
        return SecureHwpxDownload(
            fd=os.open(self.download_path, os.O_RDONLY | os.O_CLOEXEC),
            filename="eom-test.hwpx",
            content_length=self.download_path.stat().st_size,
            sha256="sha256:" + "9" * 64,
        )


class FakeQueries:
    @staticmethod
    def list_hwpx_builds(**_values: Any) -> PageResult[HwpxBuildView]:
        from eom_api.services.hwpx_projection import project_hwpx_build

        return PageResult((project_hwpx_build(_record(state="SUCCEEDED")),), None, False)


def _client(tmp_path: Path, *, ready: bool = True, admin: bool = True) -> tuple[TestClient, Any]:
    output = tmp_path / "fixture.hwpx"
    output.write_bytes(b"TEST_ONLY_HWPX")
    services = disconnected_services()
    services.hwpx_capability = FakeCapabilityService(
        "READY" if ready else "PREPARED_NOT_DEPLOYED"
    )  # type: ignore[assignment]
    services.hwpx = FakeHwpxService(output)  # type: ignore[assignment]
    services.queries = FakeQueries()  # type: ignore[assignment]
    services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
    services.audit = FakeAudit()  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication(admin=admin)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services


def test_hwpx_capability_and_not_deployed_build_boundary(tmp_path: Path) -> None:
    client, services = _client(tmp_path, ready=False)
    try:
        with client:
            capability = client.get("/api/v1/capabilities/hwpx")
            assert capability.status_code == 200
            assert capability.json()["data"]["state"] == "PREPARED_NOT_DEPLOYED"
            refused = client.post(
                f"/api/v1/item-revisions/{REVISION_ID}/hwpx-builds",
                headers={"Idempotency-Key": "hwpx-api-test-0001"},
                json={"renderer": "kordoc", "options": {}},
            )
            assert refused.status_code == 503
            assert refused.json()["error_code"] == "HWPX_RENDERER_NOT_READY"
            assert services.hwpx.request_count == 0
    finally:
        services.engine.dispose()


def test_hwpx_build_replay_status_download_and_admin_list(tmp_path: Path) -> None:
    client, services = _client(tmp_path)
    body = {"renderer": "kordoc", "options": {"require_native_equations": True}}
    headers = {"Idempotency-Key": "hwpx-api-test-0002"}
    try:
        with client:
            created = client.post(
                f"/api/v1/item-revisions/{REVISION_ID}/hwpx-builds",
                headers=headers,
                json=body,
            )
            replayed = client.post(
                f"/api/v1/item-revisions/{REVISION_ID}/hwpx-builds",
                headers=headers,
                json=body,
            )
            assert created.status_code == replayed.status_code == 202
            assert created.json()["data"]["resource_id"] == BUILD_ID
            assert replayed.json()["data"] == created.json()["data"]
            assert services.hwpx.request_count == 1

            conflict = client.post(
                f"/api/v1/item-revisions/{REVISION_ID}/hwpx-builds",
                headers=headers,
                json={"renderer": "kordoc", "options": {"require_native_tables": True}},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"

            status = client.get(f"/api/v1/hwpx-builds/{BUILD_ID}")
            assert status.status_code == 200
            assert status.json()["data"]["download_available"] is True
            assert status.json()["data"]["native_equation_count"] == 5

            listing = client.get("/api/v1/hwpx-builds?state=SUCCEEDED")
            assert listing.status_code == 200
            assert listing.json()["data"][0]["build_id"] == BUILD_ID

            download = client.get(f"/api/v1/hwpx-builds/{BUILD_ID}/download")
            assert download.status_code == 200
            assert download.content == b"TEST_ONLY_HWPX"
            assert download.headers["content-type"] == "application/vnd.hancom.hwpx"
            assert download.headers["content-disposition"] == 'attachment; filename="eom-test.hwpx"'
            assert "HWPX_DOWNLOAD_AUTHORIZED" in services.audit.events
    finally:
        services.engine.dispose()


def test_hwpx_admin_explorer_is_backend_enforced(tmp_path: Path) -> None:
    client, services = _client(tmp_path, admin=False)
    try:
        with client:
            assert client.get(f"/api/v1/hwpx-builds/{BUILD_ID}").status_code == 200
            denied = client.get("/api/v1/hwpx-builds")
            assert denied.status_code == 403
            assert denied.json()["error_code"] == "PERMISSION_DENIED"
    finally:
        services.engine.dispose()
