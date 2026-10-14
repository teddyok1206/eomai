"""Real temporary Job/Artifact closure; current IAM and native derivation are synthetic seams."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    create_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import reference_query_checkpoint_receipt
from eom_workflow_runner import reference_query_completion as module
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.reference_query_completion import NativeReferenceQueryCompletion
from sqlalchemy import select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_embedding_reference_query_artifact_store import prepare, publish
from tests.unit.test_reference_query_completion_artifacts import owner as publisher_owner
from tests.unit.test_reference_query_execution_contracts import case


@pytest.fixture
def completion(tmp_path, monkeypatch):
    publisher = publisher_owner(tmp_path)
    value = prepare(tmp_path, case())
    value.store = EmbeddingArtifactStore(publisher, source_commit="a" * 40)
    current = value.case
    published = publish(
        value,
        identity=ControlFileSetIdentity(
            current.receipt.query_artifact_owner_job_id,
            current.receipt.query_input.artifact_id,
            current.receipt.query_input.artifact_revision_id,
        ),
    )
    receipt = current.receipt.model_dump(mode="json")
    receipt.update(
        query_input=published.input.model_dump(mode="json"),
        shard=published.shard.model_dump(mode="json"),
        binary=published.binary.model_dump(mode="json"),
    )
    receipt["query_execution"].update(
        result_member=published.result.model_dump(mode="json"),
        result_sha256=value.result.result_sha256,
    )
    from eom_workflow.reference_query_execution import parse_reference_query_workflow_receipt

    current = replace(
        current,
        result=value.result,
        receipt=parse_reference_query_workflow_receipt(seal(receipt, "receipt_sha256")),
    )
    records = list(query_records(current))
    # Pin the ACTUAL file-set manifest rather than the fixture's placeholder digest.
    from eom_workflow.native_reference_query_coordinator import (
        parse_native_reference_query_checkpoint,
    )

    body = records[2].model_dump(mode="json")
    body["payload"]["manifest_sha256"] = published.manifest_sha256
    records[2] = parse_native_reference_query_checkpoint(seal(body, "checkpoint_sha256"))
    receipt = reference_query_checkpoint_receipt(
        current.request, current.launch, records[0].payload, records[1].payload, records[2].payload
    )
    output = NativeEmbeddingCompletionPublisher(
        publisher, source_commit="a" * 40
    ).publish_reference_query(
        receipt,
        identity=ControlFileSetIdentity(
            current.receipt.receipt_owner_job_id,
            current.output.receipt.artifact_id,
            current.output.receipt.artifact_revision_id,
        ),
    )
    coordinator = NativeReferenceQueryCoordinator(current.request, current.launch)
    with publisher.sessions.begin() as session:
        create_native_reference_query_launch(
            session, request=current.request, launch=current.launch
        )
        for record in records[:3]:
            coordinator.append(session, record)
    calls = []
    sources = SimpleNamespace(request=current.request, policy=current.policy, bundle=current.bundle)
    owner = SimpleNamespace(
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
        resolve_execution_sources=lambda *_a, **_kw: calls.append("current") or sources,
        fence_mutation=lambda *_a, **_kw: calls.append("late"),
    )
    # Derivation itself has separate exact current-source tests; this is storage/completion closure.
    monkeypatch.setattr(
        module, "build_reference_query_native_input", lambda *_a, **_kw: current.native_input
    )
    return SimpleNamespace(
        publisher=publisher,
        current=current,
        records=records,
        output=output,
        owner=owner,
        completion=NativeReferenceQueryCompletion(owner),
        coordinator=coordinator,
        calls=calls,
    )


def arguments(value, session, monkeypatch):
    step = SimpleNamespace(step_run_id=value.current.launch.step_run_id, platform_job_id=None)
    original_get = session.get
    monkeypatch.setattr(
        session,
        "get",
        lambda model, *a, **kw: (
            step if model is WorkflowStepRunRecord else original_get(model, *a, **kw)
        ),
    )
    return dict(
        session=session,
        workflow=SimpleNamespace(workflow_id=value.current.launch.workflow_id),
        step=step,
        request=value.current.request,
        command_lease=object(),
        output=value.output,
    )


def test_current_owner_canonical_completion_before_and_after_exact_final_checkpoint(
    completion, monkeypatch
):
    value = completion
    with value.publisher.sessions.begin() as session:
        assert (
            value.completion.validate_completion(**arguments(value, session, monkeypatch))
            == value.output
        )
        value.coordinator.append(session, value.records[3])
        assert (
            value.completion.validate_completion(**arguments(value, session, monkeypatch))
            == value.output
        )
    assert value.calls == ["current", "late", "current", "late"]


@pytest.mark.parametrize(
    "fault",
    [
        "native_failed",
        "receipt_bytes",
        "query_bytes",
        "manifest",
        "producer",
        "detached_step",
        "late",
        "derivation",
    ],
)
def test_changed_history_bytes_or_current_authority_never_return_success(
    completion, monkeypatch, fault
):
    value = completion
    if fault == "late":

        def deny(*_a, **_kw):
            raise ValueError("SYNTHETIC_CURRENT_PERMISSION_REVOKED")

        value.owner.fence_mutation = deny
    if fault == "derivation":
        monkeypatch.setattr(module, "build_reference_query_native_input", lambda *_a, **_kw: None)
    with value.publisher.sessions.begin() as session:
        if fault == "native_failed":
            session.get(JobRecord, value.current.launch.native_launch_job_id).status = "FAILED"
        if fault == "producer":
            session.get(
                JobRecord, value.current.receipt.query_artifact_owner_job_id
            ).status = "RUNNING"
        if fault == "manifest":
            event = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.event == "REFERENCE_QUERY_NATIVE_PUBLISHED"
                )
            )
            body = dict(event.data)
            body["payload"] = dict(body["payload"], manifest_sha256="sha256:" + "f" * 64)
            event.data = seal(body, "checkpoint_sha256")
        if fault in {"receipt_bytes", "query_bytes"}:
            pointer = (
                value.output.receipt
                if fault == "receipt_bytes"
                else value.current.receipt.query_execution.result_member
            )
            path = (
                value.publisher.settings.nas_artifact_root
                / pointer.artifact_id
                / pointer.artifact_revision_id
                / pointer.member_path
            )
            path.write_bytes(b"corrupt committed member")
    with value.publisher.sessions.begin() as session:
        kwargs = arguments(value, session, monkeypatch)
        if fault == "detached_step":
            kwargs["step"].platform_job_id = "job_" + "f" * 32
            kwargs["step"] = SimpleNamespace(
                step_run_id=value.current.launch.step_run_id, platform_job_id=None
            )
        with pytest.raises(ValueError):
            value.completion.validate_completion(**kwargs)
    with value.publisher.sessions() as session:
        raw = canonical_json_bytes(
            session.get(JobRecord, value.current.launch.native_launch_job_id).request
        )
        assert b'"text"' not in raw and b'"vectors"' not in raw
