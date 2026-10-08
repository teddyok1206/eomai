from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.chat_knowledge_query_adapter import candidate_statement
from eom_api.services.chat_knowledge_service import ChatKnowledgeApplicationService
from eom_api_contracts.chat_knowledge import (
    ChatItemCard,
    ChatKnowledgeRequest,
    ChatKnowledgeSelection,
)
from eom_api_contracts.items import ItemApprovalView
from eom_operator_identity import PermissionKey
from eom_web_gui.chat_knowledge_contracts import (
    ChatKnowledgeRequest as WebRequest,
)
from eom_web_gui.chat_knowledge_contracts import (
    ChatKnowledgeSelection as WebSelection,
)
from fastapi import Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64
REFERENCE = {
    "item_id": "item_" + "1" * 32,
    "item_revision_id": "itemrev_" + "2" * 32,
    "manifest_sha256": HASH,
}
SNAPSHOT = {"graph_snapshot_revision_id": "graphrev_" + "3" * 32, "snapshot_sha256": HASH}
EXAM = {
    "kind": "EXAM",
    "administration_year": 2025,
    "administration_month": 6,
    "target_school_level": "HIGH_SCHOOL",
    "target_grade": 1,
    "subject_key": "integrated-science",
    "item_number": 17,
}


def selection() -> ChatKnowledgeSelection:
    return ChatKnowledgeSelection(
        values=(
            ChatItemCard(
                **REFERENCE,
                revision_number=1,
                display_name="표만 있는 문항",
                created_at=datetime(2026, 10, 8, tzinfo=UTC),
                approval=ItemApprovalView(status="PENDING", human_review_required=True),
                source_kind="GENERATED",
                graph_membership="NOT_INDEXED",
                exam=None,
            ),
        ),
        snapshot=SNAPSHOT,
        truncated=False,
    )


class Reader:
    def __init__(self) -> None:
        self.calls: list[ChatKnowledgeRequest] = []

    def search(self, request: ChatKnowledgeRequest) -> ChatKnowledgeSelection:
        self.calls.append(request)
        return selection()


@pytest.mark.parametrize(
    "query",
    [
        {"kind": "RECENT"},
        {"kind": "RECENT", "source": "GENERATED"},
        EXAM,
        {"kind": "TOPIC", "terms": ["전자기", "유도"], "source": "PAST_EXAM"},
        {"kind": "EXACT", "references": [REFERENCE]},
    ],
)
def test_schema_api_web_request_parity_and_closed_fields(query):
    canonical = ROOT / "schemas/api/v1/chat-knowledge-v1.schema.json"
    packaged = (
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/chat-knowledge-v1.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    value = {"query": query, "snapshot": SNAPSHOT}
    api = ChatKnowledgeRequest.model_validate(value).model_dump(mode="json")
    web = WebRequest.model_validate(value).model_dump(mode="json")
    assert api == web
    validator.validate(api)
    answer = selection().model_dump(mode="json")
    validator.validate(answer)
    assert WebSelection.model_validate(answer).model_dump(mode="json") == answer
    for extra in (
        "actor_id",
        "permissions",
        "policy_id",
        "artifact_member",
        "sql",
        "native_thread_id",
    ):
        bad = value | {extra: "untrusted"}
        assert not validator.is_valid(bad)
        with pytest.raises(ValidationError):
            ChatKnowledgeRequest.model_validate(bad)
        with pytest.raises(ValidationError):
            WebRequest.model_validate(bad)


@pytest.mark.parametrize(
    "body",
    [
        {"query": {"kind": "RECENT"}, "limit": 21},
        {"query": {"kind": "TOPIC", "terms": ["전자기"] * 9}},
        {"query": {"kind": "TOPIC", "terms": ["전자기", "전자기"]}},
        {"query": {"kind": "TOPIC", "terms": ["../../private"]}},
        {"query": {"kind": "TOPIC", "terms": ["x"]}},
        {"query": EXAM | {"target_grade": 4}},
        {"query": {"kind": "EXACT", "references": [REFERENCE, REFERENCE]}},
        {"query": {"kind": "EXACT", "references": [REFERENCE | {"item_revision_id": "latest"}]}},
        {"query": {"kind": "RECENT"}, "snapshot": SNAPSHOT | {"snapshot_sha256": "latest"}},
    ],
)
def test_invalid_inputs_rejected_by_both_models(body):
    for model in (ChatKnowledgeRequest, WebRequest):
        with pytest.raises(ValidationError):
            model.model_validate(body)
    validator = Draft202012Validator(
        json.loads((ROOT / "schemas/api/v1/chat-knowledge-v1.schema.json").read_text())
    )
    assert not validator.is_valid(body)


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot": None},
        {"model_calls": 1},
        {"values": [selection().values[0].model_dump(mode="json")] * 2},
    ],
)
def test_no_fake_graph_or_model_claims_or_duplicate_cards(change):
    value = selection().model_dump(mode="json") | change
    for model in (ChatKnowledgeSelection, WebSelection):
        with pytest.raises(ValidationError):
            model.model_validate(value)


@pytest.mark.parametrize(
    "permissions, expected",
    [
        (frozenset(), 403),
        (frozenset({PermissionKey.GENERAL_CHAT_READ}), 403),
        (frozenset({PermissionKey.ITEM_READ}), 403),
        (frozenset({PermissionKey.ITEM_READ, PermissionKey.GENERAL_CHAT_READ}), 200),
    ],
)
def test_search_requires_both_permissions_and_never_resolves_native_owner(permissions, expected):
    services = disconnected_services()
    services.audit = FakeAudit()  # type: ignore[assignment]
    reader = Reader()
    services.chat_knowledge = ChatKnowledgeApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = replace(_authentication(), permissions=permissions)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/general-chat/knowledge/search", json={"query": {"kind": "RECENT"}}
            )
            assert response.status_code == expected
            assert len(reader.calls) == (1 if expected == 200 else 0)
            if expected == 200:
                assert response.json()["model_calls"] == 0
            metadata = app.openapi()["paths"]["/api/v1/general-chat/knowledge/search"]["post"]
            assert metadata["x-eom-permission"] == PermissionKey.GENERAL_CHAT_READ.value
            assert metadata["x-eom-additional-permissions"] == [PermissionKey.ITEM_READ.value]
            assert metadata["x-eom-fresh-auth"] is False
    finally:
        services.engine.dispose()


def test_application_permission_guard_is_not_just_ui():
    reader = Reader()
    with pytest.raises(ApiError) as failure:
        ChatKnowledgeApplicationService(reader).search(
            ChatKnowledgeRequest(query={"kind": "RECENT"}), frozenset()
        )
    assert failure.value.status == 403
    assert reader.calls == []


@pytest.mark.parametrize(
    "query",
    [
        {"kind": "RECENT"},
        EXAM,
        {"kind": "TOPIC", "terms": ["전자기"]},
        {"kind": "EXACT", "references": [REFERENCE]},
    ],
)
def test_query_is_bounded_and_filters_before_limit_with_existing_index_keys(query):
    request = ChatKnowledgeRequest(query=query, limit=5)
    statement = candidate_statement(request, SNAPSHOT["graph_snapshot_revision_id"])
    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    sql = str(compiled)
    assert "items.lifecycle_state = 'ACTIVE'" in sql
    assert "item_revisions.revision_state IN ('IN_REVIEW', 'APPROVED')" in sql
    assert "LIMIT 6" in sql
    assert "OFFSET" not in sql and " LIKE " not in sql and "ILIKE" not in sql
    if query["kind"] in {"TOPIC", "EXAM"}:
        assert SNAPSHOT["graph_snapshot_revision_id"] in sql
    if query["kind"] == "TOPIC":
        assert "knowledge_node_terms.term IN" in sql
        assert "source_class IN ('PAST_EXAM', 'APPROVED_ITEM')" in sql
        assert "TEXTBOOK" not in sql
    if query["kind"] == "EXACT":
        assert REFERENCE["item_revision_id"] in sql
        assert "item_revisions.item_revision_id = items.current_revision_id" not in sql


@pytest.mark.parametrize("kind", ["RECENT", "TOPIC"])
def test_generated_filter_uses_canonical_internal_origin_before_top_k(kind):
    query = {"kind": kind, "source": "GENERATED"}
    if kind == "TOPIC":
        query["terms"] = ["전자기"]
    sql = str(
        candidate_statement(
            ChatKnowledgeRequest(query=query), SNAPSHOT["graph_snapshot_revision_id"]
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "item_origin_profiles.source_domain = 'INTERNAL_EOM'" in sql
    assert sql.index("item_origin_profiles.source_domain") < sql.index("LIMIT")
