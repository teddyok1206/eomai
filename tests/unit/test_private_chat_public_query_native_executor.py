"""Real local controls/Jobs/four-phase Artifact commits; private/SQL authority is synthetic.

Fake numerical backend and unit observations are not physical CPU or live Chat proof.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service.private_chat_query_artifact_read import (
    ResolvedPrivateChatPublicQueryArtifacts,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_private_chat_query_handoff import NativePrivateQueryHandoffError
from eom_orchestrator.native_private_chat_query_systemd import NativePrivateQueryLaunchError
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition
from eom_workflow.private_chat_query_workflow_v2 import PrivateChatQueryStepOutputV2
from eom_workflow_runner.private_chat_query_publication_read import (
    resolve_private_chat_query_publication,
    resolve_supported_private_chat_query_publication,
)
from sqlalchemy import func, select

from tests.unit import test_private_chat_query_native_executor as legacy
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_query_basis import TEXT


def make_public_private_executor_case(tmp_path, monkeypatch, *, source=None):
    if source is not None:
        return legacy.make_private_executor_case(tmp_path, monkeypatch, source=source)
    compiled = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    current = make_private_public_source_case(
        tmp_path,
        monkeypatch,
        definition_sha256=compiled.sha256,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    source = SimpleNamespace(
        owner=current.owner,
        publisher=current.old.publisher,
        request=current.request,
        policy=current.policy,
        bundle=current.old.bundle,
        projection=current.old.projection,
        fault=current.old.fault,
        events=current.old.events,
    )
    return legacy.make_private_executor_case(tmp_path, monkeypatch, source=source)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    return make_public_private_executor_case(tmp_path, monkeypatch)


def test_common_private_executor_commits_four_matching_phases_once_and_replays(executor):
    output = executor.execute()
    assert type(output) is PrivateChatQueryStepOutputV2
    launch, history = executor.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    assert {record.schema_version for record in history.records} == {
        "native-private-chat-query-coordinator/2.0"
    }
    assert executor.execute(generation=2) == output
    assert executor.history()[0] == launch and executor.encodes == 1 and len(executor.runs) == 1
    with executor.publisher.sessions() as session:
        # Bundle, legacy fixture policy and new common policy precede launch/query/receipt.
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 6
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 5
        for job in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        for revision in session.scalars(select(ArtifactRevisionRecord)):
            assert TEXT.encode() not in canonical_json_bytes(revision.result)
            assert TEXT.encode() not in canonical_json_bytes(revision.manifest)
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


@pytest.mark.parametrize(
    "boundary", ["query_before", "query_after", "receipt_before", "receipt_after"]
)
def test_common_private_each_publication_interruption_resumes_original_numeric_work(
    executor, monkeypatch, boundary
):
    owner = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    method = (
        "publish_private_chat_query"
        if boundary.startswith("query")
        else "publish_supported_private_chat_query"
    )
    original = getattr(owner, method)

    def interrupted(self, *args, **kwargs):
        if boundary.endswith("after"):
            original(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic original publisher interruption")

    with monkeypatch.context() as patch:
        patch.setattr(owner, method, interrupted)
        with pytest.raises(KeyboardInterrupt):
            executor.execute()
    launch, before = executor.history()
    assert len(before.records) == (2 if boundary.startswith("query") else 3)
    assert type(executor.execute(generation=2)) is PrivateChatQueryStepOutputV2
    resumed, final = executor.history()
    assert resumed == launch and final.records[: len(before.records)] == before.records
    assert executor.encodes == 1 and len(executor.runs) == 1


def test_common_private_completed_read_does_not_depend_on_prior_unit_survival(executor):
    legacy.test_completed_canonical_read_does_not_require_old_unit_runtime(executor)


@pytest.mark.parametrize(
    "code,reason",
    [
        ("NATIVE_PRIVATE_QUERY_BUSY", "BUSY"),
        ("NATIVE_PRIVATE_QUERY_UNCERTAIN", "UNCERTAIN"),
        ("NATIVE_PRIVATE_QUERY_COMPLETION_UNCERTAIN", "UNCERTAIN"),
        ("NATIVE_PRIVATE_QUERY_CAPACITY_UNAVAILABLE", "UNCERTAIN"),
    ],
)
def test_common_private_uncertainty_keeps_original_allocation(executor, code, reason):
    legacy.test_uncertain_unit_keeps_original_allocation_without_new_identity(
        executor, code, reason
    )


@pytest.mark.parametrize(
    "error",
    [
        NativePrivateQueryLaunchError("NATIVE_PRIVATE_QUERY_KNOWN_FAILED"),
        NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_OUTPUT_INVALID"),
    ],
)
def test_common_private_known_failure_stays_terminal_without_new_identity(executor, error):
    legacy.test_known_failure_is_terminal_not_a_new_encoding_attempt(executor, error)


def test_common_private_source_revocation_after_numeric_work_cannot_publish(executor):
    with executor.publisher.sessions() as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    executor.after_run = lambda _value: setattr(executor, "deny", True)
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED"):
        executor.execute()
    assert executor.encodes == 1
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before


def test_common_private_completion_reauthorizes_current_source(executor):
    legacy.test_completed_result_is_reauthorized_not_a_retained_grant(executor)


def test_common_private_changed_canonical_binary_never_reencodes_as_recovery(executor):
    legacy.test_completed_result_refuses_changed_canonical_binary_without_reencoding(executor)


def test_common_private_publication_reader_uses_exact_receipt2_and_legacy_api_stays_closed(
    executor,
):
    output = executor.execute()
    with executor.root() as session:
        sources = executor.owner.resolve_execution_sources(
            session,
            executor.request,
            executor.lease(),
            workflow_id=executor.workflow.workflow_id,
            step_run_id=executor.step.step_run_id,
        )
        arguments = dict(
            session=session,
            workflow=executor.workflow,
            step=executor.step,
            sources=sources,
            output=output,
        )
        resolved, history = resolve_supported_private_chat_query_publication(
            executor.owner.settings, **arguments
        )
        assert (
            type(resolved) is ResolvedPrivateChatPublicQueryArtifacts and len(history.records) == 4
        )
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_COMPLETION_PUBLICATION_INVALID"):
            resolve_private_chat_query_publication(executor.owner.settings, **arguments)


def test_common_private_rejects_old_request_or_runtime_before_numeric_allocation(executor):
    executor.launcher.assert_current_runtime.side_effect = OSError("missing installed common leaf")
    assert not executor.service.evaluate(executor.request).ready
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_CONTEXT_INVALID"):
        executor.execute()
    assert not executor.runs and executor.encodes == 0
