"""Actual disposable Workflow/Job/Artifact/index flow with explicit synthetic IAM/model.

Not production authentication, installed-runtime admission or real model evidence.
All DB mutations require the official marker-guarded disposable engine.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator import native_embedding_index_handoff as handoff
from eom_orchestrator.embedding_encoding_reservation_storage import ENCODING_PROTOCOL_VERSION
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
    native_coordinator_checkpoint,
)
from eom_workflow.schemas import LOCAL_EMBEDDING_SCHEMA_RESOURCES
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    LocalEmbeddingOwnerConfiguration,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.local_embedding_step_execution import (
    advance_local_embedding_step,
    complete_local_embedding_terminal,
    native_fenced_runner_transaction,
)
from eom_workflow_runner.local_embedding_submission import start_local_embedding_in_session
from eom_workflow_runner.models import (
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    claim_command_candidate,
    command_lease_identity,
    import_workflow_definition,
    peek_command_candidate,
    require_command_lease,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_application import _artifact, _fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_local_embedding_runner_admission import scope_fixture

pytestmark = pytest.mark.integration


def test_concurrent_first_native_checkpoint_registration_is_atomic(guarded_engine: Engine) -> None:
    """Actual independent roots; synthetic request, no IAM/model/source assertions."""
    request = native_fixture().request
    with Session(guarded_engine) as session, session.begin():
        ensure_protocol_version(
            session,
            ENCODING_PROTOCOL_VERSION,
            next(r[3] for r in LOCAL_EMBEDDING_SCHEMA_RESOURCES if r[0] == "encoding-job"),
        )
    barrier = Barrier(2)

    def allocate(_ordinal):
        with Session(guarded_engine) as session, session.begin():
            launch = create_native_embedding_launch(
                session,
                request=request,
                workflow_id="workflow_" + uuid4().hex,
                step_run_id="steprun_" + uuid4().hex,
                command_id="wfcmd_" + uuid4().hex,
                runner_id="test-independent-checkpoint",
                lease_generation=1,
            )
            allocation = NativeCoordinatorAllocation(
                index_producer=NativeArtifactProducerIdentity(
                    job_id="job_" + uuid4().hex,
                    artifact_id="artifact_" + uuid4().hex,
                    artifact_revision_id="rev_" + uuid4().hex,
                ),
                receipt_producer=NativeArtifactProducerIdentity(
                    job_id="job_" + uuid4().hex,
                    artifact_id="artifact_" + uuid4().hex,
                    artifact_revision_id="rev_" + uuid4().hex,
                ),
                created_at=datetime.now(UTC),
                source_commit="a" * 40,
            )
            barrier.wait(timeout=30)
            history = NativeEmbeddingCoordinator(launch.intent, request).append(
                session, native_coordinator_checkpoint(launch.intent, "ALLOCATION", allocation)
            )
            assert history.state == "RUNNING" and len(history.records) == 1
            return launch.intent.native_launch_job_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = tuple(pool.map(allocate, range(2)))
    assert len(set(ids)) == 2


@pytest.fixture
def execution(guarded_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    command, capture = _fixture(guarded_engine)
    native = native_fixture()
    _unused, compiled = scope_fixture()
    profile = native.policy.profiles[0]
    namespace = EmbeddingIndexNamespace.model_validate(
        command.namespace.model_dump(mode="json")
        | {"space_sha256": profile.space.space_sha256, "view": "CONTENT_ONLY"}
    )
    config = EmbeddingRegistryOwnerConfiguration(
        command.corpus_id, namespace, profile.space, capture.index.recipe, ("PAST_EXAM",)
    )
    query = EmbeddingRegistryLookup(
        command.corpus_id,
        namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    resolved = ResolvedEmbeddingLookup(
        command.corpus_id, profile.space, capture.index.recipe, capture.sources, capture.entries
    )
    plan = build_local_embedding_source_plan(
        query, resolved, target_revision_ids=tuple(s.item_revision_id for s in capture.sources)
    )
    root = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    index_root = tmp_path / "index"
    for directory in (root, workspace, index_root):
        directory.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", index_root)
    # Test-owned local materialization only; never weaken the installed owner UID.
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=root, workspace_root=workspace
        ),
    )
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    created = datetime.now(UTC)
    saved_plan = controls.publish_source_plan(
        plan, idempotency_key="test-plan:" + uuid4().hex, created_at=created
    )
    policy = LocalEmbeddingExecutionPolicy.model_validate(
        seal(
            native.policy.model_dump(mode="json") | {"workflow_definition_sha256": compiled.sha256},
            "policy_sha256",
        )
    )
    saved_policy = controls.publish_policy(
        policy, idempotency_key="test-policy:" + uuid4().hex, created_at=created
    )
    body = native.request.model_dump(mode="json")
    body.update(
        workflow_definition_sha256=compiled.sha256,
        corpus_id=plan.corpus_id,
        graph_snapshot=plan.graph_snapshot.model_dump(mode="json"),
        namespace=namespace.model_dump(mode="json"),
        access_policy_revision_id=plan.access_policy_revision_id,
        access_policy_sha256=plan.access_policy_sha256,
        source_plan=saved_plan.member.model_dump(mode="json"),
        source_plan_sha256=plan.plan_sha256,
        native_execution_policy=saved_policy.member.model_dump(mode="json"),
        native_execution_policy_sha256=policy.policy_sha256,
    )
    request = LocalEmbeddingWorkflowRequestV11.model_validate(seal(body, "request_sha256"))
    settings = CatalogSettings(nas_artifact_root=root)
    fence = Mock()
    catalog = CatalogEmbeddingRegistryVerifier(
        guarded_engine, config, identity_fence=fence, settings=settings
    )
    scope = SimpleNamespace(requester_permission_keys=("knowledge_graph:publish",))
    corpus = AdmittedInferenceTransferCorpus(
        tuple(e.profile for e in capture.entries),
        (),
        False,
        0,
        tuple(
            AdmittedInferenceTransferSource(
                e.profile.source_basis.solution_evidence.base_analysis_run_id,
                e.profile.source_basis.source,
            )
            for e in capture.entries
        ),
    )
    current = SimpleNamespace(allowed=True, active_roots=0)
    captures = {query.graph_snapshot.graph_snapshot_revision_id: (corpus, capture.entries)}
    admitted = {request.request_sha256: (request, plan)}

    def authorize(session, caller, intent, phase):
        assert session.in_transaction() and caller.operator_id == request.actor_context.operator_id
        assert intent.corpus_id == query.corpus_id and intent.namespace == namespace
        if not current.allowed:
            raise ValueError("SYNTHETIC_CURRENT_PERMISSION_DENIED")
        actual_corpus, entries = captures[intent.graph_snapshot.graph_snapshot_revision_id]
        return PinnedArtifactReadContext(session, settings), InferenceTransferSessionCapture(
            scope, actual_corpus, entries
        )

    monkeypatch.setattr(catalog, "_capture", authorize)
    monkeypatch.setattr(
        catalog.sources,
        "capture_in_session",
        lambda session, command, *args, **kwargs: InferenceTransferSessionCapture(
            scope, *captures[command.graph_snapshot.graph_snapshot_revision_id]
        ),
    )

    class SourceOwner:
        configuration = LocalEmbeddingOwnerConfiguration(
            config, saved_policy.member, policy.policy_sha256
        )
        identity = fence

        def __init__(self):
            self.catalog, self.settings = catalog, settings

        def resolve_submission(self, session, supplied):
            assert session.in_transaction() and current.allowed
            fixed_request, fixed_plan = admitted[supplied.request_sha256]
            assert supplied == fixed_request
            return ResolvedLocalEmbeddingAdmission(fixed_request, fixed_plan, policy)

        def resolve_sources(self, session, supplied):
            return ResolvedLocalEmbeddingSources(
                self.resolve_submission(session, supplied),
                captures[supplied.graph_snapshot.graph_snapshot_revision_id][1],
            )

        def resolve_claim(self, session, *, command, workflow, request):
            assert command.workflow_id == workflow.workflow_id
            return self.resolve_submission(session, request)

        def resolve_mutation_sources(self, session, supplied, lease):
            require_command_lease(session, lease)
            return self.resolve_sources(session, supplied)

        def fence_mutation(self, session, supplied, lease):
            self.resolve_mutation_sources(session, supplied, lease)

    owner = SourceOwner()

    class Launcher:
        def __init__(self):
            self.forwards = 0
            self.invocations = {}

        def assert_current_runtime(self):
            pass  # Explicit synthetic installed-runtime seam, never live acceptance.

        def observe(self, handle):
            done = handle in self.invocations
            return (SimpleNamespace(fresh=not done, succeeded=done),) * 2

        def run(self, prepared):
            assert current.active_roots == 0  # no caller SQL root across computation
            if prepared.execution_id in self.invocations:
                return self.invocations[prepared.execution_id]
            self.forwards += 1
            backend = SyntheticNativeBackend(prepared.request.space)
            backend.batch_size = backend.threads = 4
            encoded = encode_incremental_batch(prepared.request, backend)
            for name, raw in (
                ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
                ("vectors.f32", encoded.vectors),
            ):
                path = prepared.workspace / name
                path.write_bytes(raw)
                path.chmod(0o600)
            self.invocations[prepared.execution_id] = encoded.result
            return encoded.result

    launcher = Launcher()
    executor = CatalogNativeEmbeddingExecutor(
        owner=owner,
        publisher=publisher,
        launcher=launcher,
        runtime_profile=profile,
        source_commit="a" * 40,
    )
    sessions = publisher.sessions
    with sessions.begin() as session:
        ensure_protocol_version(
            session,
            ENCODING_PROTOCOL_VERSION,
            next(r[3] for r in LOCAL_EMBEDDING_SCHEMA_RESOURCES if r[0] == "encoding-job"),
        )
        definition, _ = import_workflow_definition(session, compiled)

    def start():
        selected_request = request
        with sessions.begin() as session:
            supplied = start_local_embedding_in_session(
                session,
                definition=definition,
                request=request,
                idempotency_key="synthetic-full-native:" + uuid4().hex,
                actor_type="human",
                actor_id=request.actor_context.operator_id,
                owner=owner,
                executor=executor,
            )
            workflow_id = supplied.workflow.workflow_id
        with sessions.begin() as session:
            candidate = peek_command_candidate(
                session, family=CommandExecutionFamily.LOCAL_EMBEDDING, workflow_id=workflow_id
            )
            command = claim_command_candidate(
                session,
                candidate,
                runner_id="test-full-native-owner",
                lease_seconds=600,
                local_embedding_owner=owner,
                local_embedding_executor=executor,
            )
            command.state = "PROCESSING"  # disposable test fixture's current acquired processor
            lease = command_lease_identity(command)
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            session.expunge(workflow)

        @contextmanager
        def fenced():
            current.active_roots += 1
            try:
                with native_fenced_runner_transaction(
                    sessions,
                    owner=owner,
                    workflow_id=workflow_id,
                    request=selected_request,
                    lease=lease,
                ) as session:
                    yield session
            finally:
                current.active_roots -= 1

        return workflow, lease, fenced

    def advance(workflow, lease, fenced):
        selected_request = LocalEmbeddingWorkflowRequestV11.model_validate(workflow.initial_request)
        return advance_local_embedding_step(
            workflow=workflow,
            compiled=compiled,
            request=selected_request,
            lease=lease,
            owner=owner,
            executor=executor,
            fenced_transaction=fenced,
            poll_interval_seconds=1,
            actor_type="human",
            actor_id=request.actor_context.operator_id,
        )

    def finish(workflow, lease, fenced):
        selected_request = LocalEmbeddingWorkflowRequestV11.model_validate(workflow.initial_request)
        complete_local_embedding_terminal(
            workflow_id=workflow.workflow_id,
            request=selected_request,
            lease=lease,
            executor=executor,
            fenced_transaction=fenced,
            actor_type="human",
            actor_id=request.actor_context.operator_id,
        )

    def graph_delta():
        nonlocal request
        with sessions.begin() as session:
            original = session.get(
                KnowledgeGraphSnapshotRecord, query.graph_snapshot.graph_snapshot_revision_id
            )
            values = {
                c.key: getattr(original, c.key)
                for c in KnowledgeGraphSnapshotRecord.__table__.columns
            }
            old_corpus = session.get(KnowledgeCorpusRevisionRecord, original.corpus_revision_id)
            new_corpus_values = {
                c.key: getattr(old_corpus, c.key)
                for c in KnowledgeCorpusRevisionRecord.__table__.columns
            }
            new_corpus_values["corpus_revision_id"] = "corpusrev_" + uuid4().hex
            new_corpus_values["revision_number"] += 1
            new_corpus_values["previous_corpus_revision_id"] = old_corpus.corpus_revision_id
            session.add(KnowledgeCorpusRevisionRecord(**new_corpus_values))
            session.flush()
            values["corpus_revision_id"] = new_corpus_values["corpus_revision_id"]
            values["previous_graph_snapshot_revision_id"] = original.graph_snapshot_revision_id
            values["graph_snapshot_revision_id"] = "graphrev_" + uuid4().hex
            values["revision_number"] += 1
            # Synthetic Graph metadata is explicit; genuine Graph byte/source
            # admission remains a separate live gate, not proved by this fixture.
            graph_document = {
                "test_only": "graph-delta",
                "revision": values["graph_snapshot_revision_id"],
            }
            graph_pointer = type(query.graph_snapshot.manifest_artifact).model_validate(
                query.graph_snapshot.manifest_artifact.model_dump(mode="json")
                | {
                    "artifact_id": "artifact_" + uuid4().hex,
                    "artifact_revision_id": "rev_" + uuid4().hex,
                    "sha256": content_sha256(graph_document),
                }
            )
            _artifact(
                session,
                ArtifactMemberPointer.model_validate(
                    graph_pointer.model_dump(mode="json", exclude={"logical_name"})
                ),
                graph_document,
            )
            values.update(
                manifest_artifact_id=graph_pointer.artifact_id,
                manifest_artifact_revision_id=graph_pointer.artifact_revision_id,
                manifest_sha256=graph_pointer.sha256,
                snapshot_sha256=content_sha256(graph_document),
            )
            session.add(KnowledgeGraphSnapshotRecord(**values))
        entries = []
        for original in capture.entries:
            body = original.model_dump(mode="json")
            body["profile"]["source_basis"]["graph_snapshot"]["graph_snapshot_revision_id"] = (
                values["graph_snapshot_revision_id"]
            )
            body["profile"]["source_basis"]["graph_snapshot"].update(
                manifest_artifact=graph_pointer.model_dump(mode="json"),
                manifest_sha256=graph_pointer.sha256,
            )
            body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + uuid4().hex
            body["profile"] = seal(body["profile"], "profile_sha256")
            entries.append(StagedExperimentEntry.model_validate(body))
        new_graph = entries[0].profile.source_basis.graph_snapshot
        new_query = EmbeddingRegistryLookup(
            query.corpus_id,
            query.namespace,
            new_graph,
            query.policy_revision_id,
            query.policy_sha256,
        )
        new_plan = build_local_embedding_source_plan(
            new_query,
            ResolvedEmbeddingLookup(
                query.corpus_id,
                profile.space,
                capture.index.recipe,
                capture.sources,
                tuple(entries),
            ),
            target_revision_ids=tuple(s.item_revision_id for s in capture.sources),
        )
        saved = controls.publish_source_plan(
            new_plan,
            idempotency_key="test-graph-delta:" + uuid4().hex,
            created_at=datetime.now(UTC),
        )
        body = request.model_dump(mode="json")
        body.update(
            graph_snapshot=new_graph.model_dump(mode="json"),
            source_plan=saved.member.model_dump(mode="json"),
            source_plan_sha256=new_plan.plan_sha256,
        )
        request = LocalEmbeddingWorkflowRequestV11.model_validate(seal(body, "request_sha256"))
        new_corpus = AdmittedInferenceTransferCorpus(
            tuple(e.profile for e in entries),
            (),
            False,
            0,
            tuple(
                AdmittedInferenceTransferSource(
                    e.profile.source_basis.solution_evidence.base_analysis_run_id,
                    e.profile.source_basis.source,
                )
                for e in entries
            ),
        )
        captures[new_graph.graph_snapshot_revision_id] = (new_corpus, tuple(entries))
        admitted[request.request_sha256] = (request, new_plan)

    return SimpleNamespace(
        start=start,
        advance=advance,
        finish=finish,
        executor=executor,
        launcher=launcher,
        sessions=sessions,
        request=request,
        owner=owner,
        publisher=publisher,
        current=current,
        graph_delta=graph_delta,
    )


def test_actual_disposable_seed_and_graph_delta_reuses_vectors_without_model(execution) -> None:
    first = execution.start()
    assert execution.advance(*first) is True
    execution.finish(*first)
    assert execution.launcher.forwards == 1
    execution.graph_delta()
    second = execution.start()
    assert execution.advance(*second) is True
    execution.finish(*second)
    assert execution.launcher.forwards == 1
    with execution.sessions.begin() as session:
        for workflow, _lease, _fenced in (first, second):
            assert session.get(WorkflowInstanceRecord, workflow.workflow_id).state == "COMPLETED"
        assert (
            len(
                tuple(
                    session.scalars(
                        select(JobRecord).where(JobRecord.task_type == "native_embedding_encoding")
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    "phase", ["encoding_complete", "REGISTERED", "COMPLETED", "release_change"]
)
def test_actual_interruption_resumes_same_outputs_without_reencoding(
    execution, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    started = execution.start()
    interrupted_phase = "COMPLETED" if phase == "release_change" else phase
    original = (
        EmbeddingEncodingReservations.complete
        if phase == "encoding_complete"
        else NativeEmbeddingCoordinator.append
    )
    failed = False

    def fail_once(self, *args, **kwargs):
        nonlocal failed
        selected = phase == "encoding_complete" or args[1].record_type == interrupted_phase
        if selected and not failed:
            failed = True
            raise RuntimeError("synthetic actual persistence interruption")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        EmbeddingEncodingReservations
        if phase == "encoding_complete"
        else NativeEmbeddingCoordinator,
        "complete" if phase == "encoding_complete" else "append",
        fail_once,
    )
    with pytest.raises(RuntimeError, match="persistence interruption"):
        execution.advance(*started)
    assert execution.launcher.forwards == 1
    if phase == "release_change":
        execution.executor.source_commit = "b" * 40
    assert execution.advance(*started) is True
    execution.finish(*started)
    assert execution.launcher.forwards == 1
