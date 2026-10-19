"""Exact mixed preparation/HTTP carriers reuse actual current-capture transport."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService
from eom_api.services.reference_query_prepare_client import NativeReferenceQueryPrepareClient
from eom_api_contracts.reference_queries import SupportedReferenceQueryPrepareInput
from eom_api_contracts.similarity_context import SimilarityContextReadSelectionV2
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareReplyV2,
    ReferenceQueryPrepareRequest,
    ReferenceQueryPrepareRequestV2,
    parse_supported_reference_query_prepare_request,
    validate_supported_reference_query_prepare_reply,
)
from eom_catalog_contracts.similarity_context_v2 import SupportedSimilarityContext
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_identity_service.tokens import SessionTokenService
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, bind_chat_listener
from eom_orchestrator.reference_query_prepare_transport import (
    handle_reference_query_prepare_connection,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequest,
    ReferenceQueryWorkflowRequestV2,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from tests.api.test_similarity_context_read import (
    PATH as READ_PATH,
)
from tests.api.test_similarity_context_read import (
    PERMISSIONS,
    authentication,
)
from tests.api.test_similarity_context_read import (
    setup as setup,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_authenticated_session_fence import assert_current
from tests.unit.test_catalog_owner_capture_peer import SyntheticApiPeer
from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_mixed_similarity_contracts import mixed_context_body
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body
from tests.unit.test_reference_query_prepare_transport import api_context

ERRORS = (ValueError, SchemaError)


def prepare2():
    body = request_body()
    body.update(
        schema_version="system-rag-reference-query-prepare-request/2.0",
        consumer_purpose="PAST_EXAM_VARIATION",
    )
    return ReferenceQueryPrepareRequestV2.model_validate(seal(body, "request_sha256"))


def reply2(request, status="PENDING"):
    return ReferenceQueryPrepareReplyV2.model_validate(
        reply_body(request, status=status)
        | {"schema_version": "system-rag-reference-query-prepare-reply/2.0"}
    )


def test_additive_prepare2_schema_and_pure_http_model_preserve_identity_and_bounds():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-reference-query-prepare-v2"]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-reference-query-prepare-v2"))
    request = prepare2()
    assert not isinstance(request, ReferenceQueryPrepareRequest)
    assert parse_supported_reference_query_prepare_request(request) == request
    assert isinstance(
        TypeAdapter(SupportedReferenceQueryPrepareInput).validate_python(
            request.model_dump(mode="json")
        ),
        ReferenceQueryPrepareRequestV2,
    )
    reply = reply2(request)
    validate_supported_reference_query_prepare_reply(request, reply)
    with pytest.raises(ERRORS):
        ReferenceQueryPrepareRequest.model_validate(request)
    with pytest.raises(ERRORS):
        validate_supported_reference_query_prepare_reply(
            request, ReferenceQueryPrepareReply.model_validate(reply_body(request))
        )
    with pytest.raises(ERRORS):
        TypeAdapter(SupportedReferenceQueryPrepareInput).validate_python(
            request.model_dump(mode="json") | {"actor_id": "ADMIN"}
        )


def test_original_numerical_definition_policy_launch_and_input_remain1_for_workflow_metadata2():
    original = case()
    body = original.request.model_dump(mode="json")
    context = body["context_request"]
    context["schema_version"] = "system-rag-similarity-request/2.0"
    for view in context["views"]:
        view["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    body["context_request"] = seal(context, "request_sha256")
    body["schema_version"] = "reference-query-workflow-request/2.0"
    request = parse_supported_reference_query_workflow_request(seal(body, "request_sha256"))
    assert isinstance(request, ReferenceQueryWorkflowRequestV2)
    assert not isinstance(request, ReferenceQueryWorkflowRequest)
    validate_reference_query_request_references(request, original.policy, original.bundle)
    native_body = original.native_input.model_dump(mode="json")
    native_body["context_request_sha256"] = request.context_request.request_sha256
    native = parse_embedding_reference_query_input_v11(seal(native_body, "request_sha256"))
    launch_body = original.launch.model_dump(mode="json")
    launch_body.update(
        workflow_request_sha256=request.request_sha256,
        context_request_sha256=request.context_request.request_sha256,
        query_request_sha256=native.request_sha256,
    )
    launch = parse_reference_query_launch_association(seal(launch_body, "association_sha256"))
    validate_reference_query_launch_association(
        launch, request, original.policy, original.bundle, native
    )
    assert launch.schema_version == "reference-query-launch-association/1.0"
    assert native.schema_version == "embedding-reference-query-input/1.1"
    assert native.rows == original.native_input.rows
    assert request.workflow_definition_version == "1.0.0"
    assert original.policy.schema_version == "reference-query-execution-policy/1.0"


def test_public_read2_selector_and_response_discriminator_do_not_try_old_family():
    body = {
        "schema_version": "system-rag-similarity-read-selection/2.0",
        "workflow_id": "workflow_" + "a" * 32,
        "workflow_request_sha256": "sha256:" + "b" * 64,
        "context_request_sha256": "sha256:" + "c" * 64,
    }
    selector = SimilarityContextReadSelectionV2.model_validate(body)
    assert selector.exact_selection().context_request_sha256 == body["context_request_sha256"]
    context = TypeAdapter(SupportedSimilarityContext).validate_python(mixed_context_body())
    assert context.schema_version == "system-rag-similarity-context/2.0"
    with pytest.raises(ValueError):
        SimilarityContextReadSelectionV2.model_validate(body | {"actor_id": "ADMIN"})


def test_existing_authenticated_http_read_route_preserves_profile2_and_actual_actor(setup):
    from fastapi.testclient import TestClient

    app, services, reader, old_selection, _old = setup
    services.idempotency = Mock(side_effect=AssertionError("read-only must not claim"))
    services.commands = Mock(side_effect=AssertionError("read-only must not submit"))
    result = TypeAdapter(SupportedSimilarityContext).validate_python(mixed_context_body())
    reader.read_v2.return_value = result
    selector = old_selection.model_dump(mode="json") | {
        "schema_version": "system-rag-similarity-read-selection/2.0",
        "context_request_sha256": result.request.request_sha256,
    }
    with TestClient(app, base_url="http://localhost") as http:
        response = http.post(READ_PATH, json=selector)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == result.model_dump(mode="json")
    actual = reader.read_v2.call_args.args
    assert actual[0] == authentication().operator.operator_id
    assert actual[1].context_request_sha256 == result.request.request_sha256
    reader.read.assert_not_called()
    assert not services.idempotency.mock_calls and not services.commands.mock_calls


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_read2_checks_every_existing_current_permission_before_owner(setup, permission):
    from dataclasses import replace

    from eom_api.errors import ApiError

    _app, services, reader, selection, _old = setup
    with pytest.raises(ApiError) as caught:
        services.similarity_context_reads.read_v2(
            replace(authentication(), permissions=PERMISSIONS - {permission}), selection
        )
    assert caught.value.status == 403
    reader.read_v2.assert_not_called()


def test_actual_local_http_and_unix_prepare2_preserve_same_genuine_synthetic_capture(
    observation, monkeypatch, tmp_path
):
    from eom_api.app import create_app
    from fastapi.testclient import TestClient

    from tests.api.helpers import disconnected_services
    from tests.api.test_hwpx_endpoints import FakeAudit

    source, context = api_context(monkeypatch)
    request = prepare2()
    tmp_path.chmod(0o2750)
    endpoint = ChatSocketEndpoint(
        tmp_path / "owner.sock", os.getuid(), os.getgid(), parent_mode=0o2750
    )
    listener = bind_chat_listener(endpoint, backlog=1)
    listener.settimeout(10)
    calls = []

    def factory(capture):
        assert_current(source, capture)

        def prepare(actual):
            assert actual == request
            calls.append((capture.operator_id, actual.schema_version))
            return reply2(actual)

        return SimpleNamespace(prepare=prepare)

    installed = ProtectedInstalledIdentityProviderAdmission(observation[0])

    def serve():
        connection, _ = listener.accept()
        with SyntheticApiPeer(connection.detach()) as peer:
            handle_reference_query_prepare_connection(
                peer, admission=installed, api_uid=1000, application=factory
            )

    services = disconnected_services()
    services.audit = FakeAudit()
    services.auth = Mock()
    services.auth.authenticate_and_capture_access.return_value = context.authenticated_access
    services.auth.authenticate_access.side_effect = AssertionError("current capture required")
    services.reference_query_preparation = ReferenceQueryPreparationApplicationService(
        NativeReferenceQueryPrepareClient(endpoint)
    )
    monkeypatch.setattr(
        SessionTokenService,
        "authenticate_and_capture_access",
        Mock(side_effect=AssertionError("no reauthentication")),
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(serve)
            with TestClient(create_app(services), base_url="http://localhost") as http:
                response = http.post(
                    "/api/v1/knowledge/reference-queries/preparation",
                    json=request.model_dump(mode="json"),
                    headers={
                        "Authorization": "Bearer synthetic-HTTP-only-token",
                        "Idempotency-Key": request.idempotency_key,
                    },
                )
            future.result(timeout=10)
        assert response.status_code == 202
        reply = ReferenceQueryPrepareReplyV2.model_validate(response.json()["data"])
        validate_supported_reference_query_prepare_reply(request, reply)
        assert calls == [(source.operator.operator_id, request.schema_version)]
        assert response.headers["Cache-Control"] == "no-store"
        services.auth.authenticate_and_capture_access.assert_called_once()
        assert source.raw_token not in canonical_json_bytes(reply).decode()
    finally:
        listener.close()
        services.engine.dispose()
