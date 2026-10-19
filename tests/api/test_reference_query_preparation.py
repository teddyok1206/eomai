"""Real HTTP/security dependencies, synthetic Identity source and native owner client.

No installed provider, privileged service, production DB or model execution.
"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.lifespan import AppServices
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService
from eom_api.services.reference_query_prepare_client import (
    NativeReferenceQueryPrepareClient,
    ReferenceQueryPrepareClientError,
)
from eom_api.settings import ApiSettings
from eom_catalog_contracts.reference_query_prepare import (
    MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES,
    ReferenceQueryPrepareReply,
    parse_supported_reference_query_prepare_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body
from tests.unit.test_reference_query_prepare_transport import api_context

PATH = "/api/v1/knowledge/reference-queries/preparation"


@pytest.fixture
def setup(monkeypatch):
    _source, context = api_context(monkeypatch)
    pair = context.authenticated_access
    services = disconnected_services()
    services.audit = FakeAudit()
    services.auth = Mock()
    services.auth.authenticate_and_capture_access.return_value = pair
    services.auth.authenticate_access.side_effect = AssertionError("capture must be current")
    native = Mock(spec=NativeReferenceQueryPrepareClient)
    native.prepare.return_value = ReferenceQueryPrepareReply.model_validate(reply_body())
    services.reference_query_preparation = ReferenceQueryPreparationApplicationService(native)
    try:
        yield create_app(services), services, native, pair
    finally:
        services.engine.dispose()


def post(client, *, body=None, key=None, token=True):
    body = request_body() if body is None else body
    headers = {"Idempotency-Key": key or body["idempotency_key"]}
    if token:
        headers["Authorization"] = "Bearer synthetic-not-a-runtime-token"
    return client.post(PATH, json=body, headers=headers)


def test_default_composition_is_disabled_without_native_io():
    services = disconnected_services()
    try:
        assert services.settings.reference_query_preparation_enabled is False
        assert services.reference_query_preparation.client is None
    finally:
        services.engine.dispose()


def test_opt_in_composition_selects_only_the_fixed_native_client():
    services = disconnected_services()
    try:
        enabled = AppServices(
            ApiSettings(reference_query_preparation_enabled=True), services.secrets, services.engine
        )
        assert type(enabled.reference_query_preparation.client) is NativeReferenceQueryPrepareClient
        assert enabled.reference_query_preparation.client.endpoint is None
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("status", ("PENDING", "READY", "UNAVAILABLE", "FAILED"))
def test_current_capture_and_original_key_reach_native_client_once(setup, status):
    app, services, native, pair = setup
    native.prepare.return_value = ReferenceQueryPrepareReply.model_validate(
        reply_body(status=status)
    )
    services.commands = Mock()
    services.idempotency = Mock()
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client)
    assert response.status_code == (202 if status == "PENDING" else 200)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"]["status"] == status
    native.prepare.assert_called_once()
    current, request = native.prepare.call_args.args
    assert current.authenticated_access is pair
    assert current.owner_capture() is pair.capture
    assert current.actor().actor_id == pair.capture.operator_id
    assert request.model_dump(mode="json") == request_body()
    services.auth.authenticate_and_capture_access.assert_called_once()
    assert not services.commands.mock_calls and not services.idempotency.mock_calls


def test_explicit_same_key_poll_does_not_cache_pending_or_create_other_work(setup):
    app, services, native, _pair = setup
    native.prepare.side_effect = [
        ReferenceQueryPrepareReply.model_validate(reply_body(status=status))
        for status in ("PENDING", "READY", "READY")
    ]
    services.idempotency = Mock()
    with TestClient(app, base_url="http://localhost") as client:
        responses = [post(client) for _ in range(3)]
    assert [value.status_code for value in responses] == [202, 200, 200]
    assert [value.json()["data"]["status"] for value in responses] == ["PENDING", "READY", "READY"]
    assert native.prepare.call_count == 3
    assert len({call.args[1].idempotency_key for call in native.prepare.call_args_list}) == 1
    assert len({id(call.args[0]) for call in native.prepare.call_args_list}) == 3
    assert services.auth.authenticate_and_capture_access.call_count == 3
    assert not services.idempotency.mock_calls


def test_unknown_exchange_outcome_is_redacted_and_never_auto_retried(setup):
    app, _services, native, _pair = setup
    native.prepare.side_effect = ReferenceQueryPrepareClientError("synthetic private details")
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client)
    assert response.status_code == 503
    assert response.json()["error_code"] == "REFERENCE_QUERY_PREPARE_UNAVAILABLE"
    assert "synthetic private details" not in response.text
    native.prepare.assert_called_once()


def test_header_body_mismatch_never_dispatches(setup):
    app, _services, native, _pair = setup
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client, key="different-original-key")
    assert response.status_code == 409
    assert response.json()["error_code"] == "REFERENCE_QUERY_PREPARE_CONFLICT"
    native.prepare.assert_not_called()


def test_disabled_boundary_never_dispatches(setup):
    app, services, native, _pair = setup
    services.reference_query_preparation = ReferenceQueryPreparationApplicationService(None)
    with TestClient(app, base_url="http://localhost") as client:
        assert post(client).status_code == 503
    native.prepare.assert_not_called()


@pytest.mark.parametrize("fault", ("missing_login", "permission", "password", "stale", "key"))
def test_auth_action_freshness_and_key_fail_before_dispatch(setup, fault):
    app, services, native, pair = setup
    if fault == "permission":
        authentication = replace(
            pair.authentication,
            permissions=pair.authentication.permissions - {PermissionKey.WORKFLOW_START},
        )
    elif fault == "password":
        authentication = replace(pair.authentication, password_change_required=True)
    elif fault == "stale":
        from datetime import timedelta

        authentication = replace(
            pair.authentication,
            authenticated_at=pair.authentication.authenticated_at - timedelta(days=1),
        )
    else:
        authentication = pair.authentication
    services.auth.authenticate_and_capture_access.return_value = replace(
        pair, authentication=authentication
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = post(
            client, token=fault != "missing_login", key="bad" if fault == "key" else None
        )
    assert response.status_code == {"missing_login": 401, "key": 422}.get(fault, 403)
    native.prepare.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "ADMIN"),
        ("permissions", ["ADMIN"]),
        ("selection", {"workflow_id": "latest"}),
        ("capture", {}),
        ("path", "/mnt/nas/private"),
        ("runtime_bundle", {}),
        ("source_item_revision_id", True),
        ("request_sha256", "sha256:" + "0" * 64),
    ),
)
def test_closed_canonical_schema_errors_are_sanitized_http_input_errors(setup, field, value):
    app, _services, native, _pair = setup
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client, body=request_body() | {field: value})
    assert response.status_code == 422
    assert response.json()["error_code"] == "API_REQUEST_INVALID"
    assert all(
        issue["detail"] == "The supplied value does not satisfy the request schema."
        for issue in response.json()["errors"]
    )
    native.prepare.assert_not_called()


def test_raw_whitespace_cannot_bypass_byte_budget(setup):
    app, _services, native, _pair = setup
    body = request_body()
    raw = canonical_json_bytes(body) + b" " * MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            PATH,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer synthetic-not-a-runtime-token",
                "Idempotency-Key": body["idempotency_key"],
            },
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == "REFERENCE_QUERY_PREPARE_REQUEST_INVALID"
    native.prepare.assert_not_called()


def test_operation_declares_fresh_mutation_not_read_only(setup):
    app, _services, _native, _pair = setup
    operation = app.openapi()["paths"][PATH]["post"]
    assert operation["x-eom-permission"] == PermissionKey.WORKFLOW_START.value
    assert operation["x-eom-fresh-auth"] is True
    assert {"200", "202"} <= operation["responses"].keys()
    assert not operation.get("x-eom-read-only", False)
    assert any(parameter["name"] == "Idempotency-Key" for parameter in operation["parameters"])


def test_openapi_declares_exact_inputs_without_reinterpreting_predecessors(setup):
    app, _services, _native, _pair = setup
    schema = app.openapi()
    body = schema["paths"][PATH]["post"]["requestBody"]["content"]["application/json"]["schema"]
    prefix = "#/components/schemas/ReferenceQueryPrepareInput"
    assert body["discriminator"] == {
        "propertyName": "schema_version",
        "mapping": {
            "system-rag-reference-query-prepare-request/1.0": prefix,
            "system-rag-reference-query-prepare-request/1.1": prefix + "V11",
            "system-rag-reference-query-prepare-request/2.0": prefix + "V2",
        },
    }
    assert len(body["oneOf"]) == 3
    old = schema["components"]["schemas"]["ReferenceQueryPrepareInput"]
    new = schema["components"]["schemas"]["ReferenceQueryPrepareInputV11"]
    mixed = schema["components"]["schemas"]["ReferenceQueryPrepareInputV2"]
    assert "consumer_purpose" not in old["properties"]
    assert new["properties"]["consumer_purpose"]["enum"] == ["ITEM_AUTHORING", "ITEM_REVIEW"]
    assert "consumer_purpose" in new["required"]
    assert old["additionalProperties"] is False and new["additionalProperties"] is False
    assert mixed["properties"]["consumer_purpose"]["enum"] == [
        "PAST_EXAM_VARIATION",
        "ITEM_AUTHORING",
        "ITEM_REVIEW",
    ]
    assert "consumer_purpose" in mixed["required"] and mixed["additionalProperties"] is False


@pytest.mark.parametrize("purpose", ("ITEM_AUTHORING", "ITEM_REVIEW"))
def test_explicit_successor_uses_same_authenticated_operation_and_bound_reply(setup, purpose):
    app, services, native, pair = setup
    body = request_body(consumer_purpose=purpose)
    expected = parse_supported_reference_query_prepare_request(body)
    native.prepare.return_value = ReferenceQueryPrepareReply.model_validate(reply_body(expected))
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client, body=body)
    assert response.status_code == 202 and response.headers["Cache-Control"] == "no-store"
    current, request = native.prepare.call_args.args
    assert current.authenticated_access is pair and request.consumer_purpose == purpose
    assert request.model_dump(mode="json") == body
    assert response.json()["data"]["request_sha256"] == expected.request_sha256
    services.auth.authenticate_and_capture_access.assert_called_once()


@pytest.mark.parametrize(
    "purpose", ("PAST_EXAM_VARIATION", "GENERAL_CHAT_READ", "MOCK_EXAM_OBSERVATION")
)
def test_successor_unoffered_purpose_is_rejected_before_native_io(setup, purpose):
    from tests.unit.inference_transfer_embedding_fixtures import seal

    app, _services, native, _pair = setup
    body = request_body(consumer_purpose="ITEM_AUTHORING")
    body = seal(body | {"consumer_purpose": purpose}, "request_sha256")
    with TestClient(app, base_url="http://localhost") as client:
        response = post(client, body=body)
    assert response.status_code == 422 and response.json()["error_code"] == "API_REQUEST_INVALID"
    native.prepare.assert_not_called()
