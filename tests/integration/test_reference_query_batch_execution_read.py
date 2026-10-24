"""Guarded PG and actual canonical files/parent history, synthetic IAM/numerical leaves."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    create_native_reference_query_launch,
)
from eom_orchestrator.settings import Settings
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    native_reference_query_continuation_checkpoint,
)
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.reference_query_batch_execution_read import (
    resolve_reference_query_batch_execution,
    validate_reference_query_batch_child_result,
)
from eom_workflow_runner.reference_query_completion import NativeReferenceQueryCompletion
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import query_batch_case

pytestmark = pytest.mark.integration


@pytest.fixture
def query_batch(guarded_engine, tmp_path, monkeypatch):
    nas = tmp_path / "artifacts"
    nas.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging",
            nas_artifact_root=nas,
        ),
    )
    return query_batch_case(tmp_path, monkeypatch, publisher, key=uuid4().hex)


def read(value, *, executed=None, launch=None, sources=None):
    with value.publisher.sessions.begin() as session:
        # Actual current source/lease admission is tested by the separate owner
        # suites. This exercises immutable canonical/read closure, not a grant.
        reader = PinnedArtifactReadContext.for_session(session, value.catalog.settings)
        return resolve_reference_query_batch_execution(
            session,
            reader=reader,
            sources=sources or value.sources,
            launch=launch or value.query.launch,
            native_input=value.query.native_input,
            executed=executed or value.executed,
        )


def test_canonical_batch_proof_resolves_original_child_without_unit_or_gpu_execution(query_batch):
    value = query_batch
    assert read(value) == value.receipt.children[0]
    validate_reference_query_batch_child_result(
        read(value), value.numeric.result.children[0].result
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: read(value), range(2)))
    assert result == [value.receipt.children[0]] * 2
    with value.publisher.sessions.begin() as session:
        assert value.store.read(session) == value.history


@pytest.mark.parametrize(
    "field,value",
    (
        ("child_ordinal", 1),
        ("result_sha256", "sha256:" + "f" * 64),
        ("batch_receipt_sha256", "sha256:" + "f" * 64),
    ),
)
def test_wrong_child_or_semantic_hash_is_not_a_completed_read(query_batch, field, value):
    source = query_batch
    changed = type(source.executed).model_validate(
        source.executed.model_dump(mode="json") | {field: value}
    )
    with pytest.raises(ValueError):
        read(source, executed=changed)
    assert read(source) == source.receipt.children[0]


@pytest.mark.parametrize("fault", ("parent", "scope", "binding", "time", "route"))
def test_schema_valid_other_receipt_cannot_substitute_original_parent_or_child(query_batch, fault):
    value = query_batch
    body = value.receipt.model_dump(mode="json")
    if fault == "parent":
        body["parent_plan_job_id"] = "job_" + "f" * 32
    elif fault == "scope":
        body["scope"] = seal(body["scope"] | {"actor_id": "operator_" + "f" * 32}, "scope_sha256")
    elif fault == "time":
        completed = seal(
            body["completed"] | {"retired_at": "2026-10-24T19:00:02Z"}, "message_sha256"
        )
        body["completed"] = completed
    elif fault == "route":
        grant = seal(
            body["completed"]["grant"]
            | {
                "routing_decision_sha256": "sha256:" + "f" * 64,
            },
            "message_sha256",
        )
        body["completed"] = seal(body["completed"] | {"grant": grant}, "message_sha256")
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
    changed = EmbeddingBatchExecutionReceipt.model_validate(seal(body, "receipt_sha256"))
    saved = value.controls.publish_batch_execution_receipt(
        changed, idempotency_key="synthetic-other-receipt:" + uuid4().hex
    )
    executed = type(value.executed).model_validate(
        value.executed.model_dump(mode="json")
        | {
            "batch_receipt": saved.member.model_dump(mode="json"),
            "batch_receipt_sha256": changed.receipt_sha256,
        }
    )
    with pytest.raises(ValueError):
        read(value, executed=executed)


def test_actual_canonical_file_hash_corruption_is_rejected_not_repaired(query_batch):
    value = query_batch
    with value.publisher.sessions() as session:
        revision = session.get(ArtifactRevisionRecord, value.saved.member.artifact_revision_id)
        path = Path(revision.nas_path) / "receipt.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(PinnedArtifactResolutionError):
        read(value)
    assert path.read_bytes() == original + b" "


@pytest.mark.parametrize(
    "field,value", (("sha256", "sha256:" + "f" * 64), ("artifact_revision_id", "rev_" + "f" * 32))
)
def test_missing_revision_or_wrong_raw_hash_never_selects_latest(query_batch, field, value):
    source = query_batch
    pointer = source.executed.batch_receipt.model_dump(mode="json") | {field: value}
    executed = type(source.executed).model_validate(
        source.executed.model_dump(mode="json") | {"batch_receipt": pointer}
    )
    with pytest.raises(PinnedArtifactResolutionError):
        read(source, executed=executed)


def test_child_metadata_is_checked_against_already_verified_result_without_another_vector_read(
    query_batch,
):
    value = query_batch
    result = value.numeric.result.children[0].result
    changed = result.model_copy(update={"result_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError):
        validate_reference_query_batch_child_result(read(value), changed)


def completion_case(value, tmp_path, monkeypatch):
    query = value.query
    coordinator = NativeReferenceQueryCoordinator(query.request, query.launch)
    allocation = NativeQueryAllocation(
        query_producer=new_native_artifact_producer(),
        receipt_producer=new_native_artifact_producer(),
        created_at=query.launch.launched_at,
        source_commit="a" * 40,
    )
    with value.publisher.sessions.begin() as session:
        create_native_reference_query_launch(session, request=query.request, launch=query.launch)
        history = coordinator.read(session)
        for phase, payload in (("ALLOCATION", allocation), ("EXECUTED", value.executed)):
            history = coordinator.append(
                session,
                native_reference_query_continuation_checkpoint(
                    query.launch,
                    phase,
                    payload,
                    previous=history.records,
                    initial_version="native-reference-query-coordinator/1.2",
                ),
            )
    child_root = tmp_path / "child-output"
    child_root.mkdir(mode=0o700)
    for name, raw in (
        ("input.json", canonical_json_bytes(query.native_input.model_dump(mode="json"))),
        (
            "result.json",
            canonical_json_bytes(value.numeric.result.children[0].result.model_dump(mode="json")),
        ),
        ("vectors.f32", value.verified.child_vectors[0]),
    ):
        path = child_root / name
        path.write_bytes(raw)
        path.chmod(0o600)
    publications = native_embedding_publications(value.publisher, source_commit="a" * 40)
    source_calls = []
    owner = SimpleNamespace(
        settings=value.catalog.settings,
        resolve_execution_sources=lambda *_a, **_kw: (
            source_calls.append("current") or value.sources
        ),
        fence_mutation=lambda *_a, **_kw: source_calls.append("late"),
    )
    completion = NativeReferenceQueryCompletion(owner)
    step = SimpleNamespace(step_run_id=query.launch.step_run_id, platform_job_id=None)

    @contextmanager
    def transaction():
        with value.publisher.sessions.begin() as session:
            original_get = session.get
            # Workflow/command/IAM remain explicit synthetic leaves. Actual Job,
            # canonical artifacts, parent/control reads and child commits use PG.
            monkeypatch.setattr(
                session,
                "get",
                lambda model, *args, **kwargs: (
                    step if model is WorkflowStepRunRecord else original_get(model, *args, **kwargs)
                ),
            )
            yield session

    prepared = SimpleNamespace(
        workflow_request=query.request,
        policy=query.policy,
        bundle=query.bundle,
        association=query.launch,
        request=query.native_input,
        workspace=child_root,
    )

    def publish():
        return completion.publish(
            workflow=SimpleNamespace(workflow_id=query.launch.workflow_id),
            step=step,
            request=query.request,
            command_lease=CommandLeaseIdentity("wfcmd_" + "1" * 32, "test", "test", 1),
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=publications,
            fenced_transaction=transaction,
        )

    return SimpleNamespace(
        publish=publish,
        coordinator=coordinator,
        allocation=allocation,
        publications=publications,
        child_root=child_root,
        source_calls=source_calls,
    )


@pytest.mark.parametrize(
    "interruption", ("NONE", "QUERY_COMMITTED", "RECEIPT_BEFORE", "RECEIPT_COMMITTED")
)
def test_existing_query_completion_consumes_batch_proof_and_resumes_original_producers(
    query_batch,
    tmp_path,
    monkeypatch,
    interruption,
):
    value = query_batch
    execution = completion_case(value, tmp_path, monkeypatch)
    if interruption != "NONE":
        leaf, name = (
            (execution.publications.artifacts, "publish_reference_query")
            if interruption == "QUERY_COMMITTED"
            else (execution.publications.completions, "publish_reference_query")
        )
        original = getattr(leaf, name)

        def interrupt(*args, **kwargs):
            if interruption != "RECEIPT_BEFORE":
                original(*args, **kwargs)
            raise RuntimeError("synthetic interruption at immutable publication boundary")

        monkeypatch.setattr(leaf, name, interrupt)
        with pytest.raises(RuntimeError):
            execution.publish()
        monkeypatch.setattr(leaf, name, original)
    output = execution.publish()
    with value.publisher.sessions.begin() as session:
        original = execution.coordinator.read(session)
        assert original.state == "SUCCEEDED" and len(original.records) == 4
        assert original.records[1].payload == value.executed
    # After completion only canonical evidence is needed, not root-local bytes,
    # the old GPU unit, PID or numerical execution. This is a read/replay, not retry.
    for member in execution.child_root.iterdir():
        member.unlink()
    assert execution.publish() == output
    with value.publisher.sessions.begin() as session:
        assert execution.coordinator.read(session) == original
        assert value.store.read(session) == value.history
    assert "current" in execution.source_calls and "late" in execution.source_calls


def test_disposable_postgres_concurrent_batch_checkpoint_replay_has_one_original_history(
    query_batch,
    tmp_path,
    monkeypatch,
):
    value = query_batch
    execution = completion_case(value, tmp_path, monkeypatch)
    execution.publish()
    with value.publisher.sessions.begin() as session:
        original = execution.coordinator.read(session)

    def replay():
        with value.publisher.sessions.begin() as session:
            for record in original.records:
                execution.coordinator.append(session, record)
            return execution.coordinator.read(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: replay(), range(2))) == [original, original]
