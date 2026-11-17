"""Schema-first input metadata, no runtime provider/model interaction."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_capture_intake import (
    ConfirmKakaoManualCapture,
    KakaoManualCapturePage,
)
from eom_catalog_contracts.kakao_capture_rpc import (
    ListKakaoCapturesReply,
    ListKakaoCapturesRequest,
    check_kakao_capture_reply,
    parse_kakao_capture_reply,
    parse_kakao_capture_request,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_capture_dispatch import dispatch_kakao_capture
from eom_identifiers import sha256_bytes


def request():
    return ListKakaoCapturesRequest(
        actor_id="operator_" + "1" * 32,
        session_id="apisession_" + "2" * 32,
        request_id="capture-request",
        authentication_time=datetime.now(UTC),
        source_binding_id="kakaobinding_" + "3" * 32,
    )


def test_schema_mirrors_and_closed_identity():
    root = Path(__file__).resolve().parents[2]
    for name in ("kakao-manual-capture-intake-v1", "catalog-kakao-capture-v1"):
        entry = CATALOG_SCHEMA_RESOURCES[name]
        raw = (root / entry.canonical_path).read_bytes()
        assert sha256_bytes(raw) == entry.sha256
        assert (
            raw
            == (
                root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
            ).read_bytes()
        )
    value = request()
    assert parse_kakao_capture_request(value.model_dump(mode="json")) == value
    service = Mock()
    service.list_captures.return_value = KakaoManualCapturePage(
        source_binding_id=value.source_binding_id,
        binding_resource_version=1,
        items=(),
        truncated=False,
    )
    reply = parse_kakao_capture_reply(
        json.loads(dispatch_kakao_capture(service, value.model_dump(mode="json")))
    )
    check_kakao_capture_reply(value, reply)
    assert service.list_captures.call_args.args[0].permissions == frozenset()


@pytest.mark.parametrize("field", ["permissions", "role", "root", "cookie", "provider_key"])
def test_public_wire_cannot_supply_execution_authority(field):
    service = Mock()
    value = request().model_dump(mode="json") | {field: "forged"}
    result = json.loads(dispatch_kakao_capture(service, value))
    assert result["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    service.list_captures.assert_not_called()


def test_wrong_binding_or_correlation_and_invalid_service_reply_rejected():
    value = request()
    page = KakaoManualCapturePage(
        source_binding_id="kakaobinding_" + "f" * 32,
        binding_resource_version=1,
        items=(),
        truncated=False,
    )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_capture_reply(
            value, ListKakaoCapturesReply(request_id=value.request_id, result=page)
        )
    service = Mock()
    service.list_captures.return_value = page
    reply = json.loads(dispatch_kakao_capture(service, value.model_dump(mode="json")))
    assert reply["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and reply["result"] is None


@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_confirmation_is_explicit_and_not_coerced(confirmed):
    with pytest.raises(ValueError):
        ConfirmKakaoManualCapture(
            source_binding_id=request().source_binding_id,
            manual_lease_id="kakaoremotelease_" + "4" * 32,
            capture_id="kakaodownload_" + "5" * 32,
            expected_preview_sha256="sha256:" + "a" * 64,
            expected_binding_version=1,
            display_name="익명 방",
            channel_and_room_confirmed=confirmed,
        )
