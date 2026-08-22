from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts import (
    AssessmentItemContent,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    ReviewedItemContentImportCommand,
    validate_contract,
)
from eom_catalog_service.application_server import CatalogApplicationServer

from tests.unit.test_assessment_item_content import item_content


class FakeImports:
    def import_reviewed(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            item_id="item_" + "1" * 32,
            item_revision_id="itemrev_" + "2" * 32,
            resource_version=1,
            content_artifact_id="artifact_" + "3" * 32,
            content_artifact_revision_id="rev_" + "4" * 32,
            content_sha256="sha256:" + "5" * 64,
        )


class FakeRegistry:
    def load_item_content(self, _revision_id: str) -> AssessmentItemContent:
        return AssessmentItemContent.model_validate(item_content())


def _server(tmp_path: Path, *, allowed_uid: int | None = None) -> CatalogApplicationServer:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    return CatalogApplicationServer(  # type: ignore[arg-type]
        FakeImports(),
        FakeRegistry(),
        socket_path=runtime / "manager.sock",
        allowed_uid=os.getuid() if allowed_uid is None else allowed_uid,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def _client(server: CatalogApplicationServer) -> CatalogApplicationClient:
    return CatalogApplicationClient(
        server.socket_path,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_catalog_application_contract_validates_schema_and_typed_models() -> None:
    command = ReviewedItemContentImportCommand(
        base_revision_id="itemrev_" + "6" * 32,
        expected_version=1,
        reviewed_by="operator_test_admin",
        review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
        content=AssessmentItemContent.model_validate(item_content()),
    )
    request = CatalogApplicationRequest(root=command).model_dump(mode="json")
    validate_contract("catalog-application-request", request)
    response = CatalogApplicationResponse(
        status="OK",
        operation="GET_ITEM_CONTENT",
        content=AssessmentItemContent.model_validate(item_content()),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response", response)


def test_catalog_socket_round_trip_preserves_typed_content_and_import_result(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        imported = client.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id="itemrev_" + "6" * 32,
                expected_version=1,
                reviewed_by="operator_test_admin",
                review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
                content=AssessmentItemContent.model_validate(item_content()),
            )
        )
        assert imported.item_revision_id == "itemrev_" + "2" * 32
        loaded = client.load_item_content("itemrev_" + "2" * 32)
        assert loaded == AssessmentItemContent.model_validate(item_content())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_rejects_wrong_peer_and_unsafe_socket_metadata(tmp_path: Path) -> None:
    server = _server(tmp_path, allowed_uid=os.getuid() + 1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(CatalogApplicationClientError) as raised:
            _client(server).load_item_content("itemrev_" + "2" * 32)
        assert (
            raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    regular = tmp_path / "not-a-socket"
    regular.write_bytes(b"")
    client = CatalogApplicationClient(
        regular,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    with pytest.raises(CatalogApplicationClientError) as raised:
        client.load_item_content("itemrev_" + "2" * 32)
    assert raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value


def test_catalog_application_systemd_boundary_keeps_api_away_from_nas() -> None:
    unit = Path("infra/systemd/eom-catalog-application-runner.service").read_text(encoding="utf-8")
    assert "User=eom" in unit
    assert "Group=eom-api" in unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" in unit
    assert "ReadWritePaths=/mnt/nas/eom/artifacts" in unit
    assert "InaccessiblePaths=/etc/eom/secrets/api.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=\n" in unit
    api_unit = Path("infra/systemd/eom-api.service").read_text(encoding="utf-8")
    assert (
        "After=network-online.target docker.service eom-catalog-application-runner.service"
        in api_unit
    )
    assert "Wants=network-online.target eom-catalog-application-runner.service" in api_unit
    assert "ReadWritePaths=/mnt/nas" not in api_unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in api_unit
    assert "InaccessiblePaths=/etc/eom/secrets/catalog-manager.env" in api_unit


def test_application_api_catalog_client_depends_on_protocol_not_server_implementation() -> None:
    client_source = Path(
        "apps/application_api/eom_api/services/catalog_application_client.py"
    ).read_text(encoding="utf-8")
    problem_source = Path("apps/application_api/eom_api/problem_details.py").read_text(
        encoding="utf-8"
    )

    assert "eom_catalog_contracts" in client_source
    assert "eom_catalog_service" not in client_source
    assert "eom_catalog_service" not in problem_source
