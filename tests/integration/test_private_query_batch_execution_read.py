"""Real canonical parent/receipt/control files and Chat text, declared IAM/doc/GPU seams."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.embedding_batch_execution_receipt import PrivateChatBatchExecutionReceipt
from eom_workflow.native_reference_query_coordinator import NativeQueryBatchExecuted
from eom_workflow_runner.query_batch_execution_read import (
    resolve_private_chat_query_batch_execution,
    resolve_reference_query_batch_execution,
    validate_query_batch_child_result,
)
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_query_batch_execution_fixtures import private_query_batch_case
from tests.unit.test_private_chat_query_basis import TEXT

pytestmark = pytest.mark.integration


@pytest.fixture
def private_batch(guarded_engine, tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas, workspace_root=tmp_path),
    )
    return private_query_batch_case(tmp_path, monkeypatch, publisher=publisher, key=uuid4().hex)


def read(value, *, executed=None, launch=None, sources=None):
    with value.publisher.sessions.begin() as session:
        current = value.owner.cuda.resolve_submission(session, value.child, value.origin_context)
        return resolve_private_chat_query_batch_execution(
            session,
            reader=PinnedArtifactReadContext.for_session(session, value.owner.cuda.settings),
            sources=sources or current,
            launch=launch or value.launch,
            native_input=value.native,
            executed=executed or value.executed,
        )


def test_private_canonical_proof_reads_original_child_and_never_reencodes(
    private_batch, monkeypatch
):
    from eom_catalog_service import embedding_work_batch_execution

    value = private_batch

    def forbidden(*_args, **_kwargs):
        raise AssertionError("canonical read must not launch or rerun a numerical model")

    monkeypatch.setattr(embedding_work_batch_execution, "execute_embedding_work_batch", forbidden)
    with value.publisher.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    for _index in range(2):
        child = read(value)
        assert child == value.receipt.children[0]
        validate_query_batch_child_result(child, value.numeric.result.children[0].result)
    with value.publisher.sessions.begin() as session:
        assert value.store.read(session) == value.history
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert TEXT.encode() not in canonical_json_bytes(value.receipt)


@pytest.mark.parametrize("field", ("result_sha256", "batch_receipt_sha256"))
def test_wrong_semantic_hash_is_not_a_private_completed_read(private_batch, field):
    value = private_batch
    executed = type(value.executed).model_validate(
        value.executed.model_dump(mode="json") | {field: "sha256:" + "f" * 64}
    )
    with pytest.raises(ValueError):
        read(value, executed=executed)
    assert read(value) == value.receipt.children[0]


@pytest.mark.parametrize("field", ("artifact_revision_id", "sha256"))
def test_missing_or_wrong_raw_pointer_never_selects_latest(private_batch, field):
    value = private_batch
    body = value.executed.model_dump(mode="json")
    body["batch_receipt"][field] = (
        "rev_" + "f" * 32 if field == "artifact_revision_id" else "sha256:" + "f" * 64
    )
    executed = type(value.executed).model_validate(body)
    with pytest.raises(PinnedArtifactResolutionError):
        read(value, executed=executed)


@pytest.mark.parametrize("fault", ("parent", "actor", "binding", "time", "route"))
def test_resealed_other_receipt_cannot_substitute_original_private_proof(private_batch, fault):
    value = private_batch
    body = value.receipt.model_dump(mode="json")
    if fault == "parent":
        body["parent_plan_job_id"] = "job_" + "f" * 32
    elif fault == "actor":
        body["scope"] = seal(body["scope"] | {"actor_id": "operator_" + "f" * 32}, "scope_sha256")
    elif fault == "time":
        body["completed"] = seal(
            body["completed"] | {"retired_at": "2026-10-24T19:00:02Z"}, "message_sha256"
        )
    elif fault == "route":
        body["completed"]["grant"] = seal(
            body["completed"]["grant"] | {"routing_decision_sha256": "sha256:" + "f" * 64},
            "message_sha256",
        )
        body["completed"] = seal(body["completed"], "message_sha256")
    else:
        binding = body["bound"]["binding"]
        binding["children"][0]["workflow_request_sha256"] = "sha256:" + "f" * 64
        body["bound"] = seal(
            body["bound"] | {"binding": seal(binding, "record_sha256")}, "message_sha256"
        )
        body["completed"] = seal(
            body["completed"] | {"bound_message_sha256": body["bound"]["message_sha256"]},
            "message_sha256",
        )
    receipt = PrivateChatBatchExecutionReceipt.model_validate(seal(body, "receipt_sha256"))
    saved = value.controls.publish_batch_execution_receipt(
        receipt, idempotency_key="other-private-proof:" + uuid4().hex
    )
    executed = type(value.executed).model_validate(
        value.executed.model_dump(mode="json")
        | {
            "batch_receipt": saved.member.model_dump(mode="json"),
            "batch_receipt_sha256": receipt.receipt_sha256,
        }
    )
    with pytest.raises(ValueError):
        read(value, executed=executed)


def test_canonical_receipt_hash_corruption_is_rejected_without_repair(private_batch):
    value = private_batch
    with value.publisher.sessions() as session:
        row = session.get(ArtifactRevisionRecord, value.saved.member.artifact_revision_id)
        path = Path(row.nas_path) / "receipt.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(PinnedArtifactResolutionError):
        read(value)
    assert path.read_bytes() == original + b" "


def test_failed_receipt_producer_is_not_reinterpreted_as_success(private_batch):
    value = private_batch
    with value.publisher.sessions.begin() as session:
        # Isolated deliberate corruption, never an operating state repair/retry.
        row = session.get(JobRecord, value.saved.owner_job_id)
        row.status = "FAILED"
    with pytest.raises(PinnedArtifactResolutionError):
        read(value)
    with value.publisher.sessions() as session:
        assert session.get(JobRecord, value.saved.owner_job_id).status == "FAILED"


@pytest.mark.parametrize("fault", ("chat", "public", "identity"))
def test_current_private_and_public_source_withdrawal_prevents_canonical_read(private_batch, fault):
    value = private_batch
    assert read(value) == value.receipt.children[0]
    if fault == "chat":
        value.chat.repository.revoked = True
    else:
        value.fault.value = fault
    with pytest.raises((ValueError, OperatorAuthorizationFenceError)):
        read(value)


def test_same_question_from_another_chat_origin_cannot_borrow_original_gpu_result(private_batch):
    value = private_batch
    projection = value.sources.projection.model_dump(mode="json")
    projection["origin"] = seal(
        projection["origin"] | {"runtime_id": "chatrt_" + "f" * 32}, "origin_sha256"
    )
    sources = replace(
        value.sources, projection=type(value.sources.projection).model_validate(projection)
    )
    with pytest.raises(ValueError):
        read(value, sources=sources)


def test_public_and_private_entries_do_not_share_authority(private_batch):
    value = private_batch
    public_body = value.executed.model_dump(mode="json")
    public_body["batch_receipt"]["schema_ref"] = (
        "eom://schemas/workflow/embedding-batch-execution-receipt/1.0"
    )
    public = NativeQueryBatchExecuted.model_validate(public_body)
    with value.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext.for_session(session, value.owner.cuda.settings)
        with pytest.raises(ValueError, match="REFERENCE_QUERY_BATCH_EXECUTION_INVALID"):
            resolve_reference_query_batch_execution(
                session,
                reader=reader,
                sources=value.sources,
                launch=value.launch,
                native_input=value.native,
                executed=public,
            )
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_EXECUTION_INVALID"):
            resolve_private_chat_query_batch_execution(
                session,
                reader=reader,
                sources=value.sources,
                launch=value.launch,
                native_input=value.native,
                executed=public,
            )


@pytest.mark.parametrize("field", ("workflow_id", "step_run_id"))
def test_foreign_original_launch_cannot_read_the_child(private_batch, field):
    value = private_batch
    launch = type(value.launch).model_validate(
        seal(
            value.launch.model_dump(mode="json")
            | {
                field: ("workflow_" if field == "workflow_id" else "steprun_") + "f" * 32,
            },
            "association_sha256",
        )
    )
    with pytest.raises(ValueError):
        read(value, launch=launch)
