"""Real BFF→API→UDS→disposable storage→PDF, with synthetic questions and notes."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pymupdf
import pytest
from eom_catalog_service.kakao_delivery_application import KakaoDeliveryApplication
from eom_catalog_service.kakao_pdf_coordinator import KakaoPdfCoordinator
from eom_catalog_service.kakao_study_service import KakaoStudyService
from eom_identifiers import sha256_bytes
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_packet_storage import packet_store as packet_store
from tests.integration.test_kakao_question_http import question_api, studio_api
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.integration.test_kakao_study_export_storage import (
    study_export_store as study_export_store,
)
from tests.integration.test_kakao_study_storage import study_store as study_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
BASE = "/studio/api/v1/kakao-archive"


def application(store):
    _engine, _actor, studies, exports, driver, *_ = store
    coordinator = KakaoPdfCoordinator(driver)
    return KakaoDeliveryApplication(
        studies.packets, exports, coordinator.submit, studies
    ), coordinator


def test_bff_saved_edit_pdf_replay_reopen_and_current_download_permission(
    study_export_store,
    question_store,
    tmp_path,
):
    engine, actor, studies, _exports, _driver, _command, _saved, original, launcher = (
        study_export_store
    )
    app, coordinator = application(study_export_store)
    with (
        question_api(question_store, tmp_path, delivery=app) as (api, _state, _reads),
        studio_api(api, actor.operator_id) as (web, csrf),
    ):
        create = original.model_dump(mode="json")
        params = {"source_binding_id": original.source_binding_id}
        selection = web.get(
            BASE
            + f"/question-packets/{original.packet_id}/revisions/{original.packet_revision_id}"
            + f"/students/{original.student_id}/study-selection",
            params=params,
        )
        assert selection.status_code == 200, selection.text
        assert [q["question_revision_id"] for q in selection.json()["questions"]] == [
            q["question_revision_id"] for q in create["questions"]
        ]
        assert all(
            not q["notes"] and not q["blocks"] and q["concept_task_id"] is None
            for q in selection.json()["questions"]
        )
        key = "http-study-" + uuid4().hex
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": key}
        assert (
            web.post(BASE + "/studies", json=create, headers={"Idempotency-Key": key}).status_code
            == 403
        )
        response = web.post(BASE + "/studies", json=create, headers=headers)
        assert response.status_code == 201, response.text
        assert (
            response.headers["etag"] == '"v1"' and response.headers["cache-control"] == "no-store"
        )
        first = response.json()["study"]
        assert web.post(BASE + "/studies", json=create, headers=headers).json()["study"] == first
        changed = {**create, "title": "다른 제목"}
        assert web.post(BASE + "/studies", json=changed, headers=headers).status_code == 409
        params = {"source_binding_id": first["source_binding_id"]}
        path = BASE + "/studies/" + first["study_id"]
        revision_path = path + "/revisions/" + first["study_revision_id"]
        read = web.get(revision_path, params=params)
        assert read.status_code == 200, read.text
        assert read.json()["questions"] == create["questions"]
        # No raw question bodies, model result or source path is returned by the editing view.
        assert set(read.json()) == {"schema_version", "study", "questions"}
        body = {
            **create,
            "schema_version": "kakao-study-revise/1.0",
            "study_id": first["study_id"],
            "parent_revision_id": first["study_revision_id"],
            "expected_resource_version": 1,
            "title": "교재 설명을 보강한 질문 자료",
        }
        body["questions"][0]["notes"] = [
            {"title": "추가 설명", "text": "저장한 설명을 질문·답변 다음 쪽에 표시합니다."}
        ]
        editing = {
            **headers,
            "Idempotency-Key": "http-study-edit-" + uuid4().hex,
            "If-Match": '"v1"',
        }
        assert (
            web.patch(path, json=body, headers={**editing, "If-Match": '"v2"'}).status_code == 412
        )
        response = web.patch(path, json=body, headers=editing)
        assert response.status_code == 200, response.text
        second = response.json()["study"]
        assert response.headers["etag"] == '"v2"'
        assert second["previous_revision_id"] == first["study_revision_id"]
        assert web.patch(path, json=body, headers=editing).json()["study"] == second
        assert web.get(revision_path, params=params).json()["study"] == first
        export_request = {
            "schema_version": "kakao-study-export-create/1.0",
            **params,
            "study": {
                "study_id": second["study_id"],
                "study_revision_id": second["study_revision_id"],
                "manifest_sha256": second["manifest"]["sha256"],
            },
        }
        pdf_headers = {**headers, "Idempotency-Key": "http-study-pdf-" + uuid4().hex}
        response = web.post(BASE + "/study-exports", json=export_request, headers=pdf_headers)
        assert response.status_code == 202, response.text
        exported = response.json()["result"]["export"]
        assert coordinator.advance_once() == "COMPLETED"
        response = web.get(BASE + "/study-exports/" + exported["export_id"], params=params)
        assert response.status_code == 200, response.text
        completed = response.json()
        assert completed["study"] == export_request["study"]
        assert completed["export"]["state"] == "COMPLETED"
        pdf_path = BASE + "/exports/" + exported["export_id"] + "/file"
        pdf_params = {**params, "revision_id": completed["export"]["export_revision_id"]}
        for _ in range(2):
            response = web.get(pdf_path, params=pdf_params)
            assert response.status_code == 200, response.text
            assert sha256_bytes(response.content) == completed["export"]["pdf"]["sha256"]
            with pymupdf.open(stream=response.content, filetype="pdf") as pdf:
                assert "추가 설명" in "".join(page.get_text() for page in pdf)
                assert len(pdf) >= 2
        assert (
            web.post(BASE + "/study-exports", json=export_request, headers=pdf_headers).json()[
                "result"
            ]
            == completed
        )
        assert coordinator.advance_once() == "IDLE" and launcher.calls == 1
        restored = KakaoStudyService(
            engine,
            artifacts=studies.artifacts,
            packets=studies.packets,
            sources=studies.sources,
            concepts=studies.concepts,
        )
        # Reconstruct the owner behind the same public service; no UI-local edit authority.
        app = replace(app, studies=restored)
    with (
        question_api(question_store, tmp_path, delivery=app) as (api, _state, _reads),
        studio_api(api, actor.operator_id) as (web, _csrf),
    ):
        result = web.get(path + "/revisions/" + second["study_revision_id"], params=params)
        assert result.status_code == 200, result.text
        assert result.json()["questions"] == body["questions"]
        history = web.get(BASE + "/studies", params={**params, "limit": 1})
        assert history.status_code == 200, history.text
        assert len(history.json()["items"]) == 1
        cursor = history.json()["next_cursor"]
        assert cursor is not None
        following = web.get(BASE + "/studies", params={**params, "limit": 1, "cursor": cursor})
        assert following.status_code == 200 and len(following.json()["items"]) == 1
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        assert web.get(pdf_path, params=pdf_params).status_code == 403
    assert launcher.calls == 1


@pytest.mark.parametrize("change", ["question", "study-hash", "authority"])
def test_http_rejects_wrong_question_pin_and_caller_authority_without_render(
    study_export_store,
    question_store,
    tmp_path,
    change,
):
    _, actor, _studies, _exports, _driver, command, _saved, original, launcher = study_export_store
    app, coordinator = application(study_export_store)
    with question_api(question_store, tmp_path, delivery=app) as (api, _state, _reads):
        if change == "study-hash":
            body = command.model_dump(mode="json")
            body["study"]["manifest_sha256"] = "sha256:" + "f" * 64
            endpoint, expected = "/study-exports", 409
        else:
            body = original.model_dump(mode="json")
            if change == "question":
                body["questions"][0]["question_revision_id"] = "kakaoquestionrev_" + "f" * 32
                expected = 422
            else:
                body["actor_id"] = actor.operator_id
                expected = 422
            endpoint = "/studies"
        response = api.post(
            "/api/v1/kakao-archive" + endpoint,
            json=body,
            headers={"Idempotency-Key": "bad-study-http-" + uuid4().hex},
        )
        assert response.status_code == expected, response.text
        assert coordinator.advance_once() == "IDLE" and launcher.calls == 0
