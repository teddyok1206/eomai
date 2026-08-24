from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import eom_identity_service.models  # noqa: F401
import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisSourceV2,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeGraphPublicationResult,
    PublishKnowledgeGraphSnapshotCommand,
    ReconcileKnowledgeAnalysisCommand,
    ReviewKnowledgeAnalysisCommand,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_analysis_service import (
    KnowledgeAnalysisApplicationService,
    KnowledgeAnalysisServiceError,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_bytes,
)
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.artifacts import commit_file_set_artifact
from eom_orchestrator.control_bootstrap import (
    bootstrap_knowledge_analysis_control_plane,
    bootstrap_standard_control_plane,
)
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow import ArtifactPointer, compile_definition
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)
OPERATOR_ID = "operator_" + "7" * 32
POLICY_ID = "analysisriskrev_7f0f1d7c2f7c4a3cb97c090938e8ac30"


def _settings(tmp_path: Path) -> tuple[Settings, CatalogSettings]:
    staging = tmp_path / "staging"
    catalog_staging = tmp_path / "catalog-staging"
    nas = tmp_path / "nas"
    staging.mkdir()
    catalog_staging.mkdir()
    nas.mkdir()
    return (
        Settings(
            worker_config=Path("config/worker-slots.example.yaml").resolve(),
            staging_root=staging,
            workspace_root=tmp_path / "worker-workspaces",
            worker_home_root=tmp_path / "worker-homes",
            nas_artifact_root=nas.resolve(),
            codex_binary=Path("/usr/local/bin/codex"),
            codex_capability_policy=Path("config/codex-capabilities.example.yaml").resolve(),
            worker_timeout_seconds=600,
        ),
        CatalogSettings(
            staging_root=catalog_staging,
            nas_artifact_root=nas.resolve(),
            intake_root=tmp_path / "intake",
            placeholder_pack_source=tmp_path / "placeholder-pack",
            knowledge_stimulus_source=tmp_path / "stimulus.png",
        ),
    )


def _ensure_dependencies(engine: Engine, settings: Settings) -> None:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        if session.get(OperatorRecord, OPERATOR_ID) is None:
            session.add(
                OperatorRecord(
                    operator_id=OPERATOR_ID,
                    username="phase7-integration",
                    normalized_username="phase7-integration",
                    display_name="Phase 7 integration",
                    status="ACTIVE",
                    must_change_password=False,
                    role_version=1,
                    created_by="integration",
                    lock_version=1,
                )
            )
        compiled = compile_definition(
            Path("config/workflows/knowledge-analysis.v1.yaml").resolve(), {"support"}
        )
        import_workflow_definition(session, compiled)
        capacity = session.scalar(
            select(WorkerCapacityPolicyRecord).where(
                WorkerCapacityPolicyRecord.policy_key == "fixed-host"
            )
        )
    if capacity is None:
        bootstrap_standard_control_plane(
            engine,
            config_directory=Path("config/control-plane/standard-item-v1").resolve(),
            source_commit="a" * 40,
            actor_id="phase7-integration",
            evaluation_cases_total=1,
            settings=settings,
        )
    with sessions() as session:
        analysis_preset = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "knowledge-analysis"
            )
        )
    if analysis_preset is None:
        bootstrap_knowledge_analysis_control_plane(
            engine,
            config_directory=Path("config/control-plane/knowledge-analysis-v1").resolve(),
            source_commit="b" * 40,
            actor_id="phase7-integration",
            evaluation_cases_total=3,
            settings=settings,
        )


def _source(engine: Engine, settings: CatalogSettings, tmp_path: Path) -> tuple[str, str]:
    source_bytes = b"A bounded source about plate boundaries and earthquake observations.\n"
    source_path = tmp_path / "source.txt"
    source_path.write_bytes(source_bytes)
    artifact = CatalogArtifactService(engine, settings).commit_file_set(
        files={"source.txt": source_path},
        primary_file="source.txt",
        artifact_type="phase7-test-source",
        idempotency_key=f"phase7-source:{uuid4().hex}",
        request={"fixture": "phase7"},
        result={"fixture": "phase7"},
        file_metadata={
            "source.txt": {
                "schema_ref": "eom://schemas/knowledge/source-text/1.0",
                "media_type": "text/plain",
            }
        },
    )
    intake_id = "intake_" + uuid4().hex
    source_file_id = "sourcefile_" + uuid4().hex
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        session.add(
            ContentIntakeBatchRecord(
                intake_batch_id=intake_id,
                batch_name="phase7 source",
                state="HASHED",
                purpose="knowledge analysis integration",
                received_by=OPERATOR_ID,
                source_owner_type="EOM",
                source_owner_reference="phase7",
                source_fingerprint=content_sha256({"source": source_file_id}),
                lock_version=1,
            )
        )
        session.add(
            ContentIntakeSourceFileRecord(
                source_file_id=source_file_id,
                intake_batch_id=intake_id,
                original_filename="source.txt",
                normalized_filename="source.txt",
                relative_path="source.txt",
                media_type="text/plain",
                size_bytes=len(source_bytes),
                sha256=sha256_bytes(source_bytes),
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                declared_role="SOURCE",
                declared_description="phase7 bounded source",
            )
        )
    return intake_id, source_file_id


def _command(
    intake_id: str,
    source_file_id: str,
    *,
    source_class: str,
    idempotency_key: str,
    predecessor: str | None = None,
) -> CreateKnowledgeAnalysisCommand:
    return CreateKnowledgeAnalysisCommand.model_validate(
        {
            "source": {
                "source_kind": "CONTENT_INTAKE_FILE",
                "source_class": source_class,
                "intake_batch_id": intake_id,
                "source_file_id": source_file_id,
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "DISABLED",
            "risk_policy_revision_id": POLICY_ID,
            "predecessor_analysis_run_id": predecessor,
            "requested_by": OPERATOR_ID,
            "idempotency_key": idempotency_key,
        }
    )


def _proposal(request: KnowledgeAnalysisRequestV2) -> KnowledgeAnalysisWorkerProposal:
    source = request.source.artifact_member
    return KnowledgeAnalysisWorkerProposal.model_validate(
        {
            "analysis_request_id": request.analysis_request_id,
            "normalized_markdown": "# Source\n\nPlate-boundary observation.\n",
            "anchors": [
                {
                    "anchor_id": "anchor_source_1",
                    "artifact_revision_id": source.artifact_revision_id,
                    "member_path": source.member_path,
                    "anchor_kind": "PARAGRAPH",
                    "locator": "paragraph=1",
                    "excerpt_sha256": "sha256:" + "c" * 64,
                }
            ],
            "nodes": [
                {
                    "node_id": "knode_plate_boundary",
                    "node_type": "CONCEPT",
                    "stable_key": "earth.plate-boundary",
                    "label": "plate boundary",
                    "anchor_ids": ["anchor_source_1"],
                }
            ],
            "edges": [],
            "claims": [],
            "component_observations": [],
            "unresolved_ambiguities": [],
            "general_knowledge_used": False,
            "completed_at": NOW + timedelta(hours=1),
        }
    )


def _complete_proposal(
    engine: Engine,
    settings: CatalogSettings,
    *,
    run_id: str,
    staging_root: Path,
) -> ArtifactPointer:
    sessions = build_session_factory(engine)
    with sessions() as session:
        run = session.get(KnowledgeAnalysisRunRecord, run_id)
        assert run is not None
        request = KnowledgeAnalysisRequestV2.model_validate(run.canonical_request)
        workflow_id = run.workflow_id
    job_id = new_job_id()
    artifact_id = new_logical_artifact_id()
    revision_id = new_revision_id()
    proposal = _proposal(request)
    # Production Orchestrator owns and creates the per-job staging root before
    # proposal serialization; mirror that boundary instead of making the
    # serializer create or broaden its parent workspace.
    staging_root.mkdir(mode=0o750, parents=False, exist_ok=False)
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id=job_id,
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        staging=staging_root,
    )
    with transaction(sessions) as session:
        ensure_protocol_version(
            session,
            "workflow-role/1.4.0",
            role_schema_bundle_hash("workflow-role/1.4.0"),
        )
        job, created = submit_structured_job(
            session,
            job_id=job_id,
            protocol_version="workflow-role/1.4.0",
            idempotency_key=f"phase7-proposal:{run_id}",
            task_type="knowledge-analysis-proposal",
            request={"analysis_run_id": run_id},
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
        )
        assert created and job.job_id == job_id
        for state, event in (
            (JobState.VALIDATED, "PHASE7_PROPOSAL_VALIDATED"),
            (JobState.QUEUED, "PHASE7_PROPOSAL_QUEUED"),
            (JobState.CLAIMED, "PHASE7_PROPOSAL_CLAIMED"),
            (JobState.RUNNING, "PHASE7_PROPOSAL_RUNNING"),
            (JobState.VALIDATING_RESULT, "PHASE7_PROPOSAL_RESULT_VALIDATING"),
            (JobState.COMMITTING, "PHASE7_PROPOSAL_COMMITTING"),
        ):
            transition_job(session, job_id, state, event)
    final = commit_file_set_artifact(staged, settings.nas_artifact_root)
    with transaction(sessions) as session:
        locked_job = session.scalar(
            select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
        )
        assert locked_job is not None
        create_artifact_records(
            session,
            job=locked_job,
            content_hash=staged.primary_hash,
            manifest_hash=staged.manifest_hash,
            content_bytes=staged.primary_bytes,
            nas_path=str(final),
            manifest=staged.manifest,
            result=receipt.model_dump(mode="json"),
        )
        transition_job(session, job_id, JobState.SUCCEEDED, "PHASE7_PROPOSAL_COMMITTED")
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        assert workflow is not None
        pointer = ArtifactPointer(
            step_key="analyze",
            attempt=1,
            job_id=job_id,
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
            content_hash=staged.primary_hash,
            result_schema="knowledge-analysis-proposal-result@1.0",
        )
        context = dict(workflow.runtime_context)
        context["final_pointer_manifest"] = {
            "workflow_id": workflow_id,
            "definition_hash": workflow.definition_hash,
            "artifact_pointers": [pointer.model_dump(mode="json")],
            "analysis_proposal": pointer.model_dump(mode="json"),
            "registration": None,
            "item_registration": None,
            "content_pack": None,
        }
        workflow.runtime_context = context
        workflow.state = "COMPLETED"
        workflow.stage = "COMPLETED"
        workflow.current_step_key = "complete"
        workflow.completed_at = proposal.completed_at
        workflow.lock_version += 1
    return pointer


def test_knowledge_analysis_history_access_patterns_have_dedicated_indexes(
    integration_engine: Engine,
) -> None:
    with integration_engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'app' AND tablename = 'knowledge_analysis_runs'"
        ).all()
        indexes: dict[str, str] = {
            str(index_name): str(index_definition) for index_name, index_definition in rows
        }
    assert {
        "ix_knowledge_analysis_created",
        "ix_knowledge_analysis_source_history",
        "ix_knowledge_analysis_state_history",
        "ix_knowledge_analysis_runnable",
    }.issubset(indexes)
    assert "created_at DESC, analysis_run_id DESC" in indexes["ix_knowledge_analysis_created"]
    assert (
        "state, created_at DESC, analysis_run_id DESC"
        in indexes["ix_knowledge_analysis_state_history"]
    )


def test_education_graph_access_patterns_have_dedicated_indexes(
    integration_engine: Engine,
) -> None:
    expected = {
        "ix_knowledge_edge_outbound",
        "ix_knowledge_edge_inbound",
        "ix_knowledge_node_source_class",
        "ix_curriculum_closure_descendants",
        "ix_curriculum_closure_ancestors",
        "ix_item_element_revision_kind",
        "ix_item_element_reverse",
    }
    with integration_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'app' AND indexname = ANY(:index_names)"
            ),
            {"index_names": sorted(expected)},
        ).scalars()
        assert set(rows) == expected


def test_concurrent_analysis_create_is_single_and_retry_replays(
    integration_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    intake_id, source_file_id = _source(integration_engine, catalog_settings, tmp_path)
    service = KnowledgeAnalysisApplicationService(integration_engine, catalog_settings)
    command = _command(
        intake_id,
        source_file_id,
        source_class="TEXTBOOK",
        idempotency_key=f"phase7-concurrent:{uuid4().hex}",
    )
    barrier = Barrier(2)
    original = service._resolve_source

    def synchronized_source(
        session: Session, requested: CreateKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisSourceV2:
        source = original(session, requested)
        barrier.wait(timeout=10)
        return source

    monkeypatch.setattr(service, "_resolve_source", synchronized_source)

    def create_once() -> str:
        try:
            return service.create(command).analysis_run_id
        except KnowledgeAnalysisServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _index: create_once(), range(2)))

    monkeypatch.setattr(service, "_resolve_source", original)
    run_ids = {value for value in outcomes if value.startswith("analysisrun_")}
    assert len(run_ids) == 1
    assert outcomes.count("KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT") == 1
    replay = service.create(command)
    assert replay.analysis_run_id == run_ids.pop()
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeAnalysisRunRecord)
                .where(KnowledgeAnalysisRunRecord.idempotency_key == command.idempotency_key)
            )
            == 1
        )


def test_knowledge_analysis_acceptance_review_and_retry_are_pointer_only(
    integration_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    intake_id, source_file_id = _source(integration_engine, catalog_settings, tmp_path)
    service = KnowledgeAnalysisApplicationService(integration_engine, catalog_settings)

    auto_command = _command(
        intake_id,
        source_file_id,
        source_class="TEXTBOOK",
        idempotency_key=f"phase7-auto:{uuid4().hex}",
    )
    created = service.create(auto_command)
    assert created.state == "QUEUED"
    assert service.create(auto_command) == created
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=created.analysis_run_id,
        staging_root=tmp_path / "proposal-auto",
    )
    accepted = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    assert accepted.state == "ACCEPTED"
    assert accepted.accepted_result_artifact_revision_id is not None
    assert (
        service.reconcile(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=created.analysis_run_id,
                requested_by=OPERATOR_ID,
            )
        )
        == accepted
    )

    review_command = _command(
        intake_id,
        source_file_id,
        source_class="PAST_EXAM",
        idempotency_key=f"phase7-review:{uuid4().hex}",
    )
    review_run = service.create(review_command)
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=review_run.analysis_run_id,
        staging_root=tmp_path / "proposal-review",
    )
    needs_review = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=review_run.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    assert needs_review.state == "NEEDS_REVIEW"
    rejected = service.review(
        ReviewKnowledgeAnalysisCommand(
            analysis_run_id=review_run.analysis_run_id,
            expected_version=needs_review.resource_version,
            decision="REJECT",
            notes="Source classification requires a new bounded analysis.",
            decided_by=OPERATOR_ID,
            idempotency_key=f"phase7-reject:{uuid4().hex}",
        )
    )
    assert rejected.state == "REJECTED"
    assert rejected.accepted_result_artifact_revision_id is None

    retry_key = f"phase7-retry:{uuid4().hex}"
    retry_command = _command(
        intake_id,
        source_file_id,
        source_class="PAST_EXAM",
        idempotency_key=retry_key,
        predecessor=review_run.analysis_run_id,
    )
    retry = service.create(retry_command)
    assert retry.state == "QUEUED"
    assert retry.analysis_run_id != review_run.analysis_run_id
    assert retry.workflow_id != review_run.workflow_id
    assert service.create(retry_command) == retry
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        retry_record = session.get(KnowledgeAnalysisRunRecord, retry.analysis_run_id)
        rejected_record = session.get(KnowledgeAnalysisRunRecord, review_run.analysis_run_id)
        assert retry_record is not None and rejected_record is not None
        assert retry_record.predecessor_analysis_run_id == rejected_record.analysis_run_id
        assert retry_record.source_artifact_revision_id == (
            rejected_record.source_artifact_revision_id
        )
        assert retry_record.preset_revision_id == rejected_record.preset_revision_id
        assert retry_record.risk_policy_revision_id == rejected_record.risk_policy_revision_id
        proposal_revision = session.get(
            ArtifactRevisionRecord, accepted.proposal_artifact_revision_id
        )
        accepted_revision = session.get(
            ArtifactRevisionRecord, accepted.accepted_result_artifact_revision_id
        )
        assert proposal_revision is not None and accepted_revision is not None
        assert set(proposal_revision.result) == {
            "schema_version",
            "analysis_request_id",
            "source",
            "status",
            "members",
            "counts",
            "general_knowledge_used",
            "minimum_confidence_milli",
            "blocking_ambiguity_count",
            "content_set_sha256",
            "completed_at",
        }
        assert (
            accepted_revision.result["proposal_content_set_sha256"]
            == (proposal_revision.result["content_set_sha256"])
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeAnalysisRunRecord)
                .where(
                    KnowledgeAnalysisRunRecord.predecessor_analysis_run_id
                    == review_run.analysis_run_id
                )
            )
            == 1
        )

    conflicting = retry_command.model_copy(
        update={"general_knowledge_mode": "AUXILIARY_UNATTRIBUTED"}
    )
    with pytest.raises(KnowledgeAnalysisServiceError) as captured:
        service.create(conflicting)
    assert captured.value.code == "KNOWLEDGE_ANALYSIS_IDEMPOTENCY_CONFLICT"

    approval_command = _command(
        intake_id,
        source_file_id,
        source_class="PAST_EXAM",
        idempotency_key=f"phase7-approval:{uuid4().hex}",
    )
    approval_run = service.create(approval_command)
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=approval_run.analysis_run_id,
        staging_root=tmp_path / "proposal-approval",
    )
    approval_pending = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=approval_run.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    approve = ReviewKnowledgeAnalysisCommand(
        analysis_run_id=approval_run.analysis_run_id,
        expected_version=approval_pending.resource_version,
        decision="APPROVE",
        notes="The source-grounded proposal is approved for immutable acceptance.",
        decided_by=OPERATOR_ID,
        idempotency_key=f"phase7-approve:{uuid4().hex}",
    )
    original_accept = service._accept

    def fail_first_accept(*_args: object, **_kwargs: object) -> None:
        raise KnowledgeAnalysisServiceError(
            "KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED",
            "synthetic accepted-result commit interruption",
        )

    monkeypatch.setattr(service, "_accept", fail_first_accept)
    with pytest.raises(KnowledgeAnalysisServiceError) as interrupted:
        service.review(approve)
    assert interrupted.value.code == "KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED"
    monkeypatch.setattr(service, "_accept", original_accept)
    resumed = service.review(approve)
    assert resumed.state == "ACCEPTED"
    assert resumed.accepted_result_artifact_revision_id is not None

    malformed_command = _command(
        intake_id,
        source_file_id,
        source_class="TEXTBOOK",
        idempotency_key=f"phase7-malformed:{uuid4().hex}",
    )
    malformed = service.create(malformed_command)
    with transaction(sessions) as session:
        workflow = session.get(WorkflowInstanceRecord, malformed.workflow_id)
        assert workflow is not None
        workflow.runtime_context = {
            **workflow.runtime_context,
            "final_pointer_manifest": {"analysis_proposal": None},
        }
        workflow.state = "COMPLETED"
        workflow.stage = "COMPLETED"
        workflow.current_step_key = "complete"
        workflow.completed_at = NOW
        workflow.lock_version += 1
    failed = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=malformed.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    assert failed.state == "FAILED"
    assert failed.accepted_result_artifact_revision_id is None
    with sessions() as session:
        failed_record = session.get(KnowledgeAnalysisRunRecord, malformed.analysis_run_id)
        assert failed_record is not None
        assert failed_record.error_code == "KNOWLEDGE_ANALYSIS_POINTER_INVALID"


def test_accepted_analysis_publishes_immutable_graph_and_replays_idempotently(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    intake_id, source_file_id = _source(integration_engine, catalog_settings, tmp_path)
    analysis_service = KnowledgeAnalysisApplicationService(integration_engine, catalog_settings)
    created = analysis_service.create(
        _command(
            intake_id,
            source_file_id,
            source_class="TEXTBOOK",
            idempotency_key=f"phase8-analysis:{uuid4().hex}",
        )
    )
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=created.analysis_run_id,
        staging_root=tmp_path / "phase8-proposal",
    )
    accepted = analysis_service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    assert accepted.state == "ACCEPTED"

    value: dict[str, object] = {
        "schema_version": "knowledge-graph-publication/1.0",
        "corpus_key": f"phase8-{uuid4().hex[:12]}",
        "display_name": "Phase 8 immutable graph",
        "accepted_analysis_run_ids": [created.analysis_run_id],
        "structure_manifest": None,
        "expected_current_snapshot_revision_id": None,
        "publisher_version": "1.0.0",
        "published_by_operator_id": OPERATOR_ID,
        "idempotency_key": f"phase8-publication:{uuid4().hex}",
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    command = PublishKnowledgeGraphSnapshotCommand.model_validate(value)
    graph_service = KnowledgeGraphPublicationService(integration_engine, catalog_settings)
    published = graph_service.publish(command)
    assert published.state == "PUBLISHED"
    assert published.revision_number == 1
    assert published.counts.source_revisions == 1
    assert published.counts.nodes == 1
    assert published.counts.edges == 0
    assert graph_service.publish(command) == published

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        corpus = session.get(KnowledgeCorpusRecord, published.corpus_id)
        snapshot = session.get(
            KnowledgeGraphSnapshotRecord,
            published.graph_snapshot.graph_snapshot_revision_id,
        )
        assert corpus is not None and snapshot is not None
        assert corpus.current_graph_snapshot_revision_id == snapshot.graph_snapshot_revision_id
        assert snapshot.manifest_sha256 == published.graph_snapshot.manifest_sha256
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeNodeRecord)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == snapshot.graph_snapshot_revision_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeSnapshotAnalysisRecord)
                .where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                    == snapshot.graph_snapshot_revision_id
                )
            )
            == 1
        )

    next_commands: list[PublishKnowledgeGraphSnapshotCommand] = []
    for suffix in ("a", "b"):
        next_value = {
            **value,
            "expected_current_snapshot_revision_id": (
                published.graph_snapshot.graph_snapshot_revision_id
            ),
            "idempotency_key": f"phase8-concurrent-{suffix}:{uuid4().hex}",
        }
        next_value["request_sha256"] = content_sha256(
            {key: item for key, item in next_value.items() if key != "request_sha256"}
        )
        next_commands.append(PublishKnowledgeGraphSnapshotCommand.model_validate(next_value))

    barrier = Barrier(2)

    def publish_concurrently(command_value: PublishKnowledgeGraphSnapshotCommand) -> object:
        barrier.wait(timeout=10)
        try:
            return KnowledgeGraphPublicationService(integration_engine, catalog_settings).publish(
                command_value
            )
        except KnowledgeGraphPublicationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(publish_concurrently, next_commands))
    winners = [item for item in outcomes if isinstance(item, KnowledgeGraphPublicationResult)]
    assert len(winners) == 1
    assert winners[0].revision_number == 2
    assert outcomes.count("KNOWLEDGE_GRAPH_STALE_CURRENT") == 1

    stale_value = {**value, "idempotency_key": f"phase8-stale:{uuid4().hex}"}
    stale_value["request_sha256"] = content_sha256(
        {key: item for key, item in stale_value.items() if key != "request_sha256"}
    )
    with pytest.raises(KnowledgeGraphPublicationError) as stale_info:
        graph_service.publish(PublishKnowledgeGraphSnapshotCommand.model_validate(stale_value))
    assert stale_info.value.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"

    conflict_value = {**value, "display_name": "Different graph identity"}
    conflict_value["request_sha256"] = content_sha256(
        {key: item for key, item in conflict_value.items() if key != "request_sha256"}
    )
    with pytest.raises(KnowledgeGraphPublicationError) as conflict_info:
        graph_service.publish(PublishKnowledgeGraphSnapshotCommand.model_validate(conflict_value))
    assert conflict_info.value.code == "KNOWLEDGE_GRAPH_IDEMPOTENCY_CONFLICT"
