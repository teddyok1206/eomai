"""Authenticated creation and status replay of saved assembly delivery."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication
from tests.unit.test_curated_hwpx_build import build_record


def test_create_then_repeated_status_reads_never_resubmit_or_render():
    record = build_record()
    record.created_at = datetime.now(UTC)
    record.output_filename = "eom-assembly.hwpx"
    services = disconnected_services()
    services.curated_hwpx = SimpleNamespace(
        request_build=Mock(return_value=(record, True)),
        get_build=Mock(return_value=record),
        latest_build=Mock(return_value=None),
    )
    services.audit = SimpleNamespace(append=Mock())
    app = create_app(services)

    def authenticated(request: Request):
        auth = _authentication(admin=True)
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        base = f"/api/v1/item-db/assemblies/{record.assembly_id}/hwpx-builds"
        body = {
            "assembly_revision_id": record.assembly_revision_id,
            "manifest_sha256": record.assembly_manifest_sha256,
        }
        assert client.post(base, json=body).status_code == 400
        created = client.post(
            base, json=body, headers={"Idempotency-Key": "curated-delivery-http-key"}
        )
        assert created.status_code == 202, created.text
        assert created.json()["data"]["build_id"] == record.build_id
        assert client.get(base + "/latest", params=body).json()["data"] is None
        first = client.get(base + "/" + record.build_id)
        second = client.get(base + "/" + record.build_id)
        assert first.status_code == second.status_code == 200
        assert first.json()["data"] == second.json()["data"]
        services.curated_hwpx.request_build.assert_called_once()
        assert services.curated_hwpx.get_build.call_count == 2


def test_wrong_assembly_path_is_not_a_download_authority():
    import pytest
    from eom_api.errors import ApiError
    from eom_api.routers.curated_document_assemblies import download_curated_build

    record = build_record()
    downloads = Mock()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(
                    curated_hwpx=SimpleNamespace(get_build=Mock(return_value=record)),
                    hwpx_downloads=downloads,
                )
            )
        ),
        state=SimpleNamespace(request_context=SimpleNamespace(actor=Mock())),
    )
    with pytest.raises(ApiError) as error:
        download_curated_build(request, "assembly_" + "0" * 32, record.build_id)
    assert error.value.status == 404
    downloads.download_curated.assert_not_called()
