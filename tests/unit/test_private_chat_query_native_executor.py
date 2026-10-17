"""Real temporary Job/Artifact/FS composition; Chat/IAM/Workflow SQL/units are synthetic.

No installed runtime, production permission, genuine embedding or private claim admission.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import native_private_chat_query_handoff as handoff
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_private_chat_query_systemd import (
    PREPARE_TEMPLATE_SHA256,
    QUERY_TEMPLATE_SHA256,
    FixedNativePrivateQueryLauncher,
    NativePrivateQueryLaunchError,
)
from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import NativePrivateQueryExecuted
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowDefinition,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryStepPending
from eom_workflow_runner.private_chat_query_native_executor import (
    CatalogNativePrivateChatQueryExecutor,
)
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_embedding_private_chat_query import backend
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_source_owner import make_private_source_case
from tests.unit.test_private_chat_query_workflow import definition_body


@dataclass
class PrivateExecutorCase:
    service: CatalogNativePrivateChatQueryExecutor
    source: Any
    owner: Any
    launcher: Any
    workflow: Any
    step: Any
    runs: list[Any]
    root_depth: int = 0
    deny: bool = False
    failure: Exception | None = None
    after_run: Any = None
    encodes: int = 0

    @property
    def request(self):
        return self.source.request

    @property
    def publisher(self):
        return self.source.publisher

    @contextmanager
    def root(self) -> Iterator[Session]:
        assert self.root_depth == 0
        self.root_depth += 1
        try:
            with self.publisher.sessions.begin() as session:
                original_get = session.get

                def get(model, *args, **kwargs):
                    if model is WorkflowInstanceRecord:
                        assert args[0] == self.workflow.workflow_id
                        return self.workflow
                    if model is WorkflowStepRunRecord:
                        assert args[0] == self.step.step_run_id
                        return self.step
                    return original_get(model, *args, **kwargs)

                # These two views are explicitly synthetic: the current private
                # application-step CHECK/compiler is not activated by this test.
                session.get = get  # type: ignore[method-assign]
                yield session
                if self.deny:
                    raise ValueError("SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED")
        finally:
            self.root_depth -= 1

    def lease(self, generation=1):
        return CommandLeaseIdentity(
            "wfcmd_" + str(generation) * 32, "synthetic-private-runner", "lease", generation
        )

    def execute(self, *, generation=1, key=None):
        return self.service.execute(
            workflow=self.workflow,
            step=self.step,
            request=self.request,
            command_lease=self.lease(generation),
            idempotency_key=key
            or (
                f"private-chat-query-step:{self.workflow.workflow_id}:encode_private_chat_query:1:"
                f"{self.request.workflow_definition_sha256}"
            ),
            fenced_transaction=self.root,
        )

    def history(self):
        with self.root() as session:
            launch = read_native_query_launch(
                session,
                request=self.request,
                workflow_id=self.workflow.workflow_id,
                step_run_id=self.step.step_run_id,
            )
            assert launch is not None
            return launch, NativePrivateChatQueryCoordinator(self.request, launch).read(session)


def make_private_executor_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    definition = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    source = make_private_source_case(
        tmp_path,
        monkeypatch,
        definition_sha256=sha256_bytes(canonical_json_bytes(definition)),
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    staging = tmp_path / "private-native-owner"
    staging.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", staging)
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    owner = SimpleNamespace(
        configuration=source.owner.configuration,
        catalog=source.owner.catalog,
        settings=source.owner.settings,
    )
    launcher = Mock(spec=FixedNativePrivateQueryLauncher)
    service = CatalogNativePrivateChatQueryExecutor(
        owner=owner, publisher=source.publisher, launcher=launcher, source_commit="a" * 40
    )
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "1" * 32,
        state="RUNNING",
        current_step_key="encode_private_chat_query",
        runtime_context=build_private_chat_query_submission_context(
            source.request, source.projection.origin
        ).model_dump(mode="json"),
    )
    step = SimpleNamespace(
        workflow_id=workflow.workflow_id,
        step_run_id="steprun_" + "2" * 32,
        step_key="encode_private_chat_query",
        attempt=1,
        state="RUNNING",
        step_type="application",
        worker_role=None,
        result_schema="embedding-private-chat-query-result@1.0",
        input_pointer_manifest={"workflow_request_sha256": source.request.request_sha256},
        platform_job_id=None,
    )
    fixture = PrivateExecutorCase(service, source, owner, launcher, workflow, step, [])

    def resolve(session, request, _lease, *, workflow_id, step_run_id):
        assert fixture.root_depth == 1 and session.get_transaction().is_active
        assert request == fixture.request
        assert (workflow_id, step_run_id) == (workflow.workflow_id, step.step_run_id)
        if fixture.deny:
            raise ValueError("SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED")
        source.fault.session = session
        return source.owner.resolve_sources(session, request, source.projection.origin)

    def fence(*_args):
        assert fixture.root_depth == 1
        if fixture.deny:
            raise ValueError("SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED")

    def run(value):
        assert fixture.root_depth == 0, "SQL/source locks survived numerical execution"
        fixture.runs.append(value)
        if fixture.failure:
            raise fixture.failure
        # Numerical backend is synthetic; real publication, hashes and bytes are not.
        encoded = encode_private_chat_query(value.request, backend(value.request))
        fixture.encodes += 1
        for name, raw in (
            ("result.json", canonical_json_bytes(encoded.result)),
            ("vectors.f32", encoded.vectors),
        ):
            path = value.workspace / name
            path.write_bytes(raw)
            path.chmod(0o600)
        if fixture.after_run:
            fixture.after_run(value)
        return encoded.result

    def observation(_value, result):
        assert fixture.root_depth == 0, "SQL/source locks survived unit observation"
        return NativePrivateQueryExecuted.model_validate(
            {
                "boot_id": "11111111-1111-1111-1111-111111111111",
                "prepare": {
                    "invocation_id": "1" * 32,
                    "started_monotonic": 1,
                    "exited_monotonic": 2,
                },
                "query": {
                    "invocation_id": "2" * 32,
                    "started_monotonic": 3,
                    "exited_monotonic": 4,
                },
                "prepare_template_sha256": "sha256:" + PREPARE_TEMPLATE_SHA256,
                "query_template_sha256": "sha256:" + QUERY_TEMPLATE_SHA256,
                "cpu_environment_sha256": "sha256:" + "a" * 64,
                "owner_environment_sha256": "sha256:" + "b" * 64,
                "result_sha256": result.result_sha256,
                "completed_observed_at": datetime.now(UTC),
            }
        )

    owner.resolve_execution_sources, owner.fence_mutation = resolve, fence
    launcher.run.side_effect, launcher.completion_observation.side_effect = run, observation
    return fixture


@pytest.fixture
def executor(tmp_path, monkeypatch):
    return make_private_executor_case(tmp_path, monkeypatch)


def test_private_executor_commits_original_four_phases_and_exact_replay(executor):
    context = executor.workflow.runtime_context.copy()
    output = executor.execute()
    assert isinstance(output, PrivateChatQueryStepOutput)
    launch, history = executor.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    assert [record.record_type for record in history.records] == [
        "ALLOCATION",
        "EXECUTED",
        "PUBLISHED",
        "COMPLETED",
    ]
    assert executor.execute(generation=2) == output
    assert executor.history()[0] == launch
    assert executor.encodes == 1 and len(executor.runs) == 1
    assert executor.workflow.runtime_context == context
    with executor.publisher.sessions() as session:
        # Two pre-existing control producers plus launch, query and receipt.
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 5
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 4
        assert session.get(JobRecord, launch.native_launch_job_id).status == "SUCCEEDED"
        for job in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        for revision in session.scalars(select(ArtifactRevisionRecord)):
            assert TEXT.encode() not in canonical_json_bytes(revision.result)


def test_wrong_step_key_never_allocates_or_launches(executor):
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_CONTEXT_INVALID"):
        executor.execute(key="reference-query-step:wrong-purpose")
    assert not executor.runs
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2


@pytest.mark.parametrize(
    "code,reason",
    [
        ("NATIVE_PRIVATE_QUERY_BUSY", "BUSY"),
        ("NATIVE_PRIVATE_QUERY_UNCERTAIN", "UNCERTAIN"),
        ("NATIVE_PRIVATE_QUERY_COMPLETION_UNCERTAIN", "UNCERTAIN"),
        ("NATIVE_PRIVATE_QUERY_CAPACITY_UNAVAILABLE", "UNCERTAIN"),
    ],
)
def test_uncertain_unit_keeps_original_allocation_without_new_identity(executor, code, reason):
    executor.failure = NativePrivateQueryLaunchError(code)
    pending = executor.execute()
    assert isinstance(pending, PrivateChatQueryStepPending) and pending.reason == reason
    launch, history = executor.history()
    assert len(history.records) == 1
    again = executor.execute(generation=2)
    assert again == pending and executor.history()[0] == launch
    assert executor.encodes == 0


@pytest.mark.parametrize(
    "error",
    [
        NativePrivateQueryLaunchError("NATIVE_PRIVATE_QUERY_KNOWN_FAILED"),
        handoff.NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_OUTPUT_INVALID"),
    ],
)
def test_known_failure_is_terminal_not_a_new_encoding_attempt(executor, error):
    executor.failure = error
    with pytest.raises(type(error), match=error.code):
        executor.execute()
    launch, history = executor.history()
    assert history.state == "FAILED"
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_TERMINAL_HISTORY"):
        executor.execute(generation=2)
    assert len(executor.runs) == 1 and executor.encodes == 0
    assert executor.history()[0] == launch


def test_completed_canonical_read_does_not_require_old_unit_runtime(executor):
    output = executor.execute()
    executor.launcher.assert_current_runtime.side_effect = OSError("retired original units")
    executor.launcher.run.side_effect = AssertionError("must not encode completed query")
    assert executor.execute(generation=2) == output
    assert executor.encodes == 1


def test_revocation_after_numerical_work_cannot_publish_or_deliver(executor):
    executor.after_run = lambda _value: setattr(executor, "deny", True)
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED"):
        executor.execute()
    assert executor.encodes == 1
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 2


def test_completed_result_is_reauthorized_not_a_retained_grant(executor):
    executor.execute()
    executor.source.fault.value = "identity"
    with pytest.raises(ValueError, match="SOURCE_ACCESS_DENIED"):
        executor.execute(generation=2)
    assert executor.encodes == 1


def test_allocation_rollback_leaves_no_native_job(executor):
    with pytest.raises(RuntimeError, match="synthetic rollback"), executor.root() as session:
        executor.service.allocate_execution(
            session=session,
            workflow=executor.workflow,
            step=executor.step,
            request=executor.request,
            command_lease=executor.lease(),
        )
        raise RuntimeError("synthetic rollback")
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
    assert not executor.runs


@pytest.mark.parametrize(
    "boundary", ["query_before", "query_after", "receipt_before", "receipt_after"]
)
def test_crash_at_each_commit_boundary_reuses_original_identity_and_numeric_output(
    executor, monkeypatch, boundary
):
    owner_type = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    original = owner_type.publish_private_chat_query

    def crash(self, *args, **kwargs):
        if boundary.endswith("after"):
            original(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic controller death, not another encoding grant")

    with monkeypatch.context() as patch:
        patch.setattr(owner_type, "publish_private_chat_query", crash)
        with pytest.raises(KeyboardInterrupt):
            executor.execute()
    launch, prefix = executor.history()
    assert len(prefix.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(executor.execute(generation=2), PrivateChatQueryStepOutput)
    resumed_launch, final = executor.history()
    assert resumed_launch == launch and final.records[: len(prefix.records)] == prefix.records
    assert executor.encodes == 1 and len(executor.runs) == 1
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 5
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 4


def test_missing_installed_runtime_cannot_allocate_native_work(executor):
    executor.launcher.assert_current_runtime.side_effect = OSError("missing installed units")
    assert not executor.service.evaluate(executor.request).ready
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_CONTEXT_INVALID"):
        executor.execute()
    executor.launcher.run.assert_not_called()
    with executor.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2


def test_public_reference_launcher_cannot_stand_in_for_private_runtime(executor):
    from eom_orchestrator.native_embedding_query_systemd import FixedNativeQueryLauncher

    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_OWNER_MISMATCH"):
        CatalogNativePrivateChatQueryExecutor(
            owner=executor.owner,
            publisher=executor.publisher,
            launcher=Mock(spec=FixedNativeQueryLauncher),
            source_commit="a" * 40,
        )


@pytest.mark.parametrize("root_state", ["missing", "nested", "foreign"])
def test_allocation_requires_own_unnested_root_before_any_source_read(
    executor, monkeypatch, root_state
):
    executor.owner.resolve_execution_sources = Mock(side_effect=AssertionError("source read"))
    with executor.publisher.sessions() as session:
        if root_state == "nested":
            session.begin()
            session.begin_nested()
        elif root_state == "foreign":
            session.begin()
            monkeypatch.setattr(session, "get_bind", lambda: object())
        with pytest.raises(ValueError, match=r"ROOT_REQUIRED|ALLOCATION_OWNER_MISMATCH"):
            executor.service.allocate_execution(
                session=session,
                workflow=executor.workflow,
                step=executor.step,
                request=executor.request,
                command_lease=executor.lease(),
            )
    executor.owner.resolve_execution_sources.assert_not_called()
    assert not executor.runs


def test_completed_result_refuses_changed_canonical_binary_without_reencoding(executor):
    executor.execute()
    _, history = executor.history()
    published = history.records[2].payload
    target = (
        executor.publisher.settings.nas_artifact_root
        / published.binary.artifact_id
        / published.binary.artifact_revision_id
        / published.binary.member_path
    )
    assert target.is_file()
    target.chmod(0o600)
    target.write_bytes(b"\x00" * target.stat().st_size)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_COMPLETION_PUBLICATION_INVALID"):
        executor.execute(generation=2)
    assert executor.encodes == 1 and len(executor.runs) == 1


def test_completion_errors_do_not_echo_malformed_private_content(executor):
    with (
        executor.root() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_COMPLETION_OUTPUT_INVALID") as error,
    ):
        executor.service.validate_completion(
            session=session,
            workflow=executor.workflow,
            step=executor.step,
            request=executor.request,
            command_lease=executor.lease(),
            output={"secret_question": TEXT},
        )
    assert TEXT not in str(error.value)
