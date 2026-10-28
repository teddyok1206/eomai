"""Opt-in snapshot reset: exact disposable marker, never an operational DB.

The final test intentionally commits the reset only in the supplied disposable
snapshot. Earlier failures/drift/interruption tests must leave it unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from eom_catalog_service import prelaunch_item_cleanup as catalog
from eom_hwpx_manager import prelaunch_item_cleanup as hwpx
from eom_orchestrator import prelaunch_artifact_cleanup as artifacts
from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction
from eom_orchestrator.prelaunch_item_reset_service import PrelaunchItemResetService
from eom_protocol.prelaunch_item_reset import (
    BASE_GRAPH,
    KEEP_ITEM_ID,
    MIXED_GRAPHS,
    PrelaunchItemResetPlan,
    ResetBackupPin,
    reset_digest,
)
from eom_workflow_runner import prelaunch_item_cleanup as workflows

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def connection():
    state = os.environ.get("EOM_PRELAUNCH_RESET_TEST_STATE")
    if state is None:
        pytest.skip("exact disposable snapshot opt-in required")
    root = Path(state)
    assert root.parent == Path("/tmp") and root.name.startswith("eom-api-testdb-")
    manifest = DisposableManifest.load(root / "manifest.json")
    assert manifest.database.startswith("eom_api_test_")
    values = dict(
        line.split("=", 1)
        for line in Path("/etc/eom/secrets/postgres.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    with psycopg.connect(
        host="127.0.0.1",
        dbname=manifest.database,
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        options="-csearch_path=app,pg_catalog",
    ) as value:
        with value.cursor() as q:
            q.execute(
                "SELECT d.datname,description.description FROM pg_database d JOIN "
                "pg_shdescription description ON description.objoid=d.oid AND "
                "description.classoid='pg_database'::regclass WHERE "
                "d.datname=current_database()"
            )
            assert q.fetchone() == (manifest.database, manifest.marker)
        value.rollback()
        yield value


class DisposableSnapshotFence:
    def verify(self) -> None:
        pass  # The exact DB marker was established by the fixture; no host work uses this DB.

    def verify_backup(self, database: str, backup: ResetBackupPin) -> None:
        assert database.startswith("eom_api_test_")
        assert backup.file_name == "eom_20261028T105705Z_e13d65090d66.dump"


@pytest.fixture(scope="module")
def service() -> PrelaunchItemResetService:
    return PrelaunchItemResetService(
        catalog=catalog,
        workflows=workflows,
        hwpx=hwpx,
        artifacts=artifacts,
        host=DisposableSnapshotFence(),
    )


@pytest.fixture(scope="module")
def plan(connection, service) -> PrelaunchItemResetPlan:
    return service.prepare(
        connection,
        ResetBackupPin(
            file_name="eom_20261028T105705Z_e13d65090d66.dump",
            sha256="e13d65090d66" + "0" * 52,
            size_bytes=1,
        ),
    )


def assert_original(connection) -> None:
    with connection.cursor() as q:
        q.execute(
            (
                "SELECT count(*) FROM item_revisions WHERE item_id<>%s AND workflow_id IN "
                "(SELECT workflow_id FROM workflow_instances WHERE "
                "definition_key='generic-item-development')"
            ),
            (KEEP_ITEM_ID,),
        )
        assert q.fetchone() == (111,)
        q.execute(
            "SELECT current_graph_snapshot_revision_id FROM knowledge_corpora WHERE "
            "corpus_key='integrated-science-textbooks'"
        )
        assert q.fetchone() == (MIXED_GRAPHS[1],)
        q.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN "
            "pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND NOT "
            "t.tgisinternal AND t.tgenabled<>'O'"
        )
        assert q.fetchone() == (0,)
        q.execute(
            "SELECT "
            "to_regclass('app.eom_prelaunch_node_artifact_lookup'),to_regclass('app.eom_"
            "prelaunch_edge_artifact_lookup')"
        )
        assert q.fetchone() == (None, None)
    connection.rollback()


def test_plan_is_exact_and_hash_valid(plan) -> None:
    assert len(plan.item_ids) == 110 and len(plan.item_revision_ids) == 111
    assert len(plan.workflow_ids) >= 902 and len(plan.job_ids) >= 2096
    assert PrelaunchItemResetPlan.model_validate_json(plan.model_dump_json()) == plan


def test_drift_is_rejected_without_mutation(connection, service, plan) -> None:
    value = plan.model_dump(mode="json")
    value["baseline_sha256"] = "0" * 64
    value.pop("plan_sha256")
    changed = PrelaunchItemResetPlan.model_validate(value | {"plan_sha256": reset_digest(value)})
    with pytest.raises(ValueError, match="ITEM_RESET_PLAN_DRIFT"):
        service.apply(connection, changed)
    assert_original(connection)


def test_component_mutation_requires_own_scope(connection, plan) -> None:
    with (
        connection.transaction(),
        connection.cursor() as q,
        pytest.raises(ValueError, match="COMPONENT_SCOPE"),
    ):
        hwpx.delete_prelaunch_builds(MetadataResetTransaction(q), plan.item_ids)
    assert_original(connection)


def test_root_lock_rejects_concurrent_item_change(connection, plan) -> None:
    with connection.transaction(), connection.cursor() as q:
        cursor = MetadataResetTransaction(q)
        cursor.freeze_writes()
        with psycopg.connect(
            host=connection.info.host,
            port=connection.info.port,
            dbname=connection.info.dbname,
            user=connection.info.user,
            password=connection.info.password,
        ) as other:
            with other.cursor() as update:
                update.execute("SET LOCAL lock_timeout='200ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    update.execute(
                        "UPDATE app.items SET lock_version=lock_version+1 WHERE item_id=%s",
                        (KEEP_ITEM_ID,),
                    )
            other.rollback()
    assert_original(connection)


def test_interruption_rolls_back_graphs_items_triggers_and_indexes(
    connection, service, plan, monkeypatch
) -> None:
    def interrupted(*_args):
        raise RuntimeError("TEST_RESET_INTERRUPT")

    with monkeypatch.context() as patch:
        patch.setattr(artifacts, "delete_exclusive_reset_jobs", interrupted)
        with pytest.raises(RuntimeError, match="TEST_RESET_INTERRUPT"):
            service.apply(connection, plan)
    assert_original(connection)


def test_apply_then_exact_replay_preserves_all_protected_metadata(
    connection, service, plan
) -> None:
    receipt = service.apply(connection, plan)
    assert receipt.deleted_items == 110
    assert receipt.deleted_item_revisions == 111
    assert receipt.shared_jobs_preserved > 0
    assert receipt.exclusive_jobs_deleted > 0
    assert receipt.protected_sha256 == plan.protected_sha256
    assert service.apply(connection, plan) == receipt
    with connection.cursor() as q:
        q.execute(
            "SELECT current_graph_snapshot_revision_id FROM knowledge_corpora WHERE "
            "corpus_key='integrated-science-textbooks'"
        )
        assert q.fetchone() == (BASE_GRAPH,)
        q.execute(
            "SELECT "
            "to_regclass('app.eom_prelaunch_node_artifact_lookup'),to_regclass('app.eom_"
            "prelaunch_edge_artifact_lookup')"
        )
        assert q.fetchone() == (None, None)
    connection.rollback()
