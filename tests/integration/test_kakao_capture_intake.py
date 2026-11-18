"""Real bounded local readers and room owner in guarded disposable PostgreSQL."""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_capture_intake import ConfirmKakaoManualCapture
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_capture_intake_service import KakaoCaptureIntakeService
from eom_catalog_service.kakao_source_service import KakaoSourceService
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.kakao_download_inputs import (
    list_kakao_download_ids,
    read_kakao_download_metadata,
)
from eom_orchestrator.models import ArtifactRecord
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_http import question_api, studio_api
from tests.integration.test_kakao_room_intake import h as h
from tests.integration.test_kakao_room_intake import intake as intake
from tests.unit.test_kakao_archive_rules import csv_bytes
from tests.unit.test_kakao_photo_alignment import GROUPS, document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def capture_intake(intake):
    def metadata(fence, capture):
        return read_kakao_download_metadata(
            root=intake.root,
            fence=fence,
            capture_id=capture,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
        )

    def ids(fence):
        return list_kakao_download_ids(
            root=intake.root, fence=fence, worker_uid=os.getuid(), control_gid=os.getgid()
        )

    return SimpleNamespace(
        intake=intake,
        service=KakaoCaptureIntakeService(
            intake.engine,
            intake=intake.service,
            read_download=intake.reader,
            read_metadata=metadata,
            list_capture_ids=ids,
        ),
    )


def prepare_photo_pair(store):
    messages = ["앞의 문항", "질문\r\n이어서", "사진", "사진", "답변", "뒤의 문항"]
    page = "kakaopage_" + uuid4().hex
    csv = store.prepare(
        payload=csv_bytes([["2026-11-18 20:01:00", "synthetic", body] for body in messages]),
        page=page,
        document=document(GROUPS),
        target=dict(kind="BLOB", path=None),
    )
    photo = store.prepare(
        channel="channel1",
        room="room1",
        page=page,
        document=document(GROUPS),
        target=dict(kind="SAME_ORIGIN_PATH", path=GROUPS[1][1]),
    )
    return dict(
        source_binding_id=csv.source_binding_id,
        manual_lease_id=csv.manual_lease_id,
        csv_capture_id=csv.capture_id,
        photo_capture_id=photo.capture_id,
    )


def test_exact_photo_pair_reads_verified_payloads_without_publishing(capture_intake):
    h, service = capture_intake.intake, capture_intake.service
    pair = prepare_photo_pair(h)
    with Session(h.engine) as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRecord))
    occurrence = service.inspect_photo_occurrence(h.actor, **pair)
    assert occurrence is not None and occurrence.row_ordinal == 3
    assert occurrence.association == "SEQUENCE_INFERRED"
    assert h.calls == [pair["csv_capture_id"], pair["photo_capture_id"]]
    assert service.inspect_photo_occurrence(h.actor, **pair) == occurrence
    with Session(h.engine) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == before


def test_photo_pair_other_operator_and_tampered_payload_fail(capture_intake):
    h, service = capture_intake.intake, capture_intake.service
    pair = prepare_photo_pair(h)
    other = make_actor(h.engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.inspect_photo_occurrence(other, **pair)
    assert not h.calls
    payload = h.run / pair["photo_capture_id"] / "payload.bin"
    original = payload.read_bytes()
    payload.write_bytes(b"!" + original[1:])
    with pytest.raises(KakaoArchiveError, match="MANUAL_CAPTURE_UNAVAILABLE"):
        service.inspect_photo_occurrence(h.actor, **pair)


def test_photo_pair_rechecks_current_actor_after_payload_reads(capture_intake, monkeypatch):
    h, service = capture_intake.intake, capture_intake.service
    pair = prepare_photo_pair(h)

    def revoked(fence, capture):
        result = h.reader(fence, capture)
        if capture == pair["photo_capture_id"]:
            with Session(h.engine) as session, session.begin():
                session.execute(
                    update(OperatorRecord)
                    .where(OperatorRecord.operator_id == h.actor.operator_id)
                    .values(must_change_password=True)
                )
        return result

    monkeypatch.setattr(service, "_read_download", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.inspect_photo_occurrence(h.actor, **pair)


def prepare_public(capture_intake):
    h = capture_intake.intake
    original = h.prepare()
    page = capture_intake.service.list_captures(h.actor, h.h.binding)
    item = next(i for i in page.items if i.capture_id == original.capture_id)
    return (
        ConfirmKakaoManualCapture(
            source_binding_id=h.h.binding,
            manual_lease_id=item.manual_lease_id,
            capture_id=item.capture_id,
            expected_preview_sha256=item.preview_sha256,
            expected_binding_version=page.binding_resource_version,
            display_name="익명 대화방",
            channel_and_room_confirmed=True,
        ),
        original,
        page,
    )


def test_metadata_listing_never_reads_payload_or_returns_provider_data(capture_intake, monkeypatch):
    import eom_orchestrator.kakao_download_inputs as inputs

    h = capture_intake.intake
    h.prepare()
    original = inputs.read_protected
    calls = []

    def bounded(path, **kwargs):
        calls.append(path.name)
        assert path.name != "payload.bin"
        return original(path, **kwargs)

    monkeypatch.setattr(inputs, "read_protected", bounded)
    page = capture_intake.service.list_captures(h.actor, h.h.binding)
    assert len(page.items) == 1 and page.items[0].state == "ROOM_IDENTITY_OBSERVED"
    assert not h.calls and "payload.bin" not in calls
    assert all(
        value not in page.model_dump_json()
        for value in ("channel-one", "room-one", "same-name", str(h.root), "document")
    )


def test_public_confirmation_replays_canonical_proof_after_local_files_removed(capture_intake):
    service, h = capture_intake.service, capture_intake.intake
    command, original, _ = prepare_public(capture_intake)
    key = "public-room-confirm-" + uuid4().hex
    first = service.confirm_capture(h.actor, command, idempotency_key=key)
    assert first.room.identity_level == "MANUAL_CONFIRMED" and not first.replayed
    assert h.calls == [original.capture_id]  # Payload materialized only by actual intake.
    folder = h.run / original.capture_id
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()
    replay = service.confirm_capture(h.actor, command, idempotency_key=key)
    assert replay.replayed and replay.room == first.room and h.calls == [original.capture_id]
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.confirm_capture(
            h.actor,
            command.model_copy(update=dict(expected_preview_sha256="sha256:" + "f" * 64)),
            idempotency_key=key,
        )


def test_old_capture_without_dom_cannot_be_silently_confirmed(capture_intake):
    h = capture_intake.intake
    original = h.prepare()
    (h.run / original.capture_id / "page-observation.json").unlink()
    page = capture_intake.service.list_captures(h.actor, h.h.binding)
    assert page.items[0].state == "NO_OBSERVATION" and page.items[0].preview_sha256 is None
    assert not h.calls


def test_other_owner_is_rejected_before_local_discovery(capture_intake, monkeypatch):
    h = capture_intake.intake
    other = make_actor(h.engine)
    monkeypatch.setattr(
        capture_intake.service, "list_capture_ids", lambda *_: pytest.fail("no cross-owner I/O")
    )
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        capture_intake.service.list_captures(other, h.h.binding)


def test_late_role_change_during_listing_does_not_return_private_metadata(
    capture_intake, monkeypatch
):
    h, service = capture_intake.intake, capture_intake.service
    h.prepare()
    original = service.read_metadata

    def revoked(*args):
        value = original(*args)
        with Session(h.engine) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == h.actor.operator_id)
                .values(must_change_password=True)
            )
        return value

    monkeypatch.setattr(service, "read_metadata", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.list_captures(h.actor, h.h.binding)


def test_changed_preview_rejected_before_artifact_or_room_admission(capture_intake):
    command, _, _ = prepare_public(capture_intake)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        capture_intake.service.confirm_capture(
            capture_intake.intake.actor,
            command.model_copy(update=dict(expected_preview_sha256="sha256:" + "0" * 64)),
            idempotency_key="changed-preview-" + uuid4().hex,
        )
    assert not capture_intake.intake.calls


def test_studio_api_socket_and_storage_confirm_same_room_with_csrf_and_replay(
    capture_intake, tmp_path
):
    h = capture_intake.intake
    h.prepare()

    # Reuse the real HTTP/socket/auth harness, without creating a second storage
    # fixture or running question/source business operations in this room test.
    def no_source_admission(*_args):
        raise PermissionError("source admission is not under test")

    sources = KakaoSourceService(
        h.engine, artifacts=h.artifacts, authorize_capture=no_source_admission
    )
    store = (h.engine, h.actor, None, None, sources, h.artifacts, None)
    with (
        question_api(store, tmp_path, actor=h.actor, captures=capture_intake.service) as (
            api,
            _state,
            _,
        ),
        studio_api(api, h.actor.operator_id) as (web, csrf),
    ):
        base = "/studio/api/v1/kakao-archive/manual-captures"
        read = web.get(base, params={"source_binding_id": h.h.binding})
        assert read.status_code == 200, read.text
        page = read.json()
        item = page["items"][0]
        assert item["state"] == "ROOM_IDENTITY_OBSERVED"
        command = dict(
            schema_version="kakao-manual-capture-confirm/1.0",
            source_binding_id=h.h.binding,
            manual_lease_id=item["manual_lease_id"],
            capture_id=item["capture_id"],
            expected_preview_sha256=item["preview_sha256"],
            expected_binding_version=page["binding_resource_version"],
            display_name="브라우저 확인 방",
            channel_and_room_confirmed=True,
        )
        headers = {
            "Idempotency-Key": "studio-capture-" + uuid4().hex,
            "If-Match": f'"v{page["binding_resource_version"]}"',
        }
        assert web.post(base + "/confirm-room", json=command, headers=headers).status_code == 403
        headers["X-CSRF-Token"] = csrf
        refused = web.post(
            base + "/confirm-room",
            json={**command, "channel_and_room_confirmed": False},
            headers=headers,
        )
        assert refused.status_code == 422
        saved = web.post(base + "/confirm-room", json=command, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.headers["cache-control"] == "no-store"
        again = web.post(base + "/confirm-room", json=command, headers=headers)
        assert again.status_code == 200 and again.json()["replayed"]
        assert again.json()["room"] == saved.json()["room"]
        bad = web.post(
            base + "/confirm-room", json=command, headers={**headers, "If-Match": '"v999"'}
        )
        assert bad.status_code == 412
