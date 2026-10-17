"""Original private metadata and actual disposable SQLite history; no live source/units."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_private_chat_query_coordinator import (
    NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL,
    NativePrivateChatQueryCoordinator,
    NativePrivateQueryHistoryError,
)
from eom_orchestrator.native_query_job_allocation import create_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    native_private_chat_query_checkpoint,
    parse_native_private_chat_query_checkpoint,
    validate_native_private_chat_query_history,
)
from eom_workflow.schemas import (
    NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    load_native_private_chat_query_coordinator_schema,
)
from sqlalchemy import event, func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_private_query_coordinator_fixtures import private_query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def records(completed):
    return private_query_records(completed)


@pytest.fixture
def stored(tmp_path, completed, records):
    publisher, _engine = _publisher(tmp_path)
    with publisher.sessions.begin() as session:
        create_native_query_launch(session, request=completed.request, launch=completed.launch)
    return publisher, NativePrivateChatQueryCoordinator(completed.request, completed.launch)


def test_private_schema_exact_mirror_pinned_hash_and_independent_public_copy():
    root = Path(__file__).resolve().parents[2]
    filename, schema_id, digest = NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    schema = load_native_private_chat_query_coordinator_schema()
    assert schema["$id"] == schema_id
    schema["type"] = "null"
    assert load_native_private_chat_query_coordinator_schema()["type"] == "object"
    assert (
        len(NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL)
        <= ProtocolVersionRecord.__table__.c.version.type.length
    )


def test_text_free_original_origin_and_every_contiguous_prefix(completed, records):
    for record in records:
        assert parse_native_private_chat_query_checkpoint(record) == record
        assert parse_native_private_chat_query_checkpoint(record.model_dump(mode="json")) == record
        raw = canonical_json_bytes(record)
        assert len(raw) < 16 * 1024
        assert all(token not in raw for token in (b'"text"', b'"input.json"', b'"lease_token"'))
    for length in range(5):
        validate_native_private_chat_query_history(
            records[:length], completed.launch, completed.request
        )


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "extra",
        "phase",
        "bool",
        "float",
        "template",
        "invocation",
        "member",
        "mixed_file",
        "same_job",
        "copy",
    ],
)
def test_private_frames_do_not_accept_forged_or_cross_family_values(completed, records, fault):
    index = (
        1
        if fault in {"bool", "float", "template", "invocation"}
        else 2
        if fault in {"member", "mixed_file"}
        else 0
    )
    body = records[index].model_dump(mode="json")
    if fault == "copy":
        with pytest.raises(ValueError):
            native_private_chat_query_checkpoint(
                completed.launch,
                "ALLOCATION",
                records[0].payload.model_copy(update={"authority": "ADMIN"}),
            )
        return
    if fault == "hash":
        body["checkpoint_sha256"] = "sha256:" + "f" * 64
    elif fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "phase":
        body["record_type"] = "EXECUTED"
    elif fault in {"bool", "float"}:
        body["payload"]["query"]["started_monotonic"] = True if fault == "bool" else 3.0
    elif fault == "template":
        body["payload"]["prepare_template_sha256"] = (
            "sha256:bbd6ca87732f9a8f0c19e1a6892bdf8d41ed08b1f1473d50918dfde0e7890ec7"
        )
    elif fault == "invocation":
        body["payload"]["query"]["invocation_id"] = body["payload"]["prepare"]["invocation_id"]
    elif fault == "member":
        body["payload"]["execution_record"]["member_path"] = "input.json"
    elif fault == "mixed_file":
        body["payload"]["result"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif fault == "same_job":
        body["payload"]["allocation"]["query_producer"]["job_id"] = body["native_launch_job_id"]
    with pytest.raises(ValueError):
        parse_native_private_chat_query_checkpoint(
            body if fault in {"hash", "float"} else seal(body, "checkpoint_sha256")
        )


@pytest.mark.parametrize(
    "fault",
    ["skip", "duplicate", "foreign", "actor", "basis", "late", "intent", "producer", "output"],
)
def test_private_history_reconstructs_origin_and_exact_completion(completed, records, fault):
    if fault == "skip":
        records = records[:1] + records[2:]
    elif fault == "duplicate":
        records = (records[0], records[0])
    else:
        index = {
            "foreign": 0,
            "actor": 0,
            "basis": 0,
            "late": 1,
            "intent": 2,
            "producer": 2,
            "output": 3,
        }[fault]
        body = records[index].model_dump(mode="json")
        if fault == "foreign":
            body["association_sha256"] = "sha256:" + "f" * 64
        elif fault in {"actor", "basis"}:
            origin = body["payload"]["origin"]
            if fault == "actor":
                origin["actor_id"] = "operator_" + "f" * 32
            else:
                origin["basis"]["query_text_sha256"] = "sha256:" + "f" * 64
                origin["basis"] = seal(origin["basis"], "basis_sha256")
            body["payload"]["origin"] = seal(origin, "origin_sha256")
        elif fault == "late":
            body["payload"]["completed_observed_at"] = (
                (completed.launch.launched_at - timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z")
            )
        elif fault == "intent":
            body["payload"]["execution_record"]["sha256"] = "sha256:" + "f" * 64
        elif fault == "producer":
            body["payload"]["query_owner_job_id"] = "job_" + "f" * 32
        else:
            output = body["payload"]["output"]
            output["receipt"]["sha256"] = "sha256:" + "f" * 64
            body["payload"]["output"] = seal(output, "output_sha256")
        changed = parse_native_private_chat_query_checkpoint(seal(body, "checkpoint_sha256"))
        records = (*records[:index], changed, *records[index + 1 :])
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(records, completed.launch, completed.request)


def test_exact_private_append_and_replay_share_one_original_job_history(stored, records):
    publisher, owner = stored
    for index, record in enumerate(records):
        with publisher.sessions.begin() as session:
            result = owner.append(session, record)
            assert len(result.records) == index + 1
    with publisher.sessions.begin() as session:
        history = owner.read(session)
        assert history.state == "SUCCEEDED" and history.records == records
        for record in records:
            assert owner.append(session, record) == history
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == owner.launch.native_launch_job_id,
                    JobEventRecord.event.like("PRIVATE_CHAT_QUERY_NATIVE_%"),
                )
            )
            == 5
        )  # original launch plus four phases


def test_original_origin_cannot_be_replaced_and_caller_rollback_preserves_state(stored, records):
    publisher, owner = stored
    with pytest.raises(RuntimeError, match="rollback"), publisher.sessions.begin() as session:
        owner.append(session, records[0])
        raise RuntimeError("rollback")
    with publisher.sessions.begin() as session:
        assert owner.read(session).state == "CLAIMED" and owner.read(session).records == ()
        owner.append(session, records[0])
    origin = records[0].payload.origin.model_dump(mode="json")
    origin["runtime_id"] = "chatrt_" + "f" * 32
    changed = NativePrivateQueryAllocation(
        allocation=records[0].payload.allocation,
        origin=ChatPrivateQueryOrigin.model_validate(seal(origin, "origin_sha256")),
    )
    record = native_private_chat_query_checkpoint(owner.launch, "ALLOCATION", changed)
    with publisher.sessions.begin() as session:
        with pytest.raises(NativePrivateQueryHistoryError, match="CHECKPOINT_CONFLICT"):
            owner.append(session, record)
        assert owner.read(session).records == records[:1]


def test_missing_or_nested_root_cannot_append_and_failed_history_does_not_restart(stored, records):
    publisher, owner = stored
    with publisher.sessions() as session:
        with pytest.raises(NativePrivateQueryHistoryError, match="ROOT_REQUIRED"):
            owner.append(session, records[0])
        with (
            session.begin(),
            session.begin_nested(),
            pytest.raises(NativePrivateQueryHistoryError, match="ROOT_REQUIRED"),
        ):
            owner.append(session, records[0])
    with publisher.sessions.begin() as session:
        owner.append(session, records[0])
        history = owner.record_known_failure(session)
        assert history.state == "FAILED" and owner.record_known_failure(session) == history
        assert owner.append(session, records[0]) == history
        with pytest.raises(NativePrivateQueryHistoryError, match="TERMINAL_OR_FOREIGN"):
            owner.append(session, records[1])
        assert session.get(JobRecord, owner.launch.native_launch_job_id).status == "FAILED"


def test_foreign_purpose_event_is_not_silently_hidden_from_original_history(stored, records):
    publisher, owner = stored
    with publisher.sessions.begin() as session:
        owner.append(session, records[0])
        row = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == owner.launch.native_launch_job_id,
                JobEventRecord.event == "PRIVATE_CHAT_QUERY_NATIVE_ALLOCATION",
            )
        )
        row.event = "REFERENCE_QUERY_NATIVE_ALLOCATION"
        session.flush()
        with pytest.raises(NativePrivateQueryHistoryError, match="HISTORY_INVALID"):
            owner.read(session)


def test_shared_checkpoint_read_is_original_job_index_lookup_with_five_row_bound(stored):
    publisher, owner = stored
    observed = []

    def inspect(_connection, _cursor, statement, parameters, _context, _executemany):
        if "FROM job_events" in statement:
            observed.append((statement, parameters))

    event.listen(publisher.engine, "before_cursor_execute", inspect)
    try:
        with publisher.sessions.begin() as session:
            assert owner.read(session).records == ()
    finally:
        event.remove(publisher.engine, "before_cursor_execute", inspect)
    checkpoints = [
        (statement, parameters) for statement, parameters in observed if "LIMIT" in statement
    ]
    assert len(checkpoints) == 1
    statement, parameters = checkpoints[0]
    assert "job_events.job_id =" in statement and "ORDER BY job_events.sequence" in statement
    assert owner.launch.native_launch_job_id in parameters
    assert parameters[-2:] == (5, 0)
    # The existing (job_id, sequence) unique B-tree supplies both lookup and order.
    assert any(
        tuple(c.name for c in constraint.columns) == ("job_id", "sequence")
        for constraint in JobEventRecord.__table__.constraints
    )
