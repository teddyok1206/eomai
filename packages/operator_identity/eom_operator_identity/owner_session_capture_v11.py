"""Closed purpose successor and literal transport dispatch; never authentication or a grant."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_operator_identity.owner_session_capture import (
    MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
    MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
    OwnerSessionCaptureRequest,
    OwnerSessionCaptureResponse,
    Sha256,
    UtcDatetime,
    _canonical,
    _document,
    _raw_values,
    owner_session_capture_bytes,
    validate_owner_session_capture_response,
)

OWNER_SESSION_CAPTURE_V11_SCHEMA_REF = "eom://schemas/identity/operator-owner-session-capture/1.1"
type OwnerSessionCapturePurposeV11 = Literal["REFERENCE_QUERY", "LOCAL_EMBEDDING_DEVICE_BENCHMARK"]


@lru_cache(maxsize=1)
def _schema_bytes() -> bytes:
    raw = (
        files("eom_operator_identity")
        .joinpath("resources", "operator-owner-session-capture-v1_1.schema.json")
        .read_bytes()
    )
    if not 0 < len(raw) <= 16 * 1024:
        raise ValueError("owner-session successor schema exceeds its fixed bound")
    return raw


def owner_session_capture_v11_schema() -> dict[str, Any]:
    value: object = json.loads(_schema_bytes())
    if not isinstance(value, dict):
        raise ValueError("owner-session successor schema differs")
    return value


@lru_cache(maxsize=2)
def _validator(kind: Literal["request", "response"]) -> Draft202012Validator:
    schema = owner_session_capture_v11_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        {"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    )


class OwnerSessionCaptureRequestV11(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["operator-owner-session-capture-request/1.1"]
    request_id: str = Field(
        strict=True, pattern=r"^ownercapture_[0-9a-f]{32}$", min_length=45, max_length=45
    )
    nonce: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    purpose: OwnerSessionCapturePurposeV11

    @model_validator(mode="before")
    @classmethod
    def raw_shape(cls, value: object) -> dict[str, object]:
        values = _raw_values(value, cls)
        _validator("request").validate(values)
        return values


class OwnerSessionCaptureResponseV11(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["operator-owner-session-capture-response/1.1"]
    purpose: OwnerSessionCapturePurposeV11
    request_sha256: Sha256
    observed_at: UtcDatetime
    operator_id: str = Field(
        strict=True, pattern=r"^operator_[0-9a-f]{32}$", min_length=41, max_length=41
    )
    session_id: str = Field(
        strict=True, pattern=r"^apisession_[0-9a-f]{32}$", min_length=43, max_length=43
    )
    access_token_id: str = Field(
        strict=True, pattern=r"^apitoken_[0-9a-f]{32}$", min_length=41, max_length=41
    )
    verifier_digest: Sha256 = Field(repr=False)
    issued_at: UtcDatetime
    access_expires_at: UtcDatetime
    authenticated_at: UtcDatetime
    absolute_expires_at: UtcDatetime
    idle_expires_at: UtcDatetime
    refresh_generation: int = Field(strict=True, ge=1, le=2147483647)

    @model_validator(mode="before")
    @classmethod
    def raw_shape(cls, value: object) -> dict[str, object]:
        values = _raw_values(value, cls)
        _validator("response").validate(values)
        return values

    @model_validator(mode="after")
    def temporal_bindings(self) -> OwnerSessionCaptureResponseV11:
        if not (
            self.authenticated_at
            <= self.issued_at
            <= self.observed_at
            < min(self.access_expires_at, self.idle_expires_at)
            and self.access_expires_at <= self.absolute_expires_at
            and self.idle_expires_at <= self.absolute_expires_at
        ):
            raise ValueError("owner-session successor temporal bindings differ")
        return self


type SupportedOwnerSessionCaptureRequest = (
    OwnerSessionCaptureRequest | OwnerSessionCaptureRequestV11
)
type SupportedOwnerSessionCaptureResponse = (
    OwnerSessionCaptureResponse | OwnerSessionCaptureResponseV11
)


def supported_owner_session_capture_bytes(
    value: SupportedOwnerSessionCaptureRequest | SupportedOwnerSessionCaptureResponse,
) -> bytes:
    if isinstance(value, (OwnerSessionCaptureRequest, OwnerSessionCaptureResponse)):
        return owner_session_capture_bytes(value)
    checked: OwnerSessionCaptureRequestV11 | OwnerSessionCaptureResponseV11
    if isinstance(value, OwnerSessionCaptureRequestV11):
        checked = OwnerSessionCaptureRequestV11.model_validate(_raw_values(value, type(value)))
        maximum = MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES
    elif isinstance(value, OwnerSessionCaptureResponseV11):
        checked = OwnerSessionCaptureResponseV11.model_validate(_raw_values(value, type(value)))
        maximum = MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES
    else:
        raise ValueError("unsupported owner-session capture type")
    raw = _canonical(_raw_values(checked, type(checked)))
    if len(raw) > maximum:
        raise ValueError("owner-session successor exceeds its byte bound")
    return raw


def supported_owner_session_capture_request_sha256(
    request: SupportedOwnerSessionCaptureRequest,
) -> str:
    if type(request) not in (OwnerSessionCaptureRequest, OwnerSessionCaptureRequestV11):
        raise ValueError("owner-session hash requires a declared request")
    return "sha256:" + hashlib.sha256(supported_owner_session_capture_bytes(request)).hexdigest()


def validate_supported_owner_session_capture_response(
    request: SupportedOwnerSessionCaptureRequest, response: SupportedOwnerSessionCaptureResponse
) -> SupportedOwnerSessionCaptureResponse:
    if isinstance(request, OwnerSessionCaptureRequest) and isinstance(
        response, OwnerSessionCaptureResponse
    ):
        return validate_owner_session_capture_response(request, response)
    if not isinstance(request, OwnerSessionCaptureRequestV11) or not isinstance(
        response, OwnerSessionCaptureResponseV11
    ):
        raise ValueError("owner-session exchange versions differ")
    checked_request = OwnerSessionCaptureRequestV11.model_validate(
        _raw_values(request, type(request))
    )
    checked = OwnerSessionCaptureResponseV11.model_validate(_raw_values(response, type(response)))
    if (
        checked.purpose != checked_request.purpose
        or checked.request_sha256 != supported_owner_session_capture_request_sha256(checked_request)
    ):
        raise ValueError("owner-session response purpose or exact request differs")
    return checked


def parse_supported_owner_session_capture_request(
    raw: bytes,
) -> SupportedOwnerSessionCaptureRequest:
    value = _document(raw, MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES)
    if not isinstance(value, dict):
        raise ValueError("owner-session request requires a flat object")
    checked: SupportedOwnerSessionCaptureRequest
    if value.get("schema_version") == "operator-owner-session-capture-request/1.0":
        checked = OwnerSessionCaptureRequest.model_validate(value)
    elif value.get("schema_version") == "operator-owner-session-capture-request/1.1":
        checked = OwnerSessionCaptureRequestV11.model_validate(value)
    else:
        raise ValueError("unsupported owner-session request version")
    if supported_owner_session_capture_bytes(checked) != raw:
        raise ValueError("owner-session request is not canonical")
    return checked


def parse_supported_owner_session_capture_response(
    raw: bytes,
) -> SupportedOwnerSessionCaptureResponse:
    value = _document(raw, MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES)
    if not isinstance(value, dict):
        raise ValueError("owner-session response requires a flat object")
    checked: SupportedOwnerSessionCaptureResponse
    if value.get("schema_version") == "operator-owner-session-capture-response/1.0":
        checked = OwnerSessionCaptureResponse.model_validate(value)
    elif value.get("schema_version") == "operator-owner-session-capture-response/1.1":
        checked = OwnerSessionCaptureResponseV11.model_validate(value)
    else:
        raise ValueError("unsupported owner-session response version")
    if supported_owner_session_capture_bytes(checked) != raw:
        raise ValueError("owner-session response is not canonical")
    return checked
