"""Stored synthetic sources through actual HTTP/API-peer socket/owners.

HTTP authentication is a test dependency; Catalog still checks real disposable
Identity sessions/roles. This is not HTTPS, live credentials or real Kakao capture.
"""

import os
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pymupdf
import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.kakao_question_compose_service import KakaoQuestionComposeService
from eom_catalog_service.kakao_question_composition import KakaoQuestionApplication
from eom_catalog_service.kakao_question_reads import KakaoQuestionReads
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_identifiers import sha256_bytes
from eom_identity_service.models import ApiSessionRecord
from eom_web_gui.app import COOKIE_NAME
from eom_web_gui.app import create_app as create_web_app
from eom_web_gui.sessions import ApiTokens
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication
from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.web_gui.helpers import make_services
from tests.web_gui.test_kakao_archive_routes import http_gateway

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
BASE = "/api/v1/kakao-archive/questions"


@contextmanager
def question_api(
    store,
    tmp_path,
    *,
    actor=None,
    delivery=None,
    captures=None,
    concepts=None,
    concept_coordinator=None,
):
    engine, original_actor, _questions, _command, sources, artifacts, _binding = store
    actor = original_actor if actor is None else actor
    runtime = tmp_path / ("kq-" + uuid4().hex[:8])
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    questions = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    reads = KakaoQuestionReads(engine, questions=questions, sources=sources, artifacts=artifacts)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        kakao_questions=KakaoQuestionApplication(
            questions,
            reads,
            KakaoQuestionComposeService(
                engine, questions=questions, sources=sources, artifacts=artifacts
            ),
            concepts,
            concept_coordinator,
        ),
        kakao_delivery=delivery,
        kakao_captures=captures,
        socket_path=runtime / "manager.sock",
        allowed_uid=os.getuid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    services = disconnected_services()
    services.catalog_application = CatalogApplicationClient(
        server.socket_path, expected_uid=os.getuid(), expected_gid=os.getgid()
    )
    services.audit = Mock()
    app = create_app(services)
    authentication = _authentication()
    state = SimpleNamespace(
        authentication=replace(
            authentication,
            operator=authentication.operator.model_copy(update={"operator_id": actor.operator_id}),
            session_id=actor.session_id,
            authenticated_at=actor.authentication_time,
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            yield client, state, reads
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        services.engine.dispose()
        assert not thread.is_alive()


def create(client, command):
    key = "http-question-" + uuid4().hex
    response = client.post(
        BASE, json=command.model_dump(mode="json"), headers={"Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["question"], key


def paths(question):
    params = {key: question[key] for key in ("source_binding_id", "room_id")}
    path = BASE + "/" + question["question_id"] + "/revisions/" + question["question_revision_id"]
    return params, path


def test_studio_compose_split_merge_replay_restart_and_csrf(question_store, tmp_path):
    command = question_store[3]
    with (
        question_api(question_store, tmp_path) as (api, state, _reads),
        studio_api(api, state.authentication.operator.operator_id) as (web, csrf),
    ):
        original, _ = create(api, command)
        params, path = paths(original)
        blocks = api.get(path, params=params).json()["data"]["ordered_blocks"]
        body = dict(
            schema_version="kakao-question-compose/1.0",
            operation="SPLIT",
            source_binding_id=original["source_binding_id"],
            room_id=original["room_id"],
            input={
                key: original[key]
                for key in ("question_id", "question_revision_id", "resource_version")
            },
            partitions=[[dict(kind="BLOCK", block_id=block["block_id"])] for block in blocks],
        )
        url = "/studio" + BASE + "/compose"
        headers = {"Idempotency-Key": "studio-split-" + uuid4().hex}
        assert web.post(url, json=body, headers=headers).status_code == 403
        headers["X-CSRF-Token"] = csrf
        response = web.post(url, json=body, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert not result["replayed"] and len(result["outputs"]) == 2
        assert response.headers["cache-control"] == "no-store"
        again = web.post(url, json=body, headers=headers)
        assert again.status_code == 200 and again.json()["replayed"]
        assert again.json()["outputs"] == result["outputs"]
        assert web.get("/studio" + BASE, params=params).json()["items"] == sorted(
            result["outputs"], key=lambda row: row["question_id"]
        )
        assert api.get(path, params=params).json()["data"]["question"] == original
        conflicting = web.post(
            url, json={**body, "partitions": list(reversed(body["partitions"]))}, headers=headers
        )
        assert conflicting.status_code == 409
        stale = web.post(
            url, json=body, headers={**headers, "Idempotency-Key": "stale-split-" + uuid4().hex}
        )
        assert stale.status_code == 412
        merge = dict(
            schema_version="kakao-question-compose/1.0",
            operation="MERGE",
            source_binding_id=original["source_binding_id"],
            room_id=original["room_id"],
            inputs=[
                {
                    key: row[key]
                    for key in ("question_id", "question_revision_id", "resource_version")
                }
                for row in result["outputs"]
            ],
        )
        merged = web.post(
            url, json=merge, headers={**headers, "Idempotency-Key": "studio-merge-" + uuid4().hex}
        )
        assert merged.status_code == 200, merged.text
        output = merged.json()["outputs"][0]
    # New socket server/API reads the committed selection, not a browser cache.
    with question_api(question_store, tmp_path) as (restarted, _, _):
        assert restarted.get(BASE, params=params).json()["data"]["items"] == [output]
        qparams, qpath = paths(output)
        displayed = restarted.get(qpath, params=qparams)
        assert displayed.status_code == 200 and len(displayed.json()["data"]["ordered_blocks"]) == 2


def test_actual_http_create_exact_read_review_replay_and_restart(question_store, tmp_path):
    command = question_store[3]
    with question_api(question_store, tmp_path) as (client, _state, _reads):
        first, key = create(client, command)
        again = client.post(
            BASE, json=command.model_dump(mode="json"), headers={"Idempotency-Key": key}
        )
        assert again.status_code == 201 and again.json()["data"]["replayed"]
        assert again.json()["data"]["question"] == first
        params, path = paths(first)
        read = client.get(path, params=params)
        assert read.status_code == 200, read.text
        blocks = read.json()["data"]["ordered_blocks"]
        assert [block["text"] for block in blocks] == ["private question", "private question"]
        assert len({block["block_id"] for block in blocks}) == 2
        assert read.headers["cache-control"] == "no-store"
        assert read.headers["etag"] == '"v1"'
        # An exact deep link needs no list-page room hint; a wrong hint is not ignored.
        assert (
            client.get(path, params={"source_binding_id": first["source_binding_id"]}).json()[
                "data"
            ]
            == read.json()["data"]
        )
        assert (
            client.get(path, params={**params, "room_id": "kakaoroom_" + "9" * 32}).status_code
            == 404
        )
        review = dict(
            schema_version="kakao-question-edit/1.0",
            action="CONFIRM",
            parent_revision_id=first["question_revision_id"],
            reason="원문·질문 경계 확인",
            boundary_confirmed=True,
        )
        headers = {"Idempotency-Key": "review-" + uuid4().hex, "If-Match": '"v1"'}
        url = BASE + "/" + first["question_id"] + "/review"
        result = client.post(url, params=params, json=review, headers=headers)
        assert result.status_code == 200, result.text
        changed = result.json()["data"]["question"]
        assert changed["review_state"] == "CONFIRMED" and changed["resource_version"] == 2
        assert client.post(url, params=params, json=review, headers=headers).json()["data"][
            "replayed"
        ]
        assert client.get(path, params=params).json()["data"]["question"] == first
    with question_api(question_store, tmp_path) as (restarted, _state, _reads):
        items = restarted.get(BASE, params={"source_binding_id": command.source_binding_id}).json()[
            "data"
        ]["items"]
        assert items == [changed]
        params, path = paths(changed)
        assert restarted.get(path, params=params).json()["data"]["question"] == changed


def photo_command(question_store, source_store):
    _, actor, _questions, command, sources, _artifacts, _binding = question_store
    previous = sources.get_source(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    ).resolution
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 60))
    image.clear_with(180)
    photo = image.tobytes("png")
    admission, _ = source_store[-1](
        previous=previous,
        texts=("첫 번째 사진", "같은 사진을 다시 보냄"),
        photos={1: (photo, 80, 60), 2: (photo, 80, 60)},
    )
    accepted = sources.admit_source(
        actor, admission, idempotency_key="photo-http-source-" + uuid4().hex
    )
    return command.model_copy(
        update={"source_revision_id": accepted.resolution.source_revision_id}
    ), photo


@contextmanager
def studio_api(api, operator_id):
    """Real BFF/gateway with a synthetic cookie; API/Catalog still check actual test Identity."""

    def transport(request):
        result = api.request(
            request.method,
            str(request.url.copy_with(scheme="http", host="localhost")),
            headers={
                **{k: v for k, v in request.headers.items() if k != "host"},
                "Host": "localhost",
            },
            content=request.content,
        )
        return httpx.Response(result.status_code, headers=result.headers, content=result.content)

    services, _ = make_services(gateway=http_gateway(transport))
    now = datetime.now(UTC)
    session = services.sessions.create(
        operator={"operator_id": operator_id, "roles": ["ADMIN"]},
        tokens=ApiTokens(
            "TEST_ONLY_ACCESS",
            "TEST_ONLY_REFRESH",
            now + timedelta(hours=1),
            now + timedelta(hours=2),
        ),
        now=now,
    )
    with TestClient(create_web_app(services), base_url="http://testserver.local") as web:
        web.cookies.set(COOKIE_NAME, session.session_id)
        yield web, session.csrf_token


def test_studio_bff_through_api_socket_and_postgres_uses_same_saved_question(
    question_store, source_store, tmp_path
):
    command, photo = photo_command(question_store, source_store)
    with (
        question_api(question_store, tmp_path) as (api, state, _reads),
        studio_api(api, state.authentication.operator.operator_id) as (web, csrf_token),
    ):
        root = "/studio" + BASE
        headers = {
            "X-CSRF-Token": csrf_token,
            "Idempotency-Key": "web-question-" + uuid4().hex,
        }
        result = web.post(root, json=command.model_dump(mode="json"), headers=headers)
        assert result.status_code == 201, result.text
        q = result.json()["question"]
        assert (
            web.post(root, json=command.model_dump(mode="json"), headers=headers).json()["question"]
            == q
        )
        params = {"source_binding_id": q["source_binding_id"]}
        path = root + "/" + q["question_id"] + "/revisions/" + q["question_revision_id"]
        displayed = web.get(path, params=params)
        assert displayed.status_code == 200, displayed.text
        images = [b for b in displayed.json()["ordered_blocks"] if b["kind"] == "IMAGE"]
        assert len(images) == 2
        opened = web.get(path + "/images/" + images[0]["attachment_id"], params=params)
        assert opened.status_code == 200 and opened.content == photo
        assert opened.headers["etag"] == '"' + sha256_bytes(photo) + '"'
        review = dict(
            schema_version="kakao-question-edit/1.0",
            action="CONFIRM",
            parent_revision_id=q["question_revision_id"],
            reason="실제 BFF·원문 확인",
            boundary_confirmed=True,
        )
        params["room_id"] = q["room_id"]
        review_path = root + "/" + q["question_id"] + "/review"
        headers = {
            **headers,
            "Idempotency-Key": "web-review-" + uuid4().hex,
            "If-Match": '"v1"',
        }
        saved = web.post(review_path, params=params, json=review, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["question"]["review_state"] == "CONFIRMED"
        assert web.post(review_path, params=params, json=review, headers=headers).json()["replayed"]
        assert web.get(root, params=params).json()["items"] == [saved.json()["question"]]


def test_actual_http_photo_occurrences_are_pinned_native_bytes(
    question_store, source_store, tmp_path
):
    command, photo = photo_command(question_store, source_store)
    with question_api(question_store, tmp_path) as (client, _state, _reads):
        stored, _ = create(client, command)
        params, path = paths(stored)
        read = client.get(path, params=params)
        assert read.status_code == 200, read.text
        images = [
            block for block in read.json()["data"]["ordered_blocks"] if block["kind"] == "IMAGE"
        ]
        assert len(images) == 2 and images[0]["attachment_id"] != images[1]["attachment_id"]
        for block in images:
            response = client.get(path + "/images/" + block["attachment_id"], params=params)
            assert response.status_code == 200, response.text
            assert (
                response.content == photo
                and response.headers["etag"] == '"' + sha256_bytes(photo) + '"'
            )
            assert (
                response.headers["content-type"] == "image/png"
                and response.headers["cache-control"] == "no-store"
            )
            assert (
                client.get(
                    path + "/images/" + block["attachment_id"],
                    params={"source_binding_id": stored["source_binding_id"]},
                ).content
                == photo
            )
        denied = client.get(path + "/images/kakaoattachment_" + uuid4().hex, params=params)
        assert denied.status_code == 404 and photo not in denied.content
        wrong = client.get(
            path.replace(stored["question_revision_id"], "kakaoquestionrev_" + uuid4().hex),
            params=params,
        )
        assert wrong.status_code == 404
    with question_api(question_store, tmp_path, actor=make_actor(question_store[0])) as (
        foreign,
        *_,
    ):
        assert foreign.get(path, params=params).status_code == 404
        assert (
            foreign.get(path + "/images/" + images[0]["attachment_id"], params=params).status_code
            == 404
        )


def test_actual_http_current_identity_revocation_cannot_be_overridden_by_api_claims(
    question_store, tmp_path
):
    engine, actor, *_ = question_store
    with question_api(question_store, tmp_path) as (client, _state, _reads):
        stored, _ = create(client, question_store[3])
        params, path = paths(stored)
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        assert client.get(path, params=params).status_code == 403


def test_actual_http_photo_revoke_during_open_sends_no_image_and_closes_fd(
    question_store, source_store, tmp_path, monkeypatch
):
    engine, actor, _questions, _command, _sources, artifacts, _binding = question_store
    command, photo = photo_command(question_store, source_store)
    with question_api(question_store, tmp_path) as (client, _state, _reads):
        stored, _ = create(client, command)
        params, path = paths(stored)
        data = client.get(path, params=params).json()["data"]
        attachment = next(
            block["attachment_id"] for block in data["ordered_blocks"] if block["kind"] == "IMAGE"
        )
        original, descriptors = artifacts.open_verified_member, []

        def revoke(**kwargs):
            opened = original(**kwargs)
            descriptors.append(opened)
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC))
                )
            return opened

        monkeypatch.setattr(artifacts, "open_verified_member", revoke)
        result = client.get(path + "/images/" + attachment, params=params)
        assert result.status_code == 403 and photo not in result.content
        assert len(descriptors) == 1 and descriptors[0].stream.closed
