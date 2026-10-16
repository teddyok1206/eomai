"""Actual temporary Job/Artifact/FS composition; IAM/Workflow SQL/numerics are synthetic.

Never production authorization, installed QUERY or genuine model acceptance.
"""

from __future__ import annotations

import json
import os
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import parse_embedding_reference_query_result
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import native_embedding_query_handoff as handoff
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_embedding_query_systemd import (
    FixedNativeQueryLauncher,
    NativeQueryLaunchError,
)
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryExecuted,
    NativeQueryExecutedV11,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    parse_reference_query_workflow_request,
)
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryStepPending
from eom_workflow_runner.reference_query_native_executor import CatalogNativeReferenceQueryExecutor
from eom_workflow_runner.reference_query_owner_admission import (
    ReferenceQueryOwnerConfiguration,
    ResolvedReferenceQuerySources,
)
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_embedding_reference_query_v11_contracts import result_body
from tests.unit.test_native_embedding_query_handoff import prepared
from tests.unit.test_reference_query_completion_artifacts import owner as publisher_owner
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_similarity_context_service import case as context_case


@dataclass
class ExecutorCase:
    service: CatalogNativeReferenceQueryExecutor
    owner: Any
    publisher: Any
    launcher: Any
    request: Any
    workflow: Any
    step: Any
    sources: ResolvedReferenceQuerySources
    runs: list[handoff.PreparedNativeQuery]
    root_depth: int = 0
    deny: bool = False
    failure: str | None = None
    after_run: Any = None

    @contextmanager
    def root(self) -> Iterator[Session]:
        assert self.root_depth == 0
        self.root_depth += 1
        try:
            with self.publisher.sessions.begin() as session:
                original_get = session.get
                session.get = lambda model, *a, **kw: (  # type: ignore[method-assign]
                    self.step if model is WorkflowStepRunRecord else original_get(model, *a, **kw)
                )
                yield session
                if self.deny:
                    raise ValueError("SYNTHETIC_CURRENT_SESSION_REVOKED")
        finally:
            self.root_depth -= 1

    def execute(self, *, generation=1, key=None):
        return self.service.execute(
            workflow=self.workflow,
            step=self.step,
            request=self.request,
            command_lease=CommandLeaseIdentity(
                "wfcmd_" + str(generation) * 32, "synthetic-query-runner", "lease", generation
            ),
            idempotency_key=key
            or (
                f"reference-query-step:{self.workflow.workflow_id}:"
                f"encode_reference_query:1:{self.request.workflow_definition_sha256}"
            ),
            fenced_transaction=self.root,
        )

    def history(self):
        with self.root() as session:
            launch = read_native_reference_query_launch(
                session,
                request=self.request,
                workflow_id=self.workflow.workflow_id,
                step_run_id=self.step.step_run_id,
            )
            assert launch is not None
            return NativeReferenceQueryCoordinator(self.request, launch).read(session)

    def allocate(self, session, *, generation=1):
        return self.service.allocate_execution(
            session=session,
            workflow=self.workflow,
            step=self.step,
            request=self.request,
            command_lease=CommandLeaseIdentity(
                "wfcmd_" + str(generation) * 32, "synthetic-query-runner", "lease", generation
            ),
        )


def make_executor_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    publisher: ControlFileSetPublisher | None = None,
) -> ExecutorCase:
    current = prepared()
    publisher = publisher_owner(tmp_path) if publisher is None else publisher
    staging = tmp_path / "owner"
    staging.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", staging)
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    _, source_port, _ = context_case()
    preparation = replace(
        source_port.prepared,
        request_sha256=current.workflow_request.context_request.request_sha256,
        query_texts=tuple((row.view, row.text) for row in current.request.rows),
    )
    sources = ResolvedReferenceQuerySources(
        current.workflow_request, current.policy, current.bundle, preparation
    )
    context = current.workflow_request.context_request
    selected = context.views[0]
    assert selected.index is not None
    config = ReferenceQueryOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            "corpus_" + "1" * 32,
            EmbeddingIndexNamespace(
                storage_partition=selected.index.storage_partition,
                space_sha256=current.policy.spaces.document.space_sha256,
                view=selected.view,
                recipe_sha256=selected.recipe.recipe_sha256,
                population_scope="OCCURRENCE_BACKED_PAST_EXAM",
            ),
            current.policy.spaces.document,
            selected.recipe,
            ("PAST_EXAM",),
        ),
        current.workflow_request.native_execution_policy,
        current.workflow_request.native_execution_policy_sha256,
        current.workflow_request.runtime_bundle,
    )
    owner = SimpleNamespace(
        configuration=config,
        catalog=SimpleNamespace(engine=publisher.engine),
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    launcher = Mock(spec=FixedNativeQueryLauncher)
    # These pre-existing fixtures deliberately exercise released 1.0 history.
    launcher.checkpoint_schema_version = "native-reference-query-coordinator/1.0"
    service = CatalogNativeReferenceQueryExecutor(
        owner=owner, publisher=publisher, launcher=launcher, source_commit="a" * 40
    )
    fixture = ExecutorCase(
        service,
        owner,
        publisher,
        launcher,
        current.workflow_request,
        SimpleNamespace(workflow_id=current.association.workflow_id),
        SimpleNamespace(step_run_id=current.association.step_run_id, platform_job_id=None),
        sources,
        [],
    )

    def resolve(session, request, _lease, **_kw):
        assert fixture.root_depth == 1 and session.get_transaction().is_active
        assert request == fixture.request
        if fixture.deny:
            raise ValueError("SYNTHETIC_CURRENT_SESSION_REVOKED")
        return fixture.sources

    def fence(*_a, **_kw):
        assert fixture.root_depth == 1
        if fixture.deny:
            raise ValueError("SYNTHETIC_CURRENT_SESSION_REVOKED")

    def run(value):
        assert fixture.root_depth == 0, "SQL/source locks survived numerical execution"
        fixture.runs.append(value)
        if fixture.failure:
            raise NativeQueryLaunchError(fixture.failure)
        dimension, rows = value.request.spaces.query.model_spec.dimension, len(value.request.rows)
        binary = struct.pack(f"<{dimension * rows}f", *([1.0] + [0.0] * (dimension - 1)) * rows)
        body = result_body(value.request)
        body["shard"]["binary"]["sha256"] = sha256_bytes(binary)
        body["shard"] = seal(body["shard"], "shard_sha256")
        result = parse_embedding_reference_query_result(seal(body, "result_sha256"))
        for name, raw in (
            ("result.json", canonical_json_bytes(result.model_dump(mode="json"))),
            ("vectors.f32", binary),
        ):
            path = value.workspace / name
            path.write_bytes(raw)
            path.chmod(0o600)
        if fixture.after_run:
            fixture.after_run(value)
        return result

    def observation(_value, result):
        assert fixture.root_depth == 0, "SQL/source locks survived unit observation"
        metadata = query_records(case(), version=launcher.checkpoint_schema_version)[
            1
        ].payload.model_dump(mode="json")
        metadata.update(result_sha256=result.result_sha256, completed_observed_at=datetime.now(UTC))
        model = (
            NativeQueryExecutedV11
            if launcher.checkpoint_schema_version == "native-reference-query-coordinator/1.1"
            else NativeQueryExecuted
        )
        return model.model_validate(metadata)

    owner.resolve_execution_sources, owner.fence_mutation = resolve, fence
    launcher.run.side_effect, launcher.completion_observation.side_effect = run, observation
    return fixture


@pytest.fixture
def executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExecutorCase:
    return make_executor_case(tmp_path, monkeypatch)


def test_successor_launch_completes_and_replays_without_reencoding(executor):
    value = executor
    value.launcher.checkpoint_schema_version = "native-reference-query-coordinator/1.1"
    output = value.execute()
    assert isinstance(output, ReferenceQueryStepOutput)
    history = value.history()
    assert all(
        row.schema_version == value.launcher.checkpoint_schema_version for row in history.records
    )
    assert value.execute(generation=2) == output
    assert value.history() == history and len(value.runs) == 1


def test_legacy_unobserved_allocation_cannot_launch_under_successor_units(executor, monkeypatch):
    from eom_workflow_runner import reference_query_native_executor as module

    value = executor
    with value.root() as session:
        value.allocate(session)
    original = value.history()
    value.launcher.checkpoint_schema_version = "native-reference-query-coordinator/1.1"
    monkeypatch.setattr(module, "stage_native_query", Mock(side_effect=AssertionError("stage")))
    monkeypatch.setattr(
        module, "mark_native_query_launch_started", Mock(side_effect=AssertionError("launch"))
    )
    pending = value.execute(generation=2)
    assert isinstance(pending, ReferenceQueryStepPending)
    assert pending.reason == "UNCERTAIN"
    assert value.history() == original and not value.runs
    value.launcher.run.assert_not_called()


def test_legacy_observed_execution_finishes_metadata_only_after_release_change(
    executor, monkeypatch
):
    value = executor
    with monkeypatch.context() as patch:
        patch.setattr(
            value.service.completion,
            "publish",
            Mock(side_effect=KeyboardInterrupt("synthetic interruption")),
        )
        with pytest.raises(KeyboardInterrupt):
            value.execute()
    original = value.history()
    assert len(original.records) == 2
    value.launcher.checkpoint_schema_version = "native-reference-query-coordinator/1.1"
    assert isinstance(value.execute(generation=2), ReferenceQueryStepOutput)
    final = value.history()
    assert final.records[:2] == original.records and len(value.runs) == 1
    assert all(
        row.schema_version == "native-reference-query-coordinator/1.0" for row in final.records
    )


def test_actual_missing_query_root_is_not_ready_and_cannot_allocate(
    executor, tmp_path, monkeypatch
):
    value = executor
    missing = tmp_path / "missing-query-root"
    monkeypatch.setattr(handoff, "OWNER_ROOT", missing)
    value.launcher.assert_current_runtime.side_effect = handoff.require_native_query_owner_root
    report = value.service.evaluate(value.request)
    assert not report.ready
    assert report.checks[0].code == "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE"
    with value.root() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    with value.root() as session, pytest.raises(ValueError, match="EXECUTOR_CONTEXT_INVALID"):
        value.allocate(session)
    with value.root() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert not missing.exists() and value.runs == []
    value.launcher.run.assert_not_called()


def test_allocation_only_is_committed_without_staging_and_reused_by_physical_execution(
    executor, monkeypatch
):
    from eom_workflow_runner import reference_query_native_executor as module

    value = executor
    before = tuple(value.publisher.settings.workspace_root.rglob("*"))
    with monkeypatch.context() as patch:
        patch.setattr(module, "stage_native_query", Mock(side_effect=AssertionError("stage")))
        patch.setattr(
            module, "mark_native_query_launch_started", Mock(side_effect=AssertionError("launch"))
        )
        with value.root() as session:
            association = value.allocate(session)
        original = value.history()
        assert original.launch == association and len(original.records) == 1
        assert original.state == "RUNNING"
        with value.root() as session:
            assert value.allocate(session, generation=2) == association
        assert value.history() == original
    assert tuple(value.publisher.settings.workspace_root.rglob("*")) == before
    assert value.runs == []
    value.launcher.run.assert_not_called()
    assert isinstance(value.execute(generation=2), ReferenceQueryStepOutput)
    assert value.history().launch == association
    assert value.history().records[:1] == original.records
    assert len(value.runs) == 1


@pytest.mark.parametrize("failure", ("before", "after", "late_root"))
def test_allocation_failure_rolls_back_original_job_and_checkpoint_without_model(executor, failure):
    value = executor
    with pytest.raises(ValueError), value.root() as session:
        if failure == "before":
            value.deny = True
        value.allocate(session)
        if failure == "after":
            raise ValueError("synthetic caller root aborted after allocation")
        value.deny = True
    value.deny = False
    with value.root() as session:
        assert (
            read_native_reference_query_launch(
                session,
                request=value.request,
                workflow_id=value.workflow.workflow_id,
                step_run_id=value.step.step_run_id,
            )
            is None
        )
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
    assert value.runs == []
    value.launcher.run.assert_not_called()


@pytest.mark.parametrize("root_state", ("missing", "nested", "foreign"))
def test_allocation_cannot_use_missing_nested_or_foreign_root(executor, monkeypatch, root_state):
    value = executor
    value.owner.resolve_execution_sources = Mock(side_effect=AssertionError("owner IO"))
    with value.publisher.sessions() as session:
        if root_state == "nested":
            session.begin()
            session.begin_nested()
        elif root_state == "foreign":
            session.begin()
            monkeypatch.setattr(session, "get_bind", lambda: object())
        with pytest.raises(ValueError, match="REFERENCE_QUERY_ALLOCATION_"):
            value.allocate(session)
    value.owner.resolve_execution_sources.assert_not_called()
    assert value.runs == []


@pytest.mark.parametrize("view_count", (1, 2, 3))
def test_composed_real_job_publication_completion_and_replay_never_reencode(executor, view_count):
    value = executor
    context = value.request.context_request.model_dump(mode="json")
    if view_count == 3:
        third = value.request.context_request.views[0].model_dump(mode="json")
        third["view"] = "METADATA_ONLY"
        third["index"].update(
            index_id="embeddingindex_" + "3" * 32, index_revision_id="embeddingindexrev_" + "3" * 32
        )
        context["views"].append(third)
    if view_count > 1:
        request = parse_reference_query_workflow_request(
            seal(
                value.request.model_dump(mode="json")
                | {"context_request": seal(context, "request_sha256")},
                "request_sha256",
            )
        )
        texts = tuple(
            (selection.view, f"synthetic current source for {selection.view}")
            for selection in request.context_request.views
        )
        value.request = request
        value.sources = ResolvedReferenceQuerySources(
            request,
            value.sources.policy,
            value.sources.bundle,
            replace(
                value.sources.prepared,
                request_sha256=request.context_request.request_sha256,
                query_texts=texts,
            ),
        )
    output = value.execute()
    assert isinstance(output, ReferenceQueryStepOutput)
    original = value.history()
    assert original.state == "SUCCEEDED" and len(original.records) == 4
    assert value.execute(generation=2) == output
    assert len(value.runs) == 1
    assert value.history() == original
    assert value.runs[0].request.batch_size == 4 and len(value.runs[0].request.rows) == view_count
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 2
        for job in session.scalars(select(JobRecord)):
            assert job.status == "SUCCEEDED" and job.worker_slot_id is None
            assert b'"text"' not in canonical_json_bytes(job.request)


@pytest.mark.parametrize(
    "code",
    [
        "NATIVE_QUERY_BUSY",
        "NATIVE_QUERY_UNCERTAIN",
        "NATIVE_QUERY_COMPLETION_UNCERTAIN",
        "NATIVE_QUERY_CAPACITY_UNAVAILABLE",
    ],
)
def test_waiting_rejoins_exact_original_allocation_without_new_job_identity(executor, code):
    value = executor
    value.failure = code
    pending = value.execute()
    assert isinstance(pending, ReferenceQueryStepPending)
    original = value.history()
    assert original.state == "RUNNING" and len(original.records) == 1
    value.failure = None
    output = value.execute(generation=2)
    assert isinstance(output, ReferenceQueryStepOutput)
    assert value.history().launch == original.launch
    assert value.history().records[0] == original.records[0]
    assert value.runs[0] == value.runs[1]


def test_known_failure_is_terminal_and_cannot_be_repaired_or_renamed(executor):
    value = executor
    value.failure = "NATIVE_QUERY_KNOWN_FAILED"
    with pytest.raises(NativeQueryLaunchError):
        value.execute()
    before = value.history()
    assert before.state == "FAILED"
    value.failure = None
    with pytest.raises(ValueError, match="TERMINAL_HISTORY"):
        value.execute(generation=2)
    assert value.history() == before and len(value.runs) == 1


@pytest.mark.parametrize(
    "boundary", ("query_before", "query_after", "receipt_before", "receipt_after")
)
def test_crash_at_each_publication_boundary_reuses_original_producers_without_reencoding(
    executor,
    monkeypatch,
    boundary,
):
    value = executor
    query = boundary.startswith("query")
    owner_type = EmbeddingArtifactStore if query else NativeEmbeddingCompletionPublisher
    method = owner_type.publish_reference_query

    def crash(self, *a, **kw):
        if boundary.endswith("after"):
            method(self, *a, **kw)
        raise KeyboardInterrupt("synthetic controller death; never a retry grant")

    with monkeypatch.context() as patch:
        patch.setattr(owner_type, "publish_reference_query", crash)
        with pytest.raises(KeyboardInterrupt):
            value.execute()
    before = value.history()
    assert len(before.records) == (2 if query else 3)
    output = value.execute(generation=2)
    assert isinstance(output, ReferenceQueryStepOutput) and len(value.runs) == 1
    after = value.history()
    assert after.launch == before.launch
    assert after.records[: len(before.records)] == before.records
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 2


def test_valid_but_changed_local_result_cannot_replace_observed_numerical_output(executor):
    value = executor

    def replace_result(prepared):
        path = prepared.workspace / "result.json"
        document = json.loads(path.read_bytes())
        dimension, count = (
            prepared.request.spaces.query.model_spec.dimension,
            len(prepared.request.rows),
        )
        binary = struct.pack(
            f"<{dimension * count}f", *([0.0, 1.0] + [0.0] * (dimension - 2)) * count
        )
        document["shard"]["binary"]["sha256"] = sha256_bytes(binary)
        document["shard"] = seal(document["shard"], "shard_sha256")
        path.write_bytes(canonical_json_bytes(seal(document, "result_sha256")))
        (prepared.workspace / "vectors.f32").write_bytes(binary)

    value.after_run = replace_result
    with pytest.raises(ValueError):
        value.execute()
    assert len(value.history().records) == 2 and len(value.runs) == 1
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 0


def test_late_revoke_after_query_commit_cannot_promote_receipt_and_recovery_reuses_output(
    executor,
    monkeypatch,
):
    value = executor
    original = EmbeddingArtifactStore.publish_reference_query

    def revoke(self, **kwargs):
        result = original(self, **kwargs)
        value.deny = True
        return result

    with monkeypatch.context() as patch:
        patch.setattr(EmbeddingArtifactStore, "publish_reference_query", revoke)
        with pytest.raises(ValueError, match="REVOKED"):
            value.execute()
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
    value.deny = False
    before = value.history()
    assert len(before.records) == 2
    assert isinstance(value.execute(generation=2), ReferenceQueryStepOutput)
    assert len(value.runs) == 1 and value.history().records[:2] == before.records


@pytest.mark.parametrize("fault", ["key", "uninstalled", "revoked", "no_views"])
def test_denied_or_unavailable_context_never_allocates_or_runs(executor, fault):
    value = executor
    if fault == "uninstalled":
        value.launcher.assert_current_runtime.side_effect = ValueError("absent")
    if fault == "revoked":
        value.deny = True
    if fault == "no_views":
        value.sources = ResolvedReferenceQuerySources(
            value.sources.request,
            value.sources.policy,
            value.sources.bundle,
            replace(value.sources.prepared, query_texts=()),
        )
    with pytest.raises(ValueError):
        value.execute(key="wrong" if fault == "key" else None)
    assert not value.runs
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


@pytest.mark.parametrize("fault", ["permission", "input", "observation"])
def test_late_revocation_or_changed_current_input_never_publishes_a_completion(executor, fault):
    value = executor
    if fault == "permission":
        value.after_run = lambda _: setattr(value, "deny", True)
    if fault == "input":

        def changed(_):
            before = value.sources
            value.sources = ResolvedReferenceQuerySources(
                before.request,
                before.policy,
                before.bundle,
                replace(
                    before.prepared,
                    query_texts=tuple(
                        (view, text + " changed") for view, text in before.prepared.query_texts
                    ),
                ),
            )

        value.after_run = changed
    if fault == "observation":
        value.launcher.completion_observation.side_effect = OSError("synthetic lost observation")
        assert isinstance(value.execute(), ReferenceQueryStepPending)
    else:
        with pytest.raises(ValueError):
            value.execute()
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 0
