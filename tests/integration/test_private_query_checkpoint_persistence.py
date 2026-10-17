"""Guarded real PostgreSQL Job checkpoints; Chat/native observations are synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCoordinator,
    NativePrivateQueryHistoryError,
)
from eom_orchestrator.native_query_job_allocation import create_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    parse_native_private_chat_query_checkpoint,
)
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_workflow_receipt,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_private_query_coordinator_fixtures import private_query_records
from tests.unit.test_embedding_private_chat_query import backend
from tests.unit.test_private_chat_query_workflow import completed as completed

pytestmark = pytest.mark.integration


@pytest.fixture
def private_history(guarded_engine, completed):
    assert guarded_engine.dialect.name == "postgresql"
    value = completed
    value.native = EmbeddingPrivateChatQueryInput.model_validate(
        seal(
            value.native.model_dump(mode="json")
            | {"job_id": "job_" + uuid4().hex, "query_request_id": "embeddingquery_" + uuid4().hex},
            "request_sha256",
        )
    )
    value.launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            value.launch.model_dump(mode="json")
            | {
                "workflow_id": "workflow_" + uuid4().hex,
                "step_run_id": "steprun_" + uuid4().hex,
                "original_command_id": "wfcmd_" + uuid4().hex,
                "native_launch_job_id": value.native.job_id,
                "query_request_id": value.native.query_request_id,
                "query_request_sha256": value.native.request_sha256,
            },
            "association_sha256",
        )
    )
    intent = validate_private_chat_query_launch(
        value.launch, value.request, value.policy, value.bundle, value.native
    )
    value.result = encode_private_chat_query(value.native, backend(value.native)).result
    receipt = value.receipt.model_dump(mode="json")
    receipt.update(
        {
            "workflow_id": value.launch.workflow_id,
            "step_run_id": value.launch.step_run_id,
            "native_launch_job_id": value.native.job_id,
            "launch_association_sha256": value.launch.association_sha256,
            "execution_record": receipt["execution_record"]
            | {"sha256": sha256_bytes(canonical_json_bytes(intent))},
            "query_execution": receipt["query_execution"]
            | {
                "job_id": value.native.job_id,
                "query_request_id": value.native.query_request_id,
                "request_sha256": value.native.request_sha256,
                "result_sha256": value.result.result_sha256,
                "result_member": receipt["query_execution"]["result_member"]
                | {
                    "sha256": sha256_bytes(canonical_json_bytes(value.result)),
                },
            },
        }
    )
    value.receipt = PrivateChatQueryWorkflowReceipt.model_validate(seal(receipt, "receipt_sha256"))
    validate_private_chat_query_workflow_receipt(
        value.receipt,
        value.request,
        value.policy,
        value.bundle,
        value.launch,
        value.native,
        value.result,
        origin=value.expected["origin"],
        workflow_id=value.launch.workflow_id,
        step_run_id=value.launch.step_run_id,
        query_artifact_owner_job_id=value.receipt.query_artifact_owner_job_id,
        receipt_owner_job_id=value.receipt.receipt_owner_job_id,
    )
    output = value.output.model_dump(mode="json") | {
        "workflow_id": value.launch.workflow_id,
        "step_run_id": value.launch.step_run_id,
        "receipt_sha256": value.receipt.receipt_sha256,
        "receipt": value.output.receipt.model_dump(mode="json")
        | {
            "sha256": sha256_bytes(canonical_json_bytes(value.receipt)),
        },
    }
    value.output = PrivateChatQueryStepOutput.model_validate(seal(output, "output_sha256"))
    records = private_query_records(value)
    with Session(guarded_engine) as session, session.begin():
        create_native_query_launch(session, request=value.request, launch=value.launch)
    return NativePrivateChatQueryCoordinator(value.request, value.launch), records


def test_postgres_four_original_phases_commit_and_replay_text_free(guarded_engine, private_history):
    owner, records = private_history
    for record in records:
        with Session(guarded_engine) as session, session.begin():
            owner.append(session, record)
    with Session(guarded_engine) as session, session.begin():
        final = owner.read(session)
        assert final.state == "SUCCEEDED" and final.records == records
        for record in records:
            assert owner.append(session, record) == final
        rows = tuple(
            session.scalars(
                select(JobEventRecord).where(
                    JobEventRecord.job_id == owner.launch.native_launch_job_id,
                    JobEventRecord.event.like("PRIVATE_CHAT_QUERY_NATIVE_%"),
                )
            )
        )
        assert len(rows) == 5
        job = session.get(JobRecord, owner.launch.native_launch_job_id)
        assert job.worker_slot_id is None
        assert b'"text"' not in canonical_json_bytes(job.request)
        assert all(b'"text"' not in canonical_json_bytes(row.data) for row in rows)


def test_postgres_concurrent_same_private_phase_has_one_event(guarded_engine, private_history):
    owner, records = private_history
    barrier = Barrier(2)

    def append():
        barrier.wait(timeout=10)
        with Session(guarded_engine) as session, session.begin():
            return owner.append(session, records[0])

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(append), pool.submit(append)
        assert a.result(timeout=30) == b.result(timeout=30)
    with Session(guarded_engine) as session, session.begin():
        assert owner.read(session).records == records[:1]
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == owner.launch.native_launch_job_id,
                    JobEventRecord.event == "PRIVATE_CHAT_QUERY_NATIVE_ALLOCATION",
                )
            )
            == 1
        )


def test_postgres_private_append_caller_rollback_leaves_original_claimed(
    guarded_engine, private_history
):
    owner, records = private_history
    with (
        pytest.raises(RuntimeError, match="rollback"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        owner.append(session, records[0])
        raise RuntimeError("rollback")
    with Session(guarded_engine) as session, session.begin():
        original = owner.read(session)
        assert original.state == "CLAIMED" and original.records == ()
        assert owner.append(session, records[0]).state == "RUNNING"


def test_postgres_changed_original_chat_origin_is_a_conflict_not_new_work(
    guarded_engine, private_history
):
    owner, records = private_history
    with Session(guarded_engine) as session, session.begin():
        owner.append(session, records[0])
    body = records[0].model_dump(mode="json")
    origin = body["payload"]["origin"]
    origin["runtime_id"] = "chatrt_" + uuid4().hex
    body["payload"]["origin"] = seal(origin, "origin_sha256")
    changed = parse_native_private_chat_query_checkpoint(seal(body, "checkpoint_sha256"))
    with Session(guarded_engine) as session, session.begin():
        with pytest.raises(NativePrivateQueryHistoryError, match="CHECKPOINT_CONFLICT"):
            owner.append(session, changed)
        assert owner.read(session).records == records[:1]


def test_postgres_private_known_failure_is_immutable_terminal_history(
    guarded_engine, private_history
):
    owner, records = private_history
    with Session(guarded_engine) as session, session.begin():
        owner.append(session, records[0])
        failed = owner.record_known_failure(session)
    with Session(guarded_engine) as session, session.begin():
        assert owner.record_known_failure(session) == failed
        assert owner.append(session, records[0]) == failed
        with pytest.raises(NativePrivateQueryHistoryError, match="TERMINAL_OR_FOREIGN"):
            owner.append(session, records[1])
        assert owner.read(session) == failed and failed.state == "FAILED"


def test_postgres_private_checkpoint_cannot_use_nested_only_root(guarded_engine, private_history):
    owner, records = private_history
    with Session(guarded_engine) as session, session.begin():
        with (
            session.begin_nested(),
            pytest.raises(NativePrivateQueryHistoryError, match="ROOT_REQUIRED"),
        ):
            owner.append(session, records[0])
        assert owner.read(session).records == ()
