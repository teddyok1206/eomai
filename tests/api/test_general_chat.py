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
