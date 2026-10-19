"""Prepared process races; requires an explicitly prepared disposable limited profile.

Never executed in the source-only stage. Does not install the routine or grant /
repair prerequisite privileges. Only the guard's unique disposable runtime role
is substituted in tests; production role literals are pinned by source tests.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from eom_catalog_contracts.knowledge import (
    EducationRetrievalAccessPolicy,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.ordinary_item_graph_publication import (
    PublishOrdinaryApprovedItemAnalysesCommand,
)
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.ordinary_item_graph_publication_service import (
    OrdinaryItemGraphPublicationError,
    OrdinaryItemGraphPublicationService,
)
from eom_identifiers import content_sha256
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    PostgresOperatorAuthorizationFence,
    require_operator_authorization_fence_installation,
)
from eom_identity_service import operator_authorization_fence_sql as routine
from eom_identity_service import postgres_operator_authorization_fence as adapter_module
from eom_identity_service.auth_service import AuthService
from eom_identity_service.models import (
    OperatorCredentialRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.repository import effective_permissions, require_role
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError
from eom_operator_identity.identifiers import new_credential_id, new_role_assignment_id
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker
from sqlalchemy.sql import ClauseElement

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_embedding_registry_persistence import _seed
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_ordinary_item_graph_publication import _command_value, _rehash

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
_SYNTHETIC_KEY = b"synthetic-disposable-fence-key-not-production" * 2


def _test_role(role: str) -> None:
    # No public runtime role argument or environment switch exists in the adapter.
    patcher = pytest.MonkeyPatch()
    patcher.setattr(routine, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", role)
    patcher.setattr(adapter_module, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", role)


def _auth(engine: Engine) -> AuthService:
    return AuthService(engine, SessionTokenService(TokenCodec(_SYNTHETIC_KEY)))


@dataclass(frozen=True)
class PreparedFence:
    owner_url: str = field(repr=False)
    runtime_url: str = field(repr=False)
    state: str
    owner_pin: OperatorAuthorizationFenceOwnerPin
    runtime_role: str
    admin_id: str
    admin_username: str
    target_id: str
    target_username: str
    password: str = field(repr=False)


def _guard_process(value: PreparedFence, *, runtime: bool) -> Engine:
    state = validate_state_directory(Path(value.state))
    manifest = DisposableManifest.load(state / "manifest.json")
    url = value.runtime_url if runtime else value.owner_url
    parsed = urlsplit(url)
    assert parsed.path.removeprefix("/") == manifest.database
    assert parsed.username == (manifest.runtime_role if runtime else manifest.owner_role)
    assert value.runtime_role == manifest.runtime_role
    assert value.owner_pin.role_name == manifest.owner_role
    _test_role(manifest.runtime_role)
    engine = build_engine(url)
    try:
        with engine.connect() as connection:
            actual = connection.execute(
                text(
                    "SELECT pg_catalog.current_database(), CURRENT_USER, owner.rolname, "
                    "pg_catalog.obj_description(namespace.oid,'pg_namespace') "
                    "FROM pg_catalog.pg_namespace AS namespace "
                    "JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner "
                    "WHERE namespace.nspname='app'"
                )
            ).one()
        assert actual == (
            manifest.database,
            manifest.runtime_role if runtime else manifest.owner_role,
            manifest.owner_role,
            manifest.marker,
        )
    except BaseException:
        engine.dispose()
        raise
    return engine


@pytest.fixture
def prepared(guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> PreparedFence:
    if os.environ.get("EOM_RUN_OPERATOR_FENCE_INTEGRATION") != "1":
        pytest.skip("prepared opt-in disposable fence profile required; never production")
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    runtime_url = values["EOM_API_DATABASE_URL"]
    assert urlsplit(runtime_url).username == manifest.runtime_role
    owner_url = guarded_engine.url.render_as_string(hide_password=False)
    monkeypatch.setattr(routine, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", manifest.runtime_role)
    monkeypatch.setattr(
        adapter_module, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", manifest.runtime_role
    )
    with guarded_engine.connect() as connection:
        oid = connection.scalar(
            text("SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:role"),
            {"role": manifest.owner_role},
        )
    assert type(oid) is int
    owner_pin = OperatorAuthorizationFenceOwnerPin(manifest.owner_role, oid)
    runtime_engine = build_engine(runtime_url)
    try:
        with runtime_engine.connect() as connection:
            # The default API test profile has IAM writes: it must NOT pass.
            # Preparation must admit exact body/owner/ACL plus limited IAM SELECT.
            require_operator_authorization_fence_installation(connection, owner_pin)
    finally:
        runtime_engine.dispose()
    seed, now = uuid4().hex, datetime.now(UTC)
    password = "Synthetic-Only-" + uuid4().hex + "!9"
    ids = ("operator_" + uuid4().hex, "operator_" + uuid4().hex)
    names = ("fence_admin_" + seed[:12], "fence_reader_" + seed[:12])
    with Session(guarded_engine) as session, session.begin():
        for operator_id, username, role_key in zip(
            ids, names, (RoleKey.ADMIN, RoleKey.REVIEWER), strict=True
        ):
            session.add(
                OperatorRecord(
                    operator_id=operator_id,
                    username=username,
                    normalized_username=username,
                    display_name="Synthetic disposable fence",
                    status="ACTIVE",
                    must_change_password=False,
                    role_version=1,
                    created_by="synthetic-fence",
                    lock_version=1,
                )
            )
            session.flush()
            session.add(
                OperatorCredentialRecord(
                    operator_credential_id=new_credential_id(),
                    operator_id=operator_id,
                    password_hash=PasswordService().hash_password(
                        password, username=username, display_name="Synthetic disposable fence"
                    ),
                    password_algorithm="argon2id",
                    password_version=1,
                    must_change_password=False,
                    password_changed_at=now,
                    failed_login_count=0,
                )
            )
            role = require_role(session, role_key)
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id=new_role_assignment_id(),
                    operator_id=operator_id,
                    role_id=role.role_id,
                    assigned_by="synthetic-fence",
                    assigned_at=now,
                )
            )
    return PreparedFence(
        owner_url,
        runtime_url,
        str(state),
        owner_pin,
        manifest.runtime_role,
        ids[0],
        names[0],
        ids[1],
        names[1],
        password,
    )


def _actor(auth: AuthService, value: PreparedFence) -> ActorContext:
    login = auth.login(
        username=value.admin_username, password=value.password, client_name="synthetic-fence"
    )
    authentication = auth.authenticate_access(login.pair.access_token)
    assert authentication.operator.operator_id == value.admin_id
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=value.admin_id,
        session_id=authentication.session_id,
        request_id="synthetic-fence-revoke",
        authentication_time=authentication.authenticated_at,
        permissions=authentication.permissions,
        source=ActorSource.APPLICATION_API,
    )


def _writer(
    value: PreparedFence, operation: str, events: Any, release: Any, pause_after_lock: bool
) -> None:
    engine = _guard_process(value, runtime=False)
    auth, actor = _auth(engine), None
    actor = _actor(auth, value)
    password_authentication = None
    if operation == "password":
        login = auth.login(
            username=value.target_username,
            password=value.password,
            client_name="synthetic-password-writer",
        )
        password_authentication = auth.authenticate_access(login.pair.access_token)

    class ObservedSession(Session):
        pass

    def observe(state: ORMExecuteState) -> Any:
        statement = str(state.statement)
        is_target = (
            "FROM operators" in statement
            and "FOR UPDATE" in statement
            and value.target_id in cast(ClauseElement, state.statement).compile().params.values()
        )
        if is_target:
            pid = state.session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            events.put(("WRITER_TRY", pid))
        result = state.invoke_statement()
        if is_target:
            events.put(("WRITER_LOCKED", pid))
            if pause_after_lock and not release.wait(10):
                raise AssertionError("bounded writer controller expired")
        return result

    event.listen(ObservedSession, "do_orm_execute", observe, retval=True)
    factory = sessionmaker(
        bind=engine, class_=cast(type[Session], ObservedSession), expire_on_commit=False
    )
    try:
        if operation == "password":
            assert password_authentication is not None
            auth.sessions = factory
            auth.change_password(
                password_authentication,
                current_password=value.password,
                new_password="Synthetic-Changed-" + uuid4().hex + "!9",
            )
        else:
            service = OperatorService(engine)
            service.sessions = factory
            if operation == "revoke":
                service.revoke_role(
                    value.target_id, RoleKey.REVIEWER, actor, reason="synthetic disposable denial"
                )
            elif operation == "disable":
                service.disable(value.target_id, actor, reason="synthetic disposable denial")
            else:
                raise AssertionError("unsupported fixed test writer")
        events.put(("WRITER_COMMITTED", 0))
    finally:
        engine.dispose()


def _reader(value: PreparedFence, events: Any) -> str:
    engine = _guard_process(value, runtime=True)
    try:
        adapter = PostgresOperatorAuthorizationFence(value.owner_pin)
        with Session(engine, expire_on_commit=False) as session, session.begin():
            operator = session.get(OperatorRecord, value.target_id)
            assert operator is not None and operator.status == "ACTIVE"
            pid = session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            events.put(("READER_TRY", pid))
            try:
                adapter.fence_current_operator(session, value.target_id)
            except OperatorAuthorizationFenceError as error:
                return error.code
            assert session.get(OperatorRecord, value.target_id) is operator
            return "FENCED_ACTIVE_NOT_SESSION_AUTHORITY"
    finally:
        engine.dispose()


def _blocked(owner: Engine, waiting_pid: int, holding_pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with owner.connect() as connection:
            blockers = connection.scalar(
                text("SELECT pg_catalog.pg_blocking_pids(:pid)"), {"pid": waiting_pid}
            )
        if holding_pid in blockers:
            return
        multiprocessing.Event().wait(0.02)
    raise AssertionError("expected bounded real PostgreSQL row-lock contention")


def test_actual_limited_role_executes_fixed_routine_and_denies_iam_writes(
    prepared: PreparedFence,
) -> None:
    engine = _guard_process(prepared, runtime=True)
    try:
        with Session(engine) as session, session.begin():
            PostgresOperatorAuthorizationFence(prepared.owner_pin).fence_current_operator(
                session, prepared.target_id
            )
            assert PermissionKey.WORKFLOW_APPROVE in effective_permissions(
                session, prepared.target_id
            )
        for statement in (
            "SELECT operator_id FROM app.operators FOR SHARE",
            "UPDATE app.operators SET status=status WHERE false",
            "SELECT password_hash FROM app.operator_credentials WHERE false",
            "SELECT * FROM app.api_sessions WHERE false",
            "ALTER FUNCTION public.eom_fence_operator_authorization_v1(text) SECURITY INVOKER",
        ):
            with engine.begin() as connection, pytest.raises(DBAPIError) as error:
                connection.execute(text(statement))
            assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        engine.dispose()


def test_nested_rollback_retains_outer_fence_against_actual_role_revoke(
    prepared: PreparedFence,
) -> None:
    runtime, owner = _guard_process(prepared, runtime=True), _guard_process(prepared, runtime=False)
    context = multiprocessing.get_context("spawn")
    try:
        with context.Manager() as manager, ProcessPoolExecutor(1, mp_context=context) as pool:
            events, release = manager.Queue(), manager.Event()
            with Session(runtime) as session:
                root = session.begin()
                adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
                adapter.fence_current_operator(session, prepared.target_id)
                pid = session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
                nested = session.begin_nested()
                adapter.fence_current_operator(session, prepared.target_id)
                nested.rollback()
                adapter.fence_current_operator(session, prepared.target_id)
                writer = pool.submit(_writer, prepared, "revoke", events, release, False)
                label, writer_pid = events.get(timeout=10)
                assert label == "WRITER_TRY"
                _blocked(owner, writer_pid, pid)
                root.rollback()
                writer.result(timeout=15)
            with Session(runtime) as session:
                assert PermissionKey.WORKFLOW_APPROVE not in effective_permissions(
                    session, prepared.target_id
                )
    finally:
        runtime.dispose()
        owner.dispose()


@pytest.mark.parametrize("operation", ["disable", "password"])
def test_writer_first_wait_refresh_and_session_distinction(
    prepared: PreparedFence, operation: str
) -> None:
    owner = _guard_process(prepared, runtime=False)
    auth = _auth(owner)
    login = auth.login(
        username=prepared.target_username,
        password=prepared.password,
        client_name="synthetic-retired-session",
    )
    context = multiprocessing.get_context("spawn")
    try:
        with context.Manager() as manager, ProcessPoolExecutor(2, mp_context=context) as pool:
            events, release = manager.Queue(), manager.Event()
            writer = pool.submit(_writer, prepared, operation, events, release, True)
            label, writer_pid = events.get(timeout=10)
            assert label == "WRITER_TRY"
            assert events.get(timeout=10)[0] == "WRITER_LOCKED"
            reader = pool.submit(_reader, prepared, events)
            label, reader_pid = events.get(timeout=10)
            assert label == "READER_TRY"
            _blocked(owner, reader_pid, writer_pid)
            release.set()
            writer.result(timeout=15)
            result = reader.result(timeout=15)
            assert result == (
                "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                if operation == "disable"
                else "FENCED_ACTIVE_NOT_SESSION_AUTHORITY"
            )
        with pytest.raises(IdentityError):
            auth.authenticate_access(login.pair.access_token)
    finally:
        owner.dispose()


def test_acl_drift_cannot_reuse_root_witness_as_a_grant(prepared: PreparedFence) -> None:
    owner, runtime = _guard_process(prepared, runtime=False), _guard_process(prepared, runtime=True)
    try:
        with Session(runtime) as session, session.begin():
            adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
            adapter.fence_current_operator(session, prepared.target_id)
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "GRANT EXECUTE ON FUNCTION "
                        + OPERATOR_AUTHORIZATION_FENCE_SIGNATURE
                        + " TO PUBLIC"
                    )
                )
            try:
                with pytest.raises(
                    OperatorAuthorizationFenceError,
                    match="OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE",
                ):
                    adapter.fence_current_operator(session, prepared.target_id)
            finally:
                with owner.begin() as connection:
                    connection.execute(text(routine.OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL))
    finally:
        owner.dispose()
        runtime.dispose()


def test_actual_temp_shadow_is_denied_without_reading_or_deleting_its_contents(
    prepared: PreparedFence,
) -> None:
    runtime = _guard_process(prepared, runtime=True)
    try:
        with Session(runtime) as session, session.begin():
            adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
            adapter.fence_current_operator(session, prepared.target_id)
            session.connection().execute(
                text("CREATE TEMP TABLE operators (operator_id text, status text)")
            )
            with pytest.raises(
                OperatorAuthorizationFenceError,
                match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
            ):
                adapter.fence_current_operator(session, prepared.target_id)
        # No broad temp cleanup: dispose this guarded synthetic connection pool.
    finally:
        runtime.dispose()


@pytest.fixture
def ordinary_publication(prepared: PreparedFence, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real IAM/fence/policy/Graph rows; NOT a full Graph or NAS publication fixture.

    The existing relational seed deliberately has unmaterialized Artifact bytes.
    Only that immutable member-resolution port is synthetic here. The public
    policy parser, actual restricted login, installed SECURITY DEFINER routine,
    current actor/grants, and pinned Graph-row checks are real PostgreSQL paths.
    No ACL, function or cluster role is installed or widened by this fixture.
    """
    owner, runtime = _guard_process(prepared, runtime=False), _guard_process(prepared, runtime=True)
    now = datetime.now(UTC)
    value: dict[str, Any] = {
        "schema_version": "education-retrieval-access-policy/1.0",
        "access_policy_revision_id": "accessrev_" + uuid4().hex,
        "state": "RELEASED",
        "allowed_query_kinds": ["ITEM_PREPARATION"],
        "allowed_requester_roles": ["ADMIN"],
        "allowed_source_classes": ["APPROVED_ITEM", "CURRICULUM", "TEXTBOOK"],
        "answer_bearing_roles": ["ADMIN"],
        "maximum_budget": {
            "max_documents": 8,
            "max_item_revisions": 0,
            "max_graph_nodes": 64,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    value["content_sha256"] = content_sha256(value)
    policy = EducationRetrievalAccessPolicy.model_validate(value)
    try:
        with Session(owner) as session, session.begin():
            seed = _seed(session)
            snapshot = session.get(KnowledgeGraphSnapshotRecord, seed["snapshot"])
            assert snapshot is not None
            command_value = _command_value()
            graph_value = command_value["expected_graph_snapshot"]
            graph_value.update(
                graph_id=snapshot.graph_id,
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                manifest_sha256=snapshot.manifest_sha256,
            )
            graph_value["manifest_artifact"].update(
                artifact_id=snapshot.manifest_artifact_id,
                artifact_revision_id=snapshot.manifest_artifact_revision_id,
                sha256=snapshot.manifest_sha256,
            )
            graph = KnowledgeGraphSnapshotPointer.model_validate(graph_value)
            command_value.update(
                requested_by_operator_id=prepared.admin_id,
                access_policy_revision_id=policy.access_policy_revision_id,
                access_policy_sha256=policy.content_sha256,
                expected_graph_snapshot_sha256=snapshot.snapshot_sha256,
            )
            command = PublishOrdinaryApprovedItemAnalysesCommand.model_validate(
                _rehash(command_value)
            )
            session.add(
                EducationRetrievalAccessPolicyRevisionRecord(
                    access_policy_revision_id=policy.access_policy_revision_id,
                    schema_version=policy.schema_version,
                    state=policy.state,
                    content_sha256=policy.content_sha256,
                    canonical_document=policy.model_dump(mode="json"),
                    created_by="synthetic-disposable-publication-fence",
                    created_at=now,
                )
            )
        retrieval = KnowledgeRetrievalApplicationService(runtime)

        def resolved_member(_session: Session, revision_id: str) -> KnowledgeGraphSnapshotPointer:
            assert revision_id == graph.graph_snapshot_revision_id
            return graph

        monkeypatch.setattr(retrieval, "resolve_snapshot_pointer", resolved_member)
        service = OrdinaryItemGraphPublicationService(
            runtime,
            identity_fence=PostgresOperatorAuthorizationFence(prepared.owner_pin),
            retrieval=retrieval,
        )
        yield owner, runtime, service, command
    finally:
        owner.dispose()
        runtime.dispose()


def test_ordinary_publisher_real_limited_login_fences_actor_not_immutable_leaves(
    ordinary_publication: Any, prepared: PreparedFence
) -> None:
    owner, runtime, service, command = ordinary_publication
    with Session(runtime) as session, session.begin():
        assert session.scalar(text("SELECT SESSION_USER=CURRENT_USER")) is True
        assert session.scalar(text("SELECT CURRENT_USER")) == prepared.runtime_role
        service._authorize(session, command)
        assert (
            service._validate_pinned_base(session, command).graph_snapshot_revision_id
            == command.expected_graph_snapshot.graph_snapshot_revision_id
        )
        for table in (
            "operators",
            "roles",
            "permissions",
            "role_permissions",
            "operator_role_assignments",
            "education_retrieval_access_policy_revisions",
            "knowledge_graph_snapshots",
            "workflow_definitions",
            "resolved_execution_plans",
            "artifacts",
            "artifact_revisions",
        ):
            assert (
                session.scalar(
                    text("SELECT has_table_privilege(CURRENT_USER,:table,'SELECT')"),
                    {"table": "app." + table},
                )
                is True
            )
            assert (
                session.scalar(
                    text("SELECT has_any_column_privilege(CURRENT_USER,:table,'UPDATE')"),
                    {"table": "app." + table},
                )
                is False
            )
        held = {
            name: set(modes)
            for name, modes in session.execute(
                text(
                    "SELECT relation.relname,array_agg(locks.mode) FROM pg_locks locks "
                    "JOIN pg_class relation ON relation.oid=locks.relation "
                    "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
                    "WHERE locks.pid=pg_backend_pid() AND locks.granted "
                    "AND namespace.nspname='app' GROUP BY relation.relname"
                )
            )
        }
        assert "RowShareLock" in held["operators"]  # Actual SECURITY DEFINER target lock.
        for table in (
            "roles",
            "permissions",
            "role_permissions",
            "operator_role_assignments",
            "education_retrieval_access_policy_revisions",
            "knowledge_graph_snapshots",
        ):
            assert "AccessShareLock" in held[table]
            assert "RowShareLock" not in held[table]
        with pytest.raises(DBAPIError) as error, owner.begin() as writer:
            writer.execute(
                text(
                    "SELECT operator_id FROM app.operators WHERE operator_id=:id FOR UPDATE NOWAIT"
                ),
                {"id": command.requested_by_operator_id},
            )
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"
        # These old immutable row-lock calls would reproduce the real 42501.
        for table, column in (
            ("education_retrieval_access_policy_revisions", "access_policy_revision_id"),
            ("knowledge_graph_snapshots", "graph_snapshot_revision_id"),
        ):
            with pytest.raises(DBAPIError) as denied, session.begin_nested():
                session.execute(text(f"SELECT {column} FROM app.{table} FOR SHARE"))
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        service._authorize(session, command)  # Late check still uses this exact root fence.
        assert not session.new and not session.dirty and not session.deleted


@pytest.mark.parametrize("withdrawal", ["disable", "revoke_admin"])
def test_ordinary_publisher_rechecks_actual_actor_grants_after_prior_root(
    ordinary_publication: Any, prepared: PreparedFence, withdrawal: str
) -> None:
    owner, runtime, service, command = ordinary_publication
    with Session(runtime, expire_on_commit=False) as session:
        with session.begin():
            cached = session.get(OperatorRecord, prepared.admin_id)
            assert cached is not None and cached.status == "ACTIVE"
            service._authorize(session, command)
        # Synthetic test metadata only, after the prior root has ended; no live
        # actor mutation, impersonation or additional permissions are involved.
        with Session(owner) as writer, writer.begin():
            if withdrawal == "disable":
                actor = writer.get(OperatorRecord, prepared.admin_id)
                assert actor is not None
                actor.status = "DISABLED"
            else:
                admin = require_role(writer, RoleKey.ADMIN)
                assignment = writer.scalar(
                    select(OperatorRoleAssignmentRecord).where(
                        OperatorRoleAssignmentRecord.operator_id == prepared.admin_id,
                        OperatorRoleAssignmentRecord.role_id == admin.role_id,
                        OperatorRoleAssignmentRecord.revoked_at.is_(None),
                    )
                )
                assert assignment is not None
                assignment.revoked_at = datetime.now(UTC)
                assignment.revoked_by = "synthetic-disposable-owner"
        with (
            pytest.raises(
                (OrdinaryItemGraphPublicationError, OperatorAuthorizationFenceError),
                match="FORBIDDEN",
            ),
            session.begin(),
        ):
            service._authorize(session, command)


@pytest.mark.parametrize("pin", ["policy", "graph_semantic", "graph_member"])
def test_ordinary_publisher_limited_role_rejects_changed_pins_without_publication(
    ordinary_publication: Any, pin: str
) -> None:
    _owner, runtime, service, command = ordinary_publication
    value = command.model_dump(mode="json")
    if pin == "policy":
        value["access_policy_sha256"] = "sha256:" + "0" * 64
    elif pin == "graph_semantic":
        value["expected_graph_snapshot_sha256"] = "sha256:" + "0" * 64
    else:
        value["expected_graph_snapshot"]["manifest_sha256"] = "sha256:" + "0" * 64
        value["expected_graph_snapshot"]["manifest_artifact"]["sha256"] = "sha256:" + "0" * 64
    changed = PublishOrdinaryApprovedItemAnalysesCommand.model_validate(_rehash(value))
    with (
        Session(runtime) as session,
        pytest.raises(
            OrdinaryItemGraphPublicationError,
            match="FORBIDDEN" if pin == "policy" else "BASE_POINTER_INVALID",
        ),
        session.begin(),
    ):
        service._authorize(session, changed)
        service._validate_pinned_base(session, changed)
