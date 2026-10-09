from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.general_chat_service import GeneralChatApplicationService
from eom_api_contracts.general_chat import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatMessage,
    GeneralChatSlot,
    GeneralChatSubmission,
)
from eom_operator_identity import ROLE_PERMISSIONS, PermissionKey, RoleKey
from eom_protocol.general_chat_grounding import ChatGroundingViews, GroundedChatSubmission
from eom_protocol.general_chat_owner_messages import ChatOwnerErrorCode, ChatOwnerFault
from eom_web_gui.general_chat_contracts import (
    ChatConversation,
    ChatCreate,
    ChatList,
    ChatSlot,
    ChatSubmission,
)
from fastapi import Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit

NOW = datetime(2026, 10, 7, tzinfo=UTC)
CHAT_ID = "chat_" + "2" * 32
ROOT = Path(__file__).resolve().parents[2]


def conversation() -> GeneralChatConversation:
    return GeneralChatConversation(
        conversation_id=CHAT_ID, title="안녕하세요", resource_version=1, updated_at=NOW
    )


class Owner:
    def __init__(self) -> None:
        self.actors: list[str] = []

    def slot(self) -> GeneralChatSlot:
        return GeneralChatSlot(state="READY")

    def conversations(self, *, actor_id: str, cursor: str | None) -> GeneralChatList:
        self.actors.append(actor_id)
        return GeneralChatList(values=())

    def create(
        self, *, actor_id: str, request: GeneralChatCreate, idempotency_key: str
    ) -> GeneralChatConversation:
        self.actors.append(actor_id)
        assert idempotency_key == "chat-create-test-0001"
        return conversation()

    def conversation(
        self, *, actor_id: str, conversation_id: str, cursor: str | None
    ) -> GeneralChatConversation:
        self.actors.append(actor_id)
        if conversation_id != CHAT_ID:
            raise ApiError(404, "GENERAL_CHAT_NOT_FOUND", "Not found", "Conversation unavailable")
        return conversation()

    def submit(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        self.actors.append(actor_id)
        assert conversation_id == CHAT_ID
        return conversation()

    def grounding(
        self, *, actor_id: str, conversation_id: str, turn_ids: tuple[str, ...]
    ) -> ChatGroundingViews:
        self.actors.append(actor_id)
        assert conversation_id == CHAT_ID
        assert turn_ids == ("chatturn_" + "1" * 32,)
        return ChatGroundingViews(conversation_id=conversation_id, values=())


def client(*, enabled: bool = False, allowed: bool = True):
    services = disconnected_services()
    services.audit = FakeAudit()  # type: ignore[assignment]
    owner = Owner()
    services.general_chat = GeneralChatApplicationService(owner if enabled else None)
    app = create_app(services)

    def authenticated(request: Request):
        permissions = (
            frozenset({PermissionKey.GENERAL_CHAT_READ, PermissionKey.GENERAL_CHAT_WRITE})
            if allowed
            else frozenset()
        )
        value = replace(_authentication(), permissions=permissions)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, owner


def test_not_activated_never_reports_ready_or_accepts_inference():
    value, services, _ = client()
    try:
        with value:
            slot = value.get("/api/v1/general-chat/slot")
            assert slot.status_code == 200
            assert slot.json()["state"] == "UNAVAILABLE"
            assert slot.json()["slot_key"] == "chat"
            response = value.post(
                "/api/v1/general-chat/conversations",
                json={"title": "새 대화"},
                headers={"Idempotency-Key": "chat-create-test-0001"},
            )
            assert response.status_code == 503
            assert response.json()["error_code"] == "GENERAL_CHAT_NOT_READY"
    finally:
        services.engine.dispose()


def test_grounded_submission_and_read_only_sources_use_authenticated_owner():
    value, services, owner = client(enabled=True)
    try:
        with value:
            submitted = value.post(
                f"/api/v1/general-chat/conversations/{CHAT_ID}/grounded-turns",
                json=GroundedChatSubmission(
                    text="시스템을 설명해주세요", expected_version=1, selection=None
                ).model_dump(mode="json"),
                headers={"Idempotency-Key": "chat-create-test-0001"},
            )
            assert submitted.status_code == 202
            viewed = value.post(
                f"/api/v1/general-chat/conversations/{CHAT_ID}/grounding",
                json={"turn_ids": ["chatturn_" + "1" * 32]},
            )
            assert viewed.status_code == 200
            assert viewed.json() == {"conversation_id": CHAT_ID, "values": []}
            assert len(owner.actors) == 2
            assert (
                value.post(
                    f"/api/v1/general-chat/conversations/{CHAT_ID}/grounding",
                    json={"turn_ids": ["bad"], "actor_id": "foreign"},
                ).status_code
                == 422
            )
    finally:
        services.engine.dispose()


def test_grounded_routes_reject_missing_permissions():
    value, services, _ = client(enabled=True, allowed=False)
    try:
        with value:
            assert (
                value.post(
                    f"/api/v1/general-chat/conversations/{CHAT_ID}/grounded-turns",
                    json={"text": "질문", "expected_version": 1, "selection": None},
                    headers={"Idempotency-Key": "chat-create-test-0001"},
                ).status_code
                == 403
            )
            assert (
                value.post(
                    f"/api/v1/general-chat/conversations/{CHAT_ID}/grounding",
                    json={"turn_ids": ["chatturn_" + "1" * 32]},
                ).status_code
                == 403
            )
    finally:
        services.engine.dispose()


def test_textbook_grounding_is_a_document_reference_not_a_fake_item_link(monkeypatch):
    from eom_protocol.general_chat_rag_turn import (
        ChatGroundingViewsV2,
        ChatRagSourceCard,
        ChatTurnGroundingViewV2,
        validate_rag_citations,
    )

    from tests.unit.general_chat_rag_fixtures import context, request, result

    value, services, owner = client(enabled=True)
    prepared = request(knowledge=context())
    receipt = validate_rag_citations(prepared, result(prepared), item=None, rag=context())
    view = ChatGroundingViewsV2(
        conversation_id=CHAT_ID,
        values=(
            ChatTurnGroundingViewV2(
                turn_id="chatturn_" + "1" * 32,
                sources=(
                    ChatRagSourceCard.model_validate(
                        context().sources[0].model_dump(mode="json", exclude={"text"})
                    ),
                ),
                receipt=receipt,
                observed_at=None,
            ),
        ),
    )

    def projected(*, actor_id, **_):
        owner.actors.append(actor_id)
        return view

    monkeypatch.setattr(owner, "grounding", projected)
    try:
        with value:
            response = value.post(
                f"/api/v1/general-chat/conversations/{CHAT_ID}/grounding",
                json={"turn_ids": ["chatturn_" + "1" * 32]},
            )
            assert response.status_code == 200
            assert response.json() == view.model_dump(mode="json")
            card = response.json()["values"][0]["sources"][0]
            assert card["kind"] == "RAG_ANALYSIS" and "item" not in card
            assert card["reference"]["source"]["source_class"] == "TEXTBOOK"
            assert card["text_kind"] == "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
            assert owner.actors == [_authentication().operator.operator_id]
    finally:
        services.engine.dispose()


def test_all_routes_use_authenticated_operator_and_have_separate_permissions():
    value, services, owner = client(enabled=True)
    try:
        with value:
            assert value.get("/api/v1/general-chat/conversations").status_code == 200
            assert value.get(f"/api/v1/general-chat/conversations/{CHAT_ID}").status_code == 200
            assert (
                value.post(
                    "/api/v1/general-chat/conversations",
                    json={"title": "대화"},
                    headers={"Idempotency-Key": "chat-create-test-0001"},
                ).status_code
                == 201
            )
            assert (
                value.post(
                    f"/api/v1/general-chat/conversations/{CHAT_ID}/turns",
                    json={"text": "질문", "expected_version": 1},
                    headers={"Idempotency-Key": "chat-create-test-0001"},
                ).status_code
                == 202
            )
            assert value.get("/api/v1/general-chat/conversations/invalid").status_code == 422
            missing = "chat_" + "f" * 32
            assert value.get(f"/api/v1/general-chat/conversations/{missing}").status_code == 404
        assert set(owner.actors) == {"operator_" + "1" * 32}
        for role in RoleKey:
            assert {
                PermissionKey.GENERAL_CHAT_READ,
                PermissionKey.GENERAL_CHAT_WRITE,
            } <= ROLE_PERMISSIONS[role]
    finally:
        services.engine.dispose()


def test_permission_denied_before_owner_resolution():
    value, services, owner = client(enabled=True, allowed=False)
    try:
        with value:
            assert value.get("/api/v1/general-chat/conversations").status_code == 403
            assert (
                value.post(
                    "/api/v1/general-chat/conversations",
                    json={"title": "대화"},
                    headers={"Idempotency-Key": "chat-create-test-0001"},
                ).status_code
                == 403
            )
        assert not owner.actors
    finally:
        services.engine.dispose()


@pytest.mark.parametrize(
    "code, status",
    [
        (ChatOwnerErrorCode.FORBIDDEN, 403),
        (ChatOwnerErrorCode.NOT_FOUND, 404),
        (ChatOwnerErrorCode.IDEMPOTENCY_INVALID, 400),
        (ChatOwnerErrorCode.IDEMPOTENCY_CONFLICT, 409),
        (ChatOwnerErrorCode.STALE_REVISION, 409),
        (ChatOwnerErrorCode.TURN_IN_PROGRESS, 409),
        (ChatOwnerErrorCode.CURSOR_INVALID, 400),
        (ChatOwnerErrorCode.POINTER_INVALID, 503),
        (ChatOwnerErrorCode.UNAVAILABLE, 503),
        (ChatOwnerErrorCode.PROTOCOL_INVALID, 503),
        (ChatOwnerErrorCode.NOT_READY, 503),
    ],
)
def test_private_owner_faults_keep_stable_http_meaning_without_internal_details(
    monkeypatch, code, status
):
    value, services, owner = client(enabled=True)

    def fault(**_):
        raise ChatOwnerFault(code)

    monkeypatch.setattr(owner, "conversations", fault)
    try:
        with value:
            response = value.get("/api/v1/general-chat/conversations")
            assert response.status_code == status
            assert response.json()["error_code"] == code.value
            assert "Traceback" not in response.text
    finally:
        services.engine.dispose()


def test_disconnected_private_owner_does_not_make_the_dedicated_slot_look_ready(monkeypatch):
    value, services, owner = client(enabled=True)

    def fault():
        raise ChatOwnerFault(ChatOwnerErrorCode.UNAVAILABLE)

    monkeypatch.setattr(owner, "slot", fault)
    try:
        with value:
            response = value.get("/api/v1/general-chat/slot")
            assert response.status_code == 200
            assert response.json()["state"] == "UNAVAILABLE"
            assert response.json()["unavailable_reason"]
    finally:
        services.engine.dispose()


@pytest.mark.parametrize(
    "api_model,web_model,value",
    [
        (GeneralChatCreate, ChatCreate, {"title": "새 대화"}),
        (GeneralChatSubmission, ChatSubmission, {"text": "질문", "expected_version": 1}),
        (GeneralChatSlot, ChatSlot, {"state": "UNAVAILABLE", "unavailable_reason": "준비 중"}),
        (GeneralChatConversation, ChatConversation, conversation().model_dump(mode="json")),
        (GeneralChatList, ChatList, {"values": [], "has_more": False, "next_cursor": None}),
    ],
)
def test_schema_api_web_mirrors_agree(api_model, web_model, value):
    canonical = ROOT / "schemas/api/v1/general-chat-v1.schema.json"
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas/general-chat-v1.schema.json"
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)
    wire = api_model.model_validate(value).model_dump(mode="json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(wire)
    assert web_model.model_validate(wire).model_dump(mode="json") == wire


@pytest.mark.parametrize(
    "data",
    [
        {"text": " ", "expected_version": 1},
        {"text": "abc\x00", "expected_version": 1},
        {"text": "q", "expected_version": 0},
        {"text": "q", "expected_version": 1, "operator_id": "other"},
    ],
)
def test_chat_submission_rejects_invalid_or_caller_selected_owner(data):
    for model in (GeneralChatSubmission, ChatSubmission):
        with pytest.raises(ValidationError):
            model.model_validate(data)


def test_no_empty_completed_answer_or_duplicate_messages():
    message = dict(
        turn_id="chatturn_" + "3" * 32,
        sequence=1,
        role="assistant",
        text="",
        state="COMPLETED",
        created_at=NOW,
    )
    with pytest.raises(ValidationError):
        GeneralChatMessage(**message)
    message.update(text="실제 답변")
    item = GeneralChatMessage(**message)
    with pytest.raises(ValidationError):
        GeneralChatConversation(**{**conversation().model_dump(), "messages": (item, item)})


@pytest.mark.parametrize(
    "invalid",
    [
        {"title": " "},
        {"text": "q\x00", "expected_version": 1},
        {
            "slot_key": "chat",
            "state": "READY",
            "dedicated": True,
            "resident": True,
            "unavailable_reason": "actually broken",
        },
        {"values": [], "has_more": True, "next_cursor": None},
    ],
)
def test_schema_rejects_semantic_wire_contradictions(invalid):
    schema = json.loads((ROOT / "schemas/api/v1/general-chat-v1.schema.json").read_bytes())
    assert list(Draft202012Validator(schema).iter_errors(invalid))
