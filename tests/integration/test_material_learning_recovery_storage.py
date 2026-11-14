"""Real disposable recovery/lineage; synthetic PDF extractor, no model execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    GetMaterialLearningRunQuery,
    GetMaterialLearningTaskQuery,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_contracts.material_learning_preparation import MaterialPreparationProfile
from eom_catalog_contracts.material_preparation_recovery import RecoverMaterialPreparationCommand
from eom_catalog_service import material_learning_recovery as owner
from eom_catalog_service.educational_material_registration import material_document_identity
from eom_catalog_service.material_intake_read import (
    material_preparation_pointer,
    read_material_preparation,
)
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_models import (
    LearningMaterialRevisionRecord,
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
from eom_catalog_service.material_preparation_recovery import MaterialPreparationRecoveryService
from eom_catalog_service.material_task_history import read_material_task_histories
from eom_identifiers import content_sha256
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
from tests.integration.test_material_native_registration_storage import (
    native_read_case as native_read_case,
)
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

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def failed_preparation(creative_engine, coordinator_case):
    accepted, settings, restart = coordinator_case
    first = restart(InterruptibleExtractor())
    with pytest.raises(RuntimeError, match="synthetic process interruption"):
        first.advance_once()
    with Session(creative_engine) as session:
        run = session.get(MaterialLearningRunRecord, accepted.run_id)
        task = session.scalar(
            select(MaterialLearningTaskRecord).where(
                MaterialLearningTaskRecord.run_id == accepted.run_id
            )
        )
        pointer = material_preparation_pointer(
            session,
            artifact_id=task.input_artifact_id,
            revision_id=task.input_artifact_revision_id,
            sha256=task.input_sha256,
        )
        actor, updated = run.created_by, run.updated_at
    raw = first.coordinator.profile.model_dump(mode="json")
    # This fixture is an identity-PDF source, so its Office profile stays absent.
    raw["source_commit"] = "2" * 40
    raw["profile_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "profile_sha256"})
    target = MaterialPreparationProfile.model_validate(raw)
    drain = SimpleNamespace(require_quiescent=lambda: None)
    service = MaterialPreparationRecoveryService(
        creative_engine,
        settings=settings,
        target_profile=target,
        drain=drain,
    )
    command = RecoverMaterialPreparationCommand(
        actor_id=actor,
        run_id=accepted.run_id,
        expected_updated_at=updated,
        expected_input_sha256=pointer.sha256,
        target_profile_sha256=target.profile_sha256,
        error_code="CREATIVE_PAGE_RENDERER_FAILED",
    )
    old_work = read_material_preparation(service.artifacts, pointer, authorize=lambda: None)
    return SimpleNamespace(
        accepted=accepted,
        settings=settings,
        restart=restart,
        target=target,
        service=service,
        command=command,
        old_pointer=pointer,
        old_work=old_work,
    )


def test_preparation_successor_preserves_failed_input_replays_and_coordinator_uses_new_pin(
    creative_engine, failed_preparation
):
    case = failed_preparation
    result = case.service.recover(case.command)
    assert not result.replayed and result.state == "RECEIVED"
    assert case.service.recover(case.command).replayed
    assert result.old_input == case.old_pointer
    assert result.new_input.sha256 != result.old_input.sha256
    assert (
        read_material_preparation(case.service.artifacts, result.old_input, authorize=lambda: None)
        == case.old_work
    )
    with Session(creative_engine) as session:
        old = session.get(MaterialLearningRunRecord, result.predecessor_run_id)
        new = session.get(MaterialLearningRunRecord, result.run_id)
        task = session.get(MaterialLearningTaskRecord, result.task_id)
        assert old.state == "FAILED" and old.error_code == case.command.error_code
        assert new.attempt == old.attempt + 1
        assert new.material_revision_id == old.material_revision_id
        assert task.attempt == 2 and task.predecessor_task_id == result.predecessor_task_id
        assert task.output_artifact_revision_id is None
        assert len(read_material_task_histories(session, (task,))[task.task_id].tasks) == 2
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    processing = case.restart(extractor)
    # Trusted synthetic runtime composition, not a user-supplied profile override.
    processing.coordinator.profile = case.target
    processing.coordinator.preparation.source_commit = case.target.source_commit
    assert processing.advance_once().phase == "PREPARED"
    replayed = case.service.recover(case.command)
    assert replayed.replayed and replayed.state == "DISCOVERING"
    processing.registration.register_completed.assert_not_called()


def test_concurrent_preparation_recovery_creates_one_successor(creative_engine, failed_preparation):
    case = failed_preparation
    gate = Barrier(2)

    def recover():
        gate.wait(timeout=10)
        return case.service.recover(case.command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _number: recover(), range(2)))
    assert len({result.run_id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(
                    MaterialLearningRunRecord.material_revision_id
                    == results[0].material_revision_id
                )
            )
            == 2
        )


@pytest.mark.parametrize(
    "fault", ["stale", "foreign_actor", "live_lease", "output", "partial_document_job"]
)
def test_preparation_recovery_rejects_unsafe_scope_before_successor(
    creative_engine, failed_preparation, fault
):
    case = failed_preparation
    command = case.command
    if fault == "stale":
        command = command.model_copy(
            update={"expected_updated_at": command.expected_updated_at - timedelta(seconds=1)}
        )
    elif fault == "foreign_actor":
        command = command.model_copy(update={"actor_id": "operator_" + "0" * 32})
    elif fault == "partial_document_job":
        revision_id = material_document_identity(case.accepted.material_revision_id, "MAIN")[1]
        # A conflicting committed/incomplete document job can precede its DB row.
        # Reuse the real Artifact owner to create that occupied publication key.
        publish_material_metadata(
            case.service.artifacts,
            case.settings,
            case.old_work,
            member_path="material/preparation-input.json",
            schema_ref=case.old_pointer.schema_ref,
            artifact_type="material-learning-preparation-input",
            idempotency_key="material-document:" + revision_id,
        )
    else:
        with Session(creative_engine) as session, session.begin():
            run = session.get(MaterialLearningRunRecord, case.accepted.run_id)
            task = session.scalar(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.run_id == run.run_id
                )
            )
            if fault == "live_lease":
                run.lease_owner, run.lease_token = "synthetic-active-owner", "1" * 32
                run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
            else:
                task.output_artifact_id = case.old_pointer.artifact_id
                task.output_artifact_revision_id = case.old_pointer.artifact_revision_id
                task.output_sha256 = case.old_pointer.sha256
    with pytest.raises(ValueError):
        case.service.recover(command)
    with Session(creative_engine) as session:
        run = session.get(MaterialLearningRunRecord, case.accepted.run_id)
        assert run.state == "PREPARING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.material_revision_id == run.material_revision_id)
            )
            == 1
        )


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


@pytest.fixture
def native_visual_retry_case(creative_engine, native_read_case):
    """Real source/rights/Artifacts/Item; preparation and completed AI admission are synthetic."""
    from eom_catalog_contracts.material_native_intake import MaterialNativePreparedArtifact
    from eom_catalog_contracts.material_native_visual_preparation import (
        MaterialNativeVisualPreparedArtifact,
    )
    from eom_catalog_service.material_intake_read import (
        material_intake_pointer,
        read_material_intake,
    )

    from tests.unit.test_material_learning_contracts import rehash
    from tests.unit.test_material_native_visual_preparation import base_prepared, visual_profile

    create, resolved, binding = native_read_case
    registration = create()
    artifacts, settings = registration.artifacts, registration.settings
    item = registration.register_completed(
        task_id=resolved.task_id, operator_id=resolved.operator_id
    )
    with Session(creative_engine) as session:
        revision = session.get(LearningMaterialRevisionRecord, binding.material_revision_id)
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
    intake = read_material_intake(artifacts, intake_pointer, authorize=lambda: None)
    body = base_prepared().model_dump(mode="json")
    body.update(
        material_id=binding.material_id,
        material_revision_id=binding.material_revision_id,
        intake_manifest=intake_pointer.model_dump(mode="json"),
        native_bundle=intake.native_bundle.model_dump(mode="json"),
    )
    for source, selected in zip(body["sources"], intake.sources, strict=True):
        source.update(
            original=selected.source_upload.original.model_dump(mode="json"),
            actual_format=selected.source_upload.source_format,
            original_filename=selected.source_upload.original_filename,
        )
    # The frozen preparation adapter is explicitly synthetic, as in the existing
    # native finalization fixture. No live renderer, model or NAS production tree.
    base = MaterialNativePreparedArtifact.model_validate(rehash(body, "prepared_sha256"))
    base_pointer = publish_material_metadata(
        artifacts,
        settings,
        base,
        member_path="material/prepared.json",
        schema_ref="eom://schemas/material-learning/prepared/2.0",
        artifact_type="material-learning-prepared",
        idempotency_key="native-visual-base:" + uuid4().hex,
    )

    def publish_visual(*, options="3"):
        profile = visual_profile()
        profile["options_sha256"] = "sha256:" + options * 64
        profile = rehash(profile, "profile_sha256")
        value = base.model_dump(mode="json")
        catalog = value["sources"][0]["office_catalog"]
        value.update(
            schema_version="material-learning-prepared/3.0",
            base_prepared=base_pointer.model_dump(mode="json"),
            visual_profile=profile,
            catalog_supplements=[dict(source_role="MAIN", base_catalog=catalog, catalog=catalog)],
            question_visual_scopes=[
                dict(
                    item_number=binding.item_number,
                    question_document=binding.question.document.model_dump(mode="json"),
                    split_evidence=binding.question.split_evidence.model_dump(mode="json"),
                    source_catalog_sha256=catalog["sha256"],
                    allowed_picture_use_ids=[],
                )
            ],
        )
        prepared = MaterialNativeVisualPreparedArtifact.model_validate(
            rehash(value, "prepared_sha256")
        )
        return publish_material_metadata(
            artifacts,
            settings,
            prepared,
            member_path="material/prepared.json",
            schema_ref="eom://schemas/material-learning/prepared/3.0",
            artifact_type="material-learning-prepared",
            idempotency_key="native-visual-target:" + uuid4().hex,
        )

    pointer = publish_visual()
    run_id, prepare_id, failed_id = (
        "materialrun_" + uuid4().hex,
        "materialtask_" + uuid4().hex,
        "materialtask_" + uuid4().hex,
    )
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        session.add(
            MaterialLearningRunRecord(
                run_id=run_id,
                material_revision_id=binding.material_revision_id,
                attempt=1,
                state="COMPLETED_WITH_EXCEPTIONS",
                next_event_sequence=1,
                created_by=resolved.operator_id,
                prepared_artifact_id=base_pointer.artifact_id,
                prepared_artifact_revision_id=base_pointer.artifact_revision_id,
                prepared_sha256=base_pointer.sha256,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add_all(
            [
                MaterialLearningTaskRecord(
                    task_id=prepare_id,
                    run_id=run_id,
                    task_kind="PREPARE",
                    unit_key="source-preparation",
                    ordinal=1,
                    attempt=1,
                    state="COMPLETED",
                    execution_lane="MATERIAL_LEARNING",
                    output_artifact_id=base_pointer.artifact_id,
                    output_artifact_revision_id=base_pointer.artifact_revision_id,
                    output_sha256=base_pointer.sha256,
                ),
                MaterialLearningTaskRecord(
                    task_id=resolved.task_id,
                    run_id=run_id,
                    task_kind="QUESTION",
                    unit_key=resolved.unit_key,
                    ordinal=2,
                    attempt=1,
                    state="COMPLETED",
                    execution_lane="MATERIAL_LEARNING",
                    workflow_id=resolved.selection.workflow_id,
                    input_artifact_id=resolved.work_pointer.artifact_id,
                    input_artifact_revision_id=resolved.work_pointer.artifact_revision_id,
                    input_sha256=resolved.work_pointer.sha256,
                    output_artifact_id=resolved.result_pointer.artifact_id,
                    output_artifact_revision_id=resolved.result_pointer.artifact_revision_id,
                    output_sha256=resolved.result_pointer.sha256,
                    item_revision_id=item.item_revision_id,
                ),
                MaterialLearningTaskRecord(
                    task_id=failed_id,
                    run_id=run_id,
                    task_kind="QUESTION",
                    unit_key="failed-visual-unit",
                    ordinal=3,
                    attempt=1,
                    state="FAILED",
                    execution_lane="MATERIAL_LEARNING",
                    error_code="OFFICE_VISUAL_USE_UNRESOLVED",
                ),
            ]
        )
    command = RetryMaterialLearningRunCommand(
        actor_id=resolved.operator_id, run_id=run_id, expected_updated_at=now
    )
    return SimpleNamespace(
        artifacts=artifacts,
        settings=settings,
        command=command,
        pointer=pointer,
        base=base_pointer,
        source_task=resolved.task_id,
        failed_task=failed_id,
        item=item,
        publish_visual=publish_visual,
        sessions=artifacts.sessions,
    )


def test_native_visual_recovery_concurrent_replay_preserves_real_item_and_failed_history(
    creative_engine, native_visual_retry_case
):
    case = native_visual_retry_case
    barrier = Barrier(2)

    def recover(_):
        barrier.wait(timeout=10)
        return owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(recover, range(2)))
    assert len({value.run_id for value in results}) == 1
    assert sum(not value.replayed for value in results) == 1
    with Session(creative_engine) as session:
        old = session.get(MaterialLearningRunRecord, case.command.run_id)
        new = session.get(MaterialLearningRunRecord, results[0].run_id)
        assert old.prepared_sha256 == case.base.sha256
        assert old.updated_at == case.command.expected_updated_at
        assert new.prepared_sha256 == case.pointer.sha256 and new.attempt == 2
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == new.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert [task.state for task in tasks] == ["COMPLETED", "COMPLETED", "PENDING"]
        assert tasks[1].item_revision_id == case.item.item_revision_id
        assert tasks[1].predecessor_task_id == case.source_task
        assert session.get(MaterialLearningTaskRecord, case.failed_task).state == "FAILED"
        assert (
            read_material_task_histories(session, tasks)[tasks[1].task_id].result_task().task_id
            == case.source_task
        )
    replay = owner.recover_native_material_visuals(
        case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
    )
    assert replay.replayed and replay.run_id == results[0].run_id


def test_native_visual_and_ordinary_retry_share_one_revision_capacity(
    creative_engine, native_visual_retry_case
):
    case = native_visual_retry_case
    barrier = Barrier(2)

    def submit(visual):
        barrier.wait(timeout=10)
        try:
            return (
                owner.recover_native_material_visuals(
                    case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
                )
                if visual
                else owner.retry_material_learning_run(case.sessions, case.command)
            )
        except MaterialLearningSourceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, (False, True)))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "MATERIAL_LEARNING_RETRY_SUPERSEDED" in results
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 1
        )


def test_native_visual_recovery_interruption_rolls_back_and_changed_target_cannot_fork(
    creative_engine, native_visual_retry_case, monkeypatch
):
    case = native_visual_retry_case
    append = owner.append_material_event

    def interrupt(*args, **kwargs):
        append(*args, **kwargs)
        if kwargs["event_type"] == "MATERIAL_TASK_RETRY_CREATED":
            raise RuntimeError("synthetic visual retry interruption")

    with monkeypatch.context() as context:
        context.setattr(owner, "append_material_event", interrupt)
        with pytest.raises(RuntimeError, match="visual retry interruption"):
            owner.recover_native_material_visuals(
                case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
            )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 0
        )
    result = owner.recover_native_material_visuals(
        case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
    )
    changed = case.publish_visual(options="4")
    with pytest.raises(MaterialLearningSourceError, match="RETRY_SUPERSEDED"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=changed, artifacts=case.artifacts
        )
    assert (
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        ).run_id
        == result.run_id
    )


def test_native_visual_recovery_rejects_old_prepared_as_target_without_successor(
    creative_engine, native_visual_retry_case
):
    case = native_visual_retry_case
    with pytest.raises(MaterialLearningSourceError, match="VISUAL_BASE_REQUIRED"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.base, artifacts=case.artifacts
        )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 0
        )
