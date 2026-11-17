"""Synthetic admitted CSV/photos→real API/UDS/PG→separate PDF process→authorized download."""

import os
from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import uuid4

import pymupdf
import pytest
from eom_catalog_contracts.kakao_export_store import KakaoExportProfile
from eom_catalog_service.kakao_delivery_application import KakaoDeliveryApplication
from eom_catalog_service.kakao_export_service import KakaoExportService
from eom_catalog_service.kakao_packet_service import KakaoPacketService
from eom_catalog_service.kakao_pdf_coordinator import KakaoPdfCoordinator
from eom_catalog_service.kakao_pdf_delivery import KakaoPdfDelivery
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_question_http import photo_command, question_api, studio_api
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.integration.test_kakao_stored_student_pdf import RELEASE, RenderProcess, font

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
BASE = "/api/v1/kakao-archive"


class StoppedLocalRender(RenderProcess):
    """subprocess.run has waited for this exact child; not privileged OS acceptance."""

    def __init__(self):
        super().__init__()
        self.finished = set()

    def run(self, command, workspace):
        super().run(command, workspace)
        self.finished.add(command.execution.attempt_id)

    def stopped(self, command, workspace):
        assert workspace.name == command.execution.attempt_id
        assert command.execution.attempt_id in self.finished


@contextmanager
def delivery_api(question_store, tmp_path, *, launcher=None):
    engine, _actor, questions, _initial, sources, artifacts, _binding = question_store
    packets = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    font_path, member = font(tmp_path)
    profile = KakaoExportProfile(
        renderer_release_sha256=RELEASE,
        font_sha256=member.sha256,
        font_size_bytes=member.size_bytes,
    )
    exports = KakaoExportService(
        engine, artifacts=artifacts, packets=packets, sources=sources, profile=profile
    )
    inputs = artifacts.settings.staging_root / ("pdf-inputs-" + uuid4().hex)
    workspace = tmp_path / ("pdf-work-" + uuid4().hex)
    inputs.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    launcher = launcher or StoppedLocalRender()
    driver = KakaoPdfDelivery(
        exports,
        artifacts,
        inputs,
        workspace,
        font_path,
        member,
        os.getuid(),
        os.getgid(),
        launcher,
        launcher.stopped,
    )
    coordinator = KakaoPdfCoordinator(driver)
    application = KakaoDeliveryApplication(packets, exports, coordinator.submit)
    with question_api(question_store, tmp_path, delivery=application) as (api, _state, _reads):
        yield api, coordinator, launcher, exports, driver, application


def create_packet(api, qcommand, *, final=False):
    result = api.post(
        BASE + "/questions",
        json=qcommand.model_dump(mode="json"),
        headers={"Idempotency-Key": "delivery-question-" + uuid4().hex},
    )
    assert result.status_code == 201, result.text
    question = result.json()["data"]["question"]
    if final:
        result = api.post(
            BASE + "/questions/" + question["question_id"] + "/review",
            params={key: question[key] for key in ("source_binding_id", "room_id")},
            json=dict(
                schema_version="kakao-question-edit/1.0",
                action="CONFIRM",
                parent_revision_id=question["question_revision_id"],
                reason="원문과 첨부 확인",
                boundary_confirmed=True,
            ),
            headers={"Idempotency-Key": "delivery-confirm-" + uuid4().hex, "If-Match": '"v1"'},
        )
        assert result.status_code == 200, result.text
        question = result.json()["data"]["question"]
    command = dict(
        schema_version="kakao-packet-create/1.0",
        source_binding_id=qcommand.source_binding_id,
        title="사진 질문 자료",
        questions=[{key: question[key] for key in ("question_id", "question_revision_id")}],
        display_start_date=str(date(2026, 1, 1)),
        display_end_date_inclusive=str(date(2026, 12, 31)),
        mode="FINAL" if final else "DRAFT",
        include_replies=False,
    )
    headers = {"Idempotency-Key": "delivery-packet-" + uuid4().hex}
    result = api.post(BASE + "/question-packets", json=command, headers=headers)
    assert result.status_code == 201, result.text
    packet = result.json()["data"]["packet"]
    assert (
        api.post(BASE + "/question-packets", json=command, headers=headers).json()["data"]["packet"]
        == packet
    )
    return packet, question


def request_export(api, packet, student):
    command = dict(
        schema_version="kakao-export-create/1.0",
        source_binding_id=packet["source_binding_id"],
        packet_id=packet["packet_id"],
        packet_revision_id=packet["packet_revision_id"],
        student_id=student,
    )
    headers = {"Idempotency-Key": "delivery-export-" + uuid4().hex}
    result = api.post(BASE + "/exports", json=command, headers=headers)
    assert result.status_code == 202, result.text
    return result.json()["data"]["export"], command, headers


def test_actual_http_photo_pdf_replay_and_current_download_authority(
    question_store, source_store, tmp_path
):
    qcommand, _photo = photo_command(question_store, source_store)
    with delivery_api(question_store, tmp_path) as (
        api,
        coordinator,
        launcher,
        _exports,
        _driver,
        _application,
    ):
        packet, question = create_packet(api, qcommand, final=True)
        params = {"source_binding_id": packet["source_binding_id"]}
        view = api.get(
            BASE
            + "/question-packets/"
            + packet["packet_id"]
            + "/revisions/"
            + packet["packet_revision_id"],
            params=params,
        )
        assert view.status_code == 200, view.text
        assert view.json()["data"]["students"][0]["student_id"] == question["student"]["student_id"]
        assert view.json()["data"]["questions"] == [
            {key: question[key] for key in ("question_id", "question_revision_id")}
        ]
        exported, command, headers = request_export(api, packet, question["student"]["student_id"])
        assert exported["state"] == "PENDING"
        assert coordinator.advance_once() == "COMPLETED"
        path = BASE + "/exports/" + exported["export_id"]
        result = api.get(path, params=params)
        assert result.status_code == 200, result.text
        completed = result.json()["data"]
        assert completed["state"] == "COMPLETED" and completed["page_count"] == 1
        for _ in range(2):
            opened = api.get(
                path + "/file", params={**params, "revision_id": completed["export_revision_id"]}
            )
            assert opened.status_code == 200, opened.text
            assert opened.headers["etag"] == '"' + completed["pdf"]["sha256"] + '"'
            with pymupdf.open(stream=opened.content, filetype="pdf") as pdf:
                assert len(pdf) == 1 and len(pdf[0].get_images(full=True)) == 2
        assert (
            api.post(BASE + "/exports", json=command, headers=headers).json()["data"]["export"]
            == completed
        )
        assert coordinator.advance_once() == "IDLE" and launcher.calls == 1
        assert (
            api.get(
                path + "/file", params={**params, "revision_id": "kakaoexportrev_" + "9" * 32}
            ).status_code
            == 409
        )
        engine, actor, *_ = question_store
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        assert (
            api.get(
                path + "/file", params={**params, "revision_id": completed["export_revision_id"]}
            ).status_code
            == 403
        )


def test_http_publication_interruption_recovers_same_attempt_without_render(
    question_store, tmp_path, monkeypatch
):
    with delivery_api(question_store, tmp_path) as (
        api,
        coordinator,
        launcher,
        exports,
        _driver,
        _application,
    ):
        packet, question = create_packet(api, question_store[3])
        original = exports.complete_export

        def interrupted(*args, **kwargs):
            raise RuntimeError("synthetic adoption interruption")

        monkeypatch.setattr(exports, "complete_export", interrupted)
        exported, command, headers = request_export(api, packet, question["student"]["student_id"])
        assert coordinator.advance_once() == "ERROR" and launcher.calls == 1
        params = {"source_binding_id": packet["source_binding_id"]}
        path = BASE + "/exports/" + exported["export_id"]
        assert api.get(path, params=params).json()["data"]["state"] == "RUNNING"
        monkeypatch.setattr(exports, "complete_export", original)
        assert api.post(BASE + "/exports", json=command, headers=headers).status_code == 202
        assert coordinator.advance_once() == "COMPLETED" and launcher.calls == 1
        result = api.get(path, params=params).json()["data"]
        assert api.get(
            path + "/file", params={**params, "revision_id": result["export_revision_id"]}
        ).content.startswith(b"%PDF-")


def test_actual_studio_packet_student_pdf_download_and_same_request_replay(
    question_store, source_store, tmp_path
):
    qcommand, _photo = photo_command(question_store, source_store)
    with (
        delivery_api(question_store, tmp_path) as (
            api,
            coordinator,
            launcher,
            _exports,
            _driver,
            _app,
        ),
        studio_api(api, question_store[1].operator_id) as (web, csrf),
    ):
        root = "/studio/api/v1/kakao-archive"

        def post(path, body, key):
            return web.post(
                root + path, json=body, headers={"X-CSRF-Token": csrf, "Idempotency-Key": key}
            )

        candidates = web.get(
            root + "/questions/candidates",
            params={
                "source_binding_id": qcommand.source_binding_id,
                "room_id": qcommand.room_id,
            },
        )
        assert candidates.status_code == 200, candidates.text
        candidate_page = candidates.json()
        assert candidate_page["source_revision_id"] == qcommand.source_revision_id
        assert candidate_page["items"][0]["photo_count"] == 2
        qcommand = qcommand.model_copy(
            update={
                "source_revision_id": candidate_page["source_revision_id"],
                "candidate_ordinal": candidate_page["items"][0]["candidate_ordinal"],
                "expected_mapping_revision_id": candidate_page["mapping_revision_id"],
            }
        )
        created = post(
            "/questions", qcommand.model_dump(mode="json"), "studio-question-" + uuid4().hex
        )
        assert created.status_code == 201, created.text
        question = created.json()["question"]
        body = dict(
            schema_version="kakao-packet-create/1.0",
            source_binding_id=qcommand.source_binding_id,
            title="Studio 실제 다운로드 검증",
            questions=[{key: question[key] for key in ("question_id", "question_revision_id")}],
            display_start_date="2026-01-01",
            display_end_date_inclusive="2026-12-31",
            mode="DRAFT",
            include_replies=False,
        )
        key = "studio-packet-" + uuid4().hex
        assert (
            web.post(
                root + "/question-packets", json=body, headers={"Idempotency-Key": key}
            ).status_code
            == 403
        )
        stored = post("/question-packets", body, key)
        assert stored.status_code == 201, stored.text
        packet = stored.json()["packet"]
        assert post("/question-packets", body, key).json()["packet"] == packet
        params = {"source_binding_id": qcommand.source_binding_id}
        viewed = web.get(
            root
            + "/question-packets/"
            + packet["packet_id"]
            + "/revisions/"
            + packet["packet_revision_id"],
            params=params,
        )
        assert viewed.status_code == 200, viewed.text
        student = viewed.json()["students"][0]
        request = dict(
            schema_version="kakao-export-create/1.0",
            source_binding_id=qcommand.source_binding_id,
            packet_id=packet["packet_id"],
            packet_revision_id=packet["packet_revision_id"],
            student_id=student["student_id"],
        )
        key = "studio-export-" + uuid4().hex
        exported = post("/exports", request, key)
        assert exported.status_code == 202, exported.text
        assert coordinator.advance_once() == "COMPLETED"
        path = root + "/exports/" + exported.json()["export"]["export_id"]
        completed = web.get(path, params=params)
        assert completed.status_code == 200, completed.text
        value = completed.json()
        file_params = {**params, "revision_id": value["export_revision_id"]}
        first = web.get(path + "/file", params=file_params)
        second = web.get(path + "/file", params=file_params)
        assert first.status_code == second.status_code == 200, (
            first.text if first.status_code != 200 else second.text
        )
        assert (
            first.content == second.content
            and first.headers["etag"] == '"' + value["pdf"]["sha256"] + '"'
        )
        assert first.headers["cache-control"] == "no-store"
        with pymupdf.open(stream=first.content, filetype="pdf") as pdf:
            assert len(pdf) == 1 and len(pdf[0].get_images(full=True)) == 2
        assert post("/exports", request, key).json()["export"] == value
        assert coordinator.advance_once() == "IDLE" and launcher.calls == 1
        assert web.get(root + "/exports", params=params).json()["items"] == [value]
