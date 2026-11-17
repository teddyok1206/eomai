"""Small saved-study transport reuses owners; no worker or browser authority expansion."""

import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_delivery_rpc import (
    KAKAO_STUDY_ERRORS,
    CreateKakaoStudyExportRequest,
    KakaoDeliverySuccess,
    KakaoStudyView,
    ListKakaoStudiesRequest,
    ReadKakaoStudyExportRequest,
    ReadKakaoStudyRequest,
    ReadKakaoStudySelectionRequest,
    SaveKakaoStudyRequest,
    check_kakao_delivery_reply,
    parse_kakao_delivery_reply,
    parse_kakao_delivery_request,
)
from eom_catalog_contracts.kakao_study_export import KakaoStudyExport, KakaoStudyExportMutation
from eom_catalog_contracts.kakao_study_store import KakaoStudyMutation, KakaoStudyPage
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_delivery_dispatch import dispatch_kakao_delivery
from eom_identifiers import sha256_bytes
from jsonschema.exceptions import ValidationError

from tests.unit.test_kakao_question_rpc import IDENTITY
from tests.unit.test_kakao_study_export import command as export_command
from tests.unit.test_kakao_study_export_contracts import study_export
from tests.unit.test_kakao_study_store import command, identity, stored

ROOT = Path(__file__).resolve().parents[2]


def cases():
    study = stored()
    exported = KakaoStudyExport(
        study=export_command().study,
        export=study_export().model_copy(
            update={"source_binding_id": export_command().source_binding_id}
        ),
    )
    return (
        (
            SaveKakaoStudyRequest(
                **IDENTITY, command=command(), idempotency_key="study-rpc-fixture-0001"
            ),
            KakaoStudyMutation(study=study, replayed=True),
            "save",
        ),
        (
            ReadKakaoStudyRequest(
                **IDENTITY,
                source_binding_id=study.source_binding_id,
                study_id=study.study_id,
                study_revision_id=study.study_revision_id,
            ),
            KakaoStudyView(study=study, questions=command().questions),
            "read",
        ),
        (
            ListKakaoStudiesRequest(**IDENTITY, source_binding_id=study.source_binding_id),
            KakaoStudyPage(items=(study,), next_cursor=None),
            "list",
        ),
        (
            CreateKakaoStudyExportRequest(
                **IDENTITY, command=export_command(), idempotency_key="study-rpc-fixture-0001"
            ),
            KakaoStudyExportMutation(result=exported, replayed=True),
            "export",
        ),
        (
            ReadKakaoStudyExportRequest(
                **IDENTITY,
                source_binding_id=exported.export.source_binding_id,
                export_id=exported.export.export_id,
            ),
            exported,
            "read-export",
        ),
        (
            ReadKakaoStudySelectionRequest(
                **IDENTITY,
                source_binding_id=study.source_binding_id,
                packet_id=study.packet_id,
                packet_revision_id=study.packet_revision_id,
                student_id=study.student_id,
            ),
            command(),
            "selection",
        ),
    )


def test_schema_mirror_hash():
    path = "kakao-archive/catalog-kakao-study-v1.schema.json"
    raw = (ROOT / "schemas" / path).read_bytes()
    assert (
        raw
        == (ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / path).read_bytes()
    )
    assert sha256_bytes(raw) == CATALOG_SCHEMA_RESOURCES["catalog-kakao-study-v1"].sha256


@pytest.mark.parametrize("req,result,name", cases())
def test_actual_dispatch_uses_existing_owner_and_closed_correlation(req, result, name):
    app, out = Mock(), io.BytesIO()
    method = {
        "save": app.study_owner.return_value.save_study,
        "read": app.read_study,
        "list": app.study_owner.return_value.list_studies,
        "export": app.request_study_export,
        "read-export": app.export_owner.return_value.read_study_export,
        "selection": app.read_study_selection,
    }[name]
    method.return_value = result
    payload = req.model_dump(mode="json")
    assert parse_kakao_delivery_request(payload) == req
    dispatch_kakao_delivery(app, payload, out)
    reply = parse_kakao_delivery_reply(json.loads(out.getvalue()))
    assert reply.status == "OK" and reply.result == result
    check_kakao_delivery_reply(req, reply)
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions


@pytest.mark.parametrize("req,result,_name", cases())
def test_other_binding_reply_rejected(req, result, _name):
    data = json.dumps(result.model_dump(mode="json"))
    binding = req.command.source_binding_id if hasattr(req, "command") else req.source_binding_id
    changed = json.loads(data.replace(binding, identity("kakaobinding", 999)))
    reply = KakaoDeliverySuccess(operation=req.operation, request_id=req.request_id, result=changed)
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_delivery_reply(req, reply)


@pytest.mark.parametrize(
    "field,value",
    [("roles", ["ADMIN"]), ("slot", "05"), ("path", "/mnt/nas/private"), ("latest", True)],
)
def test_caller_cannot_extend_scope(field, value):
    request = cases()[0][0]
    application, out = Mock(), io.BytesIO()
    dispatch_kakao_delivery(application, request.model_dump(mode="json") | {field: value}, out)
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not application.mock_calls


@pytest.mark.parametrize("code", sorted(KAKAO_STUDY_ERRORS))
def test_study_errors_are_stable_without_private_content(code):
    request = cases()[0][0]
    application, out = Mock(), io.BytesIO()
    application.study_owner.return_value.save_study.side_effect = KakaoArchiveError(code)
    dispatch_kakao_delivery(application, request.model_dump(mode="json"), out)
    reply = parse_kakao_delivery_reply(json.loads(out.getvalue()))
    assert reply.status == "ERROR" and reply.error_code == code
    assert "직접 작성한 메모" not in out.getvalue().decode()


def test_bad_operation_container_is_schema_failure_not_uncaught_type_error():
    with pytest.raises(ValidationError):
        parse_kakao_delivery_request({"operation": []})
