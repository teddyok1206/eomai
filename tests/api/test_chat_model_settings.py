"""Admin-only model changes, fresh authentication, CAS headers and HTTP replay."""

from types import SimpleNamespace

import pytest
from eom_api_contracts.chat_model_settings import ChatModelSettingsView
from eom_protocol.general_chat_model_settings import read_chat_model_settings

from tests.api.test_preset_model_selection_contracts import _route_client
from tests.unit.test_chat_model_settings import settings_value

PATH = "/api/v1/general-chat/model-settings"
BODY = {"model": "synthetic-model", "reasoning_effort": "medium"}
HEADERS = {"If-Match": '"v1"', "Idempotency-Key": "chat-model-selection-test-0001"}


def client(**scope):
    http, services, _ = _route_client(**scope)
    calls = []

    def change(**values):
        calls.append(values)
        return read_chat_model_settings(
            settings_value(
                revision_number=values["expected_version"] + 1, created_by=values["actor"].actor_id
            )
        )

    services.preset_models = SimpleNamespace(
        chat_settings=lambda: ChatModelSettingsView(
            current=None, revision_id=None, sha256=None, resource_version=1, candidates=(BODY,)
        ),
        change_chat_settings=change,
    )
    return http, services, calls


def test_current_setting_and_exact_http_replay_preserve_one_application_call():
    http, services, calls = client()
    try:
        response = http.get(PATH)
        assert response.status_code == 200 and response.headers["etag"] == '"v1"'
        assert response.json()["data"]["applies_to"] == "NEXT_TURN"
        first = http.post(PATH, json=BODY, headers=HEADERS)
        assert first.status_code == 200
        second = http.post(PATH, json=BODY, headers=HEADERS)
        assert second.status_code == 200 and second.json()["data"] == first.json()["data"]
        assert len(calls) == 1
        assert calls[0]["expected_version"] == 1
        assert calls[0]["actor"].actor_id.startswith("operator_")
    finally:
        http.close()
        services.engine.dispose()


@pytest.mark.parametrize("scope", ({"admin": False}, {"fresh": False}, {"manage": False}))
def test_change_requires_admin_current_auth_and_permission(scope):
    http, services, calls = client(**scope)
    try:
        assert http.post(PATH, json=BODY, headers=HEADERS).status_code == 403
        assert not calls
    finally:
        http.close()
        services.engine.dispose()


@pytest.mark.parametrize(
    "field", ("actor_id", "slot_id", "native_runtime", "approved", "prompt", "preset_id")
)
def test_request_cannot_change_authority_slot_runtime_or_prompt(field):
    http, services, calls = client()
    try:
        assert http.post(PATH, json=BODY | {field: "untrusted"}, headers=HEADERS).status_code == 422
        assert not calls
    finally:
        http.close()
        services.engine.dispose()


@pytest.mark.parametrize(
    "headers", ({}, {"If-Match": '"v1"'}, {"Idempotency-Key": "chat-model-selection-test-0001"})
)
def test_change_without_etag_or_idempotency_never_executes(headers):
    http, services, calls = client()
    try:
        assert http.post(PATH, json=BODY, headers=headers).status_code in {400, 428}
        assert not calls
    finally:
        http.close()
        services.engine.dispose()
