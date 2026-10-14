"""Actual disposable Identity metadata/locks; no machine auth, data grant, model or NAS.

Committed synthetic control history is retained between executions. Only the
official marker-guarded owner test purpose may execute this module.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from queue import Queue
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_identity_service import (
    activate_local_indexing_service,
    disable_local_indexing_service,
    lock_current_local_indexing_service_metadata,
    register_local_indexing_service,
)
from eom_identity_service import local_indexing_service_registry as registry
from eom_identity_service.local_indexing_service_models import LocalIndexingServiceEventRecord
from eom_operator_identity import (
    LocalIndexingServiceError,
    LocalIndexingServiceErrorCode,
    LocalIndexingServiceIdentity,
    local_indexing_service_identity_sha256,
    local_indexing_service_reference,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_local_indexing_service_registry import migration

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in() -> None:
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


def identity(**changes: Any) -> LocalIndexingServiceIdentity:
    document = {
        "schema_version": "local-indexing-service-identity/1.0",
        "service_id": "localindexservice_" + uuid4().hex,
        "service_revision_id": "localindexservicerev_" + uuid4().hex,
        "previous_service_revision_id": None,
        "revision_number": 1,
        "purpose": "LOCAL_EMBEDDING_INDEX",
        "runtime_user": "eom-workflow-runner",
        "database_role": "synthetic_indexing_owner",
        "runtime_source_commit": "3" * 40,
        "created_at": "2026-10-14T00:00:00Z",
        "content_sha256": "sha256:" + "0" * 64,
    }
    document.update(changes)
    document["content_sha256"] = local_indexing_service_identity_sha256(document)
    return LocalIndexingServiceIdentity.model_validate(document)


@dataclass(frozen=True)
class Case:
    engine: Engine
    identity: LocalIndexingServiceIdentity
    prefix: str

    def key(self, name: str) -> str:
        return self.prefix + ":" + name

    def register(self):
        with Session(self.engine) as session, session.begin():
            return register_local_indexing_service(
                session, self.identity, operation_key=self.key("register")
            )

    def activate(self, *, expected: int = 1):
        with Session(self.engine) as session, session.begin():
            return activate_local_indexing_service(
                session,
                local_indexing_service_reference(self.identity),
                expected_resource_version=expected,
                operation_key=self.key("activate"),
            )


@pytest.fixture
def case(guarded_engine: Engine) -> Case:
    return Case(guarded_engine, identity(), "synthetic-lis:" + uuid4().hex)


def counts(value: Case) -> tuple[int, int, int]:
    with value.engine.connect() as connection:
        return tuple(
            connection.scalar(
                text(f"SELECT count(*) FROM app.{table} WHERE service_id=:id"),
                {"id": value.identity.service_id},
            )
            for table in (
                "local_indexing_services",
                "local_indexing_service_revisions",
                "local_indexing_service_events",
            )
        )


def test_actual_disabled_registration_then_explicit_activation_and_disable(case):
    first = case.register()
    assert first.status_after_operation.state == "DISABLED"
    assert first.status_after_operation.current is None
    assert first.status_after_operation.resource_version == 1 and not first.replayed
    active = case.activate()
    assert active.status_after_operation.current == local_indexing_service_reference(case.identity)
    assert active.status_after_operation.state == "ACTIVE"
    assert active.status_after_operation.resource_version == 2
    with Session(case.engine) as session, session.begin():
        assert lock_current_local_indexing_service_metadata(session, active.target) == case.identity
        disabled = disable_local_indexing_service(
            session,
            case.identity.service_id,
            expected_resource_version=2,
            operation_key=case.key("disable"),
        )
    assert disabled.status_after_operation.state == "DISABLED"
    assert disabled.status_after_operation.current == active.status_after_operation.current
    with (
        Session(case.engine) as session,
        session.begin(),
        pytest.raises(LocalIndexingServiceError) as error,
    ):
        lock_current_local_indexing_service_metadata(session, active.target)
    assert error.value.code == LocalIndexingServiceErrorCode.INACTIVE
    assert counts(case) == (1, 1, 3)


def test_replay_returns_original_historical_result_without_reactivating(case):
    case.register()
    original = case.activate()
    with Session(case.engine) as session, session.begin():
        disable_local_indexing_service(
            session,
            case.identity.service_id,
            expected_resource_version=2,
            operation_key=case.key("disable"),
        )
    replay = case.activate()
    assert replay.replayed and replay.status_after_operation == original.status_after_operation
    old_registration = case.register()
    assert old_registration.replayed
    assert old_registration.status_after_operation.state == "DISABLED"
    assert old_registration.status_after_operation.resource_version == 1
    with (
        Session(case.engine) as session,
        session.begin(),
        pytest.raises(LocalIndexingServiceError) as error,
    ):
        lock_current_local_indexing_service_metadata(session, original.target)
    assert error.value.code == LocalIndexingServiceErrorCode.INACTIVE
    assert counts(case) == (1, 1, 3)


def test_successor_registration_keeps_active_revision_and_explicit_rollback_is_allowed(case):
    case.register()
    original = case.activate()
    next_identity = identity(
        service_id=case.identity.service_id,
        previous_service_revision_id=case.identity.service_revision_id,
        revision_number=2,
        runtime_source_commit="4" * 40,
    )
    with Session(case.engine) as session, session.begin():
        registered = register_local_indexing_service(
            session,
            next_identity,
            operation_key=case.key("next"),
        )
        assert registered.status_after_operation.current == original.target
        assert (
            lock_current_local_indexing_service_metadata(session, original.target) == case.identity
        )
    with (
        Session(case.engine) as session,
        session.begin(),
        pytest.raises(LocalIndexingServiceError) as error,
    ):
        lock_current_local_indexing_service_metadata(
            session,
            local_indexing_service_reference(next_identity),
        )
    assert error.value.code == LocalIndexingServiceErrorCode.STALE_REVISION
    with Session(case.engine) as session, session.begin():
        activate_local_indexing_service(
            session,
            local_indexing_service_reference(next_identity),
            expected_resource_version=3,
            operation_key=case.key("select-next"),
        )
        rollback = activate_local_indexing_service(
            session,
            original.target,
            expected_resource_version=4,
            operation_key=case.key("rollback"),
        )
        assert (
            lock_current_local_indexing_service_metadata(session, original.target) == case.identity
        )
    assert rollback.status_after_operation.current == original.target
    assert counts(case) == (1, 2, 5)


def test_conflicting_key_stale_version_and_wrong_identity_hash_are_atomic(case):
    case.register()
    with Session(case.engine) as session, session.begin():
        actions = (
            (
                lambda: disable_local_indexing_service(
                    session,
                    case.identity.service_id,
                    expected_resource_version=1,
                    operation_key=case.key("register"),
                ),
                LocalIndexingServiceErrorCode.OPERATION_CONFLICT,
            ),
            (
                lambda: activate_local_indexing_service(
                    session,
                    local_indexing_service_reference(case.identity),
                    expected_resource_version=2,
                    operation_key=case.key("stale"),
                ),
                LocalIndexingServiceErrorCode.VERSION_CONFLICT,
            ),
            (
                lambda: activate_local_indexing_service(
                    session,
                    local_indexing_service_reference(case.identity).model_copy(
                        update={"service_identity_sha256": "sha256:" + "f" * 64}
                    ),
                    expected_resource_version=1,
                    operation_key=case.key("bad-hash"),
                ),
                LocalIndexingServiceErrorCode.HASH_MISMATCH,
            ),
        )
        for action, expected_code in actions:
            with pytest.raises(LocalIndexingServiceError) as error:
                action()
            assert error.value.code == expected_code
    assert counts(case) == (1, 1, 1)


def test_event_failure_rolls_back_even_when_caller_commits_its_root(case, monkeypatch):
    def failed(*_args, **_kwargs):
        raise ValueError("SYNTHETIC_EVENT_FAILURE")

    monkeypatch.setattr(registry, "_append", failed)
    # Catch inside the outer root: combining these contexts would instead roll it back.
    with Session(case.engine) as session, session.begin():  # noqa: SIM117
        with pytest.raises(ValueError, match="EVENT_FAILURE"):
            register_local_indexing_service(
                session,
                case.identity,
                operation_key=case.key("register"),
            )
    assert counts(case) == (0, 0, 0)


def test_concurrent_same_key_registration_commits_once(case):
    barrier = Barrier(2)

    def submit(_number):
        barrier.wait(timeout=5)
        return case.register()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(value.replayed for value in results) == [False, True]
    assert results[0].status_after_operation == results[1].status_after_operation
    assert counts(case) == (1, 1, 1)


def test_concurrent_distinct_commands_require_same_expected_head_version(case):
    case.register()
    barrier = Barrier(2)

    def activate(number):
        barrier.wait(timeout=5)
        try:
            with Session(case.engine) as session, session.begin():
                activate_local_indexing_service(
                    session,
                    local_indexing_service_reference(case.identity),
                    expected_resource_version=1,
                    operation_key=case.key("activate-" + str(number)),
                )
            return "COMMITTED"
        except LocalIndexingServiceError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate, range(2)))
    assert sorted(results) == sorted(
        [
            "COMMITTED",
            LocalIndexingServiceErrorCode.VERSION_CONFLICT.value,
        ]
    )
    assert counts(case) == (1, 1, 2)


def test_shared_metadata_lock_is_retained_until_root_and_blocks_supported_disable(case):
    case.register()
    case.activate()
    pids: Queue[int] = Queue()

    def disable():
        with Session(case.engine) as session, session.begin():
            pids.put(session.scalar(text("SELECT pg_catalog.pg_backend_pid()")))
            return disable_local_indexing_service(
                session,
                case.identity.service_id,
                expected_resource_version=2,
                operation_key=case.key("blocked-disable"),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(case.engine) as reader, reader.begin():
            lock_current_local_indexing_service_metadata(
                reader,
                local_indexing_service_reference(case.identity),
            )
            future = pool.submit(disable)
            pid = pids.get(timeout=3)
            deadline = time.monotonic() + 2
            while not reader.scalar(
                text("SELECT cardinality(pg_catalog.pg_blocking_pids(:pid))"),
                {"pid": pid},
            ):
                assert time.monotonic() < deadline and not future.done()
                time.sleep(0.01)
            assert not future.done()
        assert future.result(timeout=5).status_after_operation.state == "DISABLED"
    assert counts(case) == (1, 1, 3)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE app.local_indexing_service_revisions "
        "SET runtime_source_commit=repeat('9',40) WHERE service_id=:id",
        "DELETE FROM app.local_indexing_service_revisions WHERE service_id=:id",
        "UPDATE app.local_indexing_service_events "
        "SET actor_database_principal='forged' WHERE service_id=:id",
        "DELETE FROM app.local_indexing_service_events WHERE service_id=:id",
        "DELETE FROM app.local_indexing_services WHERE service_id=:id",
        "TRUNCATE app.local_indexing_services,app.local_indexing_service_revisions,"
        "app.local_indexing_service_events",
    ],
)
def test_actual_history_update_delete_and_truncate_are_rejected(case, sql):
    case.register()
    with pytest.raises(DBAPIError) as error, case.engine.begin() as connection:
        connection.execute(text(sql), {"id": case.identity.service_id})
    assert error.value.orig.sqlstate == "23514"
    assert counts(case) == (1, 1, 1)


def test_cross_service_head_pointer_is_rejected_at_commit(case):
    case.register()
    other = Case(case.engine, identity(), "synthetic-lis:" + uuid4().hex)
    other.register()
    with pytest.raises(IntegrityError), case.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.local_indexing_services SET state='ACTIVE', "
                "current_revision_id=:other,resource_version=resource_version+1,"
                "updated_at=clock_timestamp() WHERE service_id=:id"
            ),
            {"other": other.identity.service_revision_id, "id": case.identity.service_id},
        )
    assert counts(case) == (1, 1, 1)


def test_runtime_acl_not_expanded_and_audit_uses_real_database_principal(case):
    case.register()
    manifest = DisposableManifest.load(Path(os.environ["EOM_API_TEST_STATE"]) / "manifest.json")
    with case.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT to_regrole(:role)"), {"role": manifest.runtime_role})
            is not None
        )
        for table in (
            "local_indexing_services",
            "local_indexing_service_revisions",
            "local_indexing_service_events",
        ):
            assert not connection.scalar(
                text(
                    "SELECT has_table_privilege("
                    ":role,:table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"
                ),
                {"role": manifest.runtime_role, "table": "app." + table},
            )
        assert (
            connection.scalar(
                text(
                    "SELECT actor_database_principal FROM app.local_indexing_service_events "
                    "WHERE service_id=:id"
                ),
                {"id": case.identity.service_id},
            )
            == manifest.owner_role
        )


def test_wait_limits_restored_and_smaller_caller_limits_preserved(case):
    with Session(case.engine) as session, session.begin():
        session.execute(text("SET LOCAL lock_timeout='1234ms'"))
        session.execute(text("SET LOCAL statement_timeout='2345ms'"))
        register_local_indexing_service(
            session,
            case.identity,
            operation_key=case.key("register"),
        )
        assert session.scalar(text("SHOW lock_timeout")) == "1234ms"
        assert session.scalar(text("SHOW statement_timeout")) == "2345ms"


def test_downgrade_refuses_actual_history_without_rewriting_head_or_rows(case, monkeypatch):
    case.register()
    module = migration()
    with pytest.raises(IntegrityError, match="absent history"), case.engine.begin() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.downgrade()
    assert counts(case) == (1, 1, 1)
    with case.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == CURRENT_MIGRATION_REVISION
        )


def test_global_key_conflict_leaves_no_new_service_or_orphan_revision(case):
    case.register()
    other = Case(case.engine, identity(), "synthetic-lis:" + uuid4().hex)
    with Session(case.engine) as session, session.begin():
        with pytest.raises(LocalIndexingServiceError) as error:
            register_local_indexing_service(
                session, other.identity, operation_key=case.key("register")
            )
        assert error.value.code == LocalIndexingServiceErrorCode.OPERATION_CONFLICT
    assert counts(case) == (1, 1, 1) and counts(other) == (0, 0, 0)


def test_concurrent_successors_do_not_fork_the_immutable_revision_chain(case):
    case.register()
    barrier = Barrier(2)

    def successor(number):
        value = identity(
            service_id=case.identity.service_id,
            previous_service_revision_id=case.identity.service_revision_id,
            revision_number=2,
        )
        barrier.wait(timeout=5)
        try:
            with Session(case.engine) as session, session.begin():
                register_local_indexing_service(
                    session, value, operation_key=case.key(f"next-{number}")
                )
            return "COMMITTED"
        except LocalIndexingServiceError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(successor, range(2)))
    assert sorted(results) == sorted(
        ["COMMITTED", LocalIndexingServiceErrorCode.REVISION_CONFLICT.value]
    )
    assert counts(case) == (1, 2, 2)


@pytest.mark.parametrize(
    "assignment",
    [
        "resource_version=resource_version",
        "service_id='localindexservice_' || repeat('9',32),resource_version=resource_version+1",
        "created_at=created_at-interval '1 second',resource_version=resource_version+1",
    ],
)
def test_head_identity_and_monotonic_resource_version_are_protected(case, assignment):
    case.register()
    with pytest.raises(DBAPIError) as error, case.engine.begin() as connection:
        connection.execute(
            text(f"UPDATE app.local_indexing_services SET {assignment} WHERE service_id=:id"),
            {"id": case.identity.service_id},
        )
    assert error.value.orig.sqlstate == "23514" and counts(case) == (1, 1, 1)


def test_latest_registered_revision_cannot_be_rewound_by_a_raw_head_update(case):
    case.register()
    next_identity = identity(
        service_id=case.identity.service_id,
        previous_service_revision_id=case.identity.service_revision_id,
        revision_number=2,
    )
    with Session(case.engine) as session, session.begin():
        register_local_indexing_service(session, next_identity, operation_key=case.key("next"))
    with pytest.raises(DBAPIError) as error, case.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.local_indexing_services SET latest_revision_id=:old, "
                "resource_version=resource_version+1,updated_at=clock_timestamp() "
                "WHERE service_id=:id"
            ),
            {"id": case.identity.service_id, "old": case.identity.service_revision_id},
        )
    assert error.value.orig.sqlstate == "23514" and counts(case) == (1, 2, 2)


def test_null_expected_version_is_not_accepted_by_postgresql_three_valued_check(case):
    case.register()
    with case.engine.connect() as connection:
        event = dict(
            connection.execute(
                text("SELECT * FROM app.local_indexing_service_events WHERE service_id=:id"),
                {"id": case.identity.service_id},
            )
            .mappings()
            .one()
        )
    event.update(
        sequence=2,
        operation_key=case.key("null-check"),
        event_type="ACTIVATE",
        target_revision_id=case.identity.service_revision_id,
        current_revision_id=case.identity.service_revision_id,
        state_after="ACTIVE",
        expected_resource_version=None,
    )
    with pytest.raises(IntegrityError) as error, case.engine.begin() as connection:
        connection.execute(
            LocalIndexingServiceEventRecord.__table__.insert()
            .values(**event)
            .execution_options(schema_translate_map={None: "app"})
        )
    assert error.value.orig.diag.constraint_name == "ck_lis_event_operation"
    assert counts(case) == (1, 1, 1)


def test_database_client_timezone_does_not_change_canonical_identity_or_output_utc(case):
    with Session(case.engine) as session, session.begin():
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Seoul'"))
        registered = register_local_indexing_service(
            session, case.identity, operation_key=case.key("register")
        )
        assert registered.status_after_operation.updated_at.utcoffset() == timedelta(0)
        active = activate_local_indexing_service(
            session,
            registered.target,
            expected_resource_version=1,
            operation_key=case.key("activate"),
        )
        assert lock_current_local_indexing_service_metadata(session, active.target) == case.identity


def test_metadata_lock_refuses_a_savepoint_that_can_release_the_fence_early(case):
    case.register()
    case.activate()
    with Session(case.engine) as session, session.begin(), session.begin_nested():
        with pytest.raises(LocalIndexingServiceError) as error:
            lock_current_local_indexing_service_metadata(
                session, local_indexing_service_reference(case.identity)
            )
        assert error.value.code == LocalIndexingServiceErrorCode.CONTEXT_INVALID


def test_shared_metadata_wait_does_not_mask_the_original_postgresql_lock_error(case):
    case.register()
    case.activate()
    with Session(case.engine) as writer, writer.begin():
        writer.execute(
            text(
                "SELECT service_id FROM app.local_indexing_services WHERE service_id=:id FOR UPDATE"
            ),
            {"id": case.identity.service_id},
        )
        with Session(case.engine) as reader, reader.begin():
            reader.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(LocalIndexingServiceError) as error:
                lock_current_local_indexing_service_metadata(
                    reader, local_indexing_service_reference(case.identity)
                )
            assert error.value.code == LocalIndexingServiceErrorCode.BUSY
            assert isinstance(error.value.__cause__, DBAPIError)
            assert error.value.__cause__.orig.sqlstate == "55P03"
            reader.rollback()
    assert counts(case) == (1, 1, 2)


def test_writer_wait_rollback_preserves_outer_root_and_same_key_can_be_replayed(case):
    case.register()
    case.activate()
    with Session(case.engine) as reader, reader.begin():
        lock_current_local_indexing_service_metadata(
            reader, local_indexing_service_reference(case.identity)
        )
        with Session(case.engine) as writer, writer.begin():
            writer.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(LocalIndexingServiceError) as error:
                disable_local_indexing_service(
                    writer,
                    case.identity.service_id,
                    expected_resource_version=2,
                    operation_key=case.key("wait-then-disable"),
                )
            assert error.value.code == LocalIndexingServiceErrorCode.BUSY
            assert writer.scalar(text("SHOW lock_timeout")) == "100ms"
            assert writer.scalar(text("SELECT 1")) == 1
    assert counts(case) == (1, 1, 2)
    with Session(case.engine) as writer, writer.begin():
        result = disable_local_indexing_service(
            writer,
            case.identity.service_id,
            expected_resource_version=2,
            operation_key=case.key("wait-then-disable"),
        )
    assert result.status_after_operation.state == "DISABLED" and counts(case) == (1, 1, 3)
