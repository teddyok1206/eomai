"""Actual runtime + authenticated DB-principal fence on one retained SQL root."""

from __future__ import annotations

from _thread import LockType
from dataclasses import dataclass, field
from threading import Lock, Thread, current_thread
from weakref import ReferenceType, WeakKeyDictionary, ref

from eom_operator_identity import (
    LocalIndexingServiceIdentity,
    LocalIndexingServiceStatus,
    local_indexing_service_reference,
    validate_local_indexing_service_current,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransaction

from eom_identity_service.local_indexing_fence_sql import (
    LOCAL_INDEXING_FENCE_CALL_SQL,
    LOCAL_INDEXING_FENCE_EXECUTE_ROLE,
    LocalIndexingFenceError,
    LocalIndexingFenceOwnerPin,
    require_local_indexing_fence_installation,
)
from eom_identity_service.local_indexing_runtime import (
    AuthenticatedLocalIndexingRuntime,
    LocalIndexingRuntimePin,
)

_CONTEXT_SQL = """
SELECT SESSION_USER AS principal, CURRENT_USER AS role_name,
    pg_catalog.current_setting('transaction_isolation') AS isolation,
    pg_catalog.current_setting('transaction_read_only') AS read_only,
    pg_catalog.current_schemas(false) AS schemas,
    pg_catalog.pg_my_temp_schema() AS temp_schema,
    pg_catalog.pg_backend_pid() AS backend_pid,
    pg_catalog.txid_current() AS transaction_id
"""
_LIMITS_SQL = """
SELECT name, setting::pg_catalog.int8 AS milliseconds,
    pg_catalog.current_setting(name) AS previous
FROM pg_catalog.pg_settings
WHERE name IN ('lock_timeout','statement_timeout') AND unit='ms'
"""
_SET_LIMIT_SQL = "SELECT pg_catalog.set_config(:name,:value,true)"


@dataclass(frozen=True, slots=True)
class _RootServiceWitness:
    root: ReferenceType[SessionTransaction]
    connection: ReferenceType[Connection]
    thread: ReferenceType[Thread]
    backend_pid: int
    transaction_id: int


@dataclass(frozen=True, slots=True)
class PostgresLocalIndexingServiceFence:
    """Identity authentication only; a released Catalog data grant remains required.

    Each instance binds one exact runtime pin. Never serialize/cache its success,
    join an implicit root, or first acquire a lock inside a rollbackable savepoint.
    """

    owner: LocalIndexingFenceOwnerPin
    pin: LocalIndexingRuntimePin
    runtime: AuthenticatedLocalIndexingRuntime
    _witnesses: WeakKeyDictionary[Session, _RootServiceWitness] = field(
        default_factory=WeakKeyDictionary, init=False, repr=False, compare=False
    )
    _lock: LockType = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        LocalIndexingFenceOwnerPin(self.owner.role_name, self.owner.role_oid)
        if type(self.pin) is not LocalIndexingRuntimePin or type(self.runtime) is not (
            AuthenticatedLocalIndexingRuntime
        ):
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONFIGURATION_INVALID")

    def _current_runtime(self) -> None:
        self.runtime.assert_current(
            service=self.pin.service,
            runtime_source_commit=self.pin.runtime_source_commit,
            configuration_sha256=self.pin.configuration_sha256,
        )

    def fence_current_service(self, session: Session) -> LocalIndexingServiceIdentity:
        """Retain one shared head lock until the caller commits/rolls back its root."""
        try:
            self._current_runtime()
        except ValueError:
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE") from None
        root, nested = session.get_transaction(), session.get_nested_transaction()
        if root is None or not root.is_active:
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
        with self._lock:
            witness = self._witnesses.get(session)
            if witness is not None and witness.root() is not root:
                del self._witnesses[session]
                witness = None
        if witness is None and (
            nested is not None or session.new or session.dirty or session.deleted
        ):
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
        if witness is not None and witness.thread() is not current_thread():
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
        try:
            connection = session.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.dialect.driver != "psycopg"
                or connection.invalidated
                or not connection.in_transaction()
                or (witness is None and connection.in_nested_transaction())
                or getattr(connection.connection.driver_connection, "autocommit", None) is not False
                or connection.get_isolation_level() != "READ COMMITTED"
            ):
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            previous: dict[str, str] = {}
            rows = connection.execute(text(_LIMITS_SQL)).mappings().all()
            if len(rows) != 2:
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            for row in rows:
                name, actual, prior = row["name"], row["milliseconds"], row["previous"]
                if (
                    name not in {"lock_timeout", "statement_timeout"}
                    or name in previous
                    or type(actual) is not int
                    or not 0 <= actual <= 2147483647
                    or type(prior) is not str
                    or not 0 < len(prior) <= 32
                ):
                    raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
                cap = 5000 if name == "lock_timeout" else 10000
                previous[name] = prior
                connection.execute(
                    text(_SET_LIMIT_SQL),
                    {
                        "name": name,
                        "value": str(min(actual, cap) if actual else cap) + "ms",
                    },
                )
            if set(previous) != {"lock_timeout", "statement_timeout"}:
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            context = connection.execute(text(_CONTEXT_SQL)).mappings().one()
            if (
                context["principal"] != LOCAL_INDEXING_FENCE_EXECUTE_ROLE
                or context["role_name"] != context["principal"]
                or context["isolation"] != "read committed"
                or context["read_only"] != "off"
                or context["schemas"] != ["app", "pg_catalog"]
                or type(context["temp_schema"]) is not int
                or context["temp_schema"] != 0
                or type(context["backend_pid"]) is not int
                or context["backend_pid"] < 1
                or type(context["transaction_id"]) is not int
                or context["transaction_id"] < 1
            ):
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            if witness is not None and (
                witness.connection() is not connection
                or witness.backend_pid != context["backend_pid"]
                or witness.transaction_id != context["transaction_id"]
            ):
                with self._lock:
                    self._witnesses.pop(session, None)
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            require_local_indexing_fence_installation(connection, self.owner)
            value: object = connection.execute(
                text(LOCAL_INDEXING_FENCE_CALL_SQL),
                {
                    "service_id": self.pin.service.service_id,
                    "revision_id": self.pin.service.service_revision_id,
                    "identity_sha256": self.pin.service.service_identity_sha256,
                    "source_commit": self.pin.runtime_source_commit,
                },
            ).scalar_one()
            if type(value) is not dict or set(value) != {"identity", "status"}:
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE")
            identity = LocalIndexingServiceIdentity.model_validate(value["identity"])
            status = LocalIndexingServiceStatus.model_validate(value["status"])
            validate_local_indexing_service_current(status, identity)
            if (
                local_indexing_service_reference(identity) != self.pin.service
                or identity.runtime_source_commit != self.pin.runtime_source_commit
                or identity.database_role != context["principal"]
            ):
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_FORBIDDEN")
            self._current_runtime()
            if (
                session.get_transaction() is not root
                or not root.is_active
                or session.get_nested_transaction() is not nested
                or session.connection() is not connection
                or connection.invalidated
            ):
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONTEXT_INVALID")
            for name, prior in previous.items():
                connection.execute(text(_SET_LIMIT_SQL), {"name": name, "value": prior})
            if witness is None:
                with self._lock:
                    self._witnesses[session] = _RootServiceWitness(
                        ref(root),
                        ref(connection),
                        ref(current_thread()),
                        context["backend_pid"],
                        context["transaction_id"],
                    )
            return identity
        except LocalIndexingFenceError:
            raise
        except DBAPIError as error:
            if (
                getattr(error.orig, "sqlstate", None) == "P0001"
                and getattr(getattr(error.orig, "diag", None), "message_primary", None)
                == "LOCAL_INDEXING_FENCE_FORBIDDEN"
            ):
                raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_FORBIDDEN") from None
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE") from None
        except (SQLAlchemyError, ValueError, KeyError, TypeError):
            # Errors contain neither DB text, configuration bytes nor returned metadata.
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE") from None
