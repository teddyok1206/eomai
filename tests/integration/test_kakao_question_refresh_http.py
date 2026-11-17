"""Real BFF/API/local socket/owners for explicit refresh; synthetic disposable input."""

from uuid import uuid4

import pytest

from tests.integration.test_kakao_question_http import question_api, studio_api
from tests.integration.test_kakao_question_refresh_storage import refresh_case as refresh_case
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_studio_refresh_source_and_exact_replay_survive_reconstruction(refresh_case, tmp_path):
    store, old, _source, command = refresh_case
    path = "/kakao-archive/questions/" + old.question_id + "/refresh-source"
    key = "http-refresh-" + uuid4().hex
    with question_api(store, tmp_path) as (api, state, _reads):
        with studio_api(api, state.authentication.operator.operator_id) as (web, csrf):
            headers = {
                "Idempotency-Key": key,
                "If-Match": f'"v{old.resource_version}"',
                "X-CSRF-Token": csrf,
            }
            response = web.post(
                "/studio/api/v1" + path, json=command.model_dump(mode="json"), headers=headers
            )
            assert response.status_code == 200, response.text
            original = response.json()
            assert original["question"]["review_state"] == "UNREVIEWED"
            assert response.headers["etag"] == f'"v{old.resource_version + 1}"'
            assert response.headers["cache-control"] == "no-store"
            exact = original["question"]
            reopened = web.get(
                f"/studio/api/v1/kakao-archive/questions/{old.question_id}/revisions/{exact['question_revision_id']}",
                params={"source_binding_id": old.source_binding_id, "room_id": old.room_id},
            )
            assert reopened.status_code == 200, reopened.text
            assert any(
                block.get("text") == "later staff reply"
                for block in reopened.json()["ordered_blocks"]
            )
        with studio_api(api, state.authentication.operator.operator_id) as (web, csrf):
            headers["X-CSRF-Token"] = csrf
            replay = web.post(
                "/studio/api/v1" + path, json=command.model_dump(mode="json"), headers=headers
            )
            assert replay.status_code == 200, replay.text
            assert replay.json()["question"] == original["question"] and replay.json()["replayed"]


@pytest.mark.parametrize("cause", ["csrf", "version", "path", "acknowledgement", "authority"])
def test_refresh_studio_rejects_unconfirmed_or_wrong_boundary(refresh_case, tmp_path, cause):
    store, old, _source, command = refresh_case
    with (
        question_api(store, tmp_path) as (api, state, _reads),
        studio_api(api, state.authentication.operator.operator_id) as (web, csrf),
    ):
        body = command.model_dump(mode="json")
        headers = {
            "Idempotency-Key": "bad-refresh-" + uuid4().hex,
            "If-Match": f'"v{old.resource_version}"',
            "X-CSRF-Token": csrf,
        }
        target = old.question_id
        if cause == "csrf":
            del headers["X-CSRF-Token"]
        elif cause == "version":
            headers["If-Match"] = '"v99"'
        elif cause == "path":
            target = "kakaoquestion_" + "f" * 32
        elif cause == "acknowledgement":
            body["replace_display_edits"] = 1
        else:
            body["owner_operator_id"] = "operator_" + "f" * 32
        response = web.post(
            f"/studio/api/v1/kakao-archive/questions/{target}/refresh-source",
            json=body,
            headers=headers,
        )
        assert response.status_code in {403, 412, 422}, response.text
        current = store[2].list_questions(store[1], old.source_binding_id)
        assert current.items == (old,)
