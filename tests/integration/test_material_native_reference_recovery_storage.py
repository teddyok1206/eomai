"""Disposable combined-retry storage with an explicit synthetic reference-proof port.

The source/rights/Item/accepted base and extraction lineage are real fixture data.
Only the Knowledge owner's invalid-reference proof is mocked here: genuine
historical-invalid acceptance and repaired-base ownership have separate owner tests.
No model, live NAS, renderer or production database is used.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisWorkerProposal,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand
from eom_catalog_service import knowledge_analysis_service as knowledge_owner
from eom_catalog_service import material_learning_recovery as owner
from eom_catalog_service.material_learning_models import (
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_task_history import read_material_task_histories
from eom_catalog_service.models import ItemRevisionRecord
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration import test_knowledge_analysis_service as knowledge
from tests.integration import test_registered_item_solution_application as solutions
from tests.integration.test_material_learning_recovery_storage import (
    controls as controls,
)
from tests.integration.test_material_learning_recovery_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_learning_recovery_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_read_case as native_read_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_registration_case as native_registration_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    native_visual_retry_case as native_visual_retry_case,
)
from tests.integration.test_material_learning_recovery_storage import (
    registration_case as registration_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@dataclass(frozen=True)
class _ReferenceProofPortValue:
    """Declarative equality snapshot, not an assertion of real invalid content."""

    task_id: str
    item_revision_id: str
    base_analysis_run_id: str
    accepted_result_sha256: str


def _accepted_base(case, engine, tmp_path):
    """Use the existing synthetic worker-response adapter, never a live model."""
    analyses = knowledge_owner.KnowledgeAnalysisApplicationService(engine, case.settings)
    base = analyses.create(
        CreateKnowledgeAnalysisCommand.model_validate(
            dict(
                source=dict(
                    source_kind="APPROVED_ITEM_REVISION",
                    source_class="APPROVED_ITEM",
                    item_revision_id=case.item.item_revision_id,
                ),
                preset_key="knowledge-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id=knowledge.POLICY_ID,
                requested_by=case.command.actor_id,
                idempotency_key="native-reference-storage-base:" + uuid4().hex,
            )
        )
    )
    with Session(engine) as session:
        request = KnowledgeAnalysisRequestV2.model_validate(
            session.get(KnowledgeAnalysisRunRecord, base.analysis_run_id).canonical_request
        )
    pointer = request.source.artifact_member
    content = json.loads(
        case.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
    )
    proposal = solutions._base_proposal(
        request,
        {
            "stem": json.dumps(content["body"], ensure_ascii=False),
            "explanations": {"correct_answer": content["solution"]},
        },
    ).model_dump(mode="json")
    proposal["anchors"][0].update(locator="/body", excerpt_sha256=content_sha256(content["body"]))
    proposal["anchors"][1]["locator"] = "/solution"
    knowledge._complete_proposal(
        engine,
        case.settings,
        run_id=base.analysis_run_id,
        staging_root=tmp_path / "native-reference-storage-response",
        proposal_override=KnowledgeAnalysisWorkerProposal.model_validate(proposal),
    )
    result = analyses.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=base.analysis_run_id, requested_by=case.command.actor_id
        )
    )
    assert result.state == "ACCEPTED"
    return result.analysis_run_id


@pytest.fixture
def native_reference_retry_case(creative_engine, native_visual_retry_case, tmp_path, monkeypatch):
    case = native_visual_retry_case
    base_id = _accepted_base(case, creative_engine, tmp_path)
    run_id, reference_id = "materialrun_" + uuid4().hex, "materialtask_" + uuid4().hex
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        old = session.get(MaterialLearningRunRecord, case.command.run_id)
        old_tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == old.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        # INSERT a new historical attempt, not an UPDATE to immutable task pins.
        # Its accepted base is valid; the invalid-reference guard below is the
        # explicitly synthetic application port under test, not this fixture.
        session.add(
            MaterialLearningRunRecord(
                run_id=run_id,
                material_revision_id=old.material_revision_id,
                attempt=2,
                predecessor_run_id=old.run_id,
                state="COMPLETED_WITH_EXCEPTIONS",
                next_event_sequence=1,
                created_by=old.created_by,
                prepared_artifact_id=case.base.artifact_id,
                prepared_artifact_revision_id=case.base.artifact_revision_id,
                prepared_sha256=case.base.sha256,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        for row in old_tasks:
            reference = row.task_id == case.source_task
            session.add(
                MaterialLearningTaskRecord(
                    task_id=reference_id if reference else "materialtask_" + uuid4().hex,
                    run_id=run_id,
                    task_kind=row.task_kind,
                    unit_key=row.unit_key,
                    ordinal=row.ordinal,
                    attempt=2,
                    predecessor_task_id=row.task_id,
                    state="FAILED" if reference else row.state,
                    execution_lane="MATERIAL_LEARNING",
                    analysis_run_id=base_id if reference else None,
                    error_code="REGISTERED_ITEM_SOLUTION_ANCHOR_INVALID"
                    if reference
                    else row.error_code,
                    **{name: getattr(row, name) for name in owner._ARTIFACT_FIELDS},
                )
            )
        # A second empty visual failure models the combined 9/13 + 14 boundary.
        session.add(
            MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid4().hex,
                run_id=run_id,
                task_kind="QUESTION",
                unit_key="second-failed-visual-unit",
                ordinal=4,
                attempt=2,
                state="FAILED",
                execution_lane="MATERIAL_LEARNING",
                error_code="OFFICE_VISUAL_USE_UNRESOLVED",
            )
        )
        accepted = session.get(KnowledgeAnalysisRunRecord, base_id)
        proof = _ReferenceProofPortValue(
            reference_id, case.item.item_revision_id, base_id, accepted.accepted_result_sha256
        )
    validate = Mock(return_value=proof)
    application = Mock(return_value=SimpleNamespace(validate_material_base_recovery=validate))
    monkeypatch.setattr(knowledge_owner, "KnowledgeAnalysisApplicationService", application)
    return SimpleNamespace(
        source=case,
        command=RetryMaterialLearningRunCommand(
            actor_id=case.command.actor_id, run_id=run_id, expected_updated_at=now
        ),
        reference_id=reference_id,
        base_id=base_id,
        validate=validate,
        proof=proof,
    )


def _recover(case, *, prepared=None):
    return owner.recover_native_material_references(
        case.source.sessions,
        case.command,
        prepared=case.source.pointer if prepared is None else prepared,
        artifacts=case.source.artifacts,
    )


def _successor_count(engine, run_id):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(MaterialLearningRunRecord)
            .where(MaterialLearningRunRecord.predecessor_run_id == run_id)
        )


def test_combined_concurrent_replay_inherits_item_but_not_old_analysis_pin(
    creative_engine, native_reference_retry_case
):
    case = native_reference_retry_case
    barrier = Barrier(2)
    with Session(creative_engine) as session:
        analysis_count = session.scalar(
            select(func.count()).select_from(KnowledgeAnalysisRunRecord)
        )
        item_count = session.scalar(select(func.count()).select_from(ItemRevisionRecord))

    def recover(_):
        barrier.wait(timeout=10)
        return _recover(case)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(recover, range(2)))
    assert len({value.run_id for value in results}) == 1
    assert sum(not value.replayed for value in results) == 1
    assert results[0].retried_tasks == 3 and results[0].reused_tasks == 1
    assert _successor_count(creative_engine, case.command.run_id) == 1
    with Session(creative_engine) as session:
        old = session.get(MaterialLearningTaskRecord, case.reference_id)
        run = session.get(MaterialLearningRunRecord, results[0].run_id)
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert [row.state for row in tasks] == ["COMPLETED", "REGISTERED", "PENDING", "PENDING"]
        assert run.attempt == 3 and run.prepared_sha256 == case.source.pointer.sha256
        assert old.state == "FAILED" and old.analysis_run_id == case.base_id
        assert all(
            getattr(tasks[1], field) == getattr(old, field) for field in owner._ARTIFACT_FIELDS
        )
        assert tasks[1].analysis_run_id is None and tasks[1].solution_analysis_run_id is None
        assert tasks[1].workflow_id is None and tasks[1].graph_snapshot_revision_id is None
        history = read_material_task_histories(session, tasks)[tasks[1].task_id]
        assert history.result_task().task_id == case.source.source_task
        assert history.analysis_owner().task_id == case.reference_id
        event = session.scalar(
            select(MaterialLearningEventRecord).where(
                MaterialLearningEventRecord.run_id == run.run_id,
                MaterialLearningEventRecord.sequence == 1,
            )
        )
        assert event.event_type == "MATERIAL_NATIVE_REFERENCE_RETRY_STARTED"
        assert (
            session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord))
            == analysis_count
        )
        assert session.scalar(select(func.count()).select_from(ItemRevisionRecord)) == item_count
    # Even a faulty application cannot erase the historical accepted-base pin.
    with (
        pytest.raises(IntegrityError, match="HISTORY_IMMUTABLE"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        session.get(MaterialLearningTaskRecord, case.reference_id).analysis_run_id = None
        session.flush()
    assert _recover(case).replayed


def test_combined_and_ordinary_retry_compete_for_one_revision_successor(
    creative_engine, native_reference_retry_case
):
    case = native_reference_retry_case
    barrier = Barrier(2)

    def recover(combined):
        barrier.wait(timeout=10)
        try:
            return (
                _recover(case)
                if combined
                else owner.retry_material_learning_run(case.source.sessions, case.command)
            )
        except MaterialLearningSourceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(recover, (False, True)))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "MATERIAL_LEARNING_RETRY_SUPERSEDED" in results
    assert _successor_count(creative_engine, case.command.run_id) == 1


@pytest.mark.parametrize("interruption", ["event", "proof_changed"])
def test_combined_partial_creation_or_changed_final_proof_rolls_back_everything(
    creative_engine, native_reference_retry_case, monkeypatch, interruption
):
    case = native_reference_retry_case
    with monkeypatch.context() as context:
        if interruption == "event":
            append = owner.append_material_event

            def interrupt(*args, **kwargs):
                append(*args, **kwargs)
                if kwargs["event_type"] == "MATERIAL_TASK_RETRY_CREATED":
                    raise RuntimeError("synthetic combined retry interruption")

            context.setattr(owner, "append_material_event", interrupt)
            expected, message = RuntimeError, "combined retry interruption"
        else:
            case.validate.side_effect = [
                case.proof,
                replace(case.proof, accepted_result_sha256="sha256:" + "f" * 64),
            ]
            expected, message = MaterialLearningSourceError, "REFERENCE_RECOVERY_CHANGED"
        with pytest.raises(expected, match=message):
            _recover(case)
    assert _successor_count(creative_engine, case.command.run_id) == 0
    with Session(creative_engine) as session:
        assert (
            session.get(MaterialLearningTaskRecord, case.reference_id).analysis_run_id
            == case.base_id
        )
    case.validate.side_effect = None
    assert not _recover(case).replayed


@pytest.mark.parametrize("failure", ["wrong_item", "wrong_base", "permission"])
def test_combined_rejects_wrong_proof_or_current_permission_without_successor(
    creative_engine, native_reference_retry_case, failure
):
    case = native_reference_retry_case
    if failure == "permission":
        case.validate.side_effect = PermissionError("synthetic current source permission revoked")
        expected, message = PermissionError, "permission revoked"
    else:
        field = "item_revision_id" if failure == "wrong_item" else "base_analysis_run_id"
        prefix = "itemrev_" if failure == "wrong_item" else "analysisrun_"
        case.validate.return_value = replace(case.proof, **{field: prefix + uuid4().hex})
        expected, message = MaterialLearningSourceError, "REFERENCE_RECOVERY_POINTER_INVALID"
    with pytest.raises(expected, match=message):
        _recover(case)
    assert _successor_count(creative_engine, case.command.run_id) == 0


def test_combined_replay_reauthorizes_and_changed_prepared_cannot_fork(
    creative_engine, native_reference_retry_case
):
    case = native_reference_retry_case
    result = _recover(case)
    changed = case.source.publish_visual(options="4")
    with pytest.raises(MaterialLearningSourceError, match="RETRY_SUPERSEDED"):
        _recover(case, prepared=changed)
    case.validate.side_effect = PermissionError("synthetic replay permission revoked")
    with pytest.raises(PermissionError, match="replay permission revoked"):
        _recover(case)
    case.validate.side_effect = None
    replay = _recover(case)
    assert replay.replayed and replay.run_id == result.run_id
    assert _successor_count(creative_engine, case.command.run_id) == 1
