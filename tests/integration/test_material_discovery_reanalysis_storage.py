"""Real guarded DB retry transactions; discovery/rights IO ports are synthetic.

Source ingestion, approved Artifact metadata fences, task lineage, locking, rollback
and replay are real. No model execution or production source is used here.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand
from eom_catalog_service import material_discovery_reanalysis as owner
from eom_catalog_service.material_intake_read import (
    material_intake_pointer,
    material_prepared_pointer,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_task_history import read_material_task_histories
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_learning_coordinator_storage import (
    coordinator_case as coordinator_case,
)
from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_learning_page_preparation import InterruptibleExtractor
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def completed_discovery(creative_engine, coordinator_case, monkeypatch):
    accepted, settings, restart = coordinator_case
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    assert restart(extractor).advance_once().phase == "PREPARED"
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id)
        revision = session.get(LearningMaterialRevisionRecord, run.material_revision_id)
        rows = list(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert len(rows) == 2
        for ordinal in range(3, 8):
            row = MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid4().hex,
                run_id=run.run_id,
                task_kind="DISCOVER",
                unit_key=f"synthetic-window-{ordinal}",
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
            row.state = "COMPLETED"
            if row.task_kind == "PREPARE":
                continue
            for prefix in ("input", "output"):
                setattr(row, prefix + "_artifact_id", run.prepared_artifact_id)
                setattr(row, prefix + "_artifact_revision_id", run.prepared_artifact_revision_id)
                setattr(row, prefix + "_sha256", run.prepared_sha256)
        run.state, run.error_code = "FAILED", owner._ERROR
        run.updated_at = datetime.now(UTC)
        command = RetryMaterialLearningRunCommand(
            actor_id=run.created_by, run_id=run.run_id, expected_updated_at=run.updated_at
        )
        material_id = revision.material_id
        selected = frozenset({rows[1].task_id, rows[4].task_id})
        original = owner._task_signature(tuple(rows))
    service = owner.NativeMaterialDiscoveryReanalysisService(creative_engine, settings)

    def capture(session, request):
        source, revision = service._source(session, request)
        rows = service._tasks(session, source)
        pointer = material_prepared_pointer(
            session,
            artifact_id=source.prepared_artifact_id,
            revision_id=source.prepared_artifact_revision_id,
            sha256=source.prepared_sha256,
        )
        keys = frozenset({(pointer.artifact_id, pointer.artifact_revision_id)})
        return owner._DiscoveryRetrySnapshot(
            SimpleNamespace(
                material_revision_id=source.material_revision_id, material_id=material_id
            ),
            material_intake_pointer(
                session,
                artifact_id=revision.manifest_artifact_id,
                revision_id=revision.manifest_artifact_revision_id,
                sha256=revision.manifest_sha256,
            ),
            pointer,
            selected,
            owner._task_signature(rows),
            keys,
            owner._artifact_signature(session, keys),
        )

    monkeypatch.setattr(service, "_capture", capture)
    monkeypatch.setattr(service, "_owners", lambda *_args: {})
    monkeypatch.setattr(service, "_reauthorize", lambda *_args: None)
    return SimpleNamespace(
        service=service,
        command=command,
        selected=selected,
        original=original,
        material_id=material_id,
        capture=capture,
    )


def test_selective_retry_preserves_failed_run_and_reuses_five_checkpoints(
    creative_engine, completed_discovery
):
    case = completed_discovery
    result = case.service.try_retry(case.command)
    assert (result.state, result.retried_tasks, result.reused_tasks) == ("DISCOVERING", 2, 5)
    assert not result.replayed
    with Session(creative_engine) as session:
        source = session.get(MaterialLearningRunRecord, case.command.run_id)
        assert (source.state, source.error_code, source.updated_at) == (
            "FAILED",
            owner._ERROR,
            case.command.expected_updated_at,
        )
        originals = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == source.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert owner._task_signature(originals) == case.original
        clones = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == result.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert len(clones) == 7
        histories = read_material_task_histories(session, clones)
        for original, clone in zip(originals, clones, strict=True):
            assert clone.predecessor_task_id == original.task_id
            assert clone.attempt == 2 and clone.workflow_id is None
            assert len(histories[clone.task_id].tasks) == 2
            if original.task_id in case.selected:
                assert clone.state == "PENDING"
                assert clone.input_artifact_revision_id is clone.output_artifact_revision_id is None
            else:
                assert clone.state == "COMPLETED"
                assert clone.output_sha256 == original.output_sha256
    replay = case.service.try_retry(case.command)
    assert replay.replayed and replay.run_id == result.run_id


def test_concurrent_retry_creates_one_successor_and_replay_survives_progress(
    creative_engine, completed_discovery, monkeypatch
):
    case = completed_discovery
    gate = Barrier(2)

    def captured(session, command):
        snapshot = case.capture(session, command)
        gate.wait(timeout=20)
        return snapshot

    monkeypatch.setattr(case.service, "_capture", captured)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: case.service.try_retry(case.command), range(2)))
    assert len({result.run_id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    monkeypatch.setattr(case.service, "_capture", case.capture)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, results[0].run_id)
        run.state = "PROCESSING"
        row = session.scalar(
            select(MaterialLearningTaskRecord)
            .where(
                MaterialLearningTaskRecord.run_id == run.run_id,
                MaterialLearningTaskRecord.state == "PENDING",
            )
            .order_by(MaterialLearningTaskRecord.ordinal)
        )
        row.state = "PREPARING"
        session.add(
            MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid4().hex,
                run_id=run.run_id,
                task_kind="QUESTION",
                unit_key="later-question",
                ordinal=8,
                attempt=1,
                state="PENDING",
                execution_lane="MATERIAL_LEARNING",
            )
        )
    replay = case.service.try_retry(case.command)
    assert replay.replayed and replay.state == "PROCESSING"
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 1
        )


def test_retry_rolls_back_tasks_events_and_run_after_interruption(
    creative_engine, completed_discovery, monkeypatch
):
    case = completed_discovery
    append = owner.append_material_event

    def interrupt(*args, **kwargs):
        append(*args, **kwargs)
        if kwargs["event_type"] == "MATERIAL_TASK_RETRY_CREATED":
            raise RuntimeError("synthetic selective retry interruption")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "append_material_event", interrupt)
        with pytest.raises(RuntimeError, match="selective retry interruption"):
            case.service.try_retry(case.command)
    with Session(creative_engine) as session:
        assert not session.scalar(
            select(MaterialLearningRunRecord.run_id).where(
                MaterialLearningRunRecord.predecessor_run_id == case.command.run_id
            )
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == case.command.run_id)
            )
            == 7
        )
        assert not session.scalar(
            select(MaterialLearningEventRecord.event_id)
            .join(
                MaterialLearningRunRecord,
                MaterialLearningRunRecord.run_id == MaterialLearningEventRecord.run_id,
            )
            .where(
                MaterialLearningRunRecord.material_revision_id
                == session.get(MaterialLearningRunRecord, case.command.run_id).material_revision_id,
                MaterialLearningEventRecord.run_id != case.command.run_id,
                MaterialLearningEventRecord.event_type == "MATERIAL_TASK_RETRY_CREATED",
            )
        )
    assert not case.service.try_retry(case.command).replayed


@pytest.mark.parametrize("fault", ["stale", "retired"])
def test_invalid_scope_cannot_create_retry(creative_engine, completed_discovery, fault):
    case = completed_discovery
    command = case.command
    if fault == "stale":
        command = command.model_copy(
            update={"expected_updated_at": command.expected_updated_at - timedelta(seconds=1)}
        )
    else:
        with Session(creative_engine) as session, session.begin():
            if fault == "retired":
                session.get(LearningMaterialRecord, case.material_id).lifecycle_state = "RETIRED"
    with pytest.raises(MaterialLearningSourceError):
        case.service.try_retry(command)
    with Session(creative_engine) as session:
        assert not session.scalar(
            select(MaterialLearningRunRecord.run_id).where(
                MaterialLearningRunRecord.predecessor_run_id == command.run_id
            )
        )
