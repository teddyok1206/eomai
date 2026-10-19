"""Guarded real-login ACL/locking regression; never production authority.

The isolated schema uses LIKE (including columns/checks/indexes, NOT triggers or
FKs). It proves the SELECT-only/parent-lock boundary with a real restricted login,
not production immutability. A separate test exercises actual app migration
triggers through the existing relational fixture, inside an owner rollback.
Local members and source authorization are synthetic; no NAS/model/IAM proof.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from eom_catalog_contracts.mixed_embedding_index import RegisteredReviewEmbeddingEntry
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.evidence_usage_receipts import OrchestratorEvidenceUsageReceiptResolver
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.registered_item_review_solution_resolver import (
    lock_registered_item_review_sources,
)
from eom_catalog_service.registered_review_embedding_capture import (
    capture_registered_review_embedding_entries,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_embedding_registry_persistence import _binding_source_ids, _seed
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import view_recipe
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_registered_review_embedding_capture import _capture_fixture

pytestmark = pytest.mark.integration

_PARENTS = (ItemRevisionRecord, WorkflowInstanceRecord, WorkflowStepRunRecord, JobRecord)
_LEAVES = (
    ItemComponentRecord,
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    ResolvedExecutionPlanRecord,
    WorkflowDefinitionRecord,
)
_MODELS = (ItemRecord, *_PARENTS, *_LEAVES)


def _payload(row: Any, number: int) -> dict[str, Any]:
    """Fill DB-only required fixture metadata, never change canonical proof JSON."""
    model = type(row)
    value = {key: item for key, item in vars(row).items() if key in model.__table__.columns}
    if model is ItemRecord:
        value.setdefault("created_by", "restricted-role-disposable-fixture")
    elif model is ItemRevisionRecord:
        value.setdefault("registration_key", "restricted-role:" + str(number))
        value.setdefault("item_type_key", "synthetic")
        value.setdefault("created_by", "restricted-role-disposable-fixture")
    elif model is ItemComponentRecord:
        value.setdefault("item_component_id", "component_" + f"{number:032x}")
    elif model is WorkflowDefinitionRecord:
        # Unit fixture uses a descriptive ID wider than the actual SQL column.
        # This SQL-only FK identity is not part of the canonical definition hash.
        value["definition_id"] = "wfdef_" + "f" * 32
        value.setdefault("schema_version", value["canonical_definition"]["schema_version"])
        value.setdefault("source_path", "synthetic:restricted-role-fixture")
    elif model is WorkflowInstanceRecord:
        value.update(
            definition_id="wfdef_" + "f" * 32,
            protocol_version="workflow/1.0",
            stage="COMPLETED",
            current_step_key="registration",
            runtime_context={},
            idempotency_key="restricted-role:" + value["workflow_id"],
            created_actor_type="human",
            created_actor_id="synthetic-fixture-not-authority",
            completed_at=NOW,
        )
    return value


@pytest.fixture
def restricted_case(
    guarded_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    environment = state / "runtime.env"
    assert not environment.is_symlink() and environment.stat().st_mode & 0o077 == 0
    values = dict(line.split("=", 1) for line in environment.read_text().splitlines())
    runtime_url = make_url(values["EOM_API_DATABASE_URL"])
    assert (
        runtime_url.database == manifest.database and runtime_url.username == manifest.runtime_role
    )
    schema = "registered_review_lock_" + uuid4().hex
    role = guarded_engine.dialect.identifier_preparer.quote(manifest.runtime_role)
    with guarded_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        for model in _MODELS:
            name = model.__tablename__
            connection.exec_driver_sql(
                f'CREATE TABLE "{schema}".{name} (LIKE app.{name} INCLUDING ALL)'
            )
            connection.exec_driver_sql(f'GRANT SELECT ON "{schema}".{name} TO {role}')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}')
        for model in _PARENTS:
            connection.exec_driver_sql(
                f'GRANT UPDATE ON "{schema}".{model.__tablename__} TO {role}'
            )
    options = {"options": f"-csearch_path={schema},pg_catalog"}
    owner = build_engine(
        guarded_engine.url.set(query=options).render_as_string(hide_password=False)
    )
    runtime = build_engine(runtime_url.set(query=options).render_as_string(hide_password=False))
    try:
        fixture = _capture_fixture(tmp_path, monkeypatch)
        fake = fixture["session"]
        rows = [*fake.records.values(), *fake.components, *fake.steps, *fake.events]
        with owner.begin() as connection:
            for number, row in enumerate(rows, start=1):
                assert type(row) in _MODELS
                connection.execute(insert(type(row).__table__), _payload(row, number))
        fixture.update(
            owner=owner, runtime=runtime, schema=schema, runtime_role=manifest.runtime_role
        )
        yield fixture
    finally:
        runtime.dispose()
        owner.dispose()
        # Exact test-created schema only; actual app rows/grants/roles are untouched.
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def _locks(session: Session, schema: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for name, mode in session.execute(
        text(
            "SELECT relation.relname,locks.mode FROM pg_locks locks "
            "JOIN pg_class relation ON relation.oid=locks.relation "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE locks.pid=pg_backend_pid() AND locks.granted AND namespace.nspname=:schema"
        ),
        {"schema": schema},
    ):
        values.setdefault(name, set()).add(mode)
    return values


def _assert_lock_boundary(session: Session, case: dict[str, Any]) -> None:
    assert session.scalar(text("SELECT session_user")) == case["runtime_role"]
    assert session.scalar(text("SELECT current_user")) == case["runtime_role"]
    assert session.scalar(text("SELECT current_schema()")) == case["schema"]
    held = _locks(session, case["schema"])
    for model in _PARENTS:
        assert "RowShareLock" in held[model.__tablename__]
    for model in _LEAVES:
        assert "AccessShareLock" in held[model.__tablename__]
        assert "RowShareLock" not in held[model.__tablename__]


def test_real_restricted_login_runs_public_proof_locks_and_blocks_parent_writers(
    restricted_case: dict[str, Any],
) -> None:
    case = restricted_case
    with Session(case["runtime"]) as session, session.begin():
        sources = tuple(value["source"] for value in case["fixtures"])
        held = lock_registered_item_review_sources(session, sources=sources)
        held.assert_current(session)
        # The standalone proof-lock API does not read plan/definition classification.
        locks = _locks(session, case["schema"])
        for model in _PARENTS:
            assert "RowShareLock" in locks[model.__tablename__]
        for model in _LEAVES[:4]:
            assert "AccessShareLock" in locks[model.__tablename__]
            assert "RowShareLock" not in locks[model.__tablename__]
        assert session.scalar(text("SELECT session_user=current_user")) is True
        assert session.scalar(text("SELECT session_user")) == case["runtime_role"]
        for model in _PARENTS:
            key = next(iter(model.__table__.primary_key.columns)).name
            identity = session.scalar(select(getattr(model, key)).limit(1))
            with case["owner"].connect() as competing:
                with pytest.raises(DBAPIError) as error, competing.begin():
                    competing.execute(
                        text(
                            f"SELECT {key} FROM {model.__tablename__} "
                            f"WHERE {key}=:id FOR UPDATE NOWAIT"
                        ),
                        {"id": identity},
                    )
                assert error.value.orig.sqlstate == "55P03"


def test_real_restricted_login_runs_full_public_mixed_capture_with_real_local_members(
    restricted_case: dict[str, Any], tmp_path: Path
) -> None:
    case = restricted_case
    artifacts = CatalogArtifactService(case["runtime"], CatalogSettings(nas_artifact_root=tmp_path))
    receipts = OrchestratorEvidenceUsageReceiptResolver(build_session_factory(case["runtime"]))
    authorized = []
    with Session(case["runtime"]) as session, session.begin():
        captured = capture_registered_review_embedding_entries(
            session,
            admitted_sources=case["admitted"],
            existing_entries=(),
            graph_snapshot=case["graph"],
            recipe=view_recipe(),
            artifacts=artifacts,
            receipts=receipts,
            authorize_source=authorized.append,
        )
        captured.assert_current(session)
        assert len(captured.entries) == 1 and captured.missing_source_revision_ids == ()
        entry = captured.entries[0]
        assert isinstance(entry, RegisteredReviewEmbeddingEntry)
        assert (
            entry.profile.source_basis.review_evidence.evidence_kind
            == "REGISTERED_ITEM_REVIEW_SOLUTION"
        )
        assert entry.profile.source_basis.review_evidence.source == case["admitted"][0].source
        assert captured.base_analysis_run_ids == (
            (case["admitted"][0].source.item_revision_id, case["admitted"][0].analysis_run_id),
        )
        assert len(authorized) == 4  # Synthetic callback only, never genuine IAM proof.
        _assert_lock_boundary(session, case)


def test_select_only_leaves_deny_rowlocks_update_delete_without_grant_widening(
    restricted_case: dict[str, Any],
) -> None:
    case = restricted_case
    with Session(case["runtime"]) as session, session.begin():
        for model in _LEAVES:
            table = model.__tablename__
            key = next(iter(model.__table__.primary_key.columns)).name
            assert session.scalar(
                text(f"SELECT has_table_privilege(current_user,'{table}','SELECT')")
            )
            assert not session.scalar(
                text(f"SELECT has_table_privilege(current_user,'{table}','UPDATE')")
            )
            assert not session.scalar(
                text(f"SELECT has_table_privilege(current_user,'{table}','DELETE')")
            )
            for statement in (
                f"SELECT {key} FROM {table} FOR SHARE",
                f"UPDATE {table} SET {key}={key}",
                f"DELETE FROM {table}",
            ):
                with pytest.raises(DBAPIError) as error, session.begin_nested():
                    session.execute(text(statement))
                assert error.value.orig.sqlstate == "42501"


def test_actual_app_approved_component_artifact_plan_definition_triggers_reject_mutation(
    guarded_engine: Engine,
) -> None:
    # Unlike LIKE clones, these are actual migrated app tables/triggers. No row
    # or grant survives this root rollback; all referenced metadata is synthetic.
    with guarded_engine.connect() as connection, connection.begin() as transaction:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            seed = _seed(session)
            _item, revision_id, base_id, _solution = _binding_source_ids(session, seed)
            revision = session.get(ItemRevisionRecord, revision_id)
            assert revision is not None
            workflow = session.get(WorkflowInstanceRecord, revision.workflow_id)
            base = session.get(KnowledgeAnalysisRunRecord, base_id)
            assert workflow is not None and base is not None
            component_id = "component_" + uuid4().hex
            session.add(
                ItemComponentRecord(
                    item_component_id=component_id,
                    item_revision_id=revision_id,
                    component_type="ITEM_CONTENT",
                    ordinal=0,
                    schema_ref="synthetic-not-source-proof",
                    media_type="application/json",
                    artifact_id=seed["artifact"],
                    artifact_revision_id=seed["artifact_revision"],
                    sha256=revision.manifest_sha256,
                    logical_name="synthetic-component",
                    required=True,
                    metadata_json={},
                )
            )
            session.flush()
            revision.revision_state, revision.approved_at, revision.approved_by = (
                "APPROVED",
                NOW,
                "test",
            )
            session.flush()
            for table, key, identity in (
                ("item_components", "item_component_id", component_id),
                ("artifacts", "logical_artifact_id", seed["artifact"]),
                ("artifact_revisions", "revision_id", seed["artifact_revision"]),
                ("resolved_execution_plans", "plan_id", base.plan_id),
                ("workflow_definitions", "definition_id", workflow.definition_id),
            ):
                for statement in (
                    f"UPDATE app.{table} SET {key}={key} WHERE {key}=:id",
                    f"DELETE FROM app.{table} WHERE {key}=:id",
                ):
                    with pytest.raises(DBAPIError) as error, session.begin_nested():
                        session.execute(text(statement), {"id": identity})
                    assert error.value.orig.sqlstate == "P0001"
                    assert (
                        session.scalar(
                            text(f"SELECT count(*) FROM app.{table} WHERE {key}=:id"),
                            {"id": identity},
                        )
                        == 1
                    )
        transaction.rollback()
