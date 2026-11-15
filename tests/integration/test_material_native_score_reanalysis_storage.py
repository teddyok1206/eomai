"""Guarded DB recovery and same-Item Registry transactions, never live model work.

Target eligibility/source-result admission is a declared synthetic port in these
transaction fixtures. Real pointer/score selection is tested separately. Artifact
publication, locking, current-revision CAS, rollback and replay use their owners.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_item_lineage import MaterialItemLineageV4
from eom_catalog_contracts.material_learning_intake import GetMaterialLearningRunQuery
from eom_catalog_contracts.material_native_score_reanalysis import (
    NATIVE_SCORE_REANALYSIS_ARTIFACT,
    NATIVE_SCORE_REANALYSIS_EVENT,
    NATIVE_SCORE_REANALYSIS_REF,
    NativeScoreReanalysisTarget,
    ReanalyzeNativeMaterialScoresCommand,
    native_score_reanalysis_run_id,
    native_score_reanalysis_target_key,
)
from eom_catalog_service import material_native_score_reanalysis as owner
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.material_intake_read import material_prepared_pointer
from eom_catalog_service.material_learning_artifacts import (
    find_material_publication,
    pin_material_primary,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_read import MaterialLearningReadService
from eom_catalog_service.material_task_history import read_material_task_histories
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_coverage_registration_storage import build_family_registration
from tests.integration.test_material_learning_coordinator_storage import (
    coordinator_case as coordinator_case,
)
from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_page_preparation import InterruptibleExtractor
from tests.integration.test_material_native_graph_batch_storage import batch_case as batch_case
from tests.integration.test_material_native_registration_storage import ROOT
from tests.integration.test_material_native_registration_storage import (
    native_registration_case as native_registration_case,
)
from tests.integration.test_material_native_registration_storage import (
    registration_case as registration_case,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls
from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_score_reanalysis import target_data

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def score_recovery(creative_engine, coordinator_case, batch_case, monkeypatch, request):
    options = getattr(request, "param", {})
    accepted, settings, restart = coordinator_case
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    assert restart(extractor).advance_once().phase == "PREPARED"
    publisher = ControlFileSetPublisher(
        creative_engine,
        Settings(staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root),
    )
    service = owner.NativeMaterialScoreReanalysisService(
        creative_engine, settings=settings, publisher=publisher, source_commit="a" * 40
    )
    seeded = batch_case.make(("COMPLETED",), accepted=True) if options.get("analyses") else None
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id)
        revision = session.get(LearningMaterialRevisionRecord, run.material_revision_id)
        material_id = revision.material_id
        if seeded is not None:
            seed = session.get(MaterialLearningTaskRecord, seeded.task_ids[0])
            item = session.get(ItemRevisionRecord, seed.item_revision_id)
            base = batch_case.analysis(session, item, actor_id=run.created_by)
            public = batch_case.analysis(
                session, item, base.analysis_run_id, actor_id=run.created_by
            )
        rows = list(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        for ordinal in range(3, 8):
            row = MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid4().hex,
                run_id=run.run_id,
                task_kind="QUESTION",
                unit_key=f"synthetic-score-question-{ordinal}",
                ordinal=ordinal,
                attempt=1,
                state="COMPLETED",
                execution_lane="MATERIAL_LEARNING",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(row)
            rows.append(row)
        for row in rows:
            if row.task_kind == "PREPARE":
                continue
            row.state = "COMPLETED"
            for prefix in ("input", "output"):
                setattr(row, prefix + "_artifact_id", run.prepared_artifact_id)
                setattr(row, prefix + "_artifact_revision_id", run.prepared_artifact_revision_id)
                setattr(row, prefix + "_sha256", run.prepared_sha256)
        selected_ids = frozenset({rows[2].task_id, rows[4].task_id})
        inherited = None
        if seeded is not None:
            normal = rows[3]
            normal.item_revision_id = item.item_revision_id
            normal.analysis_run_id = base.analysis_run_id
            normal.solution_analysis_run_id = public.analysis_run_id
            normal.graph_snapshot_revision_id = seeded.revision
            inherited = (
                normal.task_id,
                item.item_revision_id,
                base.analysis_run_id,
                public.analysis_run_id,
                seeded.revision,
            )
        run.state = options.get("phase", "COMPLETED")
        if options.get("lease"):
            run.lease_owner = "synthetic-score-owner"
            run.lease_token = uuid4().hex
            run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        session.flush()
        request = ReanalyzeNativeMaterialScoresCommand(
            actor_id=run.created_by,
            run_id=run.run_id,
            expected_updated_at=run.updated_at,
            idempotency_key="synthetic-score-recovery:" + uuid4().hex,
        )
        original = owner.native_score_task_checkpoint_sha256(service._tasks(session, run))

    def capture(session, command):
        source, _ = service._source(session, command)
        tasks = service._tasks(session, source)
        prepared = material_prepared_pointer(
            session,
            artifact_id=source.prepared_artifact_id,
            revision_id=source.prepared_artifact_revision_id,
            sha256=source.prepared_sha256,
        )
        checksum = owner.native_score_task_checkpoint_sha256(tasks)
        targets = []
        for task in tasks:
            if task.task_id not in selected_ids:
                continue
            data = target_data(command)
            data.update(
                material_id=material_id,
                material_revision_id=source.material_revision_id,
                source_task_id=task.task_id,
                unit_key=task.unit_key,
                source_tasks_sha256=checksum,
                prepared=prepared.model_dump(mode="json"),
                prior_item=None,
                reason="LEGACY_SCORE_CONTRACT",
            )
            targets.append(
                NativeScoreReanalysisTarget.model_validate(rehash(data, "target_sha256"))
            )
        return owner._ScoreSnapshot(tuple(targets), checksum, prepared)

    monkeypatch.setattr(service, "_capture", capture)
    monkeypatch.setattr(service, "validate_target", lambda *_a, **_k: None)
    return SimpleNamespace(
        service=service,
        command=request,
        selected=selected_ids,
        original=original,
        capture=capture,
        inherited=inherited,
    )


def test_score_successor_preserves_original_and_replays_after_progress(
    creative_engine, score_recovery
):
    case = score_recovery
    reply = case.service.reanalyze(case.command)
    assert (reply.state, reply.retried_tasks, reply.reused_tasks, reply.replayed) == (
        "PROCESSING",
        2,
        5,
        False,
    )
    with Session(creative_engine) as session, session.begin():
        parent = session.get(MaterialLearningRunRecord, case.command.run_id)
        assert parent.state == "COMPLETED" and parent.updated_at == case.command.expected_updated_at
        assert (
            owner.native_score_task_checkpoint_sha256(case.service._tasks(session, parent))
            == case.original
        )
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.run_id == reply.run_id
                )
            )
        )
        for task in tasks:
            assert task.predecessor_task_id and task.attempt == 2
            if task.predecessor_task_id in case.selected:
                assert task.state == "PENDING"
                assert (
                    task.input_artifact_id
                    is task.output_artifact_id
                    is task.item_revision_id
                    is task.analysis_run_id
                    is task.solution_analysis_run_id
                    is None
                )
                proof = case.service.registration_target(
                    session, task_id=task.task_id, operator_id=case.command.actor_id
                )
                assert proof.target.source_task_id == task.predecessor_task_id
                assert proof.evidence.schema_ref == NATIVE_SCORE_REANALYSIS_REF
                task.state = "PREPARING"
            else:
                assert task.state == "COMPLETED" and task.output_sha256
    replay = case.service.reanalyze(case.command)
    assert replay.replayed and replay.run_id == reply.run_id


@pytest.mark.parametrize("score_recovery", [{"analyses": True}], indirect=True)
def test_concurrent_score_successor_has_one_identity(creative_engine, score_recovery, monkeypatch):
    case = score_recovery
    gate = Barrier(2)

    def capture(session, command):
        snapshot = case.capture(session, command)
        gate.wait(timeout=20)
        return snapshot

    monkeypatch.setattr(case.service, "_capture", capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(pool.map(lambda _: case.service.reanalyze(case.command), range(2)))
    assert len({reply.run_id for reply in replies}) == 1
    assert sum(not reply.replayed for reply in replies) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 1
        )
    _assert_inherited_analyses(creative_engine, case, replies[0].run_id)


def _assert_inherited_analyses(engine, case, successor_id):
    source_id, item_id, base_id, public_id, graph_id = case.inherited
    with Session(engine) as session:
        clone = session.scalar(
            select(MaterialLearningTaskRecord).where(
                MaterialLearningTaskRecord.run_id == successor_id,
                MaterialLearningTaskRecord.predecessor_task_id == source_id,
            )
        )
        assert clone.state == "COMPLETED"
        assert clone.item_revision_id == item_id and clone.graph_snapshot_revision_id == graph_id
        assert clone.analysis_run_id is None and clone.solution_analysis_run_id is None
        history = read_material_task_histories(session, (clone,))[clone.task_id]
        assert history.analysis_owner().analysis_run_id == base_id
        assert history.analysis_owner(solution=True).solution_analysis_run_id == public_id
        assert session.get(KnowledgeAnalysisRunRecord, base_id).state == "ACCEPTED"
        assert session.get(KnowledgeAnalysisRunRecord, public_id).state == "ACCEPTED"
    detail = MaterialLearningReadService(engine, case.service.settings).inspect(
        GetMaterialLearningRunQuery(actor_id=case.command.actor_id, run_id=successor_id)
    )
    assert (
        next(row for row in detail.tasks if row.item_revision_id == item_id).analysis_run_id
        == base_id
    )


@pytest.mark.parametrize("score_recovery", [{"analyses": True}], indirect=True)
def test_completed_analyses_are_reused_through_history_not_duplicated(
    creative_engine, score_recovery
):
    case = score_recovery
    with Session(creative_engine) as session:
        count = session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord))
    result = case.service.reanalyze(case.command)
    _assert_inherited_analyses(creative_engine, case, result.run_id)
    assert case.service.reanalyze(case.command).replayed
    with Session(creative_engine) as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord)) == count


def test_score_transaction_interruption_keeps_proof_and_rolls_back_linked_rows(
    creative_engine, score_recovery, monkeypatch
):
    case = score_recovery
    append = owner.append_material_event

    def interrupt(*args, **kwargs):
        append(*args, **kwargs)
        if kwargs["event_type"] == owner._TARGET_EVENT:
            raise RuntimeError("synthetic score transaction interruption")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "append_material_event", interrupt)
        with pytest.raises(RuntimeError, match="score transaction interruption"):
            case.service.reanalyze(case.command)
    with Session(creative_engine) as session:
        assert (
            session.get(MaterialLearningRunRecord, native_score_reanalysis_run_id(case.command))
            is None
        )
        assert not session.scalar(
            select(MaterialLearningEventRecord.event_id).where(
                MaterialLearningEventRecord.event_type == NATIVE_SCORE_REANALYSIS_EVENT,
                MaterialLearningEventRecord.run_id == native_score_reanalysis_run_id(case.command),
            )
        )
    # An installed SDK fix must reuse the first successful proof publication,
    # not replace its source provenance or conflict on the same idempotency key.
    case.service.source_commit = "b" * 40
    assert case.service.reanalyze(case.command).retried_tasks == 2


@pytest.mark.parametrize(
    "score_recovery,fault",
    [
        ({"phase": "PAUSED"}, "phase"),
        ({"lease": True}, "lease"),
        ({}, "epoch"),
        ({}, "owner"),
        ({}, "retired"),
    ],
    indirect=["score_recovery"],
)
def test_unsafe_score_source_never_creates_successor(creative_engine, score_recovery, fault):
    case = score_recovery
    request = case.command
    with Session(creative_engine) as session, session.begin():
        if fault == "epoch":
            request = request.model_copy(update={"expected_updated_at": datetime.now(UTC)})
        elif fault == "owner":
            request = request.model_copy(update={"actor_id": "operator_" + "0" * 32})
        elif fault == "retired":
            session.get(
                LearningMaterialRecord, case.capture(session, request).targets[0].material_id
            ).lifecycle_state = "RETIRED"
    with pytest.raises((ValueError, PermissionError)):
        case.service.reanalyze(request)
    with Session(creative_engine) as session:
        assert (
            session.get(MaterialLearningRunRecord, native_score_reanalysis_run_id(request)) is None
        )


def test_missing_score_proof_is_not_latest_fallback(score_recovery, monkeypatch):
    case = score_recovery
    reply = case.service.reanalyze(case.command)
    monkeypatch.setattr(owner, "find_material_publication", lambda *_a, **_k: None)
    with case.service.sessions() as session:
        task = session.scalar(
            select(MaterialLearningTaskRecord).where(
                MaterialLearningTaskRecord.run_id == reply.run_id,
                MaterialLearningTaskRecord.state == "PENDING",
            )
        )
        with pytest.raises(ValueError, match="TARGET_MISSING"):
            case.service.registration_target(
                session, task_id=task.task_id, operator_id=case.command.actor_id
            )


@pytest.mark.parametrize(
    "native_registration_case", [{"native_printed_points": "1.5"}], indirect=True
)
@pytest.mark.parametrize("delivery", ["concurrent", "post_commit_interruption"])
def test_fresh_exact_result_revises_same_item_preserves_source_and_replays(
    creative_engine, native_registration_case, registration_case, tmp_path, monkeypatch, delivery
):
    create_old, old, binding = native_registration_case
    old_service = create_old()
    prior = old_service.register_completed(task_id=old.task_id, operator_id=old.operator_id)
    create_new, current = build_family_registration(
        creative_engine, registration_case, tmp_path, monkeypatch, family=3, points="1.5"
    )
    pack_service = ContentPackService(creative_engine, old_service.settings)
    pack = pack_service.release(
        pack_service.import_source(
            ROOT / "content/packs/uploaded-material-item/1.5.0"
        ).content_pack_release_id,
        actor_id=old.operator_id,
    )
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, prior.item_revision_id)
        component = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == prior.item_revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
            )
        )
        data = target_data(
            ReanalyzeNativeMaterialScoresCommand(
                actor_id=old.operator_id,
                run_id="materialrun_" + uuid4().hex,
                expected_updated_at=datetime.now(UTC),
                idempotency_key="synthetic-registry-score:" + uuid4().hex,
            )
        )
        data.update(
            material_id=old.work.material_id,
            material_revision_id=old.work.material_revision_id,
            source_task_id=old.task_id,
            unit_key=old.unit_key,
            native_binding_sha256=binding.binding_sha256,
            question=binding.question.document.model_dump(mode="json"),
            source_work=old.work_pointer.model_dump(mode="json"),
            source_result=old.result_pointer.model_dump(mode="json"),
        )
        data["prior_item"].update(
            item_id=prior.item_id,
            item_revision_id=prior.item_revision_id,
            manifest_sha256=revision.manifest_sha256,
            points=old_service.registry.load_item_content(prior.item_revision_id).score.points,
            content=dict(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path=component.logical_name,
                schema_ref=component.schema_ref,
                media_type=component.media_type,
                sha256=component.sha256,
            ),
        )
    target = NativeScoreReanalysisTarget.model_validate(rehash(data, "target_sha256"))
    old_service.score_reanalysis._publish(target)
    pointer = find_material_publication(
        old_service.publisher,
        idempotency_key=native_score_reanalysis_target_key(
            target.successor_run_id, target.source_task_id
        ),
        artifact_type=NATIVE_SCORE_REANALYSIS_ARTIFACT,
    )
    with Session(creative_engine) as session:
        proof = owner.ResolvedNativeScoreTarget(
            target, pin_material_primary(session, pointer).pointer
        )

    def create():
        service = create_new()
        service.native_exact_score_pack_release_id = pack.content_pack_release_id
        monkeypatch.setattr(service, "_verify_native_visual_scope", lambda *_a, **_k: None)
        monkeypatch.setattr(
            service.score_reanalysis, "registration_target", lambda *_a, **_k: proof
        )
        monkeypatch.setattr(service.score_reanalysis, "validate_target", lambda *_a, **_k: None)
        return service

    if delivery == "concurrent":
        gate = Barrier(2)

        def register(_):
            service = create()
            gate.wait(timeout=15)
            return service.register_completed(
                task_id=current.task_id, operator_id=current.operator_id
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(register, range(2))
        assert first.item_id == second.item_id == prior.item_id
        assert first.item_revision_id == second.item_revision_id != prior.item_revision_id
        assert sum((first.created, second.created)) == 1
    else:
        service = create()
        commit = service.registry.register

        def interrupt(command):
            commit(command)
            raise RuntimeError("synthetic corrected Item post-commit interruption")

        service.registry.register = interrupt
        with pytest.raises(RuntimeError, match="corrected Item post-commit interruption"):
            service.register_completed(task_id=current.task_id, operator_id=current.operator_id)
        first = create().register_completed(
            task_id=current.task_id, operator_id=current.operator_id
        )
        assert not first.created and first.item_id == prior.item_id
    assert isinstance(first.lineage, MaterialItemLineageV4)
    assert first.lineage.native_score_reanalysis == proof.evidence
    service = create()
    assert service.registry.load_item_content(first.item_revision_id).score.points == "1.5"
    assert service.registry.load_item_content(prior.item_revision_id).score.points != "1.5"
    assert not service.register_completed(
        task_id=current.task_id, operator_id=current.operator_id
    ).created
    with Session(creative_engine) as session:
        old_revision = session.get(ItemRevisionRecord, prior.item_revision_id)
        assert old_revision.revision_state == "SUPERSEDED"
        assert old_revision.superseded_by_revision_id == first.item_revision_id
        assert session.get(ItemRecord, prior.item_id).current_revision_id == first.item_revision_id
        rows = tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == first.item_revision_id
                )
            )
        )
        assert len(rows) == 6
        for ordinal, source in enumerate((binding.question, binding.solution)):
            actual = next(
                row for row in rows if row.component_type == "OTHER" and row.ordinal == ordinal
            )
            assert (actual.artifact_id, actual.artifact_revision_id, actual.sha256) == (
                source.document.artifact_id,
                source.document.artifact_revision_id,
                source.document.sha256,
            )


def test_configured_successor_blocks_new_legacy_native_writes_not_old_replay(
    native_registration_case,
):
    create, resolved, _binding = native_registration_case
    service = create()
    service.native_exact_score_pack_release_id = "explicitly-configured-successor"
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_SCORE_REANALYSIS_REQUIRED"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    service.native_exact_score_pack_release_id = None
    prior = service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    service.native_exact_score_pack_release_id = "explicitly-configured-successor"
    replay = service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert replay.item_revision_id == prior.item_revision_id and not replay.created
