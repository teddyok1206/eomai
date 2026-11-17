"""Exact span metadata and saved re-splits through BFF/API/owners on disposable PG."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_question import KakaoDisplayOverride, KakaoQuestionEdit
from eom_catalog_contracts.kakao_question_store import KakaoQuestionChange
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_identity_service.models import (
    ApiSessionRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_http import create, paths, question_api, studio_api
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def counts(engine, room):
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.room_id == room)
            ),
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRevisionRecord)
                .join(
                    KakaoQuestionRecord,
                    KakaoQuestionRecord.question_id == KakaoQuestionRevisionRecord.question_id,
                )
                .where(KakaoQuestionRecord.room_id == room)
            ),
        )


@pytest.mark.parametrize("unicode_source", [False, True])
def test_studio_exact_context_repeated_get_and_nonzero_resplit_survive_restart(
    question_store, source_store, tmp_path, unicode_source
):
    engine = question_store[0]
    command = question_store[3]
    cut, step = (4, 2) if unicode_source else (7, 1)
    if unicode_source:
        sources, actor = question_store[4], question_store[1]
        previous = sources.get_source(
            actor,
            command.source_binding_id,
            command.room_id,
            source_revision_id=command.source_revision_id,
        ).resolution
        admission, _ = source_store[-1](
            previous=previous, texts=("😀가\r\n가나 끝", "두 번째 질문")
        )
        accepted = sources.admit_source(
            actor, admission, idempotency_key="unicode-source-" + uuid4().hex
        )
        command = command.model_copy(
            update={"source_revision_id": accepted.resolution.source_revision_id}
        )
    with (
        question_api(question_store, tmp_path) as (api, state, _reads),
        studio_api(api, state.authentication.operator.operator_id) as (web, csrf),
    ):
        original, _ = create(api, command)
        params, path = paths(original)
        url = "/studio" + path + "/edit-context"
        before = counts(engine, original["room_id"])
        response = web.get(url, params=params)
        assert response.status_code == 200, response.text
        context = response.json()
        assert (
            response.headers["cache-control"] == "no-store" and response.headers["etag"] == '"v1"'
        )
        assert web.get(url, params=params).json() == context
        assert counts(engine, original["room_id"]) == before
        assert "private question" not in response.text and "artifact_" not in response.text
        blocks = api.get(path, params=params).json()["data"]["ordered_blocks"]
        first = context["text_blocks"][0]
        assert first["start_codepoint"] == 0 and first["can_split"]
        body = dict(
            schema_version="kakao-question-compose/1.0",
            operation="SPLIT",
            source_binding_id=original["source_binding_id"],
            room_id=original["room_id"],
            input={
                key: original[key]
                for key in ("question_id", "question_revision_id", "resource_version")
            },
            partitions=[
                [
                    dict(
                        kind="TEXT_SPAN",
                        block_id=first["block_id"],
                        start_codepoint=0,
                        end_codepoint=cut,
                    )
                ],
                [
                    dict(
                        kind="TEXT_SPAN",
                        block_id=first["block_id"],
                        start_codepoint=cut,
                        end_codepoint=first["end_codepoint"],
                    ),
                    *[dict(kind="BLOCK", block_id=block["block_id"]) for block in blocks[1:]],
                ],
            ],
        )
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "span-split-" + uuid4().hex}
        saved = web.post(
            "/studio/api/v1/kakao-archive/questions/compose", json=body, headers=headers
        )
        assert saved.status_code == 200, saved.text
        outputs = saved.json()["outputs"]
        assert (
            web.post(
                "/studio/api/v1/kakao-archive/questions/compose", json=body, headers=headers
            ).json()["outputs"]
            == outputs
        )
        params2, path2 = paths(outputs[1])
        next_context = web.get("/studio" + path2 + "/edit-context", params=params2).json()
        span = next_context["text_blocks"][0]
        assert span["start_codepoint"] == cut
        follow = dict(
            body,
            input={
                key: outputs[1][key]
                for key in ("question_id", "question_revision_id", "resource_version")
            },
            partitions=[
                [
                    dict(
                        kind="TEXT_SPAN",
                        block_id=span["block_id"],
                        start_codepoint=cut,
                        end_codepoint=cut + step,
                    )
                ],
                [
                    dict(
                        kind="TEXT_SPAN",
                        block_id=span["block_id"],
                        start_codepoint=cut + step,
                        end_codepoint=span["end_codepoint"],
                    ),
                    *[
                        dict(kind="BLOCK", block_id=block["block_id"])
                        for block in api.get(path2, params=params2).json()["data"][
                            "ordered_blocks"
                        ][1:]
                    ],
                ],
            ],
        )
        split_again = web.post(
            "/studio/api/v1/kakao-archive/questions/compose",
            json=follow,
            headers={**headers, "Idempotency-Key": "resplit-" + uuid4().hex},
        )
        assert split_again.status_code == 200, split_again.text
        parts = [outputs[0], *split_again.json()["outputs"]]
        shown = []
        for part in parts:
            p, route = paths(part)
            shown.extend(
                block["text"]
                for block in api.get(route, params=p).json()["data"]["ordered_blocks"]
                if block["kind"] == "TEXT"
            )
        assert "".join(shown) == "".join(
            block["text"] for block in blocks if block["kind"] == "TEXT"
        )
    with question_api(question_store, tmp_path) as (restarted, _state, _reads):
        assert restarted.get(path + "/edit-context", params=params).json()["data"] == context


def test_display_override_has_no_source_span_and_old_revision_remains_exact(
    question_store, tmp_path
):
    _engine, actor, service, command, *_ = question_store
    with question_api(question_store, tmp_path) as (api, _state, _reads):
        original, _ = create(api, command)
        params, path = paths(original)
        before = api.get(path + "/edit-context", params=params).json()["data"]
        full = service.get_question(
            actor,
            command.source_binding_id,
            command.room_id,
            original["question_id"],
            revision_id=original["question_revision_id"],
        ).published.question
        blocks = list(full.ordered_blocks)
        blocks[0] = blocks[0].model_copy(
            update={
                "display_override": KakaoDisplayOverride(
                    text="수정된 표시문", reason="합성 표시 교정"
                )
            }
        )
        edited = service.change_question(
            actor,
            KakaoQuestionChange(
                source_binding_id=command.source_binding_id,
                room_id=command.room_id,
                question_id=full.question_id,
                expected_resource_version=1,
                edit=KakaoQuestionEdit(
                    parent_revision_id=full.question_revision_id,
                    student=full.student,
                    ordered_blocks=tuple(blocks),
                    selection_exclusions=(),
                ),
            ),
            idempotency_key="override-" + uuid4().hex,
        )
        _, newpath = paths(edited.question.model_dump(mode="json"))
        context = api.get(newpath + "/edit-context", params=params).json()["data"]
        assert not context["text_blocks"][0]["can_split"]
        assert context["text_blocks"][0]["start_codepoint"] is None
        assert context["text_blocks"][0]["end_codepoint"] is None
        assert api.get(path + "/edit-context", params=params).json()["data"] == before


@pytest.mark.parametrize("permission_key", ["kakao_archive:read", "kakao_archive:edit"])
def test_edit_context_requires_current_read_and_edit_permissions(
    question_store, tmp_path, permission_key
):
    engine, actor, *_ = question_store
    with question_api(question_store, tmp_path) as (api, _state, _reads):
        original, _ = create(api, question_store[3])
        params, path = paths(original)
        role_id = "role_" + uuid4().hex
        with Session(engine) as session, session.begin():
            session.add(
                RoleRecord(
                    role_id=role_id,
                    role_key="KQ_TEST_" + uuid4().hex[:16],
                    display_name="Synthetic single permission",
                    description="Disposable test only",
                    built_in=False,
                )
            )
            session.flush()
            permission = session.scalar(
                select(PermissionRecord.permission_id).where(
                    PermissionRecord.permission_key == permission_key
                )
            )
            assert permission
            session.add(RolePermissionRecord(role_id=role_id, permission_id=permission))
            session.execute(
                update(OperatorRoleAssignmentRecord)
                .where(
                    OperatorRoleAssignmentRecord.operator_id == actor.operator_id,
                    OperatorRoleAssignmentRecord.revoked_at.is_(None),
                )
                .values(
                    revoked_at=datetime.now(UTC),
                    revoked_by="disposable-test",
                    revoke_reason="replace synthetic role",
                )
            )
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id="assignment_" + uuid4().hex,
                    operator_id=actor.operator_id,
                    role_id=role_id,
                    assigned_by="disposable-test",
                    assigned_at=datetime.now(UTC),
                )
            )
        try:
            assert api.get(path, params=params).status_code == (
                200 if permission_key == "kakao_archive:read" else 403
            )
            denied = api.get(path + "/edit-context", params=params)
            assert denied.status_code == 403 and "text_blocks" not in denied.text
        finally:
            with Session(engine) as session, session.begin():
                session.execute(
                    delete(OperatorRoleAssignmentRecord).where(
                        OperatorRoleAssignmentRecord.role_id == role_id
                    )
                )
                session.execute(
                    delete(RolePermissionRecord).where(RolePermissionRecord.role_id == role_id)
                )
                session.execute(delete(RoleRecord).where(RoleRecord.role_id == role_id))


def test_context_reauthorizes_after_source_io(question_store, tmp_path, monkeypatch):
    engine, actor, *_ = question_store
    with question_api(question_store, tmp_path) as (api, _state, reads):
        original, _ = create(api, question_store[3])
        params, path = paths(original)
        resolve = reads._resolve

        def revoke(*args, **kwargs):
            result = resolve(*args, **kwargs)
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC), revoke_reason="synthetic late revoke")
                )
            return result

        monkeypatch.setattr(reads, "_resolve", revoke)
        response = api.get(path + "/edit-context", params=params)
        assert response.status_code == 403 and "text_blocks" not in response.text


def test_other_owner_is_rejected_before_artifact_io(question_store, tmp_path, monkeypatch):
    with question_api(question_store, tmp_path) as (api, state, _reads):
        original, _ = create(api, question_store[3])
        params, path = paths(original)
        other = make_actor(question_store[0])
        state.authentication = replace(
            state.authentication,
            operator=state.authentication.operator.model_copy(
                update={"operator_id": other.operator_id}
            ),
            session_id=other.session_id,
            authenticated_at=other.authentication_time,
        )

        def forbidden(*args, **kwargs):
            raise AssertionError("foreign artifact must not be opened")

        monkeypatch.setattr(question_store[5], "open_verified_member", forbidden)
        assert api.get(path + "/edit-context", params=params).status_code == 404
