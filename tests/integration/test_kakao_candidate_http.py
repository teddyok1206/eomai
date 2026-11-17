"""Synthetic accepted source→candidate read→existing question writes on guarded PG."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_question_edit_context import counts
from tests.integration.test_kakao_question_http import paths, question_api, studio_api
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_room_storage import admit
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
API = "/api/v1/kakao-archive/questions"
WEB = "/studio" + API


def params(command):
    return {"source_binding_id": command.source_binding_id, "room_id": command.room_id}


def test_actual_bff_candidates_save_replay_review_split_and_restart(question_store, tmp_path):
    engine, _actor, _questions, command, *_ = question_store
    with (
        question_api(question_store, tmp_path) as (api, state, _reads),
        studio_api(api, state.authentication.operator.operator_id) as (web, csrf),
    ):
        before = counts(engine, command.room_id)
        initial = web.get(WEB + "/candidates", params=params(command))
        assert initial.status_code == 200, initial.text
        page = initial.json()
        assert initial.headers["Cache-Control"] == "no-store"
        assert (
            page["source_revision_id"] == command.source_revision_id
            and page["total_candidates"] > 0
        )
        assert page["mapping_revision_id"] == command.expected_mapping_revision_id
        assert page["items"][0]["saved_question"] is None
        pinned = {**params(command), "source_revision_id": page["source_revision_id"]}
        assert web.get(WEB + "/candidates", params=pinned).json() == page
        assert counts(engine, command.room_id) == before
        body = dict(
            schema_version="kakao-question-create/1.0",
            **params(command),
            source_revision_id=page["source_revision_id"],
            candidate_ordinal=page["items"][0]["candidate_ordinal"],
            expected_mapping_revision_id=page["mapping_revision_id"],
        )
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "candidate-save-" + uuid4().hex}
        first = web.post(WEB, json=body, headers=headers)
        assert first.status_code == 201, first.text
        question = first.json()["question"]
        assert web.post(WEB, json=body, headers=headers).json()["question"] == question
        saved = web.get(WEB + "/candidates", params=pinned).json()["items"][0]
        assert saved["saved_question"] == {
            key: question[key] for key in ("question_id", "question_revision_id")
        }
        p, path = paths(question)
        view = web.get("/studio" + path, params=p).json()
        split = dict(
            schema_version="kakao-question-compose/1.0",
            operation="SPLIT",
            **params(command),
            input={
                key: question[key]
                for key in ("question_id", "question_revision_id", "resource_version")
            },
            partitions=[
                [{"kind": "BLOCK", "block_id": view["ordered_blocks"][0]["block_id"]}],
                [
                    {"kind": "BLOCK", "block_id": block["block_id"]}
                    for block in view["ordered_blocks"][1:]
                ],
            ],
        )
        assert len(view["ordered_blocks"]) > 1
        result = web.post(
            WEB + "/compose",
            json=split,
            headers={**headers, "Idempotency-Key": "candidate-split-" + uuid4().hex},
        )
        assert result.status_code == 200, result.text
        after = web.get(WEB + "/candidates", params=pinned).json()
        assert (
            after["items"][0]["recomposed"]
            and after["items"][0]["saved_question"] == saved["saved_question"]
        )
        assert (
            web.post(
                WEB,
                json=body,
                headers={**headers, "Idempotency-Key": "candidate-duplicate-" + uuid4().hex},
            ).status_code
            == 409
        )
    with question_api(question_store, tmp_path) as (api, _state, _reads):
        assert api.get(API + "/candidates", params=pinned).json()["data"] == after


def test_exact_old_source_stays_pinned_after_new_acceptance(
    question_store, source_store, tmp_path, monkeypatch
):
    _engine, actor, _questions, command, sources, *_ = question_store
    with question_api(question_store, tmp_path) as (api, _state, _reads):
        original = api.get(API + "/candidates", params=params(command)).json()["data"]
        previous = sources.get_source(
            actor,
            command.source_binding_id,
            command.room_id,
            source_revision_id=command.source_revision_id,
        ).resolution
        admission, _ = source_store[-1](
            previous=previous, texts=("새 원본 첫 질문", "새 원본 두 번째 질문")
        )
        current = sources.admit_source(
            actor, admission, idempotency_key="candidate-new-source-" + uuid4().hex
        )
        newest = api.get(API + "/candidates", params=params(command)).json()["data"]
        assert (
            newest["source_revision_id"]
            == current.resolution.source_revision_id
            != original["source_revision_id"]
        )

        def no_latest(*args, **kwargs):
            raise AssertionError("Pinned follow-up must not select latest")

        monkeypatch.setattr(sources, "current_source_revision", no_latest)
        exact = api.get(
            API + "/candidates",
            params={**params(command), "source_revision_id": original["source_revision_id"]},
        )
        assert exact.status_code == 200 and exact.json()["data"] == original
        missing = api.get(
            API + "/candidates",
            params={**params(command), "source_revision_id": "kakaosourcerev_" + "9" * 32},
        )
        assert missing.status_code == 404


def test_candidate_source_is_resolved_once_and_late_session_revoke_hides_preview(
    question_store, tmp_path, monkeypatch
):
    engine, actor, _questions, command, sources, *_ = question_store
    resolve = sources.resolve_question_source_context
    calls = []

    def late(*args, **kwargs):
        calls.append(1)
        result = resolve(*args, **kwargs)
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(
                    revoked_at=datetime.now(UTC), revoke_reason="synthetic candidate late revoke"
                )
            )
        return result

    with question_api(question_store, tmp_path) as (api, _state, _reads):
        monkeypatch.setattr(sources, "resolve_question_source_context", late)
        denied = api.get(API + "/candidates", params=params(command))
        assert denied.status_code == 403 and "preview" not in denied.text and len(calls) == 1


def test_room_without_accepted_source_is_empty_and_not_resolved(
    question_store, tmp_path, monkeypatch
):
    engine, actor, _questions, _command, sources, _artifacts, binding = question_store
    accepted, _ = admit(engine, (actor, binding, KakaoRoomService(engine)))

    def forbidden(*args, **kwargs):
        raise AssertionError("There is no accepted source to materialize")

    monkeypatch.setattr(sources, "resolve_question_source_context", forbidden)
    with question_api(question_store, tmp_path) as (api, _state, _reads):
        scope = {"source_binding_id": binding.source_binding_id, "room_id": accepted.room.room_id}
        result = api.get(API + "/candidates", params=scope)
        assert result.status_code == 200, result.text
        page = result.json()["data"]
        assert page["source_revision_id"] is page["source_resolution_sha256"] is None
        assert not page["items"] and page["total_candidates"] == 0
        assert api.get(API + "/candidates", params={**scope, "after_ordinal": 1}).status_code == 422
