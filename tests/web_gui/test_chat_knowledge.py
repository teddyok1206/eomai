from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from eom_web_gui.chat_knowledge_contracts import ChatKnowledgeRequest, ChatKnowledgeSelection
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway

from tests.api.test_chat_knowledge import selection
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session


class KnowledgeGateway(FakeGateway):
    async def general_chat_knowledge_search(self, session, value):
        assert value.query.kind == "RECENT"
        return ChatKnowledgeSelection.model_validate(selection().model_dump(mode="json"))


def test_search_bff_requires_session_csrf_and_forbids_authority_fields():
    client, _ = make_client(gateway=KnowledgeGateway())
    path = "/studio/api/v1/general-chat/knowledge/search"
    body = {"query": {"kind": "RECENT"}}
    with client:
        assert client.post(path, json=body).status_code == 401
        session = login(client)
        assert client.post(path, json=body).status_code == 403
        headers = {"X-CSRF-Token": session["csrf_token"]}
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["values"][0]["approval"]["status"] == "PENDING"
        assert response.json()["model_calls"] == 0
        for field in ("actor_id", "policy_id", "permissions", "artifact_member"):
            assert (
                client.post(path, json=body | {field: "untrusted"}, headers=headers).status_code
                == 422
            )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_gateway_forwards_typed_query_and_validates_closed_reply():
    calls = []
    valid = selection().model_dump(mode="json")

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=valid)
        return httpx.Response(200, json=valid | {"native_thread_id": "forbidden"})

    gateway = HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        value = ChatKnowledgeRequest(query={"kind": "RECENT"})
        result = await gateway.general_chat_knowledge_search(_session(), value)
        assert result.model_calls == 0
        assert calls[0].url.path == "/api/v1/general-chat/knowledge/search"
        assert json.loads(calls[0].content) == value.model_dump(mode="json")
        assert "Idempotency-Key" not in calls[0].headers
        with pytest.raises(GatewayError) as failure:
            await gateway.general_chat_knowledge_search(_session(), value)
        assert failure.value.code == "CHAT_KNOWLEDGE_RESPONSE_INVALID"
    finally:
        await gateway.close()


def test_browser_search_stale_owner_boundary_and_safe_navigation(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node browser-module fixture unavailable")
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "chat-knowledge.js").write_bytes(
        (root / "apps/web_gui/eom_web_gui/static/chat-knowledge.js").read_bytes()
    )
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    result = subprocess.run(
        [
            node,
            str(root / "tests/web_gui/chat_knowledge_browser_checks.mjs"),
            str(tmp_path / "chat-knowledge.js"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
