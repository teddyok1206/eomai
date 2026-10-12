"""Synthetic deadline cliffs; no sleep, network, DB, model or actual owner authority."""

from __future__ import annotations

import ast
import http.client as http_client
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_api.services import inference_transfer_snapshot_client as client_module
from eom_catalog_contracts.inference_transfer_invocation_v11 import parse_pair_submit_request_v11
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import (
    COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS,
    DEFAULT_SNAPSHOT_TIMEOUT_SECONDS,
    SnapshotPhase,
    snapshot_phase_deadlines,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator import inference_transfer_owner_http as owner_http
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure
from pydantic import SecretStr

from tests.unit.inference_transfer_invocation_fixtures import rehash, submit_request
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
)
from tests.unit.test_inference_transfer_owner_http import (
    ACTOR,
    TOKEN,
    connection,
    session,
    wrapper,
)
from tests.unit.test_inference_transfer_owner_http_comparisons import (
    KEY,
    command,
)
from tests.unit.test_inference_transfer_owner_http_comparisons import (
    session as comparison_session,
)


def phase_case(
    phase: SnapshotPhase,
) -> tuple[InferenceTransferSnapshotRequest, InferenceTransferSnapshotResult]:
    prepared = snapshot_prepare_result(header=snapshot_header(actor_id=ACTOR))
    if phase == "PREPARE":
        return prepared.header.prepare, prepared
    if phase == "READ":
        request = snapshot_read_request(prepared)
        return request, snapshot_read_result(snapshot_records(), request=request)
    authorize_request = hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=prepared.header,
        staged_entry_set_sha256=content_sha256("synthetic entries"),
        staged_baseline_set_sha256=content_sha256("synthetic baselines"),
    )
    result = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        header_sha256=prepared.header.header_sha256,
        authorization_sha256=authorize_request.authorization_sha256,
        source_count=prepared.header.source_count,
        profile_count=prepared.header.profile_count,
        missing_report_count=prepared.header.missing_report_count,
        staged_entry_set_sha256=authorize_request.staged_entry_set_sha256,
        staged_baseline_set_sha256=authorize_request.staged_baseline_set_sha256,
    )
    return authorize_request, result


@pytest.mark.parametrize(
    "phase,catalog_seconds,http_seconds",
    [("PREPARE", 120.0, 120.0), ("READ", 120.0, 120.0), ("AUTHORIZE", 300.0, 330.0)],
)
def test_fixed_phase_budgets_are_finite_immutable_and_authorize_has_outer_margin(
    phase: SnapshotPhase, catalog_seconds: float, http_seconds: float
) -> None:
    policy = snapshot_phase_deadlines(phase)
    assert (policy.catalog_response_seconds, policy.owner_http_seconds) == (
        catalog_seconds,
        http_seconds,
    )
    assert math.isfinite(catalog_seconds) and math.isfinite(http_seconds)
    assert policy is snapshot_phase_deadlines(phase)
    with pytest.raises(FrozenInstanceError):
        cast(Any, policy).catalog_response_seconds = 999.0
    assert DEFAULT_SNAPSHOT_TIMEOUT_SECONDS == 120.0
    if phase == "AUTHORIZE":
        assert http_seconds - catalog_seconds == 30.0


@pytest.mark.parametrize("phase", [None, "", "UNKNOWN", "SUBMIT", 300, math.inf, []])
def test_untrusted_numeric_timeout_or_unknown_phase_is_not_a_supported_override(phase: Any) -> None:
    with pytest.raises(ValueError, match="unsupported snapshot phase"):
        snapshot_phase_deadlines(phase)


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_api_socket_timeout_uses_validated_exact_phase_and_preserves_frame_bounds(
    monkeypatch: pytest.MonkeyPatch, phase: SnapshotPhase
) -> None:
    request, result = phase_case(phase)
    reply = InferenceTransferSnapshotBindingReply(status="SUCCESS", result=result, error_code=None)
    exchange = Mock(return_value=reply.model_dump(mode="json"))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    endpoint = ChatSocketEndpoint(Path("/synthetic/fixed/catalog.sock"), 12345, 45678)
    assert client_module.CatalogInferenceTransferSnapshotClient(endpoint).execute(
        ACTOR, request
    ) == (result)
    assert exchange.call_count == 1
    assert exchange.call_args.args[0] == endpoint
    assert exchange.call_args.kwargs == {
        "request_limit": MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
        "reply_limit": MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
        "timeout": snapshot_phase_deadlines(phase).catalog_response_seconds,
    }
    assert exchange.call_args.args[1]["request"] == request.model_dump(mode="json")


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_socket_125_second_fake_cliff_changes_only_authorize(
    monkeypatch: pytest.MonkeyPatch, phase: SnapshotPhase
) -> None:
    request, result = phase_case(phase)
    reply = InferenceTransferSnapshotBindingReply(status="SUCCESS", result=result, error_code=None)

    def respond(_endpoint: Any, _document: Any, **bounds: Any) -> dict[str, Any]:
        if bounds["timeout"] <= 125.0:
            raise ChatTransportError("UNAVAILABLE")
        return reply.model_dump(mode="json")

    exchange = Mock(side_effect=respond)
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    endpoint = ChatSocketEndpoint(Path("/synthetic/fixed/catalog.sock"), 12345, 45678)
    client = client_module.CatalogInferenceTransferSnapshotClient(endpoint)
    if phase == "AUTHORIZE":
        assert client.execute(ACTOR, request) == result
    else:
        with pytest.raises(client_module.InferenceTransferSnapshotClientError) as caught:
            client.execute(ACTOR, request)
        assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert exchange.call_count == 1


def test_authorize_socket_deadline_failure_is_terminal_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _result = phase_case("AUTHORIZE")
    exchange = Mock(side_effect=ChatTransportError("UNAVAILABLE"))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    endpoint = ChatSocketEndpoint(Path("/synthetic/fixed/catalog.sock"), 12345, 45678)
    with pytest.raises(client_module.InferenceTransferSnapshotClientError) as caught:
        client_module.CatalogInferenceTransferSnapshotClient(endpoint).execute(ACTOR, request)
    assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert exchange.call_count == 1 and exchange.call_args.kwargs["timeout"] == 300.0


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_actual_owner_session_selects_same_phase_rule_before_one_http_send(
    monkeypatch: pytest.MonkeyPatch, phase: SnapshotPhase
) -> None:
    value = session(monkeypatch)
    request, result = phase_case(phase)
    transport = connection(
        monkeypatch,
        canonical_json_bytes(wrapper(result)),
        expected_timeout=snapshot_phase_deadlines(phase).owner_http_seconds,
    )
    assert value.execute(ACTOR, request) == result
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]
    assert len(transport.requests) == 1
    assert transport.requests[0][2] == canonical_json_bytes(request.model_dump(mode="json"))
    assert transport.requests[0][3]["Authorization"] == "Bearer " + TOKEN


def test_owner_authorize_timeout_is_sanitized_terminal_and_no_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    request, result = phase_case("AUTHORIZE")
    transport = connection(
        monkeypatch, canonical_json_bytes(wrapper(result)), expected_timeout=330.0
    )
    monkeypatch.setattr(transport, "getresponse", Mock(side_effect=TimeoutError(TOKEN)))
    with pytest.raises(SnapshotReadFailure) as caught:
        value.execute(ACTOR, request)
    assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None
    assert transport.events.count("FACTORY") == 1 and len(transport.requests) == 1


def test_wrong_peer_still_precedes_authorize_bearer_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    request, result = phase_case("AUTHORIZE")
    transport = connection(
        monkeypatch, canonical_json_bytes(wrapper(result)), expected_timeout=330.0
    )
    monkeypatch.setattr(
        owner_http, "require_fixed_api_peer_socket", Mock(side_effect=ValueError(TOKEN))
    )
    with pytest.raises(SnapshotReadFailure) as caught:
        value.execute(ACTOR, request)
    assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert transport.requests == [] and transport.events == ["FACTORY", "CONNECT", "CLOSE"]
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("path", [owner_http._LOGIN, owner_http._REFRESH, owner_http._METADATA])
def test_authorize_phase_cannot_extend_non_snapshot_http(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    factory = Mock(side_effect=AssertionError("connection must not be created"))
    monkeypatch.setattr(http_client, "HTTPConnection", factory)
    with pytest.raises(ControlPlaneError):
        owner_http._post(path, b"{}", snapshot_phase="AUTHORIZE")
    factory.assert_not_called()


def test_model_copy_unknown_phase_cannot_select_any_transport_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    request = snapshot_prepare().model_copy(update={"phase": "AUTHORIZE"})
    factory = Mock(side_effect=AssertionError("connection must not be created"))
    monkeypatch.setattr(http_client, "HTTPConnection", factory)
    with pytest.raises(SnapshotReadFailure):
        value.execute(ACTOR, request)
    exchange = Mock(side_effect=AssertionError("socket must not be contacted"))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    with pytest.raises(client_module.InferenceTransferSnapshotClientError):
        client_module.CatalogInferenceTransferSnapshotClient().execute(ACTOR, request)
    factory.assert_not_called()
    exchange.assert_not_called()


def test_phase_policy_has_no_optional_adapter_or_infrastructure_dependency() -> None:
    source = Path(__file__).resolve().parents[2] / (
        "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_snapshot_timing.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports <= {"__future__", "dataclasses", "types", "typing"}


def test_comparison_submit_budget_composes_existing_owner_reads_with_one_outer_margin() -> None:
    assert (
        COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS
        == (
            snapshot_phase_deadlines("PREPARE").catalog_response_seconds
            + 2 * snapshot_phase_deadlines("READ").catalog_response_seconds
            + 30.0
        )
        == 390.0
    )
    assert math.isfinite(COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS)
    assert DEFAULT_SNAPSHOT_TIMEOUT_SECONDS == 120.0
    assert snapshot_phase_deadlines("READ").owner_http_seconds == 120.0


@pytest.mark.parametrize("successor", [False, True])
@pytest.mark.parametrize("times_out", [False, True])
def test_actual_submit_both_generations_select_390_only_and_preserve_no_retry(
    monkeypatch: pytest.MonkeyPatch, successor: bool, times_out: bool
) -> None:
    value, calls = comparison_session(monkeypatch)
    legacy = submit_request()
    selected = (
        parse_pair_submit_request_v11(
            rehash(
                legacy.model_dump(mode="json")
                | {"schema_version": "inference-transfer-pair-submit/1.1"},
                "submission_sha256",
            )
        )
        if successor
        else legacy
    )
    expected = command()
    if successor:
        expected = command(status_url=expected.status_url + "/v1.1")
    transport = connection(
        monkeypatch,
        canonical_json_bytes(wrapper(expected)),
        status=202,
        expected_timeout=390.0,
    )
    if times_out:
        monkeypatch.setattr(transport, "getresponse", Mock(side_effect=TimeoutError(TOKEN)))
        with pytest.raises(ControlPlaneError) as caught:
            if successor:
                value.submit_pair_v11(cast(Any, selected), idempotency_key=KEY)
            else:
                value.submit_pair(cast(Any, selected), idempotency_key=KEY)
        assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
        assert TOKEN not in str(caught.value) and caught.value.__cause__ is None
        assert calls == ["ME", "ME"]
    else:
        actual = (
            value.submit_pair_v11(cast(Any, selected), idempotency_key=KEY)
            if successor
            else value.submit_pair(cast(Any, selected), idempotency_key=KEY)
        )
        assert actual == expected and calls == ["ME", "ME", "ME"]
    assert len(transport.requests) == 1
    assert transport.requests[0][:2] == (
        "POST",
        owner_http._COMPARISONS_V11 if successor else owner_http._COMPARISONS,
    )
    assert transport.requests[0][2] == canonical_json_bytes(selected.model_dump(mode="json"))
    assert transport.requests[0][3]["Idempotency-Key"] == KEY
    assert transport.events.count("FACTORY") == 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", owner_http._LOGIN),
        ("POST", owner_http._REFRESH),
        ("POST", owner_http._METADATA),
        ("GET", owner_http._ORIGINAL_CORPUS),
        ("GET", owner_http._EXECUTION_PRESETS),
        ("GET", owner_http._COMPARISON_WORKFLOWS + "workflow_" + "a" * 32 + "?mode=STATUS_ONLY"),
        (
            "GET",
            owner_http._COMPARISON_WORKFLOWS + "workflow_" + "a" * 32 + "/v1.1?mode=STATUS_ONLY",
        ),
    ],
)
def test_other_fixed_http_operations_keep_their_existing_120_budget(
    monkeypatch: pytest.MonkeyPatch, method: Any, path: str
) -> None:
    transport = connection(monkeypatch, b"{}", expected_timeout=120.0)
    assert owner_http._request(
        method, path, b"{}" if method == "POST" else None, bearer=SecretStr(TOKEN)
    ) == (200, {})
    assert len(transport.requests) == 1


@pytest.mark.parametrize("path", [owner_http._COMPARISONS, owner_http._COMPARISONS_V11])
def test_snapshot_phase_override_cannot_change_comparison_submit_budget(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    factory = Mock(side_effect=AssertionError("connection must not be created"))
    monkeypatch.setattr(http_client, "HTTPConnection", factory)
    with pytest.raises(ControlPlaneError):
        owner_http._request(
            "POST",
            path,
            b"{}",
            bearer=SecretStr(TOKEN),
            idempotency_key=KEY,
            snapshot_phase="AUTHORIZE",
        )
    factory.assert_not_called()
