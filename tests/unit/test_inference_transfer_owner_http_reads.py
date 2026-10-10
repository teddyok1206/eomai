"""Fake official metadata reads only; no installed, authenticated or corpus acceptance."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api_contracts.assessment_learning import AssessmentLearningCorpusViewV2
from eom_api_contracts.auth import CurrentOperator
from eom_api_contracts.common import ListResponse
from eom_api_contracts.control_plane import ExecutionPresetView
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import SecretStr

from tests.unit.test_inference_transfer_owner_http import (
    ACTOR,
    SESSION,
    TOKEN,
    connection,
    principal,
    wrapper,
)

PERMISSIONS = (
    PermissionKey.EXECUTION_PRESET_READ.value,
    PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
)


def corpus() -> AssessmentLearningCorpusViewV2:
    now = datetime.now(UTC)
    return AssessmentLearningCorpusViewV2(
        corpus_id="corpus_" + "c" * 32,
        corpus_revision_id="corpusrev_" + "d" * 32,
        display_name="합성 기출 corpus",
        graph_snapshot_revision_id="graphrev_" + "e" * 32,
        graph_snapshot_sha256="sha256:" + "f" * 64,
        graph_revision_number=3,
        source_pdf_count=50,
        exam_count=25,
        approved_item_count=520,
        solution_report_total_count=520,
        solution_report_completed_count=520,
        solution_report_active_count=0,
        solution_report_failed_count=0,
        solution_report_pending_count=0,
        solution_report_status="COMPLETED",
        solution_report_updated_at=now,
        updated_at=now,
    )


def presets() -> ListResponse[ExecutionPresetView]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    revision: dict[str, Any] = {
        "schema_version": "execution-preset-revision/2.0",
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "preset_id": "execpreset_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "합성 설정",
        "description": "순서와 exact pins 보존 검증용",
        "capacity_policy_revision_id": "capacityrev_" + "3" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.28.0"],
        "content_sha256": "sha256:" + "4" * 64,
        "created_at": now,
        "role_policies": [],
        "retrieval_policy": {
            "access_policy_revision_id": "accessrev_" + "5" * 32,
            "access_policy_sha256": "sha256:" + "6" * 64,
            "allowed_corpus_keys": ["past-exams"],
            "allowed_query_kinds": ["ITEM_PREPARATION"],
            "allowed_source_classes": ["PAST_EXAM"],
            "maximum_budget": {
                "max_documents": 8,
                "max_item_revisions": 8,
                "max_graph_nodes": 64,
                "max_claims": 32,
                "max_context_tokens": 8000,
            },
        },
        "evaluations": [],
    }
    newer_draft = revision | {
        "preset_revision_id": "execpresetrev_" + "7" * 32,
        "revision_number": 2,
        "state": "DRAFT",
        "capacity_policy_revision_id": "capacityrev_" + "8" * 32,
    }
    return ListResponse[ExecutionPresetView].model_validate(
        {
            "data": [
                {
                    "preset_id": revision["preset_id"],
                    "preset_key": "synthetic-past-exams",
                    "current_revision_id": revision["preset_revision_id"],
                    "state": "ACTIVE",
                    "created_at": now,
                    "updated_at": now,
                    "revisions": [newer_draft, revision],
                }
            ],
            "page": {"next_cursor": "synthetic-cursor", "has_more": True, "limit": 1},
            "meta": {"request_id": "synthetic-presets", "api_version": "1"},
        }
    )


def read_session(
    monkeypatch: pytest.MonkeyPatch, values: tuple[CurrentOperator, ...] | None = None
) -> tuple[http.AuthenticatedInferenceTransferHttpSession, list[str]]:
    values = values or (principal(effective_permissions=PERMISSIONS),)
    calls: list[str] = []

    def read() -> CurrentOperator:
        index = min(len(calls), len(values) - 1)
        calls.append("ME")
        return values[index]

    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=read)
    )
    return http.AuthenticatedInferenceTransferHttpSession.from_bearer(SecretStr(TOKEN)), calls


@pytest.mark.parametrize("path", [http._ORIGINAL_CORPUS, http._EXECUTION_PRESETS])
def test_fixed_get_peer_is_verified_before_bearer_and_no_body(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    transport = connection(monkeypatch, b"{}")
    assert http._get(path, bearer=SecretStr(TOKEN)) == (200, {})
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]
    method, target, body, headers = transport.requests[0]
    assert (method, target) == ("GET", path)
    assert body is None
    assert headers == {
        "Accept": "application/json",
        "Connection": "close",
        "Authorization": "Bearer " + TOKEN,
    }


def test_wrong_get_peer_never_sends_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = connection(monkeypatch, b"{}")
    monkeypatch.setattr(
        http,
        "require_fixed_api_peer_socket",
        lambda _sock: (_ for _ in ()).throw(ValueError(TOKEN)),
    )
    with pytest.raises(ControlPlaneError) as caught:
        http._get(http._ORIGINAL_CORPUS, bearer=SecretStr(TOKEN))
    assert transport.requests == [] and transport.events == ["FACTORY", "CONNECT", "CLOSE"]
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", http._LOGIN, None),
        ("POST", http._ORIGINAL_CORPUS, b"{}"),
        ("GET", http._EXECUTION_PRESETS + "?limit=200", None),
        ("GET", "http://attacker.example/api/v1/execution-presets", None),
        ("GET", http._ORIGINAL_CORPUS, b"{}"),
    ],
)
def test_method_path_and_body_are_closed_before_connect(
    monkeypatch: pytest.MonkeyPatch, method: Any, path: str, body: bytes | None
) -> None:
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError):
        http._request(method, path, body, bearer=SecretStr(TOKEN))
    assert transport.events == []


def test_original_corpus_preserves_exact_graph_and_rechecks_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = read_session(monkeypatch)
    expected = corpus()
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(expected)))
    assert value.read_original_corpus() == expected
    assert calls == ["ME", "ME", "ME"]
    assert transport.requests[0][:2] == ("GET", http._ORIGINAL_CORPUS)
    assert len(transport.requests) == 1


def test_presets_preserve_list_page_and_nonlatest_current_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = read_session(monkeypatch)
    expected = presets()
    transport = connection(monkeypatch, canonical_json_bytes(expected.model_dump(mode="json")))
    result = value.read_execution_presets()
    assert result == expected and result.page.has_more
    assert result.data[0].current_revision_id == result.data[0].revisions[1].preset_revision_id
    assert result.data[0].revisions[0].state == "DRAFT"
    assert (
        result.data[0].revisions[1].retrieval_policy
        == expected.data[0].revisions[1].retrieval_policy
    )
    assert calls == ["ME", "ME", "ME"]
    assert transport.requests[0][:2] == ("GET", http._EXECUTION_PRESETS)


@pytest.mark.parametrize("operation", ["read_original_corpus", "read_execution_presets"])
@pytest.mark.parametrize("changes", [{"roles": ["WORKER"]}, {"effective_permissions": []}])
def test_role_or_permission_absence_denies_before_get(
    monkeypatch: pytest.MonkeyPatch, operation: str, changes: dict[str, Any]
) -> None:
    value, _ = read_session(monkeypatch, (principal(**changes),))
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError) as caught:
        getattr(value, operation)()
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert transport.events == []


@pytest.mark.parametrize("operation", ["read_original_corpus", "read_execution_presets"])
@pytest.mark.parametrize(
    "changes",
    [
        {"roles": ["REVIEWER"]},
        {"effective_permissions": []},
        {"operator_id": ACTOR.replace("a", "c")},
        {"session_id": SESSION.replace("b", "c")},
        {"password_change_required": True},
    ],
)
def test_post_read_revocation_or_replacement_never_returns_pins(
    monkeypatch: pytest.MonkeyPatch, operation: str, changes: dict[str, Any]
) -> None:
    good = principal(effective_permissions=PERMISSIONS)
    revoked = (
        principal(effective_permissions=PERMISSIONS, **changes)
        if ("effective_permissions" not in changes)
        else principal(**changes)
    )
    value, calls = read_session(monkeypatch, (good, good, revoked))
    raw = (
        wrapper(corpus())
        if operation == "read_original_corpus"
        else presets().model_dump(mode="json")
    )
    transport = connection(monkeypatch, canonical_json_bytes(raw))
    with pytest.raises(ControlPlaneError) as caught:
        getattr(value, operation)()
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert calls == ["ME", "ME", "ME"] and len(transport.requests) == 1


@pytest.mark.parametrize("operation", ["read_original_corpus", "read_execution_presets"])
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_failed_status_is_secret_safe_and_never_redirects_refreshes_or_retries(
    monkeypatch: pytest.MonkeyPatch, operation: str, status: int
) -> None:
    value, calls = read_session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes({"detail": TOKEN}), status=status)
    with pytest.raises(ControlPlaneError) as caught:
        getattr(value, operation)()
    assert caught.value.code == (
        "CONTROL_AUTHORIZATION_REQUIRED"
        if status in {401, 403}
        else "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    )
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None
    assert len(transport.requests) == 1 and calls == ["ME", "ME"]


def corpus_extra_authority(raw: dict[str, Any]) -> None:
    raw["data"]["actor_id"] = ACTOR


def corpus_old_schema(raw: dict[str, Any]) -> None:
    raw["data"]["schema_version"] = "assessment-learning-corpus-view/1.0"


def corpus_incoherent_partition(raw: dict[str, Any]) -> None:
    raw["data"]["solution_report_completed_count"] = 519


@pytest.mark.parametrize(
    "change", [corpus_extra_authority, corpus_old_schema, corpus_incoherent_partition]
)
def test_official_corpus_json_schema_and_typed_semantics_both_apply(
    monkeypatch: pytest.MonkeyPatch, change: Callable[[dict[str, Any]], None]
) -> None:
    value, _ = read_session(monkeypatch)
    raw = wrapper(corpus())
    change(raw)
    connection(monkeypatch, canonical_json_bytes(raw))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_original_corpus()
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"


def test_preset_reply_does_not_accept_caller_authority_or_missing_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = read_session(monkeypatch)
    raw = presets().model_dump(mode="json")
    raw["data"][0]["authority"] = "ADMIN"
    connection(monkeypatch, canonical_json_bytes(raw))
    with pytest.raises(ControlPlaneError):
        value.read_execution_presets()
    raw = presets().model_dump(mode="json")
    del raw["page"]
    connection(monkeypatch, canonical_json_bytes(raw))
    with pytest.raises(ControlPlaneError):
        value.read_execution_presets()


@pytest.mark.parametrize("payload", [b"", b'{"data":1,"data":2}', b'{"data":NaN}', b"\xff"])
def test_get_response_is_strict_bounded_json(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    value, _ = read_session(monkeypatch)
    transport = connection(monkeypatch, payload)
    with pytest.raises(ControlPlaneError):
        value.read_original_corpus()
    assert len(transport.requests) == 1


def test_get_response_bound_and_media_type_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = read_session(monkeypatch)
    monkeypatch.setattr(http, "_MAX_ENVELOPE_BYTES", 64)
    connection(monkeypatch, b"x" * 65)
    with pytest.raises(ControlPlaneError):
        value.read_execution_presets()
    connection(monkeypatch, b"{}", media="text/html")
    with pytest.raises(ControlPlaneError):
        value.read_original_corpus()
