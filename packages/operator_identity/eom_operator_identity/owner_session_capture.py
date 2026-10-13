"""Closed owner-session transport values; parsing never mints a capture or admission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Final, Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

OWNER_SESSION_CAPTURE_SCHEMA_REF: Final = (
    "eom://schemas/identity/operator-owner-session-capture/1.0"
)
MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES: Final = 4 * 1024
MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES: Final = 8 * 1024
_RESOURCE: Final = "operator-owner-session-capture-v1.schema.json"
_UTC_PATTERN: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", re.ASCII
)
_TIME_FIELDS: Final = frozenset(
    {
        "observed_at",
        "issued_at",
        "access_expires_at",
        "authenticated_at",
        "absolute_expires_at",
        "idle_expires_at",
    }
)


@lru_cache(maxsize=1)
def _schema_bytes() -> bytes:
    with files("eom_operator_identity").joinpath("resources", _RESOURCE).open("rb") as source:
        raw = source.read(16 * 1024 + 1)
    if not raw or len(raw) > 16 * 1024:
        raise ValueError("owner-session schema resource exceeds its fixed bound")
    return raw


def owner_session_capture_schema() -> dict[str, Any]:
    """Return an independent copy of the sole public schema family, not an authority registry."""
    value: object = json.loads(_schema_bytes())
    if not isinstance(value, dict):
        raise ValueError("owner-session schema resource differs")
    return value


@lru_cache(maxsize=2)
def _validator(kind: Literal["request", "response"]) -> Draft202012Validator:
    schema = owner_session_capture_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        {"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]}, format_checker=FormatChecker()
    )


def _utc_datetime(value: object) -> datetime:
    if type(value) is str:
        if len(value) > 27 or _UTC_PATTERN.fullmatch(value) is None:
            raise ValueError("owner-session time must use bounded UTC Z notation")
        try:
            value = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError:
            raise ValueError("owner-session time is invalid") from None
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("owner-session time must be aware UTC")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, BeforeValidator(_utc_datetime)]
Sha256 = Annotated[
    str, Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$", min_length=71, max_length=71)
]


def _raw_values(value: object, expected: type[BaseModel]) -> dict[str, object]:
    """Inspect this flat bounded shape before any copied model serialization."""
    names = expected.model_fields
    if isinstance(value, BaseModel):
        if (
            not isinstance(value, expected)
            or value.__pydantic_extra__
            or set(value.__dict__) != set(names)
        ):
            raise ValueError("owner-session model has copied, missing or extra fields")
        result = {name: getattr(value, name) for name in names}
    elif type(value) is dict:
        if len(value) != len(names) or set(value) != set(names):
            raise ValueError("owner-session document must have its exact flat fields")
        result = dict(value)
    else:
        raise ValueError("owner-session values require the exact small object shape")
    for name, member in result.items():
        if name == "refresh_generation":
            if type(member) is not int or not 1 <= member <= 2147483647:
                raise ValueError("owner-session generation must be a bounded exact integer")
        elif name in _TIME_FIELDS:
            result[name] = _utc_datetime(member).isoformat().replace("+00:00", "Z")
        elif type(member) is not str or len(member) > 128:
            raise ValueError("owner-session fields must be bounded scalar strings")
    return result


class OwnerSessionCaptureRequest(BaseModel):
    """Operation-local challenge values, never a principal or permission grant."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["operator-owner-session-capture-request/1.0"]
    request_id: str = Field(
        strict=True, pattern=r"^ownercapture_[0-9a-f]{32}$", min_length=45, max_length=45
    )
    nonce: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    purpose: Literal["LOCAL_EMBEDDING_OPERATOR_SEED"]

    @model_validator(mode="before")
    @classmethod
    def raw_shape(cls, value: object) -> dict[str, object]:
        values = _raw_values(value, cls)
        _validator("request").validate(values)
        return values


class OwnerSessionCaptureResponse(BaseModel):
    """Claims requiring actual admitted provider/peer observation; no opaque minting API."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["operator-owner-session-capture-response/1.0"]
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
    def temporal_bindings(self) -> OwnerSessionCaptureResponse:
        if not (
            self.authenticated_at
            <= self.issued_at
            <= self.observed_at
            < min(self.access_expires_at, self.idle_expires_at)
            and self.access_expires_at <= self.absolute_expires_at
            and self.idle_expires_at <= self.absolute_expires_at
        ):
            raise ValueError("owner-session capture temporal bindings differ")
        return self


def _canonical(values: dict[str, object]) -> bytes:
    return json.dumps(
        values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def owner_session_capture_bytes(
    value: OwnerSessionCaptureRequest | OwnerSessionCaptureResponse,
) -> bytes:
    """Canonical wire values only; neither exporter provenance nor provider acceptance."""
    checked: OwnerSessionCaptureRequest | OwnerSessionCaptureResponse
    if isinstance(value, OwnerSessionCaptureRequest):
        checked = OwnerSessionCaptureRequest.model_validate(
            _raw_values(value, OwnerSessionCaptureRequest)
        )
        limit = MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES
    elif isinstance(value, OwnerSessionCaptureResponse):
        checked = OwnerSessionCaptureResponse.model_validate(
            _raw_values(value, OwnerSessionCaptureResponse)
        )
        limit = MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES
    else:
        raise ValueError("owner-session serializer requires a declared contract model")
    raw = _canonical(_raw_values(checked, type(checked)))
    if len(raw) > limit:
        raise ValueError("owner-session values exceed their fixed byte bound")
    return raw


def owner_session_capture_request_sha256(request: OwnerSessionCaptureRequest) -> str:
    checked = OwnerSessionCaptureRequest.model_validate(
        _raw_values(request, OwnerSessionCaptureRequest)
    )
    return "sha256:" + hashlib.sha256(owner_session_capture_bytes(checked)).hexdigest()


def validate_owner_session_capture_response(
    request: OwnerSessionCaptureRequest, response: OwnerSessionCaptureResponse
) -> OwnerSessionCaptureResponse:
    """Pure exact exchange binding, NOT authentication, admission or opaque capture minting."""
    expected = owner_session_capture_request_sha256(request)
    checked = OwnerSessionCaptureResponse.model_validate(
        _raw_values(response, OwnerSessionCaptureResponse)
    )
    if checked.request_sha256 != expected:
        raise ValueError("owner-session response names a different exact request")
    return checked


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("owner-session JSON contains a duplicate member")
        result[name] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("owner-session JSON contains a nonfinite number")


def _document(raw: bytes, limit: int) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError("owner-session wire requires bounded exact immutable bytes")
    # Both messages are flat. Deny containers before json.loads can allocate an
    # arbitrary nested input; braces within quoted strings are handled normally.
    quoted = escaped = False
    depth = 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            depth += 1
            if byte == 91 or depth > 1:
                raise ValueError("owner-session wire must be a flat scalar object")
        elif byte in (125, 93):
            depth -= 1
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("owner-session wire is invalid JSON") from None


def parse_owner_session_capture_request(raw: bytes) -> OwnerSessionCaptureRequest:
    checked = OwnerSessionCaptureRequest.model_validate(
        _document(raw, MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES)
    )
    if owner_session_capture_bytes(checked) != raw:
        raise ValueError("owner-session request is not exact canonical JSON")
    return checked


def parse_owner_session_capture_response(raw: bytes) -> OwnerSessionCaptureResponse:
    checked = OwnerSessionCaptureResponse.model_validate(
        _document(raw, MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES)
    )
    if owner_session_capture_bytes(checked) != raw:
        raise ValueError("owner-session response is not exact canonical JSON")
    return checked
