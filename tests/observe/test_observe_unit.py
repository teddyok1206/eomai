from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from importlib.resources import files
from pathlib import Path

import pytest

pytest.importorskip("eom_observe")

from eom_observe.auth import LoginRateLimiter
from eom_observe.build_info import get_build_info
from eom_observe.cli import rotate_token
from eom_observe.errors import ObserveError, ObserveErrorCode
from eom_observe.event_mapper import merge_events, role_node
from eom_observe.logging import JsonFormatter
from eom_observe.redaction import (
    logical_artifact_uri,
    metadata_summary,
    sanitize_error,
    sanitize_path,
)
from eom_observe.security import (
    SessionSigner,
    generate_access_token,
    hash_access_token,
    verify_access_token,
)
from eom_observe.settings import load_secrets, parse_environment_file
from eom_observe.snapshot import canonical_snapshot_hash
from eom_observe.state_derivation import derive_edges, derive_nodes
from eom_observe.stream import SharedSnapshotPoller, StreamMessage, SubscriptionHub, format_sse
from eom_observe_contracts import NodeStatus
from eom_observe_contracts.validation import SCHEMA_FILES, schema_resource

from tests.observe.helpers import NOW, event, settings, snapshot


def test_worker_role_mapping() -> None:
    assert role_node("authoring") == "authoring"
    assert role_node("item_management") == "item-management"
    assert role_node("unknown") == "orchestrator"


@pytest.mark.parametrize(
    ("job_status", "expected"),
    [("QUEUED", NodeStatus.QUEUED), ("RUNNING", NodeStatus.RUNNING)],
)
def test_worker_state_derivation(job_status: str, expected: NodeStatus) -> None:
    config = settings()
    nodes = derive_nodes(
        workers=[
            {"slot_id": "01", "linux_user": "eom-cdx-01", "role": "authoring", "enabled": True}
        ],
        workflows=[],
        steps=[
            {
                "step_run_id": "steprun_1",
                "workflow_id": "workflow_1",
                "step_key": "authoring",
                "attempt": 1,
                "state": "RUNNING",
                "worker_role": "authoring",
                "platform_job_id": "job_1",
                "job_status": job_status,
                "started_at": NOW,
                "finished_at": None,
                "input_pointer_manifest": {},
            }
        ],
        jobs=[],
        approvals=[],
        events=[],
        privacy=config.privacy,
        database_fresh=True,
        system_probe_fresh=True,
        now=NOW,
    )
    assert next(node for node in nodes if node.node_id == "authoring").status == expected


def test_workflow_and_approval_state_mapping() -> None:
    config = settings()
    nodes = derive_nodes(
        workers=[],
        workflows=[{"workflow_id": "workflow_1", "state": "RUNNING", "current_step_key": "review"}],
        steps=[],
        jobs=[],
        approvals=[{"workflow_id": "workflow_1", "status": "PENDING"}],
        events=[],
        privacy=config.privacy,
        database_fresh=True,
        system_probe_fresh=True,
        now=NOW,
    )
    assert next(node for node in nodes if node.node_id == "workflow-runner").status == "RUNNING"
    assert next(node for node in nodes if node.node_id == "human-approval").status == "WAITING"


def test_missing_worker_and_failed_probe_state_derivation() -> None:
    config = settings()
    unavailable = derive_nodes(
        workers=[
            {"slot_id": "01", "linux_user": "eom-cdx-01", "role": "authoring", "enabled": True}
        ],
        workflows=[],
        steps=[],
        jobs=[],
        approvals=[],
        events=[],
        privacy=config.privacy,
        database_fresh=True,
        system_probe_fresh=True,
        available_workers={"eom-cdx-01": False},
        now=NOW,
    )
    authoring = next(node for node in unavailable if node.node_id == "authoring")
    assert authoring.status == "UNAVAILABLE"

    unknown = derive_nodes(
        workers=[
            {"slot_id": "01", "linux_user": "eom-cdx-01", "role": "authoring", "enabled": True}
        ],
        workflows=[],
        steps=[],
        jobs=[],
        approvals=[],
        events=[],
        privacy=config.privacy,
        database_fresh=True,
        system_probe_fresh=False,
        now=NOW,
    )
    assert next(node for node in unknown if node.node_id == "authoring").data_freshness == "unknown"
    assert (
        next(node for node in unknown if node.node_id == "workflow-runner").data_freshness
        == "unknown"
    )


def test_event_merge_stable_ordering() -> None:
    job_rows = [
        {
            "event_id": 2,
            "job_id": "job_1",
            "sequence": 2,
            "to_state": "RUNNING",
            "event": "WORKER_STARTED",
            "created_at": NOW,
            "worker_role": "authoring",
            "workflow_id": "workflow_1",
            "step_run_id": "steprun_1",
            "logical_artifact_id": None,
            "revision_id": None,
            "error_code": None,
        }
    ]
    workflow_rows = [
        {
            "event_id": 1,
            "workflow_id": "workflow_1",
            "sequence": 1,
            "event_type": "WORKFLOW_STARTED",
            "new_state": "RUNNING",
            "step_key": "authoring",
            "created_at": NOW,
        }
    ]
    merged = merge_events(
        job_events=job_rows,
        workflow_events=workflow_rows,
        steps=[],
        approvals=[],
        revisions=[],
        limit=20,
    )
    assert [item.source for item in merged] == ["workflow_event", "job_event"]


def test_edge_mapping_and_activity() -> None:
    edges = derive_edges([event()], active_seconds=4, now=NOW + timedelta(seconds=2))
    worker_edge = next(edge for edge in edges if edge.target_node_id == "authoring")
    assert worker_edge.status == "ACTIVE"
    assert worker_edge.interaction_type == "worker_execution"

    result_edges = derive_edges(
        [
            event(
                event_type="WORKER_RESULT_RECEIVED",
                source_node_id="authoring",
                target_node_id="orchestrator",
                status="VALIDATING_RESULT",
            )
        ],
        active_seconds=4,
        now=NOW + timedelta(seconds=2),
    )
    result_edge = next(
        edge
        for edge in result_edges
        if edge.source_node_id == "authoring" and edge.target_node_id == "orchestrator"
    )
    assert result_edge.status == "ACTIVE"
    assert result_edge.interaction_type == "worker_result"


def test_snapshot_hash_ignores_generated_identity() -> None:
    first = snapshot().model_dump(mode="json")
    second = dict(first)
    second["generated_at"] = (NOW + timedelta(seconds=2)).isoformat()
    second["snapshot_id"] = "snapshot_" + "b" * 32
    second["content_hash"] = "sha256:" + "b" * 64
    assert canonical_snapshot_hash(first) == canonical_snapshot_hash(second)


def test_runtime_resources_are_package_resources() -> None:
    package = files("eom_observe")
    for name in ("index.html", "login.html", "app.js", "styles.css", "icons.svg"):
        assert package.joinpath("static", name).is_file()
    assert package.joinpath("resources", "worker-slots.example.yaml").is_file()
    for filename in SCHEMA_FILES.values():
        assert schema_resource(filename).is_file()


def test_source_build_info_is_safe_without_git_lookup() -> None:
    info = get_build_info()
    assert info.source_commit == "unbuilt" or len(info.source_commit) == 40
    assert info.package_version


def test_metadata_redaction_hides_long_text_and_keeps_safe_enums() -> None:
    config = settings().privacy.model_copy(update={"max_text_length": 64})
    result = metadata_summary(
        {"image_mode": "skip", "body": "secret content", "request_name": "x" * 70}, config
    )
    assert result["image_mode"] == "skip"
    assert result["request_name"] == "[CONTENT HIDDEN, length=70]"
    assert "body" not in result


def test_metadata_redaction_hides_future_request_name_and_hashes_idempotency_key() -> None:
    result = metadata_summary(
        {"request_name": "future domain content", "idempotency_key": "private-key-value"},
        settings().privacy,
    )
    assert result["request_name"] == "[CONTENT HIDDEN, length=21]"
    assert result["idempotency_key_hash"] == "aa749567e313"
    assert "private-key-value" not in str(result)


def test_path_and_error_sanitization() -> None:
    assert (
        sanitize_path("/mnt/nas/eom/artifacts/artifact_1/rev_1/result.json")
        == "nas://artifacts/artifact_1/rev_1"
    )
    assert logical_artifact_uri("artifact_1", "rev_1") == "nas://artifacts/artifact_1/rev_1"
    sanitized = sanitize_error("password=hunter2 at /root/.codex/auth.json")
    assert sanitized is not None and "hunter2" not in sanitized and "/root" not in sanitized


def test_structured_log_uses_allow_list_and_drops_message_content() -> None:
    record = logging.LogRecord(
        "eom_observe.test",
        logging.INFO,
        __file__,
        1,
        "access token must not appear",
        (),
        None,
    )
    record.event = "TEST_EVENT"
    record.request_id = "request_test"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["component"] == "eom_observe"
    assert payload["event"] == "TEST_EVENT"
    assert payload["request_id"] == "request_test"
    assert "access token" not in json.dumps(payload)


def test_token_kdf_and_constant_time_verification() -> None:
    token = generate_access_token()
    assert len(token) >= 43
    encoded = hash_access_token(token, salt=b"0123456789abcdef")
    assert verify_access_token(token, encoded)
    assert not verify_access_token(token + "x", encoded)
    assert not verify_access_token(token, "sha256$bad")


def test_rotate_token_replaces_hash_and_writes_one_time_file(tmp_path: Path) -> None:
    secret_path = tmp_path / "observe.env"
    output_path = tmp_path / "observe-token"
    original_hash = hash_access_token("original-observe-token-value")
    secret_path.write_text(
        "EOM_OBSERVE_DATABASE_URL='postgresql+psycopg://observe:REDACTED@localhost/eom'\n"
        f"EOM_OBSERVE_ACCESS_TOKEN_HASH='{original_hash}'\n"
        f"EOM_OBSERVE_SESSION_SECRET='{'s' * 43}'\n"
    )
    secret_path.chmod(0o640)

    assert rotate_token(secret_path, output_path) == output_path

    rotated = parse_environment_file(secret_path)
    token = output_path.read_text().strip()
    assert rotated["EOM_OBSERVE_ACCESS_TOKEN_HASH"] != original_hash
    assert verify_access_token(token, rotated["EOM_OBSERVE_ACCESS_TOKEN_HASH"])
    assert output_path.stat().st_mode & 0o777 == 0o600
    assert secret_path.stat().st_mode & 0o777 == 0o640


def test_load_secrets_prefers_complete_systemd_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EOM_OBSERVE_SECRET_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("EOM_OBSERVE_DATABASE_URL", "postgresql://runtime@example/eom")
    monkeypatch.setenv("EOM_OBSERVE_ACCESS_TOKEN_HASH", "a" * 64)
    monkeypatch.setenv("EOM_OBSERVE_SESSION_SECRET", "b" * 43)

    secrets = load_secrets()

    assert secrets.database_url == "postgresql://runtime@example/eom"


def test_load_secrets_rejects_partial_systemd_environment_without_file_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_path = tmp_path / "observe.env"
    secret_path.write_text(
        "EOM_OBSERVE_DATABASE_URL=postgresql://file@example/eom\n"
        f"EOM_OBSERVE_ACCESS_TOKEN_HASH={'a' * 64}\n"
        f"EOM_OBSERVE_SESSION_SECRET={'b' * 43}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EOM_OBSERVE_SECRET_FILE", str(secret_path))
    monkeypatch.setenv("EOM_OBSERVE_DATABASE_URL", "postgresql://runtime@example/eom")

    with pytest.raises(ObserveError) as error:
        load_secrets()

    assert error.value.code is ObserveErrorCode.OBSERVE_SECRET_MISSING


def test_signed_session_and_expiration() -> None:
    signer = SessionSigner("s" * 43, ttl_seconds=60)
    value = signer.create(now=NOW)
    assert signer.verify(value, now=NOW + timedelta(seconds=59)) is not None
    assert signer.verify(value, now=NOW + timedelta(seconds=60)) is None
    assert signer.verify(value + "x", now=NOW) is None


def test_login_rate_limit() -> None:
    limiter = LoginRateLimiter(max_failures=2, window_seconds=300)
    limiter.record_failure("client", now=NOW)
    assert limiter.allowed("client", now=NOW)
    limiter.record_failure("client", now=NOW)
    assert not limiter.allowed("client", now=NOW)
    assert limiter.allowed("client", now=NOW + timedelta(seconds=301))


def test_sse_format_contains_required_fields() -> None:
    formatted = format_sse(
        StreamMessage(event_id="1", event="heartbeat", data={"ok": True}, retry=1000)
    )
    assert formatted == 'id: 1\nevent: heartbeat\nretry: 1000\ndata: {"ok":true}\n\n'


def test_hub_drops_old_value_for_slow_client() -> None:
    async def scenario() -> None:
        hub = SubscriptionHub(max_clients=1)
        client_id, queue = await hub.subscribe()
        await hub.publish(StreamMessage("1", "delta", {"version": 1}))
        await hub.publish(StreamMessage("2", "delta", {"version": 2}))
        assert (await queue.get()).event_id == "2"
        await hub.unsubscribe(client_id)
        assert hub.client_count == 0

    asyncio.run(scenario())


def test_hub_max_client_guard() -> None:
    async def scenario() -> None:
        hub = SubscriptionHub(max_clients=1)
        await hub.subscribe()
        with pytest.raises(RuntimeError):
            await hub.subscribe()

    asyncio.run(scenario())


def test_poller_suppresses_identical_snapshot_and_emits_degraded_recovered() -> None:
    class Builder:
        def __init__(self) -> None:
            self.fail = False

        def build(self):
            if self.fail:
                raise RuntimeError("database unavailable")
            return snapshot()

        def stale_copy(self, value):
            return value.model_copy(
                update={
                    "data_freshness": value.data_freshness.model_copy(update={"database": "stale"})
                }
            )

    async def scenario() -> None:
        builder = Builder()
        hub = SubscriptionHub(max_clients=1)
        _, queue = await hub.subscribe()
        poller = SharedSnapshotPoller(builder, hub, poll_interval_seconds=1)
        await poller._poll_once()
        assert (await queue.get()).event == "snapshot"
        await poller._poll_once()
        assert queue.empty()
        builder.fail = True
        await poller._poll_once()
        assert (await queue.get()).event == "degraded"
        assert poller.current.data_freshness.database == "stale"
        builder.fail = False
        await poller._poll_once()
        assert (await queue.get()).event == "recovered"

    asyncio.run(scenario())
