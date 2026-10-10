"""Fake-principal successor API/transport tests; no live session, SQL or model."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_workflow_client import (
    CatalogInferenceTransferWorkflowClient,
)
from eom_api.services.inference_transfer_workflow_read import (
    InferenceTransferWorkflowReadApplicationServiceV11,
    InferenceTransferWorkflowReadError,
)
from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_pair_submit_request_v11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
)
from eom_catalog_contracts.inference_transfer_snapshot import InferenceTransferSnapshotReadRequest
from eom_catalog_contracts.inference_transfer_workflow_binding_v11 import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    parse_workflow_binding_reply_v11,
    parse_workflow_binding_request_v11,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorSource, PermissionKey
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from fastapi import FastAPI

from tests.unit.inference_transfer_api_fixtures import (
    ACTOR_ID,
    PERMISSIONS,
    ApiHarness,
    SnapshotReader,
    authentication,
    harness,
    selection,
)
from tests.unit.inference_transfer_invocation_fixtures import (
    WORKFLOW_ID,
    read_request,
    read_result,
    rehash,
    role_result_document,
)
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_body_v11

SUBMIT = "/api/v1/knowledge/inference-transfer/comparisons/v1.1"
LEGACY_SUBMIT = "/api/v1/knowledge/inference-transfer/comparisons"
READ = f"/api/v1/knowledge/inference-transfer/workflows/{WORKFLOW_ID}/v1.1"
KEY = {"Idempotency-Key": "synthetic-transfer-axes-0001"}


def _selection(
    reader: SnapshotReader, *, reverse: bool = False
) -> InferenceTransferPairSubmitRequestV11:
    body = selection(reader, reverse=reverse).model_dump(mode="json") | {
        "schema_version": "inference-transfer-pair-submit/1.1"
    }
    return parse_pair_submit_request_v11(rehash(body, "submission_sha256"))


def _read_query(mode: str = "CANONICAL_RESULT") -> InferenceTransferWorkflowReadRequestV11:
    body = read_request(mode).model_dump(mode="json") | {
        "schema_version": "inference-transfer-workflow-read-request/1.1"
    }
    return parse_workflow_read_request_v11(rehash(body, "read_sha256"))


def _read_reply(*, verified: bool = True) -> InferenceTransferWorkflowReadResultV11:
    body = read_result(verified=verified).model_dump(mode="json") | {
        "schema_version": "inference-transfer-workflow-read-result/1.1"
    }
    body["result_artifact"]["schema_ref"] = (
        "https://eom.local/schemas/workflow/roles/item-inference-transfer-pair-result-v2.schema.json"
    )
    body["result_artifact"]["sha256"] = content_sha256(
        role_result_document()
        | {"protocol_version": "workflow-role/1.30.0", "output": pair_result_body_v11()}
    )
    if body["result"] is not None:
        body["result"] = pair_result_body_v11()
    return parse_workflow_read_result_v11(rehash(body, "result_sha256"))


class SuccessorReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, InferenceTransferWorkflowReadRequestV11]] = []
        self.failure: str | None = None
        self.reply: Any = None

    def execute_v11(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11:
        self.calls.append((actor_id, request))
        if self.failure is not None:
            raise InferenceTransferWorkflowReadError(self.failure)
        return cast(
            InferenceTransferWorkflowReadResultV11,
            self.reply or _read_reply(verified=request.mode == "CANONICAL_RESULT"),
        )


@contextmanager
def api(reader: SnapshotReader | None = None) -> Iterator[tuple[ApiHarness, SuccessorReader]]:
    value = harness(reader)
    successor = SuccessorReader()
    value.services.inference_transfer_workflow_reads_v11 = (
        InferenceTransferWorkflowReadApplicationServiceV11(successor)
    )
    try:
        with value.client:
            yield value, successor
    finally:
        value.services.engine.dispose()


def test_successor_submit_captures_actual_actor_and_chooses_only_axes_purpose() -> None:
    with api() as (value, _):
        selected = _selection(value.snapshots, reverse=True)
        response = value.client.post(SUBMIT, headers=KEY, json=selected.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["data"]["status_url"] == READ
        submitted, actor, key = value.starter.calls[0]
        wrapper = submitted.workflow_request
        assert isinstance(wrapper, InferenceTransferWorkflowRequestV11)
        assert wrapper.schema_version == "inference-transfer-workflow-request/1.1"
        assert wrapper.execution_preset_key == "item-inference-transfer-comparison-axes"
        assert wrapper.comparison == selected.comparison
        assert wrapper.left_profile.profile_id == selected.comparison.left_profile.profile_id
        assert actor.actor_id == submitted.operator_id == ACTOR_ID
        assert actor.source == ActorSource.APPLICATION_API and actor.permissions == PERMISSIONS
        assert wrapper.requester_permissions_sha256 == content_sha256(
            sorted(permission.value for permission in PERMISSIONS)
        )
        assert key == value.idempotency.submission_key(
            operator_id=ACTOR_ID,
            endpoint_key="inference_transfer_pair_submit_v11",
            raw_key=KEY["Idempotency-Key"],
        )
        reads = [
            query
            for _, query in value.snapshots.calls
            if isinstance(query, InferenceTransferSnapshotReadRequest)
        ]
        assert [query.selected_index_entries[0] for query in reads] == list(
            value.snapshots.prepared.index[:2]
        )
        assert len(reads) == 2 and all(len(query.selected_index_entries) == 1 for query in reads)
        assert {actor_id for actor_id, _ in value.snapshots.calls} == {ACTOR_ID}


def test_cached_successor_replay_reauthorizes_sources_before_claim_and_never_restarts() -> None:
    with api() as (value, _):
        body = _selection(value.snapshots).model_dump(mode="json")
        first = value.client.post(SUBMIT, headers=KEY, json=body)
        replay = value.client.post(SUBMIT, headers=KEY, json=body)
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"] == replay.json()["data"]
        assert len(value.starter.calls) == 1
        assert [query.phase for _, query in value.snapshots.calls] == [
            "PREPARE",
            "READ",
            "READ",
        ] * 2
        assert {endpoint for _, endpoint, _ in value.idempotency.claims} == {
            "inference_transfer_pair_submit_v11"
        }


@pytest.mark.parametrize("revocation", ["SOURCE", "PERMISSION"])
def test_current_revocation_rejects_successor_cached_replay_without_history_rewrite(
    revocation: str,
) -> None:
    with api() as (value, _):
        body = _selection(value.snapshots).model_dump(mode="json")
        assert value.client.post(SUBMIT, headers=KEY, json=body).status_code == 202
        history = dict(value.idempotency.responses)
        if revocation == "SOURCE":
            value.snapshots.failure = "INFERENCE_TRANSFER_FORBIDDEN"
        else:
            value.authentication = authentication(PERMISSIONS - {PermissionKey.ITEM_READ})
        assert value.client.post(SUBMIT, headers=KEY, json=body).status_code == 403
        assert len(value.starter.calls) == len(value.idempotency.claims) == 1
        assert value.idempotency.responses == history and not value.idempotency.failures


@pytest.mark.parametrize("permission", tuple(PERMISSIONS - {PermissionKey.WORKFLOW_READ}))
def test_successor_submit_requires_actual_current_permissions_before_source_read(
    permission: PermissionKey,
) -> None:
    with api() as (value, _):
        value.authentication = authentication(PERMISSIONS - {permission})
        response = value.client.post(
            SUBMIT, headers=KEY, json=_selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 403
        assert (
            not value.snapshots.calls and not value.starter.calls and not value.idempotency.claims
        )


@pytest.mark.parametrize(
    "extra", ["actor_id", "permissions", "requester_role", "execution_preset_key", "left_profile"]
)
def test_successor_public_submission_denies_authority_and_full_profile_fields(extra: str) -> None:
    with api() as (value, _):
        body = rehash(
            _selection(value.snapshots).model_dump(mode="json") | {extra: "ADMIN"},
            "submission_sha256",
        )
        assert value.client.post(SUBMIT, headers=KEY, json=body).status_code == 422
        assert (
            not value.snapshots.calls and not value.starter.calls and not value.idempotency.claims
        )


@pytest.mark.parametrize("new_route", [False, True])
def test_public_submit_routes_do_not_reinterpret_opposite_version(new_route: bool) -> None:
    with api() as (value, _):
        path = SUBMIT if new_route else LEGACY_SUBMIT
        body = selection(value.snapshots) if new_route else _selection(value.snapshots)
        assert (
            value.client.post(path, headers=KEY, json=body.model_dump(mode="json")).status_code
            == 422
        )
        assert (
            not value.snapshots.calls and not value.starter.calls and not value.idempotency.claims
        )


@pytest.mark.parametrize("change", ["HEADER", "PROFILE_REVISION", "PROFILE_HASH"])
def test_successor_submission_does_not_substitute_latest_for_missing_or_changed_pins(
    change: str,
) -> None:
    with api() as (value, _):
        body = _selection(value.snapshots).model_dump(mode="json")
        if change == "HEADER":
            body["expected_header_sha256"] = content_sha256("changed header")
        else:
            key = "profile_revision_id" if change == "PROFILE_REVISION" else "profile_sha256"
            body["comparison"]["left_profile"][key] = (
                "inferenceprofilerev_" + "f" * 32
                if change == "PROFILE_REVISION"
                else content_sha256("changed profile")
            )
            body["comparison"] = rehash(body["comparison"], "request_sha256")
        response = value.client.post(SUBMIT, headers=KEY, json=rehash(body, "submission_sha256"))
        assert response.status_code == 409
        assert response.json()["error_code"] == (
            "INFERENCE_TRANSFER_SNAPSHOT_CHANGED"
            if change == "HEADER"
            else "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID"
        )
        assert (
            len(value.snapshots.calls) == 1
            and not value.starter.calls
            and not value.idempotency.claims
        )


def test_successor_model_copy_bypass_fails_before_read_or_submission() -> None:
    with api() as (value, _):
        selected = _selection(value.snapshots)
        changed = selected.model_copy(
            update={
                "comparison": selected.comparison.model_copy(
                    update={"request_sha256": content_sha256("changed")}
                )
            }
        )
        with pytest.raises(ApiError) as error:
            value.services.inference_transfer_submissions.authorize_submission(
                value.authentication, changed
            )
        assert error.value.error_code == "INFERENCE_TRANSFER_SUBMISSION_INVALID"
        assert not value.snapshots.calls and not value.starter.calls


@pytest.mark.parametrize("must_change", [False, True])
def test_disabled_or_password_change_operator_is_not_successor_capability(
    must_change: bool,
) -> None:
    with api() as (value, successor):
        change = {"must_change_password": True} if must_change else {"status": "DISABLED"}
        value.authentication = replace(
            value.authentication, operator=value.authentication.operator.model_copy(update=change)
        )
        assert (
            value.client.post(
                SUBMIT, headers=KEY, json=_selection(value.snapshots).model_dump(mode="json")
            ).status_code
            == 403
        )
        assert value.client.get(READ).status_code == 403
        assert not value.snapshots.calls and not value.starter.calls and not successor.calls


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_successor_read_passes_current_actual_principal_and_exposes_axes_only_if_verified(
    mode: str,
) -> None:
    with api() as (value, successor):
        response = value.client.get(READ, params={"mode": mode})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["schema_version"] == "inference-transfer-workflow-read-result/1.1"
        assert data["result_state"] == (
            "POINTER_ONLY" if mode == "STATUS_ONLY" else "MEMBER_VERIFIED"
        )
        if mode == "STATUS_ONLY":
            assert data["result"] is None
        else:
            assert [axis["axis"] for axis in data["result"]["axes"]] == [
                "CONCEPT",
                "MATERIAL",
                "CRUX",
            ]
            assert data["result"]["assessment_kind"] == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
        actual_actor, query = successor.calls[0]
        assert actual_actor == ACTOR_ID and query == _read_query(mode)
        assert not value.workflows.calls and not value.idempotency.claims


@pytest.mark.parametrize(
    "permission",
    [
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
    ],
)
def test_successor_result_read_requires_current_content_permissions(
    permission: PermissionKey,
) -> None:
    with api() as (value, successor):
        value.authentication = authentication(PERMISSIONS - {permission})
        assert value.client.get(READ).status_code == 403 and not successor.calls


@pytest.mark.parametrize(
    "change", ["LEGACY", "HASH", "WORKFLOW", "MODE", "AXIS_ORDER", "AXIS_REFERENCE"]
)
def test_successor_result_rejects_legacy_hash_lineage_mode_and_invalid_axes(change: str) -> None:
    with api() as (value, successor):
        result = _read_reply()
        if change == "LEGACY":
            successor.reply = read_result()
        elif change == "HASH":
            successor.reply = result.model_copy(update={"result_sha256": content_sha256("changed")})
        elif change == "MODE":
            successor.reply = _read_reply(verified=False)
        else:
            body = result.model_dump(mode="json")
            if change == "WORKFLOW":
                body["workflow_id"] = "workflow_" + "f" * 32
            elif change == "AXIS_ORDER":
                body["result"]["axes"].reverse()
            else:
                body["result"]["axes"][0]["left_claim_ids"] = ["transferclaim_absent"]
            if change != "WORKFLOW":
                body["result"] = rehash(body["result"], "result_sha256")
                nested = result.result
                assert nested is not None
                axes = list(nested.axes)
                if change == "AXIS_ORDER":
                    axes.reverse()
                else:
                    axes[0] = axes[0].model_copy(
                        update={"left_claim_ids": ("transferclaim_absent",)}
                    )
                copied = nested.model_copy(
                    update={
                        "axes": tuple(axes),
                        "result_sha256": body["result"]["result_sha256"],
                    }
                )
                successor.reply = result.model_copy(
                    update={
                        "result": copied,
                        "result_sha256": rehash(body, "result_sha256")["result_sha256"],
                    }
                )
            else:
                successor.reply = parse_workflow_read_result_v11(rehash(body, "result_sha256"))
        response = value.client.get(READ, params={"mode": "CANONICAL_RESULT"})
        assert response.status_code == 503
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_RESULT_INVALID"
        assert len(successor.calls) == 1


@pytest.mark.parametrize(
    "code,status",
    [
        ("INFERENCE_TRANSFER_FORBIDDEN", 403),
        ("INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND", 404),
        ("INFERENCE_TRANSFER_WORKFLOW_CHANGED", 409),
        ("INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID", 422),
        ("INFERENCE_TRANSFER_RESULT_INVALID", 503),
        ("PRIVATE_SQL_TRACEBACK", 503),
    ],
)
def test_successor_owner_read_denials_are_closed_safe_and_not_automatically_retried(
    code: str, status: int
) -> None:
    with api() as (value, successor):
        successor.failure = code
        response = value.client.get(READ)
        assert response.status_code == status
        assert response.json()["error_code"] == (
            "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE" if code == "PRIVATE_SQL_TRACEBACK" else code
        )
        assert code != "PRIVATE_SQL_TRACEBACK" or code not in response.text
        assert len(successor.calls) == 1


def test_successor_openapi_has_separate_operations_but_no_public_authority() -> None:
    with api() as (value, _):
        document = cast(FastAPI, value.client.app).openapi()
        submitted = document["paths"][SUBMIT]["post"]
        read = document["paths"][
            "/api/v1/knowledge/inference-transfer/workflows/{workflow_id}/v1.1"
        ]["get"]
        assert submitted["operationId"] == "inference_transfer_pair_submit_v11"
        assert submitted["x-eom-permission"] == PermissionKey.WORKFLOW_START.value
        assert read["x-eom-permission"] == PermissionKey.WORKFLOW_READ.value
        assert read["x-eom-read-only"] is True
        fields = document["components"]["schemas"]["InferenceTransferPairSubmitRequestV11"][
            "properties"
        ]
        assert not {
            "actor_id",
            "role",
            "permissions",
            "left_profile",
            "execution_preset_key",
        }.intersection(fields)


class SuccessorExchange:
    def __init__(self) -> None:
        self.calls: list[tuple[ChatSocketEndpoint, dict[str, object], dict[str, Any]]] = []
        self.patch: dict[str, Any] = {}
        self.failure: Exception | None = None

    def __call__(
        self, endpoint: ChatSocketEndpoint, body: dict[str, object], **settings: Any
    ) -> dict[str, object]:
        self.calls.append((endpoint, body, settings))
        if self.failure is not None:
            raise self.failure
        query = parse_workflow_binding_request_v11(body)
        reply = {
            "schema_version": "inference-transfer-workflow-binding-reply/1.1",
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "actor_id": query.actor_id,
            "request_binding_sha256": query.binding_sha256,
            "status": "SUCCESS",
            "result": _read_reply(verified=query.request.mode == "CANONICAL_RESULT").model_dump(
                mode="json"
            ),
            "error_code": None,
        }
        reply.update(self.patch)
        return rehash(reply, "reply_sha256")


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> SuccessorExchange:
    value = SuccessorExchange()
    prefix = "eom_api.services.inference_transfer_workflow_client"
    monkeypatch.setattr(prefix + ".exchange_chat_frame", value)
    monkeypatch.setattr(prefix + ".pwd.getpwnam", lambda name: SimpleNamespace(pw_uid=701))
    monkeypatch.setattr(prefix + ".grp.getgrnam", lambda name: SimpleNamespace(gr_gid=702))
    return value


def test_successor_private_client_uses_same_fixed_peer_and_closed_actor_request(
    exchange: SuccessorExchange,
) -> None:
    query = _read_query()
    actual = CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, query)
    assert actual == _read_reply()
    endpoint, body, settings = exchange.calls[0]
    assert endpoint == ChatSocketEndpoint(Path(CATALOG_APPLICATION_SOCKET_PATH), 701, 702)
    assert settings == {
        "request_limit": MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
        "reply_limit": MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
        "timeout": 120.0,
    }
    binding = parse_workflow_binding_request_v11(body)
    assert binding.actor_id == ACTOR_ID and binding.request == query
    assert set(body) == {"schema_version", "operation", "actor_id", "request", "binding_sha256"}


@pytest.mark.parametrize(
    "patch,code",
    [
        (
            {"schema_version": "inference-transfer-workflow-binding-reply/1.0"},
            "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE",
        ),
        ({"operation": "INFERENCE_TRANSFER_SNAPSHOT"}, "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"),
        ({"actor_id": "operator_" + "f" * 32}, "INFERENCE_TRANSFER_RESULT_INVALID"),
        (
            {"request_binding_sha256": content_sha256("foreign request")},
            "INFERENCE_TRANSFER_RESULT_INVALID",
        ),
        ({"error_detail": "synthetic private detail"}, "INFERENCE_TRANSFER_RESULT_INVALID"),
    ],
)
def test_successor_private_client_rejects_opposite_schema_or_foreign_context(
    exchange: SuccessorExchange, patch: dict[str, Any], code: str
) -> None:
    exchange.patch = patch
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, _read_query())
    assert error.value.code == code and len(exchange.calls) == 1


@pytest.mark.parametrize(
    "failure", [ChatTransportError("UNAVAILABLE"), OSError("synthetic socket failure")]
)
def test_successor_transport_failure_never_retries_or_uses_another_peer(
    exchange: SuccessorExchange, failure: Exception
) -> None:
    exchange.failure = failure
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, _read_query())
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
    assert len(exchange.calls) == 1


def test_successor_private_failure_without_parseable_context_is_safe_denial(
    exchange: SuccessorExchange,
) -> None:
    exchange.patch = {
        "actor_id": None,
        "request_binding_sha256": None,
        "status": "FAILED",
        "result": None,
        "error_code": "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
    }
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, _read_query())
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
    assert len(exchange.calls) == 1


def test_successor_private_request_tampering_never_reaches_transport(
    exchange: SuccessorExchange,
) -> None:
    changed = _read_query().model_copy(update={"read_sha256": content_sha256("changed")})
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, changed)
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID" and not exchange.calls


def test_successor_private_reply_parser_preserves_axes_in_frozen_result(
    exchange: SuccessorExchange,
) -> None:
    CatalogInferenceTransferWorkflowClient().execute_v11(ACTOR_ID, _read_query())
    endpoint, body, settings = exchange.calls[0]
    reply = parse_workflow_binding_reply_v11(exchange(endpoint, body, **settings))
    assert reply.result is not None and reply.result.result is not None
    assert tuple(axis.axis for axis in reply.result.result.axes) == (
        "CONCEPT",
        "MATERIAL",
        "CRUX",
    )
