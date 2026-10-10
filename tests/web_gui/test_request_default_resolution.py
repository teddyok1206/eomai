"""Request clients submit logical defaults, never a cached or chosen preset revision."""

from __future__ import annotations

from typing import Any

import pytest
from eom_web_gui.contracts import RequestDraftUpdate
from eom_web_gui.gateways import GatewayError
from eom_web_gui.sessions import WebSession
from fastapi.testclient import TestClient

from tests.web_gui.helpers import FakeGateway, login, make_client


class PublishedDefaultGateway(FakeGateway):
    """Model the supported API's current-pointer resolution at the Web boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.graph_grounding_available = True
        self.current_revision = "execpresetrev_" + "1" * 32
        self.unavailable_code: str | None = None
        self.accepted: list[tuple[str, str, str]] = []

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        assert "expected_resolution" not in payload
        assert "execution_preset_revision_id" not in payload
        if self.unavailable_code is not None:
            raise GatewayError(status=409, code=self.unavailable_code)
        command = await super().start_workflow(session, payload, idempotency_key)
        workflow_id = "workflow_" + f"{self.start_calls:032x}"
        self.accepted.append(
            (workflow_id, str(payload["execution_preset_key"]), self.current_revision)
        )
        return {**command, "resource_id": workflow_id}


def _draft(client: TestClient, headers: dict[str, str], mode: str, text: str) -> dict[str, Any]:
    response = client.post(
        "/studio/api/v1/request-drafts",
        headers=headers,
        json={"original_request_text": text},
    )
    assert response.status_code == 201
    draft: dict[str, Any] = response.json()
    values = {name: draft[name] for name in RequestDraftUpdate.model_fields}
    values["quality_profile"] = "deep"  # A resumed legacy draft is not a preset choice.
    if mode != "normal":
        values["knowledge_grounding"] = True
        values["curriculum_selected_unit_key"] = "eom.is.middle.3-2"
    if mode == "variation":
        values["past_exam_variation"] = {
            "source_item_revision_id": "itemrev_" + "9" * 32,
            "variation_axes": ["VALUES"],
        }
    updated = client.put(
        f"/studio/api/v1/request-drafts/{draft['request_draft_id']}",
        headers=headers,
        json=values,
    )
    assert updated.status_code == 200
    result: dict[str, Any] = updated.json()
    return result


def _submit(client: TestClient, headers: dict[str, str], draft: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
        headers=headers,
        json={
            "idempotency_key": f"studio:{draft['request_draft_id']}:{draft['draft_spec_sha256']}"
        },
    )
    assert response.status_code == 202
    result: dict[str, Any] = response.json()
    return result


@pytest.mark.parametrize("mode", ["normal", "grounded", "variation"])
def test_request_resolves_default_at_submission_and_preserves_old_replay(mode: str) -> None:
    gateway = PublishedDefaultGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        headers = {"X-CSRF-Token": login(client)["csrf_token"]}
        old_draft = _draft(
            client, headers, mode, "처음 작성한 전류와 전압의 관계 문항을 만들어주세요."
        )
        gateway.current_revision = "execpresetrev_" + "2" * 32
        first = _submit(client, headers, old_draft)
        assert gateway.accepted[0][2] == gateway.current_revision

        gateway.current_revision = "execpresetrev_" + "3" * 32
        replay = _submit(client, headers, old_draft)
        assert replay["replayed"] is True
        assert replay["command"] == first["command"]
        assert len(gateway.accepted) == 1
        assert gateway.accepted[0][2] == "execpresetrev_" + "2" * 32

        new_draft = _draft(
            client, headers, mode, "새로 작성한 전기 에너지의 변화를 추론하는 문항을 만들어주세요."
        )
        second = _submit(client, headers, new_draft)
        assert second["command"]["resource_id"] != first["command"]["resource_id"]
        assert gateway.accepted[1][2] == gateway.current_revision
        expected_key = "standard-item" if mode == "normal" else "knowledge-grounded-item"
        assert [record[1] for record in gateway.accepted] == [expected_key, expected_key]


@pytest.mark.parametrize("mode", ["normal", "variation"])
def test_two_request_sessions_do_not_cache_the_default_revision(mode: str) -> None:
    gateway = PublishedDefaultGateway()
    first, _ = make_client(gateway=gateway)
    second = TestClient(first.app, base_url="http://testserver.local")
    with first, second:
        first_headers = {"X-CSRF-Token": login(first)["csrf_token"]}
        second_headers = {"X-CSRF-Token": login(second)["csrf_token"]}
        first_draft = _draft(
            first, first_headers, mode, "첫 번째 작업자의 전류와 전압 문항을 만들어주세요."
        )
        second_draft = _draft(
            second, second_headers, mode, "두 번째 작업자의 세포와 에너지 문항을 만들어주세요."
        )
        gateway.current_revision = "execpresetrev_" + "4" * 32
        _submit(first, first_headers, first_draft)
        gateway.current_revision = "execpresetrev_" + "5" * 32
        _submit(second, second_headers, second_draft)
        assert [record[2] for record in gateway.accepted] == [
            "execpresetrev_" + "4" * 32,
            "execpresetrev_" + "5" * 32,
        ]


@pytest.mark.parametrize("mode", ["normal", "variation"])
def test_unpublished_default_fails_closed_without_client_fallback(mode: str) -> None:
    gateway = PublishedDefaultGateway()
    gateway.unavailable_code = "CONTROL_PRESET_NOT_PUBLISHED"
    client, _ = make_client(gateway=gateway)
    with client:
        headers = {"X-CSRF-Token": login(client)["csrf_token"]}
        draft = _draft(
            client, headers, mode, "현재 공개된 설정이 없으면 시작하지 않을 문항 요청입니다."
        )
        response = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            headers=headers,
            json={"idempotency_key": "studio:no-published-default"},
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "CONTROL_PRESET_NOT_PUBLISHED"
        assert gateway.accepted == []
        assert gateway.start_calls == 0


def test_request_submission_rejects_client_preset_revision() -> None:
    client, gateway = make_client()
    with client:
        headers = {"X-CSRF-Token": login(client)["csrf_token"]}
        draft = _draft(
            client, headers, "normal", "클라이언트가 실행 설정을 지정하지 않는 문항 요청입니다."
        )
        response = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            headers=headers,
            json={
                "idempotency_key": "studio:no-client-preset-choice",
                "execution_preset_revision_id": "execpresetrev_" + "6" * 32,
            },
        )
        assert response.status_code == 422
        assert gateway.start_calls == 0
