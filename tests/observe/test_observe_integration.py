from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

pytest.importorskip("eom_observe")

from eom_observe.database import build_readonly_engine
from eom_observe.read_model import REQUIRED_READ_MODEL_TABLES
from eom_observe.repository import ObserveRepository
from eom_observe.settings import load_secrets, load_settings
from eom_observe.snapshot import SnapshotBuilder
from eom_observe.stream import SharedSnapshotPoller, SubscriptionHub
from eom_observe_contracts import validate_contract
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.observe_integration


def enabled() -> None:
    if os.environ.get("EOM_RUN_OBSERVE_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_OBSERVE_INTEGRATION=1 after installing the read-only role")


def repository() -> ObserveRepository:
    enabled()
    config = load_settings()
    secret = load_secrets()
    return ObserveRepository(
        build_readonly_engine(secret.database_url, config.snapshot.query_timeout_ms),
        event_limit=config.snapshot.recent_event_limit,
    )


def test_readonly_role_select_and_write_denials() -> None:
    repo = repository()
    assert repo.ping()
    assert repo.database_is_readonly()
    assert repo.required_tables() == list(REQUIRED_READ_MODEL_TABLES)
    for statement in (
        "INSERT INTO worker_slots (slot_id,linux_user,role,enabled,gpu) "
        "VALUES ('zz','denied','support',false,false)",
        "UPDATE worker_slots SET enabled=enabled WHERE slot_id='01'",
        "DELETE FROM worker_slots WHERE slot_id='zz'",
        "CREATE TABLE observe_write_must_fail (id integer)",
        "UPDATE workflow_commands SET state=state WHERE false",
        "UPDATE worker_leases SET state=state WHERE false",
        "UPDATE api_idempotency_records SET state=state WHERE false",
    ):
        with pytest.raises(DBAPIError), repo.engine.connect() as connection, connection.begin():
            connection.execute(text(statement))
    repo.engine.dispose()


def test_operational_overview_contract_and_column_grant_boundaries() -> None:
    repo = repository()
    overview = repo.operational_overview_rows(
        recent_failure_window_seconds=3600,
        attention_limit=100,
    )
    assert overview.observed_at.tzinfo is not None
    assert set(overview.counts) == {
        "active_workflow_commands",
        "active_jobs",
        "held_worker_leases",
        "processing_api_requests",
        "pending_human_approvals",
        "executable_workflows",
        "quiescent_nonterminal_workflows",
        "recent_failed_workflows",
        "recent_failed_jobs",
        "historical_failed_workflows",
        "historical_failed_jobs",
    }
    for statement in (
        "SELECT payload FROM workflow_commands LIMIT 0",
        "SELECT release_reason FROM worker_leases LIMIT 0",
        "SELECT response_body FROM api_idempotency_records LIMIT 0",
    ):
        with pytest.raises(DBAPIError), repo.engine.connect() as connection:
            connection.execute(text(statement))
    repo.engine.dispose()


def test_current_platform_workflow_approval_artifact_projection() -> None:
    repo = repository()
    rows = repo.snapshot_rows()
    assert rows.workers
    assert rows.jobs
    assert rows.workflows
    assert rows.revisions
    assert [
        row["sequence"]
        for row in rows.workflow_events
        if row["workflow_id"] == rows.workflow_events[0]["workflow_id"]
    ]
    repo.engine.dispose()


def test_snapshot_contract_and_query_timeout() -> None:
    repo = repository()
    snapshot = SnapshotBuilder(repo, load_settings()).build()
    validate_contract("snapshot", snapshot.model_dump(mode="json"))
    assert snapshot.data_freshness.database == "fresh"
    assert len(snapshot.nodes) == len({node.node_id for node in snapshot.nodes})
    assert {node.role for node in snapshot.nodes if node.node_type == "WORKER"} == {
        "authoring",
        "review",
        "image",
        "item_management",
        "support",
    }
    repo.engine.dispose()


def test_database_degraded_last_good_and_recovery() -> None:
    repo = repository()
    builder = SnapshotBuilder(repo, load_settings())

    async def scenario() -> None:
        hub = SubscriptionHub(max_clients=1)
        _, queue = await hub.subscribe()
        poller = SharedSnapshotPoller(builder, hub, poll_interval_seconds=1)

        await poller._poll_once()
        assert (await queue.get()).event == "snapshot"
        last_good = poller.last_good
        assert last_good is not None

        with patch.object(builder, "build", side_effect=RuntimeError("database unavailable")):
            await poller._poll_once()
        assert (await queue.get()).event == "degraded"
        assert poller.current is not None
        assert poller.current.data_freshness.database == "stale"
        assert poller.last_good == last_good

        await poller._poll_once()
        assert (await queue.get()).event == "recovered"
        assert poller.current is not None
        assert poller.current.data_freshness.database == "fresh"

    asyncio.run(scenario())
    repo.engine.dispose()
