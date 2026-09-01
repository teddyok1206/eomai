from __future__ import annotations

import hashlib
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_identity_service.tokens import AccessAuthentication
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit, MemoryIdempotency, _authentication
from tests.unit.test_assessment_item_content import item_content

REVISION_ID = "itemrev_" + "3" * 32
NEW_REVISION_ID = "itemrev_" + "4" * 32


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def import_structured_item_content(
        self,
        base_revision_id: str,
        request: object,
        actor: object,
        *,
        expected_version: int,
    ) -> tuple[str, str, int]:
        self.calls.append(
            {
                "base_revision_id": base_revision_id,
                "request": request,
                "actor": actor,
                "expected_version": expected_version,
            }
        )
        return "apicmd_" + "5" * 32, NEW_REVISION_ID, 1


class FakeCatalogApplication:
    def load_item_content(self, item_revision_id: str) -> object:
        assert item_revision_id == REVISION_ID
        from eom_catalog_contracts import AssessmentItemContent

        return AssessmentItemContent.model_validate(item_content())

    def download_item_media(self, item_revision_id: str, block_id: str) -> object:
        assert item_revision_id == REVISION_ID
        assert block_id == "block_image"
        content = b"\x89PNG\r\n\x1a\nAPI_MEDIA"

        class Media:
            media_type = "image/png"
            content_length = len(content)
            sha256 = "sha256:" + hashlib.sha256(content).hexdigest()

            @staticmethod
            def iter_chunks() -> object:
                yield content

        return Media()


def _client(*, admin: bool) -> tuple[TestClient, Any]:
    services = disconnected_services()
    services.commands = FakeCommands()  # type: ignore[assignment]
    services.catalog_application = FakeCatalogApplication()  # type: ignore[assignment]
    services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
    services.audit = FakeAudit()  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication(admin=admin)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services


def test_admin_imports_reviewed_structured_content_with_pinned_base() -> None:
    client, services = _client(admin=True)
    try:
        with client:
            response = client.post(
                f"/api/v1/item-revisions/{REVISION_ID}/structured-content-imports",
                headers={
                    "If-Match": '"v1"',
                    "Idempotency-Key": "structured-content-import-0001",
                },
                json={
                    "reviewed": True,
                    "review_reason": "검토된 구조화 문항을 canonical content로 승인합니다.",
                    "content": item_content(),
                },
            )
        assert response.status_code == 200
        assert response.json()["data"] == {
            "command_id": "apicmd_" + "5" * 32,
            "resource_type": "item_revision",
            "resource_id": NEW_REVISION_ID,
            "status": "COMPLETED",
            "resource_version": 1,
            "status_url": f"/api/v1/item-revisions/{NEW_REVISION_ID}",
        }
        assert services.commands.calls[0]["base_revision_id"] == REVISION_ID
        assert services.commands.calls[0]["expected_version"] == 1
    finally:
        services.engine.dispose()


def test_structured_content_import_is_admin_only_and_requires_review_declaration() -> None:
    viewer, viewer_services = _client(admin=False)
    try:
        with viewer:
            denied = viewer.post(
                f"/api/v1/item-revisions/{REVISION_ID}/structured-content-imports",
                headers={
                    "If-Match": '"v1"',
                    "Idempotency-Key": "structured-content-import-0002",
                },
                json={
                    "reviewed": True,
                    "review_reason": "검토된 구조화 문항을 canonical content로 승인합니다.",
                    "content": item_content(),
                },
            )
        assert denied.status_code == 403
        assert denied.json()["error_code"] == "PERMISSION_DENIED"
    finally:
        viewer_services.engine.dispose()

    admin, admin_services = _client(admin=True)
    try:
        with admin:
            invalid = admin.post(
                f"/api/v1/item-revisions/{REVISION_ID}/structured-content-imports",
                headers={
                    "If-Match": '"v1"',
                    "Idempotency-Key": "structured-content-import-0003",
                },
                json={
                    "reviewed": False,
                    "review_reason": "검토 선언이 없는 요청은 거부되어야 합니다.",
                    "content": item_content(),
                },
            )
        assert invalid.status_code == 422
        assert invalid.json()["error_code"] == "API_REQUEST_INVALID"
    finally:
        admin_services.engine.dispose()


def test_structured_content_read_uses_catalog_application_boundary() -> None:
    client, services = _client(admin=True)
    try:
        with client:
            response = client.get(f"/api/v1/item-revisions/{REVISION_ID}/structured-content")
        assert response.status_code == 200
        assert response.json()["data"] == item_content()
    finally:
        services.engine.dispose()


def test_item_media_stream_uses_catalog_boundary_and_security_headers() -> None:
    client, services = _client(admin=True)
    try:
        with client:
            response = client.get(f"/api/v1/item-revisions/{REVISION_ID}/media/block_image")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["etag"].startswith('"sha256:')
        assert response.content == b"\x89PNG\r\n\x1a\nAPI_MEDIA"
    finally:
        services.engine.dispose()
