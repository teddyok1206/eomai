"""Actual local Workflow/terminal/history/Artifact read; Chat/IAM/numerics are synthetic.

SQLite supplies ordinary ORM roots, not PostgreSQL constraint or installed-authority
acceptance. No operating database, genuine encoder, live user session or unit.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.private_chat_similarity_ports import (
    PrivateChatQueryUnavailable,
    VerifiedPrivateChatQueryRead,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import ArtifactRevisionRecord, Base, JobRecord
from eom_workflow.private_chat_query_workflow import PrivateChatQueryWorkflowDefinition
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_similarity_read import CatalogPrivateChatSimilarityRead
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import set_committed_value

from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_native_executor import make_private_executor_case
from tests.unit.test_private_chat_query_owner_admission import seed_owner_rows
from tests.unit.test_private_chat_query_source_owner import make_private_source_case
from tests.unit.test_private_chat_query_workflow import definition_body


@pytest.fixture
def read_case(tmp_path, monkeypatch):
    fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    source = make_private_source_case(
        tmp_path,
        monkeypatch,
        definition_sha256=sha256_bytes(canonical_json_bytes(fixed)),
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    Base.metadata.create_all(
        source.publisher.engine,
        tables=[
            WorkflowDefinitionRecord.__table__,
            WorkflowInstanceRecord.__table__,
            WorkflowCommandRecord.__table__,
            WorkflowStepRunRecord.__table__,
        ],
    )
    return make_private_similarity_read_case(source, tmp_path, monkeypatch)


def make_private_similarity_read_case(source, tmp_path, monkeypatch):
    """Shared declared Workflow/Chat/numerical seams; real supplied DB/files remain real."""
    value = seed_owner_rows(source.publisher, source.request, source.projection.origin)
    value.source = source
    native = make_private_executor_case(tmp_path, monkeypatch, source=value.source)
    native.workflow.workflow_id = value.workflow_id
    native.step.workflow_id = value.workflow_id
    native.step.step_run_id = "steprun_" + uuid4().hex
    output = native.execute()
    with native.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, value.workflow_id)
        workflow.state, workflow.stage, workflow.current_step_key = (
            "COMPLETED",
            "COMPLETED",
            "complete",
        )
        step = WorkflowStepRunRecord(
            step_run_id=native.step.step_run_id,
            workflow_id=value.workflow_id,
            step_key="encode_private_chat_query",
            attempt=1,
            state="SUCCEEDED",
            step_type="application",
            worker_role=None,
            result_schema="embedding-private-chat-query-result@1.0",
            input_pointer_manifest={"workflow_request_sha256": value.request.request_sha256},
            output_pointer_manifest=output.model_dump(mode="json"),
            platform_job_id=output.receipt_owner_job_id,
        )
        terminal = WorkflowStepRunRecord(
            step_run_id="steprun_" + uuid4().hex,
            workflow_id=value.workflow_id,
            step_key="complete",
            attempt=1,
            state="SUCCEEDED",
            step_type="terminal",
            worker_role=None,
            result_schema=None,
            input_pointer_manifest={},
        )
        session.add_all([step, terminal])
    original_identity = value.source.owner.identity.fence_current_operator

    def identity(session, actor):
        value.source.fault.session = session
        return original_identity(session, actor)

    monkeypatch.setattr(value.source.owner.identity, "fence_current_operator", identity)
    read = CatalogPrivateChatSimilarityRead(
        value.source.owner, request=value.request, origin=value.context.origin
    )
    native.launcher.run.side_effect = AssertionError("consumer must never reencode")
    native.launcher.assert_current_runtime.side_effect = OSError("old physical unit retired")
    return SimpleNamespace(
        source=value.source,
        native=native,
        read=read,
        caller=EmbeddingRegistryCaller(value.context.origin.actor_id),
        request=value.request.context_request,
        workflow_id=value.workflow_id,
        output=output,
        terminal_id=terminal.step_run_id,
    )


def test_concrete_private_read_uses_actual_original_history_and_committed_bytes(read_case):
    value = read_case
    with value.native.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    result = value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert type(result) is VerifiedPrivateChatQueryRead
    assert result.request.row.text == TEXT
    assert result.request.context_request_sha256 == value.request.request_sha256
    assert result.result_member == value.native.history()[1].records[2].payload.result
    assert TEXT not in repr(prepared) and TEXT not in repr(result)
    value.read.reauthorize_private_chat_similarity(value.caller, value.request, prepared)
    with value.native.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert value.native.encodes == 1 and len(value.native.runs) == 1


@pytest.mark.parametrize("field", ["text", "request_hash", "truncated", "truncated_type", "none"])
def test_prepared_value_is_not_a_cached_or_substitute_grant(read_case, field):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    changed = (
        None
        if field == "none"
        else replace(
            prepared,
            **{"query_text": TEXT + " private replacement"}
            if field == "text"
            else {"request_sha256": "sha256:" + "f" * 64}
            if field == "request_hash"
            else {"truncated": int(prepared.truncated)}
            if field == "truncated_type"
            else {"truncated": not prepared.truncated},
        )
    )
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        value.read.resolve_private_chat_query(value.caller, value.request, changed)
    assert value.native.encodes == 1


def corrupt_scalar_read(monkeypatch, session, model, field, changed):
    """Inject after the fresh SQL read; identity-map values are correctly refreshed."""
    original = session.scalar
    witnessed = []

    def scalar(statement, *args, **kwargs):
        row = original(statement, *args, **kwargs)
        if isinstance(row, model):
            set_committed_value(row, field, changed)
            witnessed.append(True)
        return row

    monkeypatch.setattr(session, "scalar", scalar)
    return witnessed


@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "FAILED", "CANCELLED"])
def test_original_not_complete_cannot_reencode_or_deliver_an_old_result(
    read_case, monkeypatch, state
):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    with value.native.publisher.sessions.begin() as session:
        witnessed = corrupt_scalar_read(
            monkeypatch, session, WorkflowInstanceRecord, "state", state
        )
        if state in {"REQUESTED", "RUNNING"}:
            result = value.read.resolve_private_chat_query_in_session(
                session, value.caller, value.request, prepared
            )
            assert result == PrivateChatQueryUnavailable("QUERY_NOT_OFFERED")
        else:
            with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
                value.read.resolve_private_chat_query_in_session(
                    session, value.caller, value.request, prepared
                )
        assert witnessed
    assert value.native.encodes == 1


@pytest.mark.parametrize("fault", ["actor", "context", "payload", "fingerprint"])
def test_other_actor_or_changed_original_metadata_cannot_borrow_result(
    read_case, monkeypatch, fault
):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    field, changed = {
        "actor": ("created_actor_id", "operator_" + "f" * 32),
        "context": ("runtime_context", {}),
        "payload": ("request_payload", {}),
        "fingerprint": ("request_hash", "sha256:" + "f" * 64),
    }[fault]
    with value.native.publisher.sessions.begin() as session:
        witnessed = corrupt_scalar_read(
            monkeypatch, session, WorkflowInstanceRecord, field, changed
        )
        with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
            value.read.resolve_private_chat_query_in_session(
                session, value.caller, value.request, prepared
            )
        assert witnessed


def test_another_actual_caller_is_rejected_before_materializing_private_text(read_case):
    value = read_case
    before = len(value.source.events)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_ACCESS_DENIED"):
        value.read.prepare_private_chat_similarity(
            EmbeddingRegistryCaller("operator_" + "f" * 32), value.request
        )
    assert len(value.source.events) == before


@pytest.mark.parametrize("fault", ["identity", "claim", "public_during_private_auth"])
def test_current_identity_claim_or_public_withdrawal_cannot_use_preparation(read_case, fault):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    value.source.fault.value = fault
    with pytest.raises(SimilarityContextReadError):
        value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert value.native.encodes == 1


@pytest.mark.parametrize("member", ["intent.json", "result.json", "shard.json", "vectors.f32"])
def test_corrupt_committed_member_is_not_a_readable_completed_result(read_case, member):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    pointer = value.native.history()[1].records[2].payload.result
    with value.native.publisher.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        target = Path(revision.nas_path, member)
    target.write_bytes(b"PRIVATE_CORRUPTION_NOT_FOR_ERRORS")
    with pytest.raises(SimilarityContextReadError) as error:
        value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert "PRIVATE_CORRUPTION_NOT_FOR_ERRORS" not in str(error.value)
    assert value.native.encodes == 1


def test_missing_terminal_receipt_cannot_be_synthesized_by_reading(read_case, monkeypatch):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    with value.native.publisher.sessions.begin() as session:
        witnessed = corrupt_scalar_read(
            monkeypatch, session, WorkflowStepRunRecord, "state", "FAILED"
        )
        with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
            value.read.resolve_private_chat_query_in_session(
                session, value.caller, value.request, prepared
            )
        assert witnessed


@pytest.mark.parametrize("fault", ["dirty", "nested"])
def test_caller_read_root_cannot_autoflush_unrelated_writes_or_use_savepoint(read_case, fault):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    before = len(value.source.events)
    with value.native.publisher.sessions.begin() as session:
        if fault == "dirty":
            session.add(JobRecord(job_id="job_" + "f" * 32))
        else:
            session.begin_nested()
        with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
            value.read.resolve_private_chat_query_in_session(
                session, value.caller, value.request, prepared
            )
        assert len(value.source.events) == before
        session.rollback()


def test_absent_original_query_is_explicitly_unavailable_without_inventing_a_job(
    read_case, monkeypatch
):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    with value.native.publisher.sessions.begin() as session:
        original = session.scalar
        observed = []

        def scalar(statement, *args, **kwargs):
            if statement.column_descriptions[0]["entity"] is WorkflowInstanceRecord:
                observed.append(True)
                return None
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", scalar)
        assert value.read.resolve_private_chat_query_in_session(
            session, value.caller, value.request, prepared
        ) == PrivateChatQueryUnavailable("QUERY_NOT_OFFERED")
        assert observed and not session.new and not session.dirty


@pytest.mark.parametrize("fault", ["workflow", "terminal", "producer"])
def test_final_authorization_cannot_outrun_changed_canonical_producer_or_terminal(
    read_case, monkeypatch, fault
):
    value = read_case
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    query_owner = value.native.history()[1].records[2].payload.query_owner_job_id
    original = value.source.owner.resolve_sources
    calls = []

    def resolve(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            # Fault injection only in this synthetic local fixture; never a
            # production history repair or a new successful state transition.
            with value.native.publisher.sessions.begin() as writer:
                if fault == "workflow":
                    writer.get(WorkflowInstanceRecord, value.workflow_id).state = "CANCELLED"
                elif fault == "terminal":
                    writer.get(WorkflowStepRunRecord, value.terminal_id).state = "FAILED"
                else:
                    writer.get(JobRecord, query_owner).status = "FAILED"
        return result

    monkeypatch.setattr(value.source.owner, "resolve_sources", resolve)
    with pytest.raises(SimilarityContextReadError):
        value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert len(calls) == 2 and value.native.encodes == 1
