"""Closed exchange contracts and synthetic HMAC/socket provenance, not live authority."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_identity_service.owner_session_transport import (
    OwnerSessionTransportError,
    export_owner_session_capture,
    import_owner_session_capture,
    observe_owner_session_transport,
)
from eom_operator_identity import (
    OWNER_SESSION_CAPTURE_V11_SCHEMA_REF,
    OwnerSessionCaptureRequest,
    OwnerSessionCaptureRequestV11,
    OwnerSessionCaptureResponse,
    OwnerSessionCaptureResponseV11,
    owner_session_capture_bytes,
    owner_session_capture_v11_schema,
    parse_owner_session_capture_request,
    parse_owner_session_capture_response,
    parse_supported_owner_session_capture_request,
    parse_supported_owner_session_capture_response,
    supported_owner_session_capture_bytes,
    supported_owner_session_capture_request_sha256,
    validate_supported_owner_session_capture_response,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_authenticated_session_fence import SyntheticSession, verified_capture
from tests.unit.test_owner_session_capture_contracts import (
    request as legacy_request,
)
from tests.unit.test_owner_session_capture_contracts import (
    request_document,
    response_document,
)
from tests.unit.test_owner_session_capture_contracts import (
    response as legacy_response,
)
from tests.unit.test_owner_session_transport import PIN, SyntheticAdmission, SyntheticSocket

ROOT = Path(__file__).resolve().parents[2]
PURPOSES = ("REFERENCE_QUERY", "LOCAL_EMBEDDING_DEVICE_BENCHMARK")
REJECTIONS = (ValueError, SchemaError)


def request_v11(purpose="REFERENCE_QUERY"):
    return OwnerSessionCaptureRequestV11.model_validate(
        request_document()
        | {"schema_version": "operator-owner-session-capture-request/1.1", "purpose": purpose}
    )


def response_v11(purpose="REFERENCE_QUERY"):
    return OwnerSessionCaptureResponseV11.model_validate(
        response_document()
        | {
            "schema_version": "operator-owner-session-capture-response/1.1",
            "purpose": purpose,
            "request_sha256": supported_owner_session_capture_request_sha256(request_v11(purpose)),
        }
    )


def test_successor_frozen_schema_mirror_and_closed_purposes():
    raw = (ROOT / "schemas/identity/operator-owner-session-capture-v1_1.schema.json").read_bytes()
    assert (
        raw
        == (
            ROOT
            / "packages/operator_identity/eom_operator_identity/resources"
            / "operator-owner-session-capture-v1_1.schema.json"
        ).read_bytes()
    )
    assert hashlib.sha256(raw).hexdigest() == (
        "fa196b772abf756f0b4d646fa0a77f2be770a66801f1706bea474393e1d6c923"
    )
    schema = owner_session_capture_v11_schema()
    Draft202012Validator.check_schema(schema)
    assert schema == json.loads(raw) and schema["$id"] == OWNER_SESSION_CAPTURE_V11_SCHEMA_REF
    for kind in ("request", "response"):
        definition = schema["$defs"][kind]
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
        assert tuple(definition["properties"]["purpose"]["enum"]) == PURPOSES
    schema["$defs"]["request"]["properties"]["purpose"]["enum"].append("ADMIN")
    assert owner_session_capture_v11_schema()["$defs"]["request"]["properties"]["purpose"][
        "enum"
    ] == list(PURPOSES)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_exact_successor_round_trip_without_widening_legacy_parser(purpose):
    req, reply = request_v11(purpose), response_v11(purpose)
    for value, parser, legacy_parser in (
        (req, parse_supported_owner_session_capture_request, parse_owner_session_capture_request),
        (
            reply,
            parse_supported_owner_session_capture_response,
            parse_owner_session_capture_response,
        ),
    ):
        raw = supported_owner_session_capture_bytes(value)
        assert parser(raw) == value
        with pytest.raises(REJECTIONS):
            legacy_parser(raw)
        with pytest.raises(REJECTIONS):
            parser(b" " + raw)
    assert validate_supported_owner_session_capture_response(req, reply) == reply
    assert reply.verifier_digest not in repr(reply)


def test_successor_dispatch_preserves_predecessor_exact_bytes():
    for value, parser in (
        (legacy_request(), parse_supported_owner_session_capture_request),
        (legacy_response(), parse_supported_owner_session_capture_response),
    ):
        raw = owner_session_capture_bytes(value)
        assert supported_owner_session_capture_bytes(value) == raw
        assert parser(raw) == value
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureRequestV11.model_validate(legacy_request().model_dump(mode="json"))
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponseV11.model_validate(legacy_response().model_dump(mode="json"))


@pytest.mark.parametrize("change", ("version", "purpose", "hash", "nonce", "boolean", "extra"))
def test_mixed_exchange_or_copied_undeclared_authority_is_not_accepted(change):
    req, reply = request_v11(), response_v11()
    if change == "version":
        reply = legacy_response()
    elif change == "purpose":
        reply = reply.model_copy(update={"purpose": PURPOSES[1]})
    elif change == "hash":
        reply = reply.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    elif change == "nonce":
        req = req.model_copy(update={"nonce": "c" * 64})
    elif change == "boolean":
        reply = reply.model_copy(update={"refresh_generation": True})
    else:
        reply = reply.model_copy(update={"roles": ["ADMIN"]})
    with pytest.raises(REJECTIONS):
        validate_supported_owner_session_capture_response(req, reply)


@pytest.mark.parametrize("purpose", ("LOCAL_EMBEDDING_OPERATOR_SEED", "ADMIN", "", True))
def test_successor_does_not_infer_seed_or_general_authority(purpose):
    with pytest.raises(REJECTIONS):
        request_v11(purpose)


@pytest.mark.parametrize(
    "raw",
    (b"[]", b'{"schema_version":NaN}', b'{"x":1,"x":2}', b"{" * 1000 + b"}" * 1000),
)
@pytest.mark.parametrize(
    "parser",
    (parse_supported_owner_session_capture_request, parse_supported_owner_session_capture_response),
)
def test_supported_dispatch_rejects_nested_duplicate_or_nonfinite_wire(raw, parser):
    with pytest.raises(REJECTIONS):
        parser(raw)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_real_synthetic_hmac_export_held_peer_import_is_single_use(monkeypatch, purpose):
    _source, original = verified_capture(monkeypatch, SyntheticSession())
    req = request_v11(purpose)
    reply = export_owner_session_capture(req, original)
    assert isinstance(reply, OwnerSessionCaptureResponseV11) and reply.purpose == purpose
    with SyntheticSocket() as peer:
        observed = observe_owner_session_transport(
            request=req,
            response_raw=supported_owner_session_capture_bytes(reply),
            connection=peer,
            pin=PIN,
            admission=SyntheticAdmission(),
            verify_peer=lambda _: None,
            started_at=datetime.now(UTC) - timedelta(seconds=1),
            deadline=time.monotonic() + 9,
        )
        imported = import_owner_session_capture(observed)
        assert imported.operator_id == original.operator_id
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed)


def test_exporter_does_not_use_legacy_response_for_new_purpose(monkeypatch):
    _source, capture = verified_capture(monkeypatch, SyntheticSession())
    assert isinstance(
        export_owner_session_capture(legacy_request(), capture), OwnerSessionCaptureResponse
    )
    response = export_owner_session_capture(request_v11(), capture)
    assert not isinstance(response, OwnerSessionCaptureResponse)
    assert not isinstance(request_v11(), OwnerSessionCaptureRequest)


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("mutation", ("purpose", "version", "closed_peer", "provider"))
def test_import_rechecks_exact_successor_and_live_transport_origin(monkeypatch, purpose, mutation):
    _source, capture = verified_capture(monkeypatch, SyntheticSession())
    req = request_v11(purpose)
    admission = SyntheticAdmission()
    with SyntheticSocket() as peer:
        observed = observe_owner_session_transport(
            request=req,
            response_raw=supported_owner_session_capture_bytes(
                export_owner_session_capture(req, capture)
            ),
            connection=peer,
            pin=PIN,
            admission=admission,
            verify_peer=lambda _: None,
            started_at=datetime.now(UTC) - timedelta(seconds=1),
            deadline=time.monotonic() + 9,
        )
        if mutation == "purpose":
            other_purpose = PURPOSES[1] if purpose == PURPOSES[0] else PURPOSES[0]
            object.__setattr__(observed._origin.response, "purpose", other_purpose)
        elif mutation == "version":
            object.__setattr__(
                observed._origin.response,
                "schema_version",
                "operator-owner-session-capture-response/1.0",
            )
        elif mutation == "closed_peer":
            peer.close()
        else:
            admission.fail = True
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed)
