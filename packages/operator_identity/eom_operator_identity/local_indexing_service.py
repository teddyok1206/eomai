"""Purpose-specific service metadata; these values never authenticate or grant access."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, ClassVar, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_operator_identity.contracts import UtcDatetime

LOCAL_INDEXING_SERVICE_SCHEMA_REF: Final = "eom://schemas/identity/local-indexing-service/1.0"
MAX_LOCAL_INDEXING_SERVICE_BYTES: Final = 4 * 1024
_RESOURCE: Final = "local-indexing-service-v1.schema.json"
_Kind = Literal["identity", "reference", "status"]

ServiceId = Annotated[
    str,
    Field(strict=True, pattern=r"^localindexservice_[0-9a-f]{32}$", min_length=50, max_length=50),
]
ServiceRevisionId = Annotated[
    str,
    Field(
        strict=True, pattern=r"^localindexservicerev_[0-9a-f]{32}$", min_length=53, max_length=53
    ),
]
Sha256 = Annotated[
    str, Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$", min_length=71, max_length=71)
]
PositiveVersion = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class LocalIndexingServiceErrorCode(StrEnum):
    CONTRACT_INVALID = "LOCAL_INDEXING_SERVICE_CONTRACT_INVALID"
    HASH_MISMATCH = "LOCAL_INDEXING_SERVICE_HASH_MISMATCH"
    INACTIVE = "LOCAL_INDEXING_SERVICE_INACTIVE"
    STALE_REVISION = "LOCAL_INDEXING_SERVICE_STALE_REVISION"
    REVISION_CONFLICT = "LOCAL_INDEXING_SERVICE_REVISION_CONFLICT"


class LocalIndexingServiceError(ValueError):
    def __init__(self, code: LocalIndexingServiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> LocalIndexingServiceError:
    return LocalIndexingServiceError(LocalIndexingServiceErrorCode.CONTRACT_INVALID, message)


@lru_cache(maxsize=1)
def _schema_bytes() -> bytes:
    with files("eom_operator_identity").joinpath("resources", _RESOURCE).open("rb") as source:
        raw = source.read(16 * 1024 + 1)
    if not raw or len(raw) > 16 * 1024:
        raise _invalid("local indexing service schema exceeds its fixed bound")
    return raw


def local_indexing_service_schema() -> dict[str, Any]:
    """Return an independent schema document, not an installed authority registry."""
    value: object = json.loads(_schema_bytes())
    if not isinstance(value, dict):
        raise _invalid("local indexing service schema is not an object")
    return value


@lru_cache(maxsize=3)
def _validator(kind: _Kind) -> Draft202012Validator:
    schema = local_indexing_service_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        {"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]}, format_checker=FormatChecker()
    )


def _raw_values(value: object, expected: type[_ServiceValue]) -> dict[str, object]:
    """Inspect copied/constructed models before serialization can discard extra fields."""
    names = expected.model_fields
    if type(value) is expected:
        if value.__pydantic_extra__ or set(value.__dict__) != set(names):
            raise _invalid("local indexing service model has missing or extra fields")
        values = {name: getattr(value, name) for name in names}
    elif type(value) is dict:
        if len(value) != len(names) or set(value) != set(names):
            raise _invalid("local indexing service document requires its exact fields")
        values = dict(value)
    else:
        raise _invalid("local indexing service value requires its declared object shape")
    for name, member in values.items():
        if name in {"revision_number", "resource_version"}:
            if type(member) is not int or not 1 <= member <= 2147483647:
                raise _invalid("local indexing service version must be a bounded exact integer")
        elif name == "current":
            if member is not None:
                values[name] = _raw_values(member, LocalIndexingServiceReference)
        elif member is None and name == "previous_service_revision_id":
            continue
        elif name in {"created_at", "updated_at"} and type(member) is datetime:
            if member.utcoffset() != timedelta(0):
                raise _invalid("local indexing service timestamp must be aware UTC")
            values[name] = (
                member.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
            )
        elif type(member) is not str or len(member) > 128:
            raise _invalid("local indexing service fields must be bounded scalar strings")
    return values


def _schema_values(value: object, expected: type[_ServiceValue]) -> dict[str, object]:
    values = _raw_values(value, expected)
    try:
        _validator(expected._kind).validate(values)
    except SchemaError:
        raise _invalid("local indexing service value differs from its closed schema") from None
    return values


class _ServiceValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    _kind: ClassVar[_Kind]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, object]:
        return _schema_values(value, cls)


class LocalIndexingServiceIdentity(_ServiceValue):
    """Immutable identity metadata, not proof of caller identity or data permissions."""

    _kind = "identity"
    schema_version: Literal["local-indexing-service-identity/1.0"]
    service_id: ServiceId
    service_revision_id: ServiceRevisionId
    previous_service_revision_id: ServiceRevisionId | None
    revision_number: PositiveVersion
    purpose: Literal["LOCAL_EMBEDDING_INDEX"]
    runtime_user: Literal["eom-workflow-runner"]
    database_role: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,62}$", max_length=63)
    runtime_source_commit: str = Field(
        strict=True, pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40
    )
    created_at: UtcDatetime
    content_sha256: Sha256

    @model_validator(mode="after")
    def immutable_bindings(self) -> LocalIndexingServiceIdentity:
        if self.previous_service_revision_id == self.service_revision_id:
            raise _invalid("local indexing service revision cannot be its own predecessor")
        if self.content_sha256 != local_indexing_service_identity_sha256(self):
            raise LocalIndexingServiceError(
                LocalIndexingServiceErrorCode.HASH_MISMATCH,
                "local indexing service identity content hash differs",
            )
        return self


class LocalIndexingServiceReference(_ServiceValue):
    """Exact small identity pointer; resolving it requires the Identity owner."""

    _kind = "reference"
    service_id: ServiceId
    service_revision_id: ServiceRevisionId
    service_identity_sha256: Sha256


class LocalIndexingServiceStatus(_ServiceValue):
    """Current-head projection, NOT evidence that a supplied principal is admitted."""

    _kind = "status"
    schema_version: Literal["local-indexing-service-status/1.0"]
    service_id: ServiceId
    state: Literal["ACTIVE", "DISABLED"]
    current: LocalIndexingServiceReference | None
    resource_version: PositiveVersion
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def same_logical_service(self) -> LocalIndexingServiceStatus:
        if self.current is not None and self.current.service_id != self.service_id:
            raise _invalid("local indexing service head points at another logical service")
        return self


def local_indexing_service_identity_sha256(value: object) -> str:
    """Hash schema-valid metadata excluding its hash, NOT validate authority or stored SHA.

    UTC timestamps normalize to six fractional digits, matching canonical EOM datetimes.
    A schema-valid placeholder SHA may be supplied while constructing a new revision.
    """
    values = _schema_values(value, LocalIndexingServiceIdentity)
    created_at = values["created_at"]
    assert isinstance(created_at, str)  # established by the closed schema
    values["created_at"] = (
        datetime.fromisoformat(created_at[:-1] + "+00:00")
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    del values["content_sha256"]
    return content_sha256(values)


def local_indexing_service_reference(
    value: LocalIndexingServiceIdentity,
) -> LocalIndexingServiceReference:
    checked = _checked(value, LocalIndexingServiceIdentity)
    return LocalIndexingServiceReference(
        service_id=checked.service_id,
        service_revision_id=checked.service_revision_id,
        service_identity_sha256=checked.content_sha256,
    )


def validate_local_indexing_service_successor(
    predecessor: LocalIndexingServiceIdentity, successor: LocalIndexingServiceIdentity
) -> LocalIndexingServiceIdentity:
    """Pure immutable-chain rule; registration/activation belongs to the Identity owner."""
    previous = _checked(predecessor, LocalIndexingServiceIdentity)
    checked = _checked(successor, LocalIndexingServiceIdentity)
    if (
        checked.service_id != previous.service_id
        or checked.service_revision_id == previous.service_revision_id
        or checked.previous_service_revision_id != previous.service_revision_id
        or checked.revision_number != previous.revision_number + 1
        or checked.created_at < previous.created_at
    ):
        raise LocalIndexingServiceError(
            LocalIndexingServiceErrorCode.REVISION_CONFLICT,
            "local indexing service successor does not extend the exact immutable predecessor",
        )
    return checked


def validate_local_indexing_service_current(
    status: LocalIndexingServiceStatus, identity: LocalIndexingServiceIdentity
) -> LocalIndexingServiceIdentity:
    """Check supplied metadata only, NOT authenticate a runtime or mint a capability.

    An owner must resolve and lock the current head, authenticate the actual DB/runtime
    principal and separately validate the released Catalog source grant in the same root.
    """
    head = _checked(status, LocalIndexingServiceStatus)
    checked = _checked(identity, LocalIndexingServiceIdentity)
    if head.state != "ACTIVE":
        raise LocalIndexingServiceError(
            LocalIndexingServiceErrorCode.INACTIVE, "local indexing service is disabled"
        )
    if head.current != local_indexing_service_reference(checked):
        raise LocalIndexingServiceError(
            LocalIndexingServiceErrorCode.STALE_REVISION,
            "local indexing service identity is not the exact current head",
        )
    if head.updated_at < checked.created_at:
        raise _invalid("local indexing service head predates its identity revision")
    return checked


def local_indexing_service_bytes(
    value: LocalIndexingServiceIdentity
    | LocalIndexingServiceReference
    | LocalIndexingServiceStatus,
) -> bytes:
    """Canonical bounded metadata, never credentials or a permission grant."""
    if type(value) not in (
        LocalIndexingServiceIdentity,
        LocalIndexingServiceReference,
        LocalIndexingServiceStatus,
    ):
        raise _invalid("local indexing service serialization requires a declared model")
    checked = _checked(value, type(value))
    raw = canonical_json_bytes(_raw_values(checked, type(checked)))
    if len(raw) > MAX_LOCAL_INDEXING_SERVICE_BYTES:
        raise _invalid("local indexing service metadata exceeds its fixed byte bound")
    return raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise _invalid("local indexing service JSON contains a duplicate member")
        result[name] = value
    return result


def _reject_constant(_value: str) -> object:
    raise _invalid("local indexing service JSON contains a nonfinite number")


def _checked[Value: _ServiceValue](value: object, expected: type[Value]) -> Value:
    return expected.model_validate(_raw_values(value, expected))


def _parse[Value: _ServiceValue](raw: bytes, expected: type[Value]) -> Value:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_SERVICE_BYTES:
        raise _invalid("local indexing service wire requires bounded immutable bytes")
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise _invalid("local indexing service wire is invalid JSON") from None
    checked = expected.model_validate(value)
    if canonical_json_bytes(_raw_values(checked, expected)) != raw:
        raise _invalid("local indexing service wire is not exact canonical JSON")
    return checked


def parse_local_indexing_service_identity(raw: bytes) -> LocalIndexingServiceIdentity:
    return _parse(raw, LocalIndexingServiceIdentity)


def parse_local_indexing_service_reference(raw: bytes) -> LocalIndexingServiceReference:
    return _parse(raw, LocalIndexingServiceReference)


def parse_local_indexing_service_status(raw: bytes) -> LocalIndexingServiceStatus:
    return _parse(raw, LocalIndexingServiceStatus)
