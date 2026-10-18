"""Real target locks in guarded disposable PostgreSQL; no Chat/native/auth grant."""

from dataclasses import replace
from uuid import uuid4

import pytest
from eom_identity_service import OperatorAuthorizationFenceError, OperatorAuthorizationFenceOwnerPin
from eom_identity_service.models import OperatorRecord
from eom_identity_service.owned_operator_authorization_fence import OwnedOperatorAuthorizationFence
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def owned(guarded_engine):
    engine = create_engine(
        guarded_engine.url,
        connect_args={"options": "-c search_path=app,pg_catalog"},
        isolation_level="READ COMMITTED",
        pool_size=3,
        max_overflow=0,
        pool_timeout=10,
    )
    actor = "operator_" + uuid4().hex
    with engine.begin() as connection:
        name, oid = connection.execute(
            text(
                "SELECT CURRENT_USER,role.oid::pg_catalog.int8 FROM pg_catalog.pg_roles role "
                "WHERE role.rolname=CURRENT_USER"
            )
        ).one()
    with Session(engine) as session, session.begin():
        session.add(
            OperatorRecord(
                operator_id=actor,
                username="owner-fence-" + uuid4().hex,
                normalized_username="owner-fence-" + uuid4().hex,
                display_name="Disposable target",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-test",
            )
        )
    fence = OwnedOperatorAuthorizationFence(OperatorAuthorizationFenceOwnerPin(name, oid), actor)
    try:
        yield engine, actor, fence
    finally:
        engine.dispose()


def test_real_owner_target_read_changes_no_rows_and_restores_wait_settings(owned):
    engine, actor, fence = owned
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL lock_timeout='75ms'"))
        session.execute(text("SET LOCAL statement_timeout='1500ms'"))
        before = session.get(OperatorRecord, actor).role_version
        fence.fence_current_operator(session, actor)
        fence.fence_current_operator(session, actor)
        assert session.scalar(text("SHOW lock_timeout")) == "75ms"
        assert session.scalar(text("SHOW statement_timeout")) == "1500ms"
        assert not session.new and not session.dirty and not session.deleted
        assert session.get(OperatorRecord, actor).role_version == before


def test_shared_target_lock_blocks_writer_until_the_exact_root_finishes(owned):
    engine, actor, fence = owned
    with Session(engine) as reader:
        root = reader.begin()
        fence.fence_current_operator(reader, actor)
        with pytest.raises(DBAPIError) as error, engine.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout='75ms'"))
            writer.execute(
                text("UPDATE app.operators SET display_name='writer' WHERE operator_id=:actor"),
                {"actor": actor},
            )
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"
        root.commit()
    with engine.begin() as writer:
        writer.execute(text("SET LOCAL lock_timeout='500ms'"))
        writer.execute(
            text("UPDATE app.operators SET display_name='writer' WHERE operator_id=:actor"),
            {"actor": actor},
        )
    with Session(engine) as session, session.begin():
        assert session.get(OperatorRecord, actor).display_name == "writer"
        fence.fence_current_operator(session, actor)


def test_exclusive_writer_causes_bounded_failure_not_cached_authority(owned):
    engine, actor, fence = owned
    with engine.begin() as writer:
        writer.execute(
            text("SELECT operator_id FROM app.operators WHERE operator_id=:actor FOR UPDATE"),
            {"actor": actor},
        )
        with (
            Session(engine) as reader,
            pytest.raises(OperatorAuthorizationFenceError, match="UNAVAILABLE"),
            reader.begin(),
        ):
            reader.execute(text("SET LOCAL lock_timeout='75ms'"))
            fence.fence_current_operator(reader, actor)


def test_current_operator_refresh_rejects_disable_after_prior_root_success(owned):
    engine, actor, fence = owned
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            cached = session.get(OperatorRecord, actor)
            fence.fence_current_operator(session, actor)
        with engine.begin() as writer:
            writer.execute(
                text("UPDATE app.operators SET status='DISABLED' WHERE operator_id=:actor"),
                {"actor": actor},
            )
        assert cached.status == "ACTIVE"
        with pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"), session.begin():
            fence.fence_current_operator(session, actor)


@pytest.mark.parametrize(
    "fault", ("actor", "oid", "namespace", "isolation", "readonly", "nested", "pending")
)
def test_real_context_mismatch_never_becomes_a_source_grant(owned, fault):
    engine, actor, fence = owned
    selected = fence
    if fault == "oid":
        selected = replace(fence, owner=replace(fence.owner, role_oid=fence.owner.role_oid + 1))
    with (
        Session(engine) as session,
        pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"),
        session.begin(),
    ):
        if fault == "namespace":
            session.execute(text("SET LOCAL search_path=app,public"))
        elif fault == "isolation":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        elif fault == "readonly":
            session.execute(text("SET TRANSACTION READ ONLY"))
        elif fault == "nested":
            with session.begin_nested():
                selected.fence_current_operator(session, actor)
        elif fault == "pending":
            row = session.scalar(select(OperatorRecord).where(OperatorRecord.operator_id == actor))
            row.display_name = "not flushed"
        selected.fence_current_operator(
            session, "operator_" + uuid4().hex if fault == "actor" else actor
        )
