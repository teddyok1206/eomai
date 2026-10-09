from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.general_chat_contracts import (
    ChatConversation,
    ChatCreateSubmission,
    ChatList,
    ChatSlot,
    ChatTurnSubmission,
)

from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session

NOW = datetime(2026, 10, 7, tzinfo=UTC)
CHAT_ID = "chat_" + "a" * 32
ROOT = Path(__file__).resolve().parents[2]


def chat_module(tmp_path: Path) -> Path:
    static = ROOT / "apps/web_gui/eom_web_gui/static"
    for name in (
        "general-chat.js",
        "chat-knowledge.js",
        "chat-markdown.js",
        "vendor-marked-18.1.0.js",
    ):
        (tmp_path / name).write_bytes((static / name).read_bytes())
    (tmp_path / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    return tmp_path / "general-chat.js"


def conversation() -> ChatConversation:
    return ChatConversation(
        conversation_id=CHAT_ID, title="새 대화", resource_version=1, updated_at=NOW
    )


class ChatGateway(FakeGateway):
    async def general_chat_slot(self, session) -> ChatSlot:
        return ChatSlot(state="READY")

    async def general_chat_list(self, session, cursor) -> ChatList:
        return ChatList(values=())

    async def general_chat_create(self, session, value: ChatCreateSubmission) -> ChatConversation:
        assert value.idempotency_key == "studio:chat:test-0001"
        return conversation()

    async def general_chat_get(self, session, conversation_id, cursor) -> ChatConversation:
        assert conversation_id == CHAT_ID
        return conversation()

    async def general_chat_submit(
        self, session, conversation_id, value: ChatTurnSubmission
    ) -> ChatConversation:
        assert conversation_id == CHAT_ID
        assert value.text == "질문"
        return conversation()


def test_bff_chat_session_csrf_and_static_shell():
    client, _ = make_client(gateway=ChatGateway())
    with client:
        assert client.get("/studio/api/v1/general-chat/slot").status_code == 401
        session = login(client)
        csrf = {"X-CSRF-Token": session["csrf_token"]}
        for suffix in ("slot", "conversations", f"conversations/{CHAT_ID}"):
            assert client.get(f"/studio/api/v1/general-chat/{suffix}").status_code == 200
        body = {"title": "새 대화", "idempotency_key": "studio:chat:test-0001"}
        assert (
            client.post("/studio/api/v1/general-chat/conversations", json=body).status_code == 403
        )
        assert (
            client.post(
                "/studio/api/v1/general-chat/conversations", json=body, headers=csrf
            ).status_code
            == 201
        )
        assert (
            client.post(
                f"/studio/api/v1/general-chat/conversations/{CHAT_ID}/turns",
                json={
                    "text": "질문",
                    "expected_version": 1,
                    "idempotency_key": body["idempotency_key"],
                },
                headers=csrf,
            ).status_code
            == 202
        )
        assert (
            client.get("/studio/api/v1/general-chat/conversations/arbitrary-thread").status_code
            == 422
        )
        shell = client.get("/studio/")
        assert 'data-view-target="chat"' in shell.text
        assert ">일반</p>" in shell.text
        assert client.get("/studio/assets/general-chat.js").status_code == 200


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_gateway_chat_validates_response_and_proxies_idempotency_without_actor():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/slot"):
            return httpx.Response(
                200,
                json={
                    "slot_key": "01",
                    "state": "READY",
                    "resident": True,
                    "dedicated": True,
                    "unavailable_reason": None,
                },
            )
        return httpx.Response(201, json=conversation().model_dump(mode="json"))

    gateway = HttpApplicationGateway(
        application_api_url="http://testserver",
        observability_url="http://observe",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        session = _session()
        with pytest.raises(GatewayError) as failure:
            await gateway.general_chat_slot(session)
        assert failure.value.code == "GENERAL_CHAT_RESPONSE_INVALID"
        await gateway.general_chat_create(
            session, ChatCreateSubmission(title="새 대화", idempotency_key="studio:chat:test-0001")
        )
        assert calls[-1].headers["Idempotency-Key"] == "studio:chat:test-0001"
        assert json.loads(calls[-1].content) == {"title": "새 대화"}
    finally:
        await gateway.close()


def test_chat_module_safe_text_and_ordered_state_updates(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    module = chat_module(tmp_path)
    script = f"""
import assert from 'node:assert/strict';
import {{mergeChatMessages, chatIsActive}} from {json.dumps(module.as_uri())};
const a = {{sequence: 1, turn_id: 'a', role: 'user', state: 'COMPLETED'}};
const b = {{sequence: 2, turn_id: 'a', role: 'assistant', state: 'RUNNING'}};
const c = {{...b, state: 'COMPLETED', text: 'actual answer'}};
assert.equal(chatIsActive({{messages: [a, b]}}), true);
assert.equal(chatIsActive({{messages: [a, c]}}), false);
assert.deepEqual(mergeChatMessages([b], [c, a]), [a, c]);
assert.throws(() => mergeChatMessages([a], [{{...a, turn_id: 'other'}}]));
"""
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=10
    )
    assert completed.returncode == 0, completed.stderr
    source = module.read_text()
    assert "innerHTML" not in source and "localStorage" not in source
    assert "!event.isComposing" in source
    assert "if (!current(token)) return;" in source
    assert "expected_version: selected.resource_version" in source


def test_chat_frontend_api_inventory_is_closed():
    from tests.web_gui.test_frontend_backend_alignment import _bff_routes, _frontend_api_calls

    source = (ROOT / "apps/web_gui/eom_web_gui/static/general-chat.js").read_text()
    calls = _frontend_api_calls(source)
    assert calls - _bff_routes() == set()


def test_chat_browser_races_and_uncertain_send_replay(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    module = chat_module(tmp_path)
    script = ROOT / "tests/web_gui/general_chat_browser_checks.mjs"
    result = subprocess.run(
        [node, str(script), module.as_uri()], text=True, capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "CHAT_BROWSER_STATE=PASS" in result.stdout


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source_kind", ["DOCUMENT_REVISION", "CONTENT_INTAKE_FILE", "APPROVED_ITEM_REVISION"]
)
async def test_rag_gateway_preserves_exact_provenance_without_worker_dependencies(source_kind):
    from eom_protocol.general_chat_rag_knowledge import (
        ChatRagIntakeReference,
        ChatRagItemReference,
        chat_rag_context,
    )
    from eom_protocol.general_chat_rag_turn import (
        ChatGroundingViewsV2,
        ChatRagSourceCard,
        ChatTurnGroundingViewV2,
        validate_rag_citations,
    )
    from eom_web_gui.chat_grounding_contracts import ChatGroundingSubmission

    from tests.unit.general_chat_rag_fixtures import context, request, result, source

    reference = source().reference
    original = reference.source.artifact_member
    if source_kind == "CONTENT_INTAKE_FILE":
        source_pointer = ChatRagIntakeReference(
            source_file_id="sourcefile_" + "1" * 32,
            source_class="PAST_EXAM",
            artifact_member=original,
        )
        reference = reference.model_copy(update={"source": source_pointer})
    elif source_kind == "APPROVED_ITEM_REVISION":
        source_pointer = ChatRagItemReference(
            source_class="APPROVED_ITEM",
            item_id="item_" + "1" * 32,
            item_revision_id="itemrev_" + "2" * 32,
            artifact_member=original.model_copy(
                update={"media_type": "application/json", "schema_ref": None}
            ),
        )
        reference = reference.model_copy(update={"source": source_pointer})
    rag = chat_rag_context(
        scope=context().scope,
        sources=(source().model_copy(update={"reference": reference}),),
        limitations=context().limitations,
    )
    prepared = request(knowledge=rag)
    view = ChatGroundingViewsV2(
        conversation_id=CHAT_ID,
        values=(
            ChatTurnGroundingViewV2(
                turn_id=prepared.turn_id,
                sources=(
                    ChatRagSourceCard.model_validate(
                        rag.sources[0].model_dump(mode="json", exclude={"text"})
                    ),
                ),
                receipt=validate_rag_citations(prepared, result(prepared), item=None, rag=rag),
                observed_at=None,
            ),
        ),
    )
    wire = view.model_dump(mode="json")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=wire)

    gateway = HttpApplicationGateway(
        application_api_url="http://testserver",
        observability_url="http://observe",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        submission = ChatGroundingSubmission(turn_ids=(prepared.turn_id,))
        mirrored = await gateway.general_chat_grounding(_session(), CHAT_ID, submission)
        assert mirrored.model_dump(mode="json") == wire
        assert "actor_id" not in json.loads(calls[-1].content)
        wire["values"][0]["sources"][0]["reference"]["analysis_member"]["member_path"] = "../escape"
        with pytest.raises(GatewayError, match="GENERAL_CHAT_RESPONSE_INVALID"):
            await gateway.general_chat_grounding(_session(), CHAT_ID, submission)
    finally:
        await gateway.close()
