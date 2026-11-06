"""Real disposable recovery/lineage; synthetic PDF extractor, no model execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    GetMaterialLearningRunQuery,
    GetMaterialLearningTaskQuery,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_service import material_learning_recovery as owner
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_read import MaterialLearningReadService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
)
from eom_catalog_service.material_learning_store import (
    transition_material_run,
    transition_material_task,
)
from eom_catalog_service.material_task_history import read_material_task_histories
from eom_textbook_analysis.bundle import PdfInspection
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from eom_workflow_runner.models import WorkflowCommandRecord
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
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
def failed_discovery(creative_engine, coordinator_case):
    accepted, settings, restart = coordinator_case
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    processing = restart(extractor)
    assert processing.advance_once().phase == "PREPARED"
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, accepted.run_id, with_for_update=True)
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        for task in tasks:
            if task.task_kind == "DISCOVER":
                for state in (
                    MaterialTaskState.PREPARING,
                    MaterialTaskState.READY,
                    MaterialTaskState.RUNNING,
                    MaterialTaskState.FAILED,
                ):
                    assert transition_material_task(
                        session,
                        run,
                        task,
                        state,
                        now=datetime.now(UTC),
                        error_code="SYNTHETIC_WORKER_FAILURE"
                        if state == MaterialTaskState.FAILED
                        else None,
                    )
        transition_material_run(
            session,
            run,
            MaterialLearningState.FAILED,
            now=datetime.now(UTC),
            error_code="MATERIAL_LEARNING_DISCOVERY_INCOMPLETE",
        )
        command = RetryMaterialLearningRunCommand(
            actor_id=run.created_by, run_id=run.run_id, expected_updated_at=run.updated_at
        )
        prepared = run.prepared_artifact_revision_id, run.prepared_sha256
        command_count = session.scalar(select(func.count()).select_from(WorkflowCommandRecord))
    return command, settings, processing, prepared, command_count


def test_concurrent_retry_keeps_failed_history_and_reuses_prepared_input(
    creative_engine, failed_discovery
):
    command, settings, processing, prepared, commands = failed_discovery
    barrier = Barrier(2)

    def retry(_):
        barrier.wait(timeout=10)
        return MaterialLearningIntakeService(creative_engine, settings).retry(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(retry, range(2)))
    assert len({row.run_id for row in results}) == 1
    assert sum(not row.replayed for row in results) == 1
    result = results[0]
    assert (
        result.run_id != command.run_id and result.retried_tasks == 1 and result.reused_tasks == 1
    )
    with Session(creative_engine) as session:
        original = session.get(MaterialLearningRunRecord, command.run_id)
        successor = session.get(MaterialLearningRunRecord, result.run_id)
        assert original.state == "FAILED" and original.updated_at == command.expected_updated_at
        assert successor.predecessor_run_id == original.run_id and successor.attempt == 2
        assert (successor.prepared_artifact_revision_id, successor.prepared_sha256) == prepared
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == result.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert [row.state for row in tasks] == ["COMPLETED", "PENDING"]
        assert all(row.workflow_id is None and row.analysis_run_id is None for row in tasks)
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == commands
        queries = []

        def count_history_query(_connection, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)

        event.listen(creative_engine, "before_cursor_execute", count_history_query)
        try:
            histories = read_material_task_histories(session, tasks)
        finally:
            event.remove(creative_engine, "before_cursor_execute", count_history_query)
        assert len(queries) == 1 and "WITH RECURSIVE" in queries[0]
        assert histories[tasks[1].task_id].tasks[-1].state == "FAILED"
    # No re-conversion or worker: the next action builds only the original
    # discovery window's new input, under the successor's exact task ID.
    advanced = processing.advance_once()
    assert advanced.run_id == result.run_id and advanced.phase == "READY"
    reads = MaterialLearningReadService(creative_engine, settings)
    detail = reads.task(
        GetMaterialLearningTaskQuery(
            actor_id=command.actor_id, run_id=result.run_id, task_id=advanced.task_id
        )
    )
    assert [page.physical_page for page in detail.source_pages] == [1, 2, 3]
    assert {page.original_filename for page in detail.source_pages} == {"test.pdf"}
    assert detail.attempt == 2 and detail.predecessor_task_id is not None
    assert (
        reads.inspect(
            GetMaterialLearningRunQuery(actor_id=command.actor_id, run_id=result.run_id)
        ).run.state
        == "DISCOVERING"
    )
    assert MaterialLearningIntakeService(creative_engine, settings).retry(command).replayed
    with pytest.raises(MaterialLearningSourceError, match="TASK_NOT_FOUND"):
        reads.task(
            GetMaterialLearningTaskQuery(
                actor_id=command.actor_id, run_id=command.run_id, task_id=advanced.task_id
            )
        )


def test_retry_rollback_and_stale_observation_do_not_create_another_run(
    creative_engine, failed_discovery, monkeypatch
):
    command, settings, _processing, _prepared, _commands = failed_discovery
    service = MaterialLearningIntakeService(creative_engine, settings)
    with pytest.raises(MaterialLearningSourceError, match="STATE_STALE"):
        service.retry(
            command.model_copy(
                update={"expected_updated_at": command.expected_updated_at + timedelta(seconds=1)}
            )
        )
    append = owner.append_material_event

    def interrupt(*args, **kwargs):
        append(*args, **kwargs)
        if kwargs["event_type"] == "MATERIAL_TASK_RETRY_CREATED":
            raise RuntimeError("synthetic retry interruption")

    with monkeypatch.context() as context:
        context.setattr(owner, "append_material_event", interrupt)
        with pytest.raises(RuntimeError, match="retry interruption"):
            service.retry(command)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == command.run_id)
            )
            == 0
        )
    result = service.retry(command)
    assert service.retry(command).run_id == result.run_id


def test_inherited_task_cannot_resolve_another_unit(creative_engine, failed_discovery):
    command, settings, _processing, _prepared, _commands = failed_discovery
    result = MaterialLearningIntakeService(creative_engine, settings).retry(command)
    # Existing history cannot be redirected even by a faulty application write.
    with Session(creative_engine) as session:
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == result.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        wrong = tasks[0].predecessor_task_id
        target = tasks[1].task_id
    with (
        pytest.raises(IntegrityError, match="HISTORY_IMMUTABLE"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        task = session.get(MaterialLearningTaskRecord, target)
        task.predecessor_task_id = wrong
        session.flush()
    # A newly inserted, forged cross-unit reference also fails the read boundary.
    forged_id = "materialtask_" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        session.add(
            MaterialLearningTaskRecord(
                task_id=forged_id,
                run_id=result.run_id,
                task_kind="DISCOVER",
                unit_key="forged-source-unit",
                ordinal=99,
                attempt=2,
                predecessor_task_id=wrong,
                state="PENDING",
                execution_lane="MATERIAL_LEARNING",
            )
        )
    with Session(creative_engine) as session:
        task = session.get(MaterialLearningTaskRecord, forged_id)
        with pytest.raises(ValueError, match="HISTORY_SOURCE_MISMATCH"):
            read_material_task_histories(session, (task,))


@pytest.mark.parametrize(
    "page_count,encrypted,code",
    [
        (3, True, "MATERIAL_LEARNING_PDF_ENCRYPTED"),
        (2001, False, "MATERIAL_LEARNING_SOURCE_PAGE_LIMIT"),
    ],
)
def test_unprocessable_source_is_terminal_without_blocking_next_material(
    creative_engine,
    coordinator_case,
    material_intake,
    page_count,
    encrypted,
    code,
):
    accepted, settings, restart = coordinator_case
    bad = InterruptibleExtractor()
    bad.inspect = lambda _path: PdfInspection(page_count=page_count, encrypted=encrypted)
    result = restart(bad).advance_once()
    assert result.run_id == accepted.run_id and result.phase == "FAILED"
    with Session(creative_engine) as session:
        original = session.get(MaterialLearningRunRecord, accepted.run_id)
        assert original.state == "FAILED" and original.error_code == code
        assert original.lease_owner is None
    actor, _settings, path, source_command = material_intake
    receipt = MaterialLearningSourceService(creative_engine, settings).ingest(path, source_command)
    next_material = MaterialLearningIntakeService(creative_engine, settings).create(
        CreateMaterialLearningCommand.model_validate(
            dict(
                actor_id=actor,
                idempotency_key="next-material:" + uuid4().hex,
                upload=dict(
                    title="Next readable fixture",
                    material_kind="WORKBOOK",
                    source_description="disposable recovery fixture",
                    additional_instructions="",
                    curriculum_unit_hints=[],
                    rights_confirmed=True,
                ),
                sources=[dict(source_role="MAIN", source_upload=receipt.model_dump(mode="json"))],
            )
        )
    )
    valid = InterruptibleExtractor()
    valid.interrupt = False
    advanced = restart(valid).advance_once()
    assert advanced.run_id == next_material.run_id and advanced.phase == "PREPARED"
    with Session(creative_engine) as session:
        assert session.get(MaterialLearningRunRecord, accepted.run_id).error_code == code
