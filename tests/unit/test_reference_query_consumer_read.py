"""Real temporary Job/Artifact bytes; explicit synthetic completed-Workflow/IAM/numerics."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    VerifiedReferenceQueryRead,
)
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, JobRecord
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.reference_query_owner_admission import (
    ResolvedCompletedReferenceQuerySources,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_native_executor import make_executor_case


@pytest.fixture
def completed(tmp_path, monkeypatch):
    value = make_executor_case(tmp_path, monkeypatch)
    return make_completed_read_case(value, monkeypatch)


def make_completed_read_case(value, monkeypatch):
    """Shared actual storage/read composition; the current Workflow/IAM seam is synthetic."""
    output = value.execute()
    value.step.platform_job_id = output.receipt_owner_job_id
    calls = []
    hooks = []

    def current(session, caller, request, *, workflow_id):
        assert session.get_transaction() is not None and session.get_transaction().is_active
        assert caller.operator_id == request.operator_audit.operator_id
        assert workflow_id == value.workflow.workflow_id and request == value.request
        calls.append(session)
        if hooks:
            hooks.pop(0)()
        original_get = session.get
        monkeypatch.setattr(
            session,
            "get",
            lambda model, *a, **kw: (
                value.step if model is WorkflowStepRunRecord else original_get(model, *a, **kw)
            ),
        )
        return ResolvedCompletedReferenceQuerySources(
            value.sources, value.workflow, value.step, output
        )

    value.owner.resolve_completed_sources = current
    reader = CatalogCompletedReferenceQueryRead(
        value.owner, workflow_id=value.workflow.workflow_id, request=value.request
    )
    return SimpleNamespace(
        value=value,
        output=output,
        calls=calls,
        hooks=hooks,
        reader=reader,
        caller=EmbeddingRegistryCaller(value.request.operator_audit.operator_id),
    )


def read(case):
    return case.reader.resolve_reference_query(
        case.caller, case.value.request.context_request, case.value.sources.prepared
    )


def counts(value):
    with value.publisher.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (JobRecord, ArtifactRevisionRecord, JobEventRecord)
        )


def test_completed_read_is_current_canonical_and_does_not_launch_write_or_need_a_lease(completed):
    before = counts(completed.value)
    runtime_calls = tuple(completed.value.launcher.mock_calls)
    first = read(completed)
    assert isinstance(first, VerifiedReferenceQueryRead) and read(completed) == first
    assert counts(completed.value) == before and len(completed.value.runs) == 1
    assert tuple(completed.value.launcher.mock_calls) == runtime_calls
    assert len(completed.calls) == 4
    assert completed.calls[0] is completed.calls[1]
    assert completed.calls[2] is completed.calls[3]
    assert completed.calls[0] is not completed.calls[2]
    assert first.request.job_id == completed.value.history().launch.native_launch_job_id
    assert first.result_member.member_path == "result.json"
    assert read_unit_vectors(
        first.binary,
        dimension=first.result.shard.dimension,
        row_count=first.result.shard.row_count,
        expected_sha256=first.result.shard.binary.sha256,
    )
    completed.value.launcher.run.assert_called_once()


@pytest.mark.parametrize("fault", ("caller", "context", "prepared"))
def test_foreign_or_changed_context_never_reads_history(completed, fault):
    request, prepared = completed.value.request.context_request, completed.value.sources.prepared
    caller = completed.caller
    if fault == "caller":
        caller = EmbeddingRegistryCaller("operator_" + "0" * 32)
    elif fault == "context":
        request = parse_similarity_context_request(
            seal(request.model_dump(mode="json") | {"top_k": request.top_k + 1}, "request_sha256")
        )
        prepared = replace(prepared, request_sha256=request.request_sha256)
    else:
        prepared = replace(
            prepared,
            query_texts=tuple((view, text + " changed") for view, text in prepared.query_texts),
        )
    with pytest.raises(SimilarityContextReadError):
        completed.reader.resolve_reference_query(caller, request, prepared)
    assert len(completed.calls) == (1 if fault == "prepared" else 0)
    assert len(completed.value.runs) == 1


@pytest.mark.parametrize("when", (0, 1))
def test_current_denial_before_or_after_members_never_returns_a_capability(completed, when):
    def deny():
        raise ValueError("SYNTHETIC_CURRENT_PERMISSION_REVOKED")

    completed.hooks.extend(([lambda: None] if when else []) + [deny])
    before = counts(completed.value)
    with pytest.raises(SimilarityContextReadError):
        read(completed)
    assert len(completed.calls) == when + 1
    assert counts(completed.value) == before and len(completed.value.runs) == 1


@pytest.mark.parametrize(
    "kind,expected",
    (
        ("workflow", "QUERY_RESULT_INVALID"),
        ("identity", "AUTHORITY_UNAVAILABLE"),
        ("EMBEDDING_REGISTRY_FORBIDDEN", "SOURCE_ACCESS_DENIED"),
        ("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE", "AUTHORITY_UNAVAILABLE"),
        ("EMBEDDING_REGISTRY_SOURCE_INVALID", "SOURCE_POINTER_INVALID"),
    ),
)
def test_owner_errors_are_stable_context_failures_not_uncaught_api_errors(
    completed, kind, expected
):
    def deny():
        if kind == "identity":
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
        if kind.startswith("EMBEDDING_REGISTRY_"):
            raise EmbeddingRegistryError(kind)
        raise WorkflowError(WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID, "synthetic terminal")

    completed.hooks.append(deny)
    with pytest.raises(SimilarityContextReadError, match=expected):
        read(completed)


def test_uncompleted_native_history_cannot_be_promoted_by_storage(completed):
    history = completed.value.history()
    with completed.value.publisher.sessions.begin() as session:
        row = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == history.launch.native_launch_job_id,
                JobEventRecord.event == "REFERENCE_QUERY_NATIVE_COMPLETED",
            )
        )
        assert row is not None
        session.delete(row)
        session.get(JobRecord, history.launch.native_launch_job_id).status = "COMMITTING"
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        read(completed)
    assert len(completed.value.runs) == 1


def test_completed_read_rejects_current_source_change_after_canonical_bytes(completed):
    def change_source():
        prepared = completed.value.sources.prepared
        completed.value.sources = replace(
            completed.value.sources,
            prepared=replace(
                prepared,
                query_texts=tuple((view, text + " changed") for view, text in prepared.query_texts),
            ),
        )

    completed.hooks.extend([lambda: None, change_source])
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        read(completed)
    assert len(completed.calls) == 2 and len(completed.value.runs) == 1


def test_failed_native_job_cannot_be_approved_by_a_valid_committed_receipt(completed):
    job_id = completed.value.history().launch.native_launch_job_id
    with completed.value.publisher.sessions.begin() as session:
        session.get(JobRecord, job_id).status = "FAILED"
    before = counts(completed.value)
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        read(completed)
    assert counts(completed.value) == before and len(completed.value.runs) == 1


@pytest.mark.parametrize("member", ("input.json", "result.json", "shard.json", "vectors.f32"))
def test_each_damaged_canonical_member_fails_without_repair_or_reencoding(completed, member):
    output = read(completed)
    root = completed.value.publisher.settings.nas_artifact_root
    # Test-only exact temporary materialization, never a production NAS mutation.
    matches = tuple(root.rglob(member))
    assert len(matches) == 1
    target = matches[0]
    target.write_bytes(target.read_bytes() + b"corrupt")
    before = counts(completed.value)
    with pytest.raises(SimilarityContextReadError):
        read(completed)
    assert counts(completed.value) == before and len(completed.value.runs) == 1
    assert output.binary
