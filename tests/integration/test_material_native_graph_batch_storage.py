"""Opt-in disposable PostgreSQL window/linkage tests; no model or filesystem/NAS I/O.

Accepted analyses, Item and Graph rows below are deliberately synthetic metadata.
They exercise FK/state/lease/atomic-link invariants, not source/report validation
or scientific approval; those remain the existing Graph publisher's boundary.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service import material_learning_processing as processing
from eom_catalog_service import material_learning_store as store
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisRiskPolicyRevisionRecord,
    KnowledgeAnalysisRunRecord,
)
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration import test_control_plane_persistence as controls
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def identity(prefix):
    return prefix + uuid4().hex


@pytest.fixture
def batch_case(guarded_engine):
    """Reuse the marker/schema-owner guard and metadata-only control-plane seed."""
    engine = guarded_engine
    runs = []
    with Session(engine) as session, session.begin():
        plan_id, workflow_id, bundle_id = controls._complete_control_plane(session)
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        workflow.state, workflow.stage = "COMPLETED", "COMPLETED"
        workflow.completed_at = datetime.now(UTC)
        plan = session.get(ResolvedExecutionPlanRecord, plan_id)
        bundle = session.get(ExecutionBundleRevisionRecord, bundle_id)
        pointer = controls._artifact_pointer(
            session,
            schema_ref="eom://schemas/disposable/material-graph-storage/1.0",
            media_type="application/json",
            logical_name="synthetic-metadata.json",
        )
        actor, risk, pack, release = (
            identity("operator_"),
            identity("analysisriskrev_"),
            identity("contentpack_"),
            identity("packrel_"),
        )
        session.add(
            OperatorRecord(
                operator_id=actor,
                username=actor,
                normalized_username=actor,
                display_name="Disposable Graph linkage owner",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-test",
            )
        )
        session.add(
            KnowledgeAnalysisRiskPolicyRevisionRecord(
                risk_policy_revision_id=risk,
                schema_version="synthetic/1.0",
                state="RELEASED",
                content_sha256=content_sha256({"risk": risk}),
                canonical_document={"fixture": True},
                created_by=actor,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ContentPackRecord(
                content_pack_id=pack,
                pack_key="storage-" + uuid4().hex,
                display_name="Synthetic metadata only",
                description="No source publication",
                locale="ko-KR",
                domain_key="INTEGRATED_SCIENCE",
            )
        )
        session.flush()
        session.add(
            ContentPackReleaseRecord(
                content_pack_release_id=release,
                content_pack_id=pack,
                version="1.0.0",
                schema_version="1.1",
                state="RELEASED",
                source_tree_sha256=pointer.sha256,
                bundle_sha256=pointer.sha256,
                manifest_sha256=pointer.sha256,
                bundle_artifact_id=pointer.artifact_id,
                bundle_artifact_revision_id=pointer.artifact_revision_id,
                canonical_manifest_json={"fixture": True},
                compatibility_json={},
                lock_version=1,
            )
        )
        step = WorkflowStepRunRecord(
            step_run_id=identity("steprun_"),
            workflow_id=workflow_id,
            step_key="metadata",
            attempt=1,
            step_type="agent",
            worker_role="authoring",
            result_schema="authoring-result@4.0",
            state="SUCCEEDED",
            input_pointer_manifest={},
            output_pointer_manifest={},
        )
        session.add(step)
        session.flush()
        pack_release, source_workflow, source_step = release, workflow_id, step.step_run_id
        preset_id, preset_revision = plan.preset_id, plan.preset_revision_id
        assert bundle is not None

        corpus, corpus_revision, graph, graph_revision = (
            identity("corpus_"),
            identity("corpusrev_"),
            identity("graph_"),
            identity("graphrev_"),
        )
        session.add(
            KnowledgeCorpusRecord(
                corpus_id=corpus,
                corpus_key="storage-" + uuid4().hex,
                display_name="Synthetic metadata Graph",
                graph_id=graph,
                lifecycle_state="ACTIVE",
                created_by_operator_id=actor,
            )
        )
        session.flush()
        session.add(
            KnowledgeCorpusRevisionRecord(
                corpus_revision_id=corpus_revision,
                corpus_id=corpus,
                revision_number=1,
                source_set_sha256=pointer.sha256,
                state="PUBLISHED",
                created_by_operator_id=actor,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.add(
            KnowledgeGraphSnapshotRecord(
                graph_snapshot_revision_id=graph_revision,
                graph_id=graph,
                corpus_revision_id=corpus_revision,
                revision_number=1,
                state="PUBLISHED",
                ontology_version="synthetic/1.0",
                publisher_version="1.0.0",
                manifest_artifact_id=pointer.artifact_id,
                manifest_artifact_revision_id=pointer.artifact_revision_id,
                projection_artifact_id=pointer.artifact_id,
                projection_artifact_revision_id=pointer.artifact_revision_id,
                manifest_sha256=content_sha256({"graph": graph}),
                snapshot_sha256=pointer.sha256,
                source_count=1,
                node_count=1,
                edge_count=0,
                anchor_count=1,
                created_by_operator_id=actor,
                created_at=datetime.now(UTC),
            )
        )

    owner = object.__new__(processing.MaterialLearningProcessingService)
    owner.sessions = build_session_factory(engine)
    owner.coordinator = SimpleNamespace(authorize=Mock())

    def analysis(session, item, predecessor=None):
        workflow = controls._workflow(session)
        workflow.state, workflow.stage = "COMPLETED", "COMPLETED"
        run_id = identity("analysisrun_")
        row = KnowledgeAnalysisRunRecord(
            analysis_run_id=run_id,
            analysis_request_id=identity("analysisreq_"),
            predecessor_analysis_run_id=predecessor,
            request_sha256=content_sha256({"request": run_id}),
            submission_sha256=content_sha256({"submission": run_id}),
            idempotency_key="storage-analysis:" + run_id,
            canonical_request={
                "schema_version": "knowledge-analysis-request/11.0"
                if predecessor
                else "knowledge-analysis-request/2.0",
                "fixture": True,
            },
            source_kind="APPROVED_ITEM_REVISION",
            source_revision_id=item.item_revision_id,
            item_id=item.item_id,
            item_revision_id=item.item_revision_id,
            source_artifact_id=pointer.artifact_id,
            source_artifact_revision_id=pointer.artifact_revision_id,
            source_sha256=pointer.sha256,
            workflow_id=workflow.workflow_id,
            plan_id=plan_id,
            preset_id=preset_id,
            preset_revision_id=preset_revision,
            risk_policy_revision_id=risk,
            risk_policy_sha256=content_sha256({"risk": risk}),
            accepted_result_artifact_id=pointer.artifact_id,
            accepted_result_artifact_revision_id=pointer.artifact_revision_id,
            accepted_result_sha256=pointer.sha256,
            state="ACCEPTED",
            lock_version=1,
            created_by_operator_id=actor,
            completed_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return row

    def make(states, *, kinds=None, accepted=False):
        kinds = kinds or ("QUESTION",) * len(states)
        assert len(kinds) == len(states)
        material_id, material_revision_id, run_id = (
            identity("material_"),
            identity("materialrev_"),
            identity("materialrun_"),
        )
        now = datetime.now(UTC)
        claim = store.MaterialRunClaim(
            run_id, "storage-owner-" + uuid4().hex, uuid4().hex, now + timedelta(minutes=10)
        )
        with Session(engine, expire_on_commit=False) as session, session.begin():
            material = LearningMaterialRecord(
                material_id=material_id,
                lifecycle_state="ACTIVE",
                created_by=actor,
            )
            session.add(material)
            session.flush()
            session.add(
                LearningMaterialRevisionRecord(
                    material_revision_id=material_revision_id,
                    material_id=material_id,
                    revision_number=1,
                    title="Synthetic native metadata",
                    material_kind="MOCK_EXAM",
                    request_sha256=content_sha256({"material": material_id}),
                    manifest_artifact_id=pointer.artifact_id,
                    manifest_artifact_revision_id=pointer.artifact_revision_id,
                    manifest_member_path="synthetic-metadata.json",
                    manifest_sha256=pointer.sha256,
                    idempotency_key="storage-material:" + uuid4().hex,
                    created_by=actor,
                )
            )
            session.flush()
            material.current_revision_id = material_revision_id
            session.add(
                MaterialLearningRunRecord(
                    run_id=run_id,
                    material_revision_id=material_revision_id,
                    attempt=1,
                    state="PROCESSING",
                    next_event_sequence=1,
                    created_by=actor,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    lease_expires_at=claim.lease_expires_at,
                )
            )
            session.flush()
            tasks = []
            for ordinal, (state, kind) in enumerate(zip(states, kinds, strict=True), 1):
                task = MaterialLearningTaskRecord(
                    task_id=identity("materialtask_"),
                    run_id=run_id,
                    task_kind=kind,
                    unit_key=f"synthetic:{ordinal}",
                    ordinal=ordinal,
                    attempt=1,
                    state=state,
                    execution_lane="MATERIAL_LEARNING",
                )
                if accepted:
                    item = ItemRecord(
                        item_id=identity("item_"),
                        lifecycle_state="ACTIVE",
                        created_by=actor,
                        lock_version=1,
                    )
                    session.add(item)
                    session.flush()
                    revision = ItemRevisionRecord(
                        item_revision_id=identity("itemrev_"),
                        item_id=item.item_id,
                        revision_number=1,
                        revision_state="APPROVED",
                        registration_key="synthetic-storage:" + uuid4().hex,
                        content_pack_release_id=pack_release,
                        workflow_id=source_workflow,
                        workflow_definition_version="1.0.0",
                        source_workflow_step_run_id=source_step,
                        manifest_artifact_id=pointer.artifact_id,
                        manifest_artifact_revision_id=pointer.artifact_revision_id,
                        manifest_sha256=pointer.sha256,
                        item_type_key="synthetic",
                        metadata_json={"fixture": True},
                        metadata_sha256=pointer.sha256,
                        created_by=actor,
                        approved_by=actor,
                        approved_at=now,
                        lock_version=1,
                    )
                    session.add(revision)
                    session.flush()
                    item.current_revision_id = revision.item_revision_id
                    base = analysis(session, revision)
                    public = analysis(session, revision, base.analysis_run_id)
                    task.item_revision_id, task.analysis_run_id = (
                        revision.item_revision_id,
                        base.analysis_run_id,
                    )
                    task.solution_analysis_run_id = public.analysis_run_id
                session.add(task)
                tasks.append(task)
            session.flush()
            checkpoints = (
                owner._question_graph_checkpoints(session, tuple(tasks)) if accepted else ()
            )
        runs.append(run_id)
        return SimpleNamespace(
            run_id=run_id,
            claim=claim,
            task_ids=tuple(row.task_id for row in tasks),
            checkpoints=checkpoints,
            revision=graph_revision,
        )

    yield SimpleNamespace(engine=engine, owner=owner, make=make, analysis=analysis)
    # Keep immutable synthetic evidence, but never leak runnable runs or the
    # global single-AI lane into later suites in this disposable database.
    with Session(engine) as session, session.begin():
        for run_id in runs:
            run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
            for task in session.scalars(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.run_id == run_id,
                    MaterialLearningTaskRecord.state.in_(("RUNNING", "ANALYZING")),
                )
            ):
                store.transition_material_task(
                    session,
                    run,
                    task,
                    MaterialTaskState.FAILED,
                    now=datetime.now(UTC),
                    error_code="SYNTHETIC_CLEANUP",
                )
            if run.state not in {"COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED"}:
                store.transition_material_run(
                    session, run, MaterialLearningState.CANCELLED, now=datetime.now(UTC)
                )


def states(case, batch):
    with Session(case.engine) as session:
        return tuple(
            (row.state, row.graph_snapshot_revision_id)
            for row in session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.task_id.in_(batch.task_ids))
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )


@pytest.mark.parametrize("count", [1, 25, 26])
def test_original_question_window_is_bounded_at_25_actual_rows(batch_case, count):
    case = batch_case
    batch = case.make(("PUBLISHING",) + ("PENDING",) * (count - 1))
    with Session(case.engine) as session:
        first = session.get(MaterialLearningTaskRecord, batch.task_ids[0])
        window = store.material_question_processing_window(session, first, limit=25)
        assert tuple(row.task_id for row in window) == batch.task_ids[:25]
        assert tuple(row.ordinal for row in window) == tuple(range(1, min(count, 25) + 1))


def test_terminal_questions_consume_window_but_completed_prefix_is_not_resurrected(batch_case):
    case = batch_case
    batch = case.make(("PUBLISHING", "COMPLETED", "FAILED", "EXCEPTION") + ("PENDING",) * 22)
    with Session(case.engine) as session:
        first = session.get(MaterialLearningTaskRecord, batch.task_ids[0])
        window = store.material_question_processing_window(session, first, limit=25)
        assert tuple(row.task_id for row in window) == batch.task_ids[:25]
        first.state = "COMPLETED"
        next_task = session.get(MaterialLearningTaskRecord, batch.task_ids[4])
        remaining = store.material_question_processing_window(session, next_task, limit=25)
        assert tuple(row.task_id for row in remaining) == batch.task_ids[4:]


@pytest.mark.parametrize("barrier_state", ["PENDING", "COMPLETED"])
def test_explanation_is_a_kind_barrier_even_when_terminal(batch_case, barrier_state):
    case = batch_case
    batch = case.make(
        ("PUBLISHING", barrier_state, "PENDING"), kinds=("QUESTION", "EXPLANATION", "QUESTION")
    )
    with Session(case.engine) as session:
        first = session.get(MaterialLearningTaskRecord, batch.task_ids[0])
        assert (
            tuple(
                row.task_id
                for row in store.material_question_processing_window(session, first, limit=25)
            )
            == batch.task_ids[:1]
        )


@pytest.mark.parametrize("count", [1, 25])
def test_batch_links_one_graph_atomically_and_keeps_original_analysis_pins(batch_case, count):
    case = batch_case
    batch = case.make(("PUBLISHING",) * count, accepted=True)
    case.owner._pin_question_graph_batch(batch.claim, batch.checkpoints, batch.revision)
    assert states(case, batch) == (("GRAPH_READY", batch.revision),) * count
    with Session(case.engine) as session:
        rows = tuple(
            session.get(MaterialLearningTaskRecord, identity) for identity in batch.task_ids
        )
        assert case.owner._question_graph_checkpoints(session, rows) == batch.checkpoints
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningEventRecord)
                .where(
                    MaterialLearningEventRecord.run_id == batch.run_id,
                    MaterialLearningEventRecord.new_state == "GRAPH_READY",
                )
            )
            == count
        )


@pytest.mark.parametrize("fault", ["token", "expired", "cancelled"])
def test_stale_claim_or_cancelled_run_cannot_link_any_candidate(batch_case, fault):
    case = batch_case
    batch = case.make(("PUBLISHING",) * 2, accepted=True)
    with Session(case.engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, batch.run_id)
        if fault == "token":
            run.lease_token = uuid4().hex
        elif fault == "expired":
            run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            run.state = "CANCELLED"
            run.lease_owner = run.lease_token = run.lease_expires_at = None
    with pytest.raises(store.MaterialLearningStorageError, match="LEASE_STALE"):
        case.owner._pin_question_graph_batch(batch.claim, batch.checkpoints, batch.revision)
    assert states(case, batch) == (("PUBLISHING", None),) * 2


@pytest.mark.parametrize(
    "fault",
    [
        "base_pin",
        "public_pin",
        "base_sha",
        "public_sha",
        "public_rejected",
        "source_item",
        "task_state",
        "foreign_run",
    ],
)
def test_changed_current_pin_or_admission_rolls_back_the_entire_link(batch_case, fault):
    case = batch_case
    batch = case.make(("PUBLISHING",) * 2, accepted=True)
    checkpoints = batch.checkpoints
    foreign = None
    if fault in {"base_pin", "public_pin"}:
        # Canonical task pins are DB-immutable. Exercise a stale/incorrect
        # captured checkpoint without attempting to rewrite accepted history.
        field = "analysis_run_id" if fault == "base_pin" else "solution_analysis_run_id"
        checkpoints = (
            *checkpoints[:-1],
            replace(checkpoints[-1], **{field: identity("analysisrun_")}),
        )
    elif fault == "foreign_run":
        foreign = case.make(("PUBLISHING",), accepted=True)
        checkpoints = (checkpoints[0], foreign.checkpoints[0])
    else:
        with Session(case.engine) as session, session.begin():
            task = session.get(MaterialLearningTaskRecord, batch.task_ids[-1])
            base = session.get(KnowledgeAnalysisRunRecord, task.analysis_run_id)
            public = session.get(KnowledgeAnalysisRunRecord, task.solution_analysis_run_id)
            if fault in {"base_sha", "public_sha"}:
                target = base if fault == "base_sha" else public
                target.accepted_result_sha256 = content_sha256({"changed": target.analysis_run_id})
            elif fault == "public_rejected":
                public.state = "REJECTED"
                public.accepted_result_artifact_id = public.accepted_result_artifact_revision_id = (
                    None
                )
                public.accepted_result_sha256 = None
            elif fault == "source_item":
                public.item_revision_id = batch.checkpoints[0].item_revision_id
            else:
                task.state = "FAILED"
    before = states(case, batch)
    with pytest.raises(ValueError):
        case.owner._pin_question_graph_batch(batch.claim, checkpoints, batch.revision)
    assert states(case, batch) == before
    assert all(revision is None for _state, revision in before)
    if foreign is not None:
        assert states(case, foreign) == (("PUBLISHING", None),)
    if fault in {"base_pin", "public_pin", "foreign_run"}:
        with Session(case.engine) as session:
            rows = tuple(session.get(MaterialLearningTaskRecord, key) for key in batch.task_ids)
            assert case.owner._question_graph_checkpoints(session, rows) == batch.checkpoints


def test_error_after_second_transition_flush_rolls_back_rows_and_events(batch_case, monkeypatch):
    case = batch_case
    batch = case.make(("PUBLISHING",) * 2, accepted=True)
    original = processing.transition_material_task
    calls = []

    def interrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(args[2].task_id)
        if len(calls) == 2:
            raise RuntimeError("synthetic second-link interruption")
        return result

    monkeypatch.setattr(processing, "transition_material_task", interrupt)
    with pytest.raises(RuntimeError, match="second-link interruption"):
        case.owner._pin_question_graph_batch(batch.claim, batch.checkpoints, batch.revision)
    assert len(calls) == 2 and states(case, batch) == (("PUBLISHING", None),) * 2
    with Session(case.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningEventRecord)
                .where(
                    MaterialLearningEventRecord.run_id == batch.run_id,
                )
            )
            == 0
        )


def test_concurrent_link_has_one_winner_and_no_duplicate_graph_ready_events(batch_case):
    case = batch_case
    batch = case.make(("PUBLISHING",) * 2, accepted=True)
    gate = Barrier(2)

    def link(_number):
        gate.wait(timeout=10)
        try:
            case.owner._pin_question_graph_batch(batch.claim, batch.checkpoints, batch.revision)
            return "PINNED"
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(link, range(2)))
    assert outcomes.count("PINNED") == 1
    assert outcomes.count("MATERIAL_LEARNING_GRAPH_BATCH_PIN_CHANGED") == 1
    assert states(case, batch) == (("GRAPH_READY", batch.revision),) * 2


def test_waiting_publication_does_not_remove_global_one_ai_fence(batch_case):
    case = batch_case
    waiting = case.make(("PUBLISHING", "REGISTERED"))
    other = case.make(("REGISTERED",))
    gate = Barrier(2)

    def admit(batch, task_id):
        gate.wait(timeout=10)
        with Session(case.engine) as session, session.begin():
            run = store.lock_material_run(session, batch.claim, now=datetime.now(UTC))
            task = session.get(MaterialLearningTaskRecord, task_id, with_for_update=True)
            return store.transition_material_task(
                session, run, task, MaterialTaskState.ANALYZING, now=datetime.now(UTC)
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(admit, waiting, waiting.task_ids[1])
        second = pool.submit(admit, other, other.task_ids[0])
        assert sum((first.result(), second.result())) == 1
    assert states(case, waiting)[0] == ("PUBLISHING", None)
    with Session(case.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningTaskRecord)
                .where(
                    MaterialLearningTaskRecord.run_id.in_((waiting.run_id, other.run_id)),
                    MaterialLearningTaskRecord.state.in_(("RUNNING", "ANALYZING")),
                )
            )
            == 1
        )
