"""Protocol-only synthetic values; no provider/opaque capture or runtime admission."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from eom_operator_identity import (
    MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
    MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
    OWNER_SESSION_CAPTURE_SCHEMA_REF,
    OwnerSessionCaptureRequest,
    OwnerSessionCaptureResponse,
    owner_session_capture_bytes,
    owner_session_capture_request_sha256,
    owner_session_capture_schema,
    parse_owner_session_capture_request,
    parse_owner_session_capture_response,
    validate_owner_session_capture_response,
)
from eom_operator_identity import owner_session_capture as contract
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
REJECTIONS = (ValueError, SchemaError)


def request_document() -> dict[str, object]:
    return {
        "schema_version": "operator-owner-session-capture-request/1.0",
        "request_id": "ownercapture_" + "a" * 32,
        "nonce": "b" * 64,
        "purpose": "LOCAL_EMBEDDING_OPERATOR_SEED",
    }


def request() -> OwnerSessionCaptureRequest:
    return OwnerSessionCaptureRequest.model_validate(request_document())


def response_document() -> dict[str, object]:
    return {
        "schema_version": "operator-owner-session-capture-response/1.0",
        "request_sha256": owner_session_capture_request_sha256(request()),
        "observed_at": "2026-10-13T00:00:02Z",
        "operator_id": "operator_" + "1" * 32,
        "session_id": "apisession_" + "2" * 32,
        "access_token_id": "apitoken_" + "3" * 32,
        "verifier_digest": "sha256:" + "4" * 64,
        "issued_at": "2026-10-13T00:00:01Z",
        "access_expires_at": "2026-10-13T00:30:00Z",
        "authenticated_at": "2026-10-13T00:00:00Z",
        "absolute_expires_at": "2026-10-14T00:00:00Z",
        "idle_expires_at": "2026-10-13T01:00:00Z",
        "refresh_generation": 5,
    }


def response() -> OwnerSessionCaptureResponse:
    return OwnerSessionCaptureResponse.model_validate(response_document())


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_exact_schema_mirror_registration_and_packaging() -> None:
    canonical_path = ROOT / "schemas/identity/operator-owner-session-capture-v1.schema.json"
    packaged_path = (
        ROOT
        / "packages/operator_identity/eom_operator_identity/resources"
        / "operator-owner-session-capture-v1.schema.json"
    )
    raw = canonical_path.read_bytes()
    assert raw == packaged_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "bb7571ce9decf18cff2d99e4dc13f2d92f1c237c65ab05fe243ce4d27fac4436"
    )
    schema = owner_session_capture_schema()
    assert schema == json.loads(raw)
    assert schema["$id"] == OWNER_SESSION_CAPTURE_SCHEMA_REF
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(schema["$defs"]) == {"sha256", "utcDatetime", "request", "response"}
    Draft202012Validator.check_schema(schema)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["tool"]["setuptools"]["package-data"]["eom_operator_identity"] == [
        "resources/operator-owner-session-capture-v1.schema.json"
    ]
    schema["$defs"]["request"]["properties"]["purpose"]["const"] = "FORGED"
    assert (
        owner_session_capture_schema()["$defs"]["request"]["properties"]["purpose"]["const"]
        == "LOCAL_EMBEDDING_OPERATOR_SEED"
    )
    assert request().purpose == "LOCAL_EMBEDDING_OPERATOR_SEED"


def test_canonical_values_exact_request_hash_and_response_binding() -> None:
    req, reply = request(), response()
    raw = canonical(request_document())
    assert owner_session_capture_bytes(req) == raw
    assert owner_session_capture_request_sha256(req) == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert parse_owner_session_capture_request(raw) == req
    assert parse_owner_session_capture_response(owner_session_capture_bytes(reply)) == reply
    assert validate_owner_session_capture_response(req, reply) == reply
    validator = Draft202012Validator(owner_session_capture_schema(), format_checker=FormatChecker())
    validator.validate(request_document())
    validator.validate(response_document())
    assert len(raw) < MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES
    assert len(owner_session_capture_bytes(reply)) < MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES
    assert reply.verifier_digest not in repr(reply)


@pytest.mark.parametrize(
    "field", ["raw_token", "key", "roles", "permissions", "grant", "runtime", "path", "operator_id"]
)
def test_request_rejects_authority_credentials_and_extra_fields(field: str) -> None:
    document = request_document()
    document[field] = "forbidden"
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureRequest.model_validate(document)


@pytest.mark.parametrize(
    "field", ["raw_token", "key", "roles", "permissions", "grant", "runtime", "path", "purpose"]
)
def test_response_rejects_authority_credentials_and_extra_fields(field: str) -> None:
    document = response_document()
    document[field] = "forbidden"
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "ownercapture_" + "A" * 32),
        ("request_id", "operator_" + "a" * 32),
        ("nonce", "b" * 63),
        ("nonce", "B" * 64),
        ("nonce", True),
        ("purpose", "LOCAL_EMBEDDING_INDEX"),
        ("schema_version", "1.0"),
    ],
)
def test_request_exact_purpose_and_bounded_raw_fields(field: str, value: object) -> None:
    document = request_document()
    document[field] = value
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureRequest.model_validate(document)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", 0, -1, 2147483648, None])
def test_exact_generation_not_boolean_or_coerced(value: object) -> None:
    document = response_document()
    document["refresh_generation"] = value
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(document)


@pytest.mark.parametrize(
    "field", ["operator_id", "session_id", "access_token_id", "verifier_digest", "request_sha256"]
)
def test_response_exact_identity_and_digest_patterns(field: str) -> None:
    document = response_document()
    document[field] = "forged"
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(document)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-13T00:00:02",
        "2026-10-13T00:00:02+00:00",
        "2026-10-13T09:00:02+09:00",
        "2026-02-30T00:00:02Z",
        "2026-10-13T00:00:02.1234567Z",
        True,
        datetime(2026, 10, 13),
        datetime(2026, 10, 13, tzinfo=UTC) + timedelta(days=2),
    ],
)
def test_time_utc_format_and_actual_binding(value: object) -> None:
    document = response_document()
    document["observed_at"] = value
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authenticated_at", "2026-10-13T00:00:03Z"),
        ("issued_at", "2026-10-13T00:00:03Z"),
        ("access_expires_at", "2026-10-13T00:00:02Z"),
        ("idle_expires_at", "2026-10-13T00:00:02Z"),
        ("absolute_expires_at", "2026-10-13T00:10:00Z"),
    ],
)
def test_response_temporal_closure(field: str, value: str) -> None:
    document = response_document()
    document[field] = value
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(document)


def test_changed_nonce_id_and_hash_are_not_same_exchange() -> None:
    for field, value in (("nonce", "c" * 64), ("request_id", "ownercapture_" + "d" * 32)):
        changed = request_document()
        changed[field] = value
        with pytest.raises(ValueError, match="different exact request"):
            validate_owner_session_capture_response(
                OwnerSessionCaptureRequest.model_validate(changed), response()
            )
    with pytest.raises(ValueError, match="different exact request"):
        validate_owner_session_capture_response(
            request(), response().model_copy(update={"request_sha256": "sha256:" + "f" * 64})
        )


@pytest.mark.parametrize(
    "parser,value",
    [
        (parse_owner_session_capture_request, canonical(request_document()).decode()),
        (parse_owner_session_capture_request, bytearray(canonical(request_document()))),
        (parse_owner_session_capture_request, memoryview(canonical(request_document()))),
        (parse_owner_session_capture_response, "{}"),
        (parse_owner_session_capture_response, bytearray(b"{}")),
        (parse_owner_session_capture_response, memoryview(b"{}")),
    ],
)
def test_wire_requires_exact_bytes(parser: Any, value: object) -> None:
    with pytest.raises(ValueError, match="exact immutable bytes"):
        parser(value)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b'{"schema_version":"x","schema_version":"x"}',
        b'{"nonce":NaN}',
        b'{"nonce":Infinity}',
        b'{"nonce":-Infinity}',
        b"\xff",
        b"",
        b"{" * 1000 + b"}" * 1000,
    ],
)
def test_malformed_duplicate_deep_and_nonfinite_wire(raw: bytes) -> None:
    with pytest.raises(REJECTIONS):
        parse_owner_session_capture_request(raw)


def test_wire_canonical_and_byte_caps_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = owner_session_capture_bytes(request())
    with pytest.raises(ValueError, match="exact canonical"):
        parse_owner_session_capture_request(b" " + raw)
    pretty = json.dumps(request_document(), indent=2).encode()
    with pytest.raises(ValueError, match="exact canonical"):
        parse_owner_session_capture_request(pretty)

    def deny_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JSON allocation occurred before the raw byte/container gate")

    monkeypatch.setattr(json, "loads", deny_load)
    for parser, maximum in (
        (parse_owner_session_capture_request, MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES),
        (parse_owner_session_capture_response, MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES),
    ):
        with pytest.raises(ValueError):
            parser(b" " * (maximum + 1))
        with pytest.raises(ValueError, match="flat scalar object"):
            parser(b'{"nested":{"bad":1}}')


def test_copied_constructed_boolean_missing_and_extra_fail_before_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req, reply = request(), response()
    malformed_reply = reply.model_copy(update={"refresh_generation": True})
    constructed_reply = OwnerSessionCaptureResponse.model_construct(
        None, **{**response_document(), "refresh_generation": True}
    )
    malformed_req = req.model_copy(update={"nonce": True})
    extra_req = req.model_copy(update={"roles": ["ADMIN"]})

    def deny_dump(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("raw copied fields were not checked before serialization")

    monkeypatch.setattr(BaseModel, "model_dump", deny_dump)
    for value in (malformed_reply, constructed_reply, malformed_req, extra_req):
        with pytest.raises(REJECTIONS):
            owner_session_capture_bytes(value)
    with pytest.raises(REJECTIONS):
        validate_owner_session_capture_response(req, malformed_reply)
    with pytest.raises(REJECTIONS):
        owner_session_capture_request_sha256(malformed_req)
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureRequest.model_validate(OwnerSessionCaptureRequest.model_construct())
    with pytest.raises(REJECTIONS):
        owner_session_capture_request_sha256(cast(OwnerSessionCaptureRequest, reply))


def test_flat_python_cycles_and_container_fields_are_rejected() -> None:
    cycle: dict[str, object] = {}
    cycle["nonce"] = cycle
    for value in (
        cycle,
        {**request_document(), "nonce": cycle},
        {**request_document(), "nonce": [[[]]]},
    ):
        with pytest.raises(REJECTIONS):
            OwnerSessionCaptureRequest.model_validate(value)
    copied = deepcopy(response_document())
    copied["verifier_digest"] = {"nested": "sha256:" + "e" * 64}
    with pytest.raises(REJECTIONS):
        OwnerSessionCaptureResponse.model_validate(copied)


def test_contract_has_no_authority_or_infrastructure_dependency() -> None:
    module_path = Path(contract.__file__ or "")
    assert module_path.is_file()
    tree = ast.parse(module_path.read_text())
    imported = {
        entry.name if isinstance(node, ast.Import) else node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for entry in (node.names if isinstance(node, ast.Import) else [ast.alias(name="")])
    }
    for prefix in (
        "eom_identity_service",
        "eom_orchestrator",
        "eom_catalog_service",
        "eom_workflow_runner",
        "eomctl",
        "sqlalchemy",
        "socket",
        "subprocess",
        "torch",
        "transformers",
    ):
        assert not any(name == prefix or name.startswith(prefix + ".") for name in imported)
    code = (
        "import sys; import eom_operator_identity.owner_session_capture; "
        "assert not any(k.split('.')[0] in {'torch','transformers','eom_identity_service',"
        "'eom_catalog_service','eom_workflow_runner','eom_orchestrator'} for k in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, "pure contract import acquired infrastructure or ML"


def test_parsed_response_is_only_dto_not_opaque_capture() -> None:
    parsed = parse_owner_session_capture_response(owner_session_capture_bytes(response()))
    from eom_identity_service import AuthenticatedOperatorSession

    assert not isinstance(parsed, AuthenticatedOperatorSession)
    with pytest.raises(ValueError, match="CAPTURE_UNAVAILABLE"):
        AuthenticatedOperatorSession()
    assert not hasattr(parsed, "assert_current")
    assert not hasattr(parsed, "capture_access")
