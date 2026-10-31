"""Real Catalog/Orchestrator persistence with synthetic worker outputs, no inference.

Only marker-guarded disposable PostgreSQL and per-test local Artifact directories
are used. This proves contract/staging/replay/acceptance, not scientific quality,
operator HTTP authorization, a production model call or Graph/search activation.
"""

import os
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV11,
    KnowledgeAnalysisResultV11,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV8,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_catalog_service.solution_evidence_resolution import (
    SolutionEvidenceResolutionError,
    resolve_registered_solution_evidence_by_base_run,
    resolve_solution_evidence_by_base_run,
)
from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.artifacts import commit_file_set_artifact
from eom_orchestrator.control_bootstrap import bootstrap_knowledge_analysis_control_plane
from eom_orchestrator.control_models import CodexAuthBindingRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import create_artifact_records, submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow import ArtifactPointer, compile_definition
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import select

from tests.integration import test_knowledge_analysis_service as fixtures
from tests.integration import test_post_registration_item_approval as approval
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_past_exam_solution_analysis_contracts import _role_result_value
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def controls(guarded_engine, tmp_path):
    runtime, catalog = fixtures._settings(tmp_path)
    # Immutable control Artifact IDs live for the guarded DB, not for one pytest
    # invocation's temporary directory. Replays must resolve the same bytes.
    artifact_root = Path(os.environ["EOM_API_TEST_STATE"]) / "registered-solution-artifacts"
    artifact_root.mkdir(exist_ok=True)
    runtime = replace(runtime, nas_artifact_root=artifact_root)
    catalog = replace(catalog, nas_artifact_root=artifact_root)
    fixtures._ensure_dependencies(guarded_engine, runtime)
    sessions = build_session_factory(guarded_engine)
    with transaction(sessions) as session:
        before = {
            row.binding_id: (row.account_label, row.state)
            for row in session.scalars(select(CodexAuthBindingRecord)).all()
        }
    result = bootstrap_knowledge_analysis_control_plane(
        guarded_engine,
        config_directory=ROOT / "config/control-plane/knowledge-analysis-v21",
        source_commit="d" * 40,
        actor_id=fixtures.OPERATOR_ID,
        evaluation_cases_total=13,
        settings=runtime,
    )
    replay = bootstrap_knowledge_analysis_control_plane(
        guarded_engine,
        config_directory=ROOT / "config/control-plane/knowledge-analysis-v21",
        source_commit="d" * 40,
        actor_id=fixtures.OPERATOR_ID,
        evaluation_cases_total=13,
        settings=runtime,
    )
    assert replay == result
    with transaction(sessions) as session:
        after = {
            row.binding_id: (row.account_label, row.state)
            for row in session.scalars(select(CodexAuthBindingRecord)).all()
        }
        assert all(after[key] == value for key, value in before.items())
        revision = session.get(ExecutionPresetRevisionRecord, result.preset_revision_id)
        assert revision.compatible_workflow_protocols[-1] == "workflow-role/1.35.0"
        compiled = compile_definition(
            ROOT / "config/workflows/knowledge-analysis.v11.yaml", {"support"}
        )
        import_workflow_definition(session, compiled)
    return guarded_engine, catalog, result


def _base_proposal(request, source):
    reference = request_value()["base_analysis"]["reference_index"]
    pointer = request.source.artifact_member
    return KnowledgeAnalysisWorkerProposal.model_validate(
        dict(
            analysis_request_id=request.analysis_request_id,
            normalized_markdown="# Synthetic registered Item\n" + source["stem"],
            anchors=[
                dict(
                    anchor_id=key,
                    artifact_revision_id=pointer.artifact_revision_id,
                    member_path=pointer.member_path,
                    anchor_kind="ITEM_ELEMENT",
                    locator=locator,
                    excerpt_sha256=content_sha256(excerpt),
                )
                for key, locator, excerpt in (
                    ("anchor_problem", "/stem", source["stem"]),
                    (
                        "anchor_answer",
                        "/explanations/correct_answer",
                        source["explanations"]["correct_answer"],
                    ),
                )
            ],
            nodes=[
                dict(
                    node_id=node["node_id"],
                    node_type=node["node_type"],
                    stable_key="registered.fixture." + node["node_id"],
                    label=node["node_type"],
                    anchor_ids=["anchor_problem"],
                )
                for node in reference["nodes"]
            ],
            edges=[],
            claims=[],
            component_observations=[],
            unresolved_ambiguities=[],
            general_knowledge_used=False,
            completed_at=datetime.now(UTC),
        )
    )


def _complete_solution(engine, catalog, run_id, staging):
    """Synthetic worker result through the same stage/commit boundary as the real worker."""
    sessions = build_session_factory(engine)
    with sessions() as session:
        run = session.get(KnowledgeAnalysisRunRecord, run_id)
        request = KnowledgeAnalysisRequestV11.model_validate(run.canonical_request)
        workflow_id = run.workflow_id
    value = deepcopy(_role_result_value()["output"]["proposal"])
    value.update(
        analysis_request_id=request.analysis_request_id,
        base_analysis_result_id=request.base_analysis.analysis_result_id,
        completed_at=datetime.now(UTC),
    )
    value["solution_report"].update(
        analysis_request_id=request.analysis_request_id,
        base_analysis_result_id=request.base_analysis.analysis_result_id,
    )
    proposal = KnowledgeAnalysisWorkerProposalV8.model_validate(value)
    job_id, artifact_id, revision_id = new_job_id(), new_logical_artifact_id(), new_revision_id()
    staging.mkdir(mode=0o750)
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id=job_id,
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        staging=staging,
    )
    with transaction(sessions) as session:
        job, created = submit_structured_job(
            session,
            job_id=job_id,
            protocol_version="workflow-role/1.35.0",
            idempotency_key="registered-test-proposal:" + run_id,
            task_type="workflow_support",
            request={"analysis_run_id": run_id},
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
        )
        assert created
        for state in (
            JobState.VALIDATED,
            JobState.QUEUED,
            JobState.CLAIMED,
            JobState.RUNNING,
            JobState.VALIDATING_RESULT,
            JobState.COMMITTING,
        ):
            transition_job(session, job_id, state, "SYNTHETIC_REGISTERED_" + state.value)
    final = commit_file_set_artifact(staged, catalog.nas_artifact_root)
    with transaction(sessions) as session:
        job = session.scalar(select(JobRecord).where(JobRecord.job_id == job_id).with_for_update())
        create_artifact_records(
            session,
            job=job,
            content_hash=staged.primary_hash,
            manifest_hash=staged.manifest_hash,
            content_bytes=staged.primary_bytes,
            nas_path=str(final),
            manifest=staged.manifest,
            result=receipt.model_dump(mode="json"),
        )
        transition_job(session, job_id, JobState.SUCCEEDED, "SYNTHETIC_REGISTERED_COMMITTED")
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        pointer = ArtifactPointer(
            step_key="analyze",
            attempt=1,
            job_id=job_id,
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
            content_hash=staged.primary_hash,
            result_schema="knowledge-analysis-proposal-result@11.0",
        )
        workflow.runtime_context = dict(workflow.runtime_context) | {
            "final_pointer_manifest": {"analysis_proposal": pointer.model_dump(mode="json")}
        }
        workflow.state, workflow.stage, workflow.current_step_key = (
            "COMPLETED",
            "COMPLETED",
            "complete",
        )
        workflow.completed_at = proposal.completed_at
        workflow.lock_version += 1


def test_registered_item_base_to_full_solution_uses_real_persistence_and_replays(
    controls, tmp_path
):
    engine, catalog, _release = controls
    source = _content_v3().model_dump(mode="json")
    item = approval._seed_fixture(engine, catalog.nas_artifact_root, item_content=source)
    RegistryService(engine, catalog).approve_revision(
        approval._command(item, key="registered-source-approval:" + uuid4().hex)
    )
    service = KnowledgeAnalysisApplicationService(engine, catalog)
    command = CreateKnowledgeAnalysisCommand.model_validate(
        dict(
            source=dict(
                source_kind="APPROVED_ITEM_REVISION",
                source_class="APPROVED_ITEM",
                item_revision_id=item.item_revision_id,
            ),
            preset_key="knowledge-analysis",
            general_knowledge_mode="DISABLED",
            risk_policy_revision_id=fixtures.POLICY_ID,
            requested_by=fixtures.OPERATOR_ID,
            idempotency_key="registered-source-base:" + uuid4().hex,
        )
    )
    base = service.create(command)
    with service.sessions() as session:
        base_request = KnowledgeAnalysisRequestV2.model_validate(
            session.get(KnowledgeAnalysisRunRecord, base.analysis_run_id).canonical_request
        )
    fixtures._complete_proposal(
        engine,
        catalog,
        run_id=base.analysis_run_id,
        staging_root=tmp_path / "base-worker",
        proposal_override=_base_proposal(base_request, source),
    )
    accepted = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=base.analysis_run_id,
            requested_by=fixtures.OPERATOR_ID,
        )
    )
    assert accepted.state == "ACCEPTED"
    solution_command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id=accepted.analysis_run_id,
        requested_by=fixtures.OPERATOR_ID,
        idempotency_key="registered-source-solution:" + uuid4().hex,
    )
    created = service.create_solution(solution_command)
    assert service.create_solution(solution_command) == created
    workspace = tmp_path / "registered-worker-input"
    workspace.mkdir()
    workspace.chmod(0o2770)
    with service.sessions() as session:
        plan_id = session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id).plan_id
        allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan_id, step_key="analyze"
        )
        prepared = materialize_execution_step(
            session,
            plan_id=plan_id,
            step_key="analyze",
            workspace=workspace,
            canonical_artifact_root=catalog.nas_artifact_root,
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=allowed,
        )
        assert prepared.image_input_manifest_sha256 is None
        assert prepared.materialized_member_count >= 12
        assert "knowledge-analysis-request/11.0" in (workspace / "AGENTS.md").read_text()
        assert (workspace / "source/base-analysis/accepted-result.json").is_file()
        assert not (workspace / "source/base-analysis/page-images.jsonl").exists()
    _complete_solution(engine, catalog, created.analysis_run_id, tmp_path / "solution-worker")
    result = service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created.analysis_run_id,
            requested_by=fixtures.OPERATOR_ID,
        )
    )
    assert result.state == "ACCEPTED"
    assert service.create_solution(solution_command) == result
    with service.sessions() as session:
        revision = session.get(ArtifactRevisionRecord, result.accepted_result_artifact_revision_id)
        value = KnowledgeAnalysisResultV11.model_validate(revision.result)
        assert value.source.item_revision_id == item.item_revision_id
        assert value.base_analysis.analysis_run_id == base.analysis_run_id
        assert value.solution_counts.solution_steps > 0
        assert (
            value.base_analysis.accepted_result_sha256
            != value.base_analysis.accepted_result_artifact.sha256
        )
        artifacts = CatalogArtifactService(engine, catalog)
        resolved = resolve_registered_solution_evidence_by_base_run(
            session, artifacts, base_analysis_run_ids=(base.analysis_run_id,)
        )
        evidence = resolved[base.analysis_run_id]
        assert evidence.source == value.source
        assert evidence.pointer.solution_result_sha256 == value.result_sha256
        assert evidence.pointer.accepted_result_artifact.sha256 == revision.content_hash
        assert evidence.pointer.solution_analysis_run_id == result.analysis_run_id
        assert evidence.pointer.base_analysis_run_id == base.analysis_run_id
        assert evidence.report.base_analysis_result_id == value.base_analysis.analysis_result_id
        assert project_public_solution_text(evidence.report).status == "AVAILABLE"
        # The new report remains unavailable through the old past-exam family.
        assert (
            resolve_solution_evidence_by_base_run(
                session, artifacts, base_analysis_run_ids=(base.analysis_run_id,)
            )
            == {}
        )
        assert (
            resolve_registered_solution_evidence_by_base_run(
                session, artifacts, base_analysis_run_ids=("analysisrun_" + "0" * 32,)
            )
            == {}
        )

        class AlteredMemberReader:
            def __init__(self, path):
                self.path = path

            def read_member(self, **kwargs):
                raw = artifacts.read_member(**kwargs)
                return raw + b"\n" if kwargs["member_path"] == self.path else raw

        for altered_path in (
            "evidence/accepted-result.json",
            "normalized/proposal-receipt.json",
            "normalized/solution-report.json",
        ):
            with pytest.raises(SolutionEvidenceResolutionError):
                resolve_registered_solution_evidence_by_base_run(
                    session,
                    AlteredMemberReader(altered_path),
                    base_analysis_run_ids=(base.analysis_run_id,),
                )
