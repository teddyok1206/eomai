"""Real control-owner persistence, using guarded disposable DB and synthetic text.

Control cases use a test authorization port. The final source-preparation scenario
uses real Identity authentication and a synthetic Office/PDF resolution port.
Only NON_LIVE contract evaluation is released; no Codex or Workflow command runs.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_api_contracts.external_item_learning_start import ExternalItemLearningStartV1
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.external_item_learning_preparation_service import (
    ExternalItemLearningPreparationService,
    PrepareExternalItemLearningCommand,
)
from eom_catalog_service.external_item_preview_projection import ResolvedExternalItemPreview
from eom_identifiers import (
    content_sha256,
    new_execution_preset_id,
    new_execution_preset_revision_id,
)
from eom_identity_service.auth_service import AuthService
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec
from eom_operator_identity import ActorContext, ActorSource, ActorType
from eom_operator_identity.errors import IdentityError
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_capacity_policy_revision,
    record_execution_preset_revision,
)
from eom_orchestrator.creative_parallel_controls import release_creative_parallel_controls
from eom_orchestrator.creative_source_controls import release_creative_source_controls
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_control_release import (
    release_external_item_learning_controls,
)
from eom_orchestrator.external_item_learning_controls import (
    prepare_external_item_learning_control_draft,
    publish_external_item_learning_instruction_bundle,
)
from eom_orchestrator.external_item_learning_policy_preparation import (
    ExternalItemLearningControlInputs,
)
from eom_orchestrator.models import JobRecord, WorkerSlotRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.settings import Settings
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ModelCandidate
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, func, select

from tests.unit.test_external_item_learning_controls import NOW, OPERATOR, _capacity
from tests.unit.test_external_item_learning_page_render import (
    _direct_fixture_runner,
    _pdf,
    _source_for_pdf,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_controls_and_authenticated_source_prepare_without_start(
    creative_engine: Engine, tmp_path, monkeypatch
):
    sessions = build_session_factory(creative_engine)
    nas = tmp_path / "artifacts"
    nas.mkdir()
    publisher = ControlArtifactPublisher(
        creative_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas)
    )
    capacity = _capacity()
    with sessions.begin() as session:
        for pool in capacity.pools:
            for slot_key in pool.slot_keys:
                slot_id = slot_key.removeprefix("slot")
                if session.get(WorkerSlotRecord, slot_id) is None:
                    session.add(
                        WorkerSlotRecord(
                            slot_id=slot_id,
                            linux_user="synthetic-control-slot" + slot_id,
                            role=str(pool.roles[0]),
                            enabled=True,
                            gpu=slot_id == "03",
                        )
                    )
        session.flush()
        record_capacity_policy_revision(
            session,
            policy_key="fixed-host",
            document=capacity.model_dump(mode="json"),
            created_by=OPERATOR,
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=capacity.capacity_policy_id,
            capacity_policy_revision_id=capacity.capacity_policy_revision_id,
        )
        ensure_protocol_version(
            session, "workflow-role/1.33.0", role_schema_bundle_hash("workflow-role/1.33.0")
        )
    arguments = dict(
        platform_payload=b"# Synthetic isolated platform\n",
        role_payload=b"# Synthetic closed creative proposal\n",
        source_commit="a" * 40,
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=Mock(),
    )
    pointer = publish_external_item_learning_instruction_bundle(sessions, publisher, **arguments)
    assert pointer == publish_external_item_learning_instruction_bundle(
        sessions, publisher, **arguments
    )
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key.like("creative-instruction:%"))
            )
            == 3
        )
    barrier = Barrier(2)
    draft_arguments = dict(
        instruction=pointer,
        capacity_revision_id=capacity.capacity_policy_revision_id,
        candidate=ModelCandidate(model="synthetic-reviewed-model", reasoning_effort="high"),
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=Mock(),
    )

    def prepare(_index):
        with sessions.begin() as session:
            barrier.wait(timeout=10)
            return prepare_external_item_learning_control_draft(session, **draft_arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        drafts = tuple(pool.map(prepare, range(2)))
    assert drafts[0] == drafts[1] and drafts[0].state == "DRAFT"
    with sessions() as session:
        logical = session.get(ExecutionPresetRecord, drafts[0].preset_id)
        assert logical.current_revision_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == logical.preset_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetEvaluationRecord)
                .where(ExecutionPresetEvaluationRecord.preset_id == logical.preset_id)
            )
            == 0
        )
        original = session.get(ExecutionPresetRevisionRecord, drafts[0].preset_revision_id)
        original_document = original.canonical_document

    revoked = Mock(side_effect=[None, ValueError("synthetic authorization revoked")])
    with pytest.raises(ValueError), sessions.begin() as session:
        prepare_external_item_learning_control_draft(
            session, **{**draft_arguments, "authorize_control_change": revoked}
        )
    with pytest.raises(ControlPlaneError), sessions.begin() as session:
        prepare_external_item_learning_control_draft(
            session,
            **{
                **draft_arguments,
                "candidate": ModelCandidate(
                    model="different-synthetic-model", reasoning_effort="low"
                ),
            },
        )
    with sessions() as session:
        assert (
            session.get(
                ExecutionPresetRevisionRecord, drafts[0].preset_revision_id
            ).canonical_document
            == original_document
        )

    identity = OperatorService(creative_engine)
    admin = identity.bootstrap_admin(
        username="synthetic-creative-admin", display_name="Synthetic admin"
    )
    auth = AuthService(creative_engine, SessionTokenService(TokenCodec("synthetic-test-key-" * 4)))
    login = auth.login(
        username=admin.operator.username, password=admin.temporary_password, client_name="test"
    )
    pair = auth.change_password(
        auth.authenticate_access(login.pair.access_token),
        current_password=admin.temporary_password,
        new_password="synthetic-only-disposable-password",
    )

    def actor_provider():
        current = auth.authenticate_access(pair.access_token)
        return ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=current.operator.operator_id,
            session_id=current.session_id,
            request_id="synthetic-creative-preparation",
            authentication_time=current.authenticated_at,
            permissions=current.permissions,
            source=ActorSource.APPLICATION_API,
        )

    pdf = _pdf()
    source = _source_for_pdf(pdf)

    def open_source(_session, _preview, **expected):
        assert expected == dict(
            import_id=source.import_id,
            external_number=source.external_number,
            expected_source_revision_id=source.source_revision_id,
            expected_observation_sha256=source.observation_sha256,
            expected_edition=source.selected_edition,
        )
        return source, ResolvedExternalItemPreview(
            member=VerifiedArtifactMemberStream(
                stream=BytesIO(pdf),
                content_length=len(pdf),
                sha256=source.preview_manifest.pdf_sha256,
            ),
            manifest=source.preview_manifest,
            artifact_id=source.preview_artifact_id,
            artifact_revision_id=source.preview_artifact_revision_id,
        )

    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source._open_validated_source", open_source
    )
    selected = ExternalItemLearningStartV1(
        import_id=source.import_id,
        external_number=source.external_number,
        source_revision_id=source.source_revision_id,
        observation_sha256=source.observation_sha256,
        selected_edition=source.selected_edition,
    )
    root = Path(__file__).resolve().parents[2]
    inputs = ExternalItemLearningControlInputs(
        definition=compile_definition(
            root / "config/workflows/external-item-learning.v1.yaml", {"support"}
        ),
        platform_payload=arguments["platform_payload"],
        role_payload=arguments["role_payload"],
        source_commit="a" * 40,
        reviewed_at=NOW,
        capacity_revision_id=capacity.capacity_policy_revision_id,
        candidate=draft_arguments["candidate"],
    )
    command = PrepareExternalItemLearningCommand(selected, inputs, "synthetic-full-preparation")
    service = ExternalItemLearningPreparationService(
        creative_engine,
        settings=publisher.settings,
        actor_provider=actor_provider,
        worker_group_id=os.getgid(),
        pdf_tools=_direct_fixture_runner,
    )
    first = service.prepare(command)
    second = service.prepare(command)
    assert first.workflow.selection == second.workflow.selection
    assert first.workflow.workflow_created and not second.workflow.workflow_created
    assert first.materialization == second.materialization
    assert first.materialization.image_input_manifest_sha256 is not None
    assert not any(publisher.settings.staging_root.glob("creative-prepare-*"))
    with sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow.selection.workflow_id)
        step = session.get(WorkflowStepRunRecord, first.workflow.selection.step_run_id)
        assert workflow.state == "REQUESTED" and step.state == "READY"
        assert step.platform_job_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
            )
            == 0
        )
    auth.logout(pair.session_id, admin.operator.operator_id)
    with pytest.raises(IdentityError):
        service.prepare(command)
        assert session.get(ExecutionPresetRecord, drafts[0].preset_id).current_revision_id is None

    release_barrier = Barrier(2)

    def release(_index):
        release_barrier.wait(timeout=10)
        return release_external_item_learning_controls(
            sessions,
            publisher,
            draft=drafts[0],
            operator_id=OPERATOR,
            source_commit="a" * 40,
            authorize_control_change=Mock(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        released = tuple(pool.map(release, range(2)))
    assert released[0] == released[1]
    assert released[0].preset.state == "RELEASED"
    assert len(released[0].executed_cases) == 12
    replay = release_external_item_learning_controls(
        sessions,
        publisher,
        draft=drafts[0],
        operator_id=OPERATOR,
        source_commit="a" * 40,
        authorize_control_change=Mock(),
    )
    assert replay == released[0]
    with sessions() as session:
        assert session.get(ExecutionPresetRecord, drafts[0].preset_id).current_revision_id == (
            released[0].preset.preset_revision_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == drafts[0].preset_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetEvaluationRecord)
                .where(ExecutionPresetEvaluationRecord.preset_id == drafts[0].preset_id)
            )
            == 1
        )
        report = session.get(ExecutionPresetEvaluationRecord, released[0].evaluation_id)
        assert report.scope == "NON_LIVE" and report.quality_score_permille is None
        assert report.cases_total == report.cases_passed == 12
        assert (
            session.get(
                ExecutionPresetRevisionRecord, drafts[0].preset_revision_id
            ).canonical_document
            == original_document
        )
    _assert_source_successor_release(
        sessions, publisher, released[0].preset, capacity, arguments["platform_payload"]
    )


def _assert_source_successor_release(sessions, publisher, baseline, capacity, platform_payload):
    successor_arguments = dict(
        baseline_revision_id=baseline.preset_revision_id,
        capacity_revision_id=capacity.capacity_policy_revision_id,
        platform_payload=platform_payload,
        role_payload=b"# Synthetic source-visual successor\n",
        operator_id=OPERATOR,
        source_commit="b" * 40,
        authorize=Mock(),
    )
    successor = release_creative_source_controls(sessions, publisher, **successor_arguments)
    assert successor == release_creative_source_controls(sessions, publisher, **successor_arguments)
    assert successor.compatible_workflow_protocols == ("workflow-role/1.34.0",)
    assert successor.role_policies[0].model_candidates == baseline.role_policies[0].model_candidates
    assert successor.capacity_policy_revision_id == baseline.capacity_policy_revision_id
    with sessions() as session:
        assert (
            session.get(ExecutionPresetRecord, baseline.preset_id).current_revision_id
            == baseline.preset_revision_id
        )
        assert session.get(
            ExecutionPresetRevisionRecord, baseline.preset_revision_id
        ).canonical_document == baseline.model_dump(mode="json")
        logical_successor = session.get(ExecutionPresetRecord, successor.preset_id)
        assert logical_successor.preset_key == "creative-source-learning"
        assert logical_successor.current_revision_id == successor.preset_revision_id
        evaluations = tuple(
            session.scalars(
                select(ExecutionPresetEvaluationRecord).where(
                    ExecutionPresetEvaluationRecord.preset_id == successor.preset_id
                )
            )
        )
        assert len(evaluations) == 1 and evaluations[0].scope == "NON_LIVE"
    _assert_parallel_control_release(sessions, publisher, successor)


def _assert_parallel_control_release(sessions, publisher, extraction):
    """Actual lifecycle/Artifact replay and concurrent release; no synthetic PASS row."""
    with sessions.begin() as session:
        for slot_id, role in (("04", "item_management"), ("06", "support")):
            row = session.get(WorkerSlotRecord, slot_id)
            if row is None:
                session.add(
                    WorkerSlotRecord(
                        slot_id=slot_id,
                        linux_user="synthetic-creative-slot" + slot_id,
                        role=role,
                        enabled=True,
                        gpu=False,
                    )
                )
            else:
                assert row.role == role
        for protocol in ("workflow-role/1.4.0", "workflow-role/1.6.0"):
            ensure_protocol_version(session, protocol, role_schema_bundle_hash(protocol))
        document = extraction.model_dump(mode="json")
        document.update(
            preset_id=new_execution_preset_id(),
            preset_revision_id=new_execution_preset_revision_id(),
            revision_number=1,
            compatible_workflow_protocols=["workflow-role/1.4.0", "workflow-role/1.6.0"],
        )
        document["content_sha256"] = content_sha256(
            {k: v for k, v in document.items() if k != "content_sha256"}
        )
        analysis = record_execution_preset_revision(
            session,
            preset_key="creative-knowledge-analysis",
            document=document,
            created_by=OPERATOR,
        )
        publish_execution_preset_revision(
            session,
            preset_id=analysis.preset_id,
            preset_revision_id=analysis.preset_revision_id,
        )
        analysis_revision_id = analysis.preset_revision_id
        old_capacity = session.scalar(
            select(WorkerCapacityPolicyRecord).where(
                WorkerCapacityPolicyRecord.policy_key == "fixed-host"
            )
        ).current_revision_id
    arguments = dict(
        extraction_revision_id=extraction.preset_revision_id,
        analysis_revision_id=analysis_revision_id,
        operator_id=OPERATOR,
        source_commit="c" * 40,
        authorize=Mock(),
    )
    barrier = Barrier(2)

    def release(_index):
        barrier.wait(timeout=10)
        return release_creative_parallel_controls(sessions, publisher, **arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, replay = tuple(pool.map(release, range(2)))
    assert first == replay
    assert first.capacity.max_active_knowledge_analysis == 3
    assert first.extraction.preset_id != extraction.preset_id
    assert first.analysis.preset_id != analysis.preset_id
    assert (
        first.extraction.role_policies[0].instruction_bundle
        == extraction.role_policies[0].instruction_bundle
    )
    assert (
        first.extraction.role_policies[0].model_candidates
        == extraction.role_policies[0].model_candidates
    )
    assert first.extraction.role_policies[0].worker_pool_key == "support"
    with sessions() as session:
        assert (
            session.scalar(
                select(WorkerCapacityPolicyRecord).where(
                    WorkerCapacityPolicyRecord.policy_key == "fixed-host"
                )
            ).current_revision_id
            == old_capacity
        )
        assert session.get(WorkerSlotRecord, "04").role == "item_management"
        assert (
            session.get(ExecutionPresetRecord, extraction.preset_id).current_revision_id
            == extraction.preset_revision_id
        )
        assert session.get(
            ExecutionPresetRevisionRecord, extraction.preset_revision_id
        ).canonical_document == extraction.model_dump(mode="json")
        for preset in (first.extraction, first.analysis):
            reports = tuple(
                session.scalars(
                    select(ExecutionPresetEvaluationRecord).where(
                        ExecutionPresetEvaluationRecord.preset_id == preset.preset_id,
                    )
                )
            )
            assert reports and all(report.scope == "NON_LIVE" for report in reports)
