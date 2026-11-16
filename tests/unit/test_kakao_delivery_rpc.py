"""Closed packet/PDF messages, exact result correlation and bounded wake-up ownership."""

import io
import json
import threading
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_delivery_rpc import (
    CreateKakaoExportRequest,
    KakaoPacketStudent,
    KakaoPacketView,
    ListKakaoExportsRequest,
    ListKakaoPacketsRequest,
    ReadKakaoExportPdfRequest,
    ReadKakaoExportRequest,
    ReadKakaoPacketRequest,
    SaveKakaoPacketRequest,
    parse_kakao_delivery_reply,
    parse_kakao_delivery_request,
)
from eom_catalog_contracts.kakao_export_store import KakaoExportMutation, KakaoExportPage
from eom_catalog_contracts.kakao_packet_store import KakaoPacketMutation, KakaoPacketPage
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_delivery_dispatch import dispatch_kakao_delivery
from eom_catalog_service.kakao_pdf_coordinator import KakaoPdfCoordinator
from eom_catalog_service.kakao_pdf_delivery import KakaoPdfDelivery
from eom_identifiers import sha256_bytes
from pydantic import ValidationError

from tests.unit.test_kakao_export_store_contracts import export_request, pending_export
from tests.unit.test_kakao_packet_store_contracts import create_packet, stored_packet
from tests.unit.test_kakao_question_editing import packet, question
from tests.unit.test_kakao_question_rpc import IDENTITY


def packet_view():
    return KakaoPacketView(
        packet=stored_packet(),
        questions=create_packet().questions,
        students=(
            KakaoPacketStudent(
                student_id="kakaostudent_" + "1" * 32,
                student_display_revision_id="kakaostudentrev_" + "1" * 32,
                display_name="학생",
                question_count=1,
            ),
        ),
    )


def case(name):
    packet, export = stored_packet(), pending_export()
    if name == "save":
        return SaveKakaoPacketRequest(
            **IDENTITY, command=create_packet(), idempotency_key="delivery-fixture-0001"
        ), KakaoPacketMutation(packet=packet, replayed=True)
    if name == "read-packet":
        return ReadKakaoPacketRequest(
            **IDENTITY,
            source_binding_id=packet.source_binding_id,
            packet_id=packet.packet_id,
            packet_revision_id=packet.packet_revision_id,
        ), packet_view()
    if name == "list-packets":
        return ListKakaoPacketsRequest(
            **IDENTITY, source_binding_id=packet.source_binding_id
        ), KakaoPacketPage(items=(packet,), next_cursor=None)
    if name == "create-export":
        return CreateKakaoExportRequest(
            **IDENTITY, command=export_request(), idempotency_key="delivery-fixture-0001"
        ), KakaoExportMutation(export=export, replayed=True)
    if name == "read-export":
        return ReadKakaoExportRequest(
            **IDENTITY, source_binding_id=export.source_binding_id, export_id=export.export_id
        ), export
    if name == "list-exports":
        return ListKakaoExportsRequest(
            **IDENTITY, source_binding_id=export.source_binding_id
        ), KakaoExportPage(items=(export,), next_cursor=None)
    return ReadKakaoExportPdfRequest(
        **IDENTITY,
        source_binding_id=export.source_binding_id,
        export_id=export.export_id,
        export_revision_id="kakaoexportrev_" + "1" * 32,
    ), None


def owner(name, result):
    application = Mock()
    method = {
        "save": application.packets.save_packet,
        "read-packet": application.read_packet,
        "list-packets": application.packets.list_packets,
        "create-export": application.request_export,
        "read-export": application.export_owner.return_value.get_export,
        "list-exports": application.export_owner.return_value.list_exports,
        "pdf": application.export_owner.return_value.open_pdf,
    }[name]
    method.return_value = result
    return application, method


@pytest.mark.parametrize(
    "name", ["save", "read-packet", "list-packets", "create-export", "read-export", "list-exports"]
)
def test_dispatch_uses_existing_owner_with_no_claimed_authority(name):
    request, result = case(name)
    application, method = owner(name, result)
    out = io.BytesIO()
    payload = request.model_dump(mode="json")
    assert parse_kakao_delivery_request(payload) == request
    dispatch_kakao_delivery(application, payload, out)
    reply = parse_kakao_delivery_reply(json.loads(out.getvalue()))
    assert reply.status == "OK" and reply.result == result
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions


@pytest.mark.parametrize(
    "field,value",
    [("roles", ["ADMIN"]), ("font_path", "/private/font"), ("profile", {}), ("worker_uid", 0)],
)
def test_browser_cannot_supply_runtime_or_role_grants(field, value):
    request, _ = case("create-export")
    app = Mock()
    out = io.BytesIO()
    dispatch_kakao_delivery(app, {**request.model_dump(mode="json"), field: value}, out)
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not app.mock_calls


@pytest.mark.parametrize(
    "name", ["read-packet", "read-export", "list-packets", "list-exports", "save", "create-export"]
)
def test_valid_but_unrelated_result_never_reaches_caller(name):
    request, result = case(name)
    if name == "read-packet":
        result = result.model_copy(
            update={
                "packet": result.packet.model_copy(
                    update={"packet_revision_id": "kakaopacketrev_" + "9" * 32}
                )
            }
        )
    elif name == "read-export":
        result = result.model_copy(update={"export_id": "kakaoexport_" + "9" * 32})
    elif name == "save":
        result = result.model_copy(
            update={"packet": result.packet.model_copy(update={"title": "other"})}
        )
    elif name == "create-export":
        result = result.model_copy(
            update={
                "export": result.export.model_copy(
                    update={"student_id": "kakaostudent_" + "9" * 32}
                )
            }
        )
    else:
        result = result.model_copy(
            update={
                "items": tuple(
                    row.model_copy(update={"source_binding_id": "kakaobinding_" + "9" * 32})
                    for row in result.items
                )
            }
        )
    app, _ = owner(name, result)
    out = io.BytesIO()
    dispatch_kakao_delivery(app, request.model_dump(mode="json"), out)
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID"


def test_pdf_is_streamed_only_after_correlated_descriptor_and_always_closed():
    request, _ = case("pdf")
    raw = b"%PDF-synthetic"
    stream = io.BytesIO(raw)
    member = Mock(content_length=len(raw), sha256=sha256_bytes(raw), stream=stream)
    member.iter_chunks.return_value = iter((raw,))
    app, _ = owner("pdf", member)
    out = io.BytesIO()
    dispatch_kakao_delivery(app, request.model_dump(mode="json"), out)
    header, data = out.getvalue().split(b"\n", 1)
    result = parse_kakao_delivery_reply(json.loads(header))
    assert result.status == "OK" and result.result.export_revision_id == request.export_revision_id
    assert data == raw and stream.closed
    member.stream = io.BytesIO(raw)
    broken = Mock()
    broken.write.side_effect = BrokenPipeError()
    with pytest.raises(BrokenPipeError):
        dispatch_kakao_delivery(app, request.model_dump(mode="json"), broken)
    assert member.stream.closed


def test_unknown_error_has_no_private_content():
    request, result = case("save")
    app, method = owner("save", result)
    method.side_effect = RuntimeError("private student and message")
    out = io.BytesIO()
    dispatch_kakao_delivery(app, request.model_dump(mode="json"), out)
    assert b"private student" not in out.getvalue()
    assert json.loads(out.getvalue())["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"


def test_root_domain_refusal_is_preserved_without_validation_input():
    with pytest.raises(ValidationError) as caught:
        packet((question(),), mode="FINAL")
    request, result = case("save")
    app, method = owner("save", result)
    method.side_effect = caught.value
    out = io.BytesIO()
    dispatch_kakao_delivery(app, request.model_dump(mode="json"), out)
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_ARCHIVE_FINAL_BLOCKED"
    assert b"input_value" not in out.getvalue()


def test_coordinator_bounds_deduplicates_and_never_overlaps_execution():
    delivery = Mock(spec=KakaoPdfDelivery)
    queued = KakaoPdfCoordinator(delivery, capacity=1)
    actor = Mock(operator_id=IDENTITY["actor_id"])
    queued.submit(actor, "binding", "export")
    queued.submit(actor, "binding", "export")
    with pytest.raises(KakaoArchiveError, match="CAPACITY_BUSY"):
        queued.submit(actor, "binding", "other")
    entered, release = threading.Event(), threading.Event()

    def run(*_args):
        entered.set()
        assert release.wait(timeout=5)
        return pending_export()

    delivery.run.side_effect = run
    worker = threading.Thread(target=queued.advance_once)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        assert queued.advance_once() == "WAITING"
        queued.submit(actor, "binding", "export")
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and delivery.run.call_count == 1
    assert queued.advance_once() == "IDLE"
