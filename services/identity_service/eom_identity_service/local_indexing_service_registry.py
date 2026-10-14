"""Identity control-plane owner operations, not service authentication or data grants.

Each operation joins an explicit caller root, qualifies app tables and uses bounded
waits. Only the actual authenticated table owner may write/read these controls;
runtime least-privilege fencing is a separate adapter, not an owner impersonation.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, cast

from eom_identifiers import content_sha256
from eom_operator_identity import (
    LocalIndexingServiceError,
    LocalIndexingServiceErrorCode,
    LocalIndexingServiceIdentity,
    LocalIndexingServiceReference,
    LocalIndexingServiceStatus,
    local_indexing_service_bytes,
    local_indexing_service_identity_sha256,
    local_indexing_service_reference,
    parse_local_indexing_service_identity,
    parse_local_indexing_service_reference,
    validate_local_indexing_service_current,
    validate_local_indexing_service_successor,
)
from eom_operator_identity.local_indexing_service import ServiceId
from psycopg.pq import TransactionStatus
from pydantic import TypeAdapter
from sqlalchemy import Table, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from eom_identity_service.local_indexing_fence_sql import (
    LOCAL_INDEXING_FENCE_BODY_SHA256,
    LOCAL_INDEXING_FENCE_CREATE_SQL,
    LOCAL_INDEXING_FENCE_GRANT_SQL,
    LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL,
    LocalIndexingFenceError,
    LocalIndexingFenceOwnerPin,
    require_local_indexing_fence_installation,
)
from eom_identity_service.local_indexing_service_models import (
    LocalIndexingServiceEventRecord,
    LocalIndexingServiceRecord,
    LocalIndexingServiceRevisionRecord,
)

_HEAD = cast(Table, LocalIndexingServiceRecord.__table__)
_REVISION = cast(Table, LocalIndexingServiceRevisionRecord.__table__)
_EVENT = cast(Table, LocalIndexingServiceEventRecord.__table__)
_SCHEMA = {None: "app"}
_SERVICE_ID = TypeAdapter(ServiceId)


class LocalIndexingControlOperation(StrEnum):
    REGISTER = "REGISTER"
    ACTIVATE = "ACTIVATE"
    DISABLE = "DISABLE"


@dataclass(frozen=True, slots=True)
class LocalIndexingControlResult:
    """Historical mutation result; never a current grant or authenticated principal."""

    operation_key: str
    operation: LocalIndexingControlOperation
    previous_state: Literal["ACTIVE", "DISABLED"] | None
    target: LocalIndexingServiceReference | None
    status_after_operation: LocalIndexingServiceStatus
    replayed: bool


@dataclass(frozen=True, slots=True)
class LocalIndexingFenceInstallationResult:
    disposition: Literal["CREATED", "REPLAYED"]
    owner: LocalIndexingFenceOwnerPin
    body_sha256: str


def _error(code: LocalIndexingServiceErrorCode, message: str) -> LocalIndexingServiceError:
    return LocalIndexingServiceError(code, message)


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error(
            LocalIndexingServiceErrorCode.CONTEXT_INVALID, "database UTC timestamp missing"
        )
    return value.astimezone(UTC)


@contextmanager
def _owner_operation(session: Session) -> Iterator[str]:
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or session.get_nested_transaction() is not None
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise _error(
            LocalIndexingServiceErrorCode.CONTEXT_INVALID, "explicit clean owner root required"
        )
    connection = session.connection()
    driver = connection.connection.driver_connection
    if (
        connection.dialect.name != "postgresql"
        or connection.dialect.driver != "psycopg"
        or not connection.in_transaction()
        or connection.in_nested_transaction()
        or getattr(driver, "autocommit", None) is not False
    ):
        raise _error(LocalIndexingServiceErrorCode.CONTEXT_INVALID, "PostgreSQL root required")
    context = (
        connection.execute(
            text(
                "SELECT SESSION_USER AS principal, CURRENT_USER AS role, "
                "pg_catalog.current_setting('transaction_isolation') AS isolation, "
                "pg_catalog.current_setting('transaction_read_only') AS read_only"
            )
        )
        .mappings()
        .one()
    )
    owners = connection.execute(
        text(
            "SELECT c.relname, r.rolname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_catalog.pg_roles r ON r.oid=c.relowner "
            "WHERE n.nspname='app' AND c.relkind='r' AND c.relname IN "
            "('local_indexing_services','local_indexing_service_revisions','local_indexing_service_events')"
        )
    ).all()
    principal = context["principal"]
    if (
        type(principal) is not str
        or context["role"] != principal
        or len(owners) != 3
        or any(owner != principal for _table, owner in owners)
    ):
        raise _error(
            LocalIndexingServiceErrorCode.OWNER_REQUIRED, "actual Identity table owner required"
        )
    if context["isolation"] != "read committed" or context["read_only"] != "off":
        raise _error(
            LocalIndexingServiceErrorCode.CONTEXT_INVALID, "read-committed writable root required"
        )
    limits = (
        connection.execute(
            text(
                "SELECT name, setting::pg_catalog.int8 AS milliseconds, "
                "pg_catalog.current_setting(name) AS previous FROM pg_catalog.pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout') AND unit='ms'"
            )
        )
        .mappings()
        .all()
    )
    previous: dict[str, str] = {}
    for limit in limits:
        name, actual = limit["name"], limit["milliseconds"]
        cap = 5000 if name == "lock_timeout" else 10000
        if type(actual) is not int or actual < 0:
            raise _error(LocalIndexingServiceErrorCode.CONTEXT_INVALID, "owner wait limits invalid")
        previous[name] = limit["previous"]
        connection.execute(
            text("SELECT pg_catalog.set_config(:name,:value,true)"),
            {
                "name": name,
                "value": str(min(actual, cap) if actual else cap) + "ms",
            },
        )
    if set(previous) != {"lock_timeout", "statement_timeout"}:
        raise _error(LocalIndexingServiceErrorCode.CONTEXT_INVALID, "owner wait limits missing")
    try:
        yield principal
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise _error(
                LocalIndexingServiceErrorCode.BUSY,
                "local indexing identity control wait expired; "
                "roll back before replaying the same key",
            ) from error
        raise
    finally:
        # A root lock timeout leaves PostgreSQL INERROR even when Session.is_active
        # remains true. Do not mask it with a second SET/25P02 or reconnect a lost
        # connection. SET LOCAL is cleared by the required caller root rollback.
        if (
            session.is_active
            and session.get_transaction() is root
            and root.is_active
            and not connection.invalidated
            and getattr(driver, "closed", True) is False
            and getattr(getattr(driver, "info", None), "transaction_status", None)
            == TransactionStatus.INTRANS
        ):
            for name, value in previous.items():
                connection.execute(
                    text("SELECT pg_catalog.set_config(:name,:value,true)"),
                    {
                        "name": name,
                        "value": value,
                    },
                )


def _key(value: str) -> None:
    if (
        type(value) is not str
        or not 3 <= len(value) <= 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]+", value) is None
    ):
        raise _error(
            LocalIndexingServiceErrorCode.CONTRACT_INVALID, "bounded operation key required"
        )


def _version(value: int) -> None:
    if type(value) is not int or not 1 <= value < 2147483647:
        raise _error(
            LocalIndexingServiceErrorCode.VERSION_CONFLICT, "expected resource version invalid"
        )


def _head(session: Session, service_id: str, *, shared: bool = False) -> Mapping[str, Any]:
    row = (
        session.execute(
            select(_HEAD)
            .where(_HEAD.c.service_id == service_id)
            .with_for_update(read=shared)
            .execution_options(schema_translate_map=_SCHEMA)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(LocalIndexingServiceErrorCode.NOT_FOUND, "local indexing service is missing")
    return dict(row)


def _revision(session: Session, service_id: str, revision_id: str) -> LocalIndexingServiceIdentity:
    row = (
        session.execute(
            select(_REVISION)
            .where(
                _REVISION.c.service_id == service_id,
                _REVISION.c.service_revision_id == revision_id,
            )
            .execution_options(schema_translate_map=_SCHEMA)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(LocalIndexingServiceErrorCode.NOT_FOUND, "exact service revision is missing")
    values = dict(row)
    values["created_at"] = _utc(values["created_at"])
    try:
        expected = local_indexing_service_identity_sha256(values)
        if values["content_sha256"] != expected:
            raise _error(LocalIndexingServiceErrorCode.HASH_MISMATCH, "stored service hash differs")
        return LocalIndexingServiceIdentity.model_validate(values)
    except LocalIndexingServiceError:
        raise
    except ValueError:
        raise _error(
            LocalIndexingServiceErrorCode.CONTRACT_INVALID, "stored service metadata invalid"
        ) from None


def _status(
    session: Session,
    *,
    service_id: str,
    state: str,
    current_revision_id: str | None,
    resource_version: int,
    updated_at: datetime,
) -> LocalIndexingServiceStatus:
    current = (
        None
        if current_revision_id is None
        else local_indexing_service_reference(_revision(session, service_id, current_revision_id))
    )
    return LocalIndexingServiceStatus.model_validate(
        {
            "schema_version": "local-indexing-service-status/1.0",
            "service_id": service_id,
            "state": state,
            "current": current,
            "resource_version": resource_version,
            "updated_at": _utc(updated_at),
        }
    )


def _fingerprint(
    operation: LocalIndexingControlOperation,
    service_id: str,
    target: LocalIndexingServiceReference | None,
    expected: int | None,
) -> str:
    return content_sha256(
        {
            "operation": operation.value,
            "service_id": service_id,
            "target": None if target is None else target.model_dump(mode="json"),
            "expected_resource_version": expected,
        }
    )


def _result(
    session: Session, event: Mapping[str, Any], *, replayed: bool
) -> LocalIndexingControlResult:
    target = (
        None
        if event["target_revision_id"] is None
        else local_indexing_service_reference(
            _revision(session, event["service_id"], event["target_revision_id"])
        )
    )
    operation = LocalIndexingControlOperation(event["event_type"])
    if event["request_sha256"] != _fingerprint(
        operation, event["service_id"], target, event["expected_resource_version"]
    ):
        raise _error(
            LocalIndexingServiceErrorCode.HASH_MISMATCH, "control event command hash differs"
        )
    return LocalIndexingControlResult(
        event["operation_key"],
        operation,
        cast(Literal["ACTIVE", "DISABLED"] | None, event["previous_state"]),
        target,
        _status(
            session,
            service_id=event["service_id"],
            state=event["state_after"],
            current_revision_id=event["current_revision_id"],
            resource_version=event["sequence"],
            updated_at=event["created_at"],
        ),
        replayed,
    )


def _replay(session: Session, key: str, fingerprint: str) -> LocalIndexingControlResult | None:
    row = (
        session.execute(
            select(_EVENT)
            .where(_EVENT.c.operation_key == key)
            .execution_options(schema_translate_map=_SCHEMA)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["request_sha256"] != fingerprint:
        raise _error(
            LocalIndexingServiceErrorCode.OPERATION_CONFLICT, "operation key names another command"
        )
    return _result(session, dict(row), replayed=True)


def _append(
    session: Session,
    operation: LocalIndexingControlOperation,
    key: str,
    fingerprint: str,
    principal: str,
    previous: Mapping[str, Any] | None,
    head: Mapping[str, Any],
    target: LocalIndexingServiceReference | None,
    expected: int | None,
) -> LocalIndexingControlResult:
    event = {
        "service_id": head["service_id"],
        "sequence": head["resource_version"],
        "operation_key": key,
        "request_sha256": fingerprint,
        "event_type": operation.value,
        "actor_database_principal": principal,
        "target_revision_id": None if target is None else target.service_revision_id,
        "expected_resource_version": expected,
        "previous_state": None if previous is None else previous["state"],
        "previous_latest_revision_id": None if previous is None else previous["latest_revision_id"],
        "previous_current_revision_id": None
        if previous is None
        else previous["current_revision_id"],
        "state_after": head["state"],
        "latest_revision_id": head["latest_revision_id"],
        "current_revision_id": head["current_revision_id"],
        "created_at": head["updated_at"],
    }
    session.execute(insert(_EVENT).values(**event).execution_options(schema_translate_map=_SCHEMA))
    return _result(session, event, replayed=False)


def _integrity_error(error: IntegrityError) -> LocalIndexingServiceError:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    code = (
        LocalIndexingServiceErrorCode.OPERATION_CONFLICT
        if constraint == "uq_lis_operation_key"
        else LocalIndexingServiceErrorCode.REVISION_CONFLICT
    )
    return _error(
        code, "local indexing identity registration conflicts with immutable control metadata"
    )


def install_local_indexing_service_fence(
    session: Session, owner: LocalIndexingFenceOwnerPin
) -> LocalIndexingFenceInstallationResult:
    """Install only the fixed interface in the caller's actual clean owner root.

    Existing drift is never repaired or replaced. The nested mutation boundary
    removes partial CREATE/ACL on failure; caller still owns the outer root/lock.
    """
    if type(owner) is not LocalIndexingFenceOwnerPin:
        raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONFIGURATION_INVALID")
    owner = LocalIndexingFenceOwnerPin(owner.role_name, owner.role_oid)
    with _owner_operation(session) as principal:
        current = (
            session.execute(
                text(
                    "SELECT principal.oid AS owner_oid, application.nspowner AS schema_owner, "
                    "pg_catalog.current_setting('role') AS selected_role "
                    "FROM pg_catalog.pg_roles principal "
                    "JOIN pg_catalog.pg_namespace application ON application.nspname='app' "
                    "WHERE principal.rolname=SESSION_USER"
                )
            )
            .mappings()
            .one()
        )
        if (
            principal != owner.role_name
            or current["owner_oid"] != owner.role_oid
            or current["schema_owner"] != owner.role_oid
            or current["selected_role"] != "none"
        ):
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_FORBIDDEN")
        # Fixed two-int namespace: concurrent installation never replaces a
        # routine; a losing root rolls back before replaying the same operation.
        if (
            session.scalar(
                text("SELECT pg_catalog.pg_try_advisory_xact_lock(1162825554,1229869912)")
            )
            is not True
        ):
            raise _error(LocalIndexingServiceErrorCode.BUSY, "fixed fence installation is busy")
        with session.begin_nested():
            existing = session.execute(
                text(
                    "SELECT procedure.oid FROM pg_catalog.pg_proc procedure "
                    "JOIN pg_catalog.pg_namespace namespace "
                    "ON namespace.oid=procedure.pronamespace "
                    "WHERE namespace.nspname='public' "
                    "AND procedure.proname='eom_fence_local_indexing_service_v1' "
                    "ORDER BY procedure.oid LIMIT 2"
                )
            ).all()
            if not existing:
                session.execute(text(LOCAL_INDEXING_FENCE_CREATE_SQL))
                session.execute(text(LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL))
                session.execute(text(LOCAL_INDEXING_FENCE_GRANT_SQL))
            require_local_indexing_fence_installation(session.connection(), owner)
            return LocalIndexingFenceInstallationResult(
                "REPLAYED" if existing else "CREATED", owner, LOCAL_INDEXING_FENCE_BODY_SHA256
            )


def register_local_indexing_service(
    session: Session,
    identity: LocalIndexingServiceIdentity,
    *,
    operation_key: str,
) -> LocalIndexingControlResult:
    """Register exact metadata only; first registration is DISABLED, never activated."""
    checked = parse_local_indexing_service_identity(local_indexing_service_bytes(identity))
    target = local_indexing_service_reference(checked)
    _key(operation_key)
    fingerprint = _fingerprint(
        LocalIndexingControlOperation.REGISTER, checked.service_id, target, None
    )
    with _owner_operation(session) as principal:
        try:
            with session.begin_nested():
                now = _utc(session.scalar(text("SELECT pg_catalog.clock_timestamp()")))
                if checked.created_at > now:
                    raise _error(
                        LocalIndexingServiceErrorCode.CONTRACT_INVALID,
                        "revision creation is in the future",
                    )
                created = (
                    session.scalar(
                        insert(_HEAD)
                        .values(
                            service_id=checked.service_id,
                            latest_revision_id=checked.service_revision_id,
                            current_revision_id=None,
                            state="DISABLED",
                            resource_version=1,
                            created_at=now,
                            updated_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=[_HEAD.c.service_id])
                        .returning(_HEAD.c.service_id)
                        .execution_options(schema_translate_map=_SCHEMA)
                    )
                    is not None
                )
                previous = _head(session, checked.service_id)
                replay = _replay(session, operation_key, fingerprint)
                if replay is not None:
                    return replay
                if created:
                    if checked.revision_number != 1:
                        raise _error(
                            LocalIndexingServiceErrorCode.REVISION_CONFLICT,
                            "first revision must be revision one",
                        )
                else:
                    validate_local_indexing_service_successor(
                        _revision(session, checked.service_id, previous["latest_revision_id"]),
                        checked,
                    )
                    _version(previous["resource_version"])
                session.execute(
                    insert(_REVISION)
                    .values(**checked.model_dump(mode="python"))
                    .execution_options(schema_translate_map=_SCHEMA)
                )
                if not created:
                    session.execute(
                        update(_HEAD)
                        .where(_HEAD.c.service_id == checked.service_id)
                        .values(
                            latest_revision_id=checked.service_revision_id,
                            resource_version=previous["resource_version"] + 1,
                            updated_at=now,
                        )
                        .execution_options(schema_translate_map=_SCHEMA)
                    )
                return _append(
                    session,
                    LocalIndexingControlOperation.REGISTER,
                    operation_key,
                    fingerprint,
                    principal,
                    None if created else previous,
                    _head(session, checked.service_id),
                    target,
                    None,
                )
        except IntegrityError as error:
            raise _integrity_error(error) from None


def _change_activation(
    session: Session,
    operation: LocalIndexingControlOperation,
    service_id: str,
    target: LocalIndexingServiceReference | None,
    expected: int,
    key: str,
) -> LocalIndexingControlResult:
    service_id = _SERVICE_ID.validate_python(service_id)
    _key(key)
    _version(expected)
    fingerprint = _fingerprint(operation, service_id, target, expected)
    with _owner_operation(session) as principal:
        try:
            with session.begin_nested():
                previous = _head(session, service_id)
                replay = _replay(session, key, fingerprint)
                if replay is not None:
                    return replay
                if previous["resource_version"] != expected:
                    raise _error(
                        LocalIndexingServiceErrorCode.VERSION_CONFLICT,
                        "current resource version differs",
                    )
                if (
                    target is not None
                    and local_indexing_service_reference(
                        _revision(session, service_id, target.service_revision_id)
                    )
                    != target
                ):
                    raise _error(
                        LocalIndexingServiceErrorCode.HASH_MISMATCH,
                        "exact activation identity differs",
                    )
                now = _utc(session.scalar(text("SELECT pg_catalog.clock_timestamp()")))
                session.execute(
                    update(_HEAD)
                    .where(_HEAD.c.service_id == service_id)
                    .values(
                        state="ACTIVE"
                        if operation is LocalIndexingControlOperation.ACTIVATE
                        else "DISABLED",
                        current_revision_id=target.service_revision_id
                        if target is not None
                        else previous["current_revision_id"],
                        resource_version=expected + 1,
                        updated_at=now,
                    )
                    .execution_options(schema_translate_map=_SCHEMA)
                )
                return _append(
                    session,
                    operation,
                    key,
                    fingerprint,
                    principal,
                    previous,
                    _head(session, service_id),
                    target,
                    expected,
                )
        except IntegrityError as error:
            raise _integrity_error(error) from None


def activate_local_indexing_service(
    session: Session,
    reference: LocalIndexingServiceReference,
    *,
    expected_resource_version: int,
    operation_key: str,
) -> LocalIndexingControlResult:
    """Explicit control activation, still not runtime authentication or Catalog data permission."""
    checked = parse_local_indexing_service_reference(local_indexing_service_bytes(reference))
    return _change_activation(
        session,
        LocalIndexingControlOperation.ACTIVATE,
        checked.service_id,
        checked,
        expected_resource_version,
        operation_key,
    )


def disable_local_indexing_service(
    session: Session,
    service_id: str,
    *,
    expected_resource_version: int,
    operation_key: str,
) -> LocalIndexingControlResult:
    """Retain history/current reference while stopping new service admissions."""
    return _change_activation(
        session,
        LocalIndexingControlOperation.DISABLE,
        service_id,
        None,
        expected_resource_version,
        operation_key,
    )


def lock_current_local_indexing_service_metadata(
    session: Session,
    reference: LocalIndexingServiceReference,
) -> LocalIndexingServiceIdentity:
    """Owner-only retained head lock and exact metadata read, NOT an authenticated service fence.

    The shared row lock remains until the caller's root ends; supported control writers
    take an exclusive lock on that same head. No lock/capability is returned or cached.
    """
    checked = parse_local_indexing_service_reference(local_indexing_service_bytes(reference))
    with _owner_operation(session):
        head = _head(session, checked.service_id, shared=True)
        if head["state"] != "ACTIVE":
            raise _error(
                LocalIndexingServiceErrorCode.INACTIVE, "local indexing service is disabled"
            )
        if head["current_revision_id"] != checked.service_revision_id:
            raise _error(
                LocalIndexingServiceErrorCode.STALE_REVISION, "service revision is not current"
            )
        identity = _revision(session, checked.service_id, checked.service_revision_id)
        if local_indexing_service_reference(identity) != checked:
            raise _error(
                LocalIndexingServiceErrorCode.HASH_MISMATCH, "exact service identity differs"
            )
        status = LocalIndexingServiceStatus(
            schema_version="local-indexing-service-status/1.0",
            service_id=head["service_id"],
            state="ACTIVE",
            current=checked,
            resource_version=head["resource_version"],
            updated_at=_utc(head["updated_at"]),
        )
        return validate_local_indexing_service_current(status, identity)
