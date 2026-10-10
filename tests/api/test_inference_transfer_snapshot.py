"""Fake authenticated boundary checks, not live corpus or session acceptance."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService
from eom_api.services.inference_transfer_snapshot_port import InferenceTransferSnapshotReadError
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import OPERATOR_ID, _authentication
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
)

PATH = "/api/v1/knowledge/inference-transfer/snapshot"
PERMISSIONS = frozenset(
    {
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    }
)


def phases() -> dict[str, tuple[InferenceTransferSnapshotRequest, InferenceTransferSnapshotResult]]:
    records = snapshot_records()
    prepared = snapshot_prepare_result(header=snapshot_header(records, actor_id=OPERATOR_ID))
    request = snapshot_read_request(prepared)
    read = snapshot_read_result(records, request=request)
    authorize = hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=prepared.header,
        staged_entry_set_sha256=snapshot_entry_set_sha256(
            tuple(row.staged_entry for row in records if row.staged_entry is not None)
        ),
        staged_baseline_set_sha256=snapshot_baseline_set_sha256(read.baselines),
    )
    authorized = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        header_sha256=prepared.header.header_sha256,
        authorization_sha256=authorize.authorization_sha256,
        source_count=prepared.header.source_count,
        profile_count=prepared.header.profile_count,
        missing_report_count=prepared.header.missing_report_count,
        staged_entry_set_sha256=authorize.staged_entry_set_sha256,
        staged_baseline_set_sha256=authorize.staged_baseline_set_sha256,
    )
    return {
        "PREPARE": (prepared.header.prepare, prepared),
        "READ": (request, read),
        "AUTHORIZE": (authorize, authorized),
    }


class Reader:
    def __init__(self, result: Any, failure: str | None = None) -> None:
        self.result = result
        self.failure = failure
        self.calls: list[tuple[str, InferenceTransferSnapshotRequest]] = []

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actor_id, request))
        if self.failure is not None:
            raise InferenceTransferSnapshotReadError(self.failure)
        return self.result


def authentication(permissions: frozenset[PermissionKey] = PERMISSIONS):
    return replace(_authentication(), permissions=permissions)


@pytest.mark.parametrize("phase", ("PREPARE", "READ", "AUTHORIZE"))
def test_three_read_only_phases_bind_actual_operator_without_idempotency_rows(phase):
    body, result = phases()[phase]
    reader = Reader(result)
    services = disconnected_services()
    services.audit = FakeAudit()  # type: ignore[assignment]
    services.inference_transfer_snapshots = InferenceTransferSnapshotApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            first = client.post(PATH, json=body.model_dump(mode="json"))
            replay = client.post(PATH, json=body.model_dump(mode="json"))
            assert first.status_code == replay.status_code == 200
            assert first.json()["data"] == replay.json()["data"] == result.model_dump(mode="json")
            assert reader.calls == [(OPERATOR_ID, body), (OPERATOR_ID, body)]
            operation = app.openapi()["paths"][PATH]["post"]
            assert operation["x-eom-read-only"] is True
            assert operation["x-eom-permission"] == PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value
            assert operation["x-eom-admin-only"] is False
            assert not any(
                value["name"] == "Idempotency-Key" for value in operation.get("parameters", ())
            )
    finally:
        services.engine.dispose()


def test_missing_bearer_fails_before_any_catalog_read():
    body, result = phases()["PREPARE"]
    reader = Reader(result)
    services = disconnected_services()
    services.audit = FakeAudit()  # type: ignore[assignment]
    services.inference_transfer_snapshots = InferenceTransferSnapshotApplicationService(reader)
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            response = client.post(PATH, json=body.model_dump(mode="json"))
            assert response.status_code == 401
            assert reader.calls == []
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_each_source_permission_is_required_before_dispatch(permission):
    body, result = phases()["PREPARE"]
    reader = Reader(result)
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(
            authentication(PERMISSIONS - {permission}), body
        )
    assert error.value.status == 403
    assert reader.calls == []


@pytest.mark.parametrize("phase", ("READ", "AUTHORIZE"))
def test_valid_header_hash_cannot_impersonate_the_earlier_operator(phase):
    body, result = phases()[phase]
    reader = Reader(result)
    actual = authentication()
    actual = replace(
        actual,
        operator=actual.operator.model_copy(update={"operator_id": "operator_" + "2" * 32}),
    )
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(actual, body)
    assert error.value.status == 403 and reader.calls == []


@pytest.mark.parametrize("change", ({"status": "DISABLED"}, {"must_change_password": True}))
def test_inactive_or_password_change_required_operator_is_not_a_read_capability(change):
    body, result = phases()["PREPARE"]
    reader = Reader(result)
    actual = authentication()
    actual = replace(actual, operator=actual.operator.model_copy(update=change))
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(actual, body)
    assert error.value.status == 403 and reader.calls == []


def test_authentication_password_change_flag_is_independently_enforced():
    body, result = phases()["PREPARE"]
    reader = Reader(result)
    actual = replace(authentication(), password_change_required=True)
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(actual, body)
    assert error.value.status == 403 and reader.calls == []


@pytest.mark.parametrize("extra", ("actor_id", "requester_role", "permissions", "path"))
def test_public_input_cannot_supply_private_authority(extra):
    body, result = phases()["PREPARE"]
    reader = Reader(result)
    services = disconnected_services()
    services.audit = FakeAudit()  # type: ignore[assignment]
    services.inference_transfer_snapshots = InferenceTransferSnapshotApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(PATH, json=body.model_dump(mode="json") | {extra: "ADMIN"})
            assert response.status_code == 422 and reader.calls == []
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("phase", ("PREPARE", "READ", "AUTHORIZE"))
def test_model_copy_reply_hash_tampering_is_classified_before_response(phase):
    body, result = phases()[phase]
    reader = Reader(result.model_copy(update={"result_sha256": content_sha256("foreign")}))
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(authentication(), body)
    assert error.value.status == 503
    assert error.value.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"


@pytest.mark.parametrize("phase", ("PREPARE", "READ", "AUTHORIZE"))
def test_valid_hash_wrong_phase_reply_is_not_accepted(phase):
    values = phases()
    body, _ = values[phase]
    foreign_phase = "READ" if phase == "PREPARE" else "PREPARE"
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(Reader(values[foreign_phase][1])).execute(
            authentication(), body
        )
    assert error.value.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"


def test_valid_hash_prepare_reply_for_other_operator_is_not_accepted():
    body, _ = phases()["PREPARE"]
    records = snapshot_records()
    foreign = snapshot_prepare_result(header=snapshot_header(records))
    assert foreign.header.actor_id != OPERATOR_ID
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(Reader(foreign)).execute(authentication(), body)
    assert error.value.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"


@pytest.mark.parametrize("field", ("header_sha256", "read_sha256"))
def test_valid_hash_read_reply_for_other_context_is_not_accepted(field):
    body, result = phases()["READ"]
    assert isinstance(result, InferenceTransferSnapshotReadResult)
    foreign = hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(
            result.model_dump(mode="json", exclude={"result_sha256"})
            | {
                field: content_sha256("foreign context"),
            }
        ),
    )
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(Reader(foreign)).execute(authentication(), body)
    assert error.value.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"


@pytest.mark.parametrize("result", (None, {}, "not-a-result"))
def test_untyped_port_reply_is_not_an_internal_attribute_error(result):
    body, _ = phases()["PREPARE"]
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(Reader(result)).execute(authentication(), body)
    assert error.value.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"


@pytest.mark.parametrize(
    "code,status",
    (
        ("INFERENCE_TRANSFER_FORBIDDEN", 403),
        ("INFERENCE_TRANSFER_SNAPSHOT_CHANGED", 409),
        ("INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID", 409),
        ("INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED", 422),
        ("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE", 503),
        ("untrusted-private-error-details", 503),
    ),
)
def test_stable_catalog_failures_are_safe_and_do_not_retry_or_widen_pins(code, status):
    body, _ = phases()["PREPARE"]
    reader = Reader(None, code)
    with pytest.raises(ApiError) as error:
        InferenceTransferSnapshotApplicationService(reader).execute(authentication(), body)
    assert error.value.status == status
    assert len(reader.calls) == 1 and reader.calls[0] == (OPERATOR_ID, body)
    assert "untrusted-private" not in error.value.error_code
