"""Visual recovery shares retry locking/cloning with explicit synthetic read ports."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import NAMESPACE_URL, uuid5

import pytest
from eom_catalog_contracts.material_learning import (
    PERMITTED_USES,
    MaterialArtifactMember,
    MaterialLearningRights,
)
from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_service import material_learning_recovery as owner
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_task_history import MaterialTaskHistory
from eom_identifiers import canonical_json_bytes, content_sha256

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_intake import native_exam_bundle, native_intake
from tests.unit.test_material_native_visual_preparation import base_prepared, visual_prepared


def checkpoint_case(monkeypatch):
    intake = MaterialNativeLearningIntakeManifest.model_validate(native_intake())
    bundle = MaterialNativeExamBundle.model_validate(native_exam_bundle())
    data = base_prepared().model_dump(mode="json")
    for source, selected in zip(data["sources"], intake.sources, strict=True):
        source["original"] = selected.source_upload.original.model_dump(mode="json")
    base = MaterialNativePreparedArtifact.model_validate(rehash(data, "prepared_sha256"))
    data = visual_prepared()
    base_pointer = MaterialArtifactMember.model_validate(
        {
            **data["base_prepared"],
            "sha256": content_sha256(base.model_dump(mode="json")),
            "bytes": len(canonical_json_bytes(base.model_dump(mode="json"))),
        }
    )
    data.update(
        sources=base.model_dump(mode="json")["sources"],
        base_prepared=base_pointer.model_dump(mode="json"),
    )
    data["question_visual_scopes"][0].update(
        question_document=bundle.items[0].question.document.model_dump(mode="json"),
        split_evidence=bundle.items[0].question.split_evidence.model_dump(mode="json"),
    )
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(rehash(data, "prepared_sha256"))
    pointer = base_pointer.model_copy(
        update={
            "artifact_id": "artifact_" + "9" * 32,
            "artifact_revision_id": "rev_" + "9" * 32,
            "schema_ref": "eom://schemas/material-learning/prepared/3.0",
            "sha256": content_sha256(prepared.model_dump(mode="json")),
            "bytes": len(canonical_json_bytes(prepared.model_dump(mode="json"))),
        }
    )
    source = MaterialLearningRunRecord(
        run_id="materialrun_" + "7" * 32,
        material_revision_id=base.material_revision_id,
        prepared_artifact_id=base_pointer.artifact_id,
        prepared_artifact_revision_id=base_pointer.artifact_revision_id,
        prepared_sha256=base_pointer.sha256,
    )
    revision = LearningMaterialRevisionRecord(
        material_id=base.material_id,
        material_revision_id=base.material_revision_id,
        manifest_artifact_id=base.intake_manifest.artifact_id,
        manifest_artifact_revision_id=base.intake_manifest.artifact_revision_id,
        manifest_sha256=base.intake_manifest.sha256,
    )
    material = LearningMaterialRecord(
        material_id=base.material_id,
        current_revision_id=base.material_revision_id,
        created_by=ACTOR,
        lifecycle_state="ACTIVE",
    )
    engine = object()
    session = SimpleNamespace(get_bind=lambda: engine, get=lambda *a, **k: material)
    artifacts = SimpleNamespace(engine=engine, settings=object())
    pointers = {
        base_pointer.artifact_revision_id: base_pointer,
        pointer.artifact_revision_id: pointer,
    }
    monkeypatch.setattr(
        owner, "material_prepared_pointer", lambda _s, **kw: pointers[kw["revision_id"]]
    )
    monkeypatch.setattr(owner, "material_intake_pointer", lambda *a, **k: base.intake_manifest)
    monkeypatch.setattr(
        owner, "read_material_prepared", lambda _a, p, **k: base if p == base_pointer else prepared
    )
    monkeypatch.setattr(owner, "read_material_intake", lambda *a, **k: intake)
    monkeypatch.setattr(owner, "read_material_native_bundle", Mock(return_value=bundle))
    sources = Mock()
    monkeypatch.setattr(owner, "MaterialLearningSourceService", Mock(return_value=sources))
    rights = MaterialLearningRights.model_validate(
        rehash(
            dict(
                schema_version="material-learning-rights/1.0",
                material_id=base.material_id,
                material_revision_id=base.material_revision_id,
                attested_by=ACTOR,
                attested_at="2026-11-14T00:00:00Z",
                basis="UPLOADER_ATTESTED_INTERNAL_PROCESSING",
                source_hashes=tuple(
                    entry.source_upload.original.sha256 for entry in intake.sources
                ),
                permitted_uses=tuple(PERMITTED_USES),
                public_redistribution_permitted=False,
                withdrawal_policy="DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT",
            ),
            "attestation_sha256",
        )
    )
    monkeypatch.setattr(owner, "read_material_metadata", lambda *a, **k: rights)
    authorize = Mock()
    monkeypatch.setattr(owner, "authorize_material_learning", authorize)
    return SimpleNamespace(
        source=source,
        revision=revision,
        base=base,
        prepared=prepared,
        pointer=pointer,
        base_pointer=base_pointer,
        intake=intake,
        session=session,
        artifacts=artifacts,
        sources=sources,
        authorize=authorize,
        rights=rights,
        bundle=bundle,
        target=owner._NativeVisualPreparedTarget(pointer, artifacts),
    )


def test_native_checkpoint_reads_exact_new_base_intake_and_reauthorizes_real_sources(monkeypatch):
    case = checkpoint_case(monkeypatch)
    assert (
        owner._native_visual_checkpoint(
            case.session, case.source, case.revision, ACTOR, case.target
        )
        == case.prepared
    )
    assert case.source.prepared_sha256 == case.base_pointer.sha256
    assert case.sources.resolve.call_count == 2
    assert owner.read_material_native_bundle.call_args.kwargs["operator_id"] == ACTOR
    assert owner.read_material_native_bundle.call_args.kwargs["sources"] == case.intake.sources
    for call, source in zip(case.sources.resolve.call_args_list, case.intake.sources, strict=True):
        assert call.args == (source.source_upload,)
        assert call.kwargs == {"operator_id": ACTOR}


@pytest.mark.parametrize(
    "fault,code",
    (
        ("foreign_storage", "STORAGE_SCOPE_INVALID"),
        ("retired", "RUN_NOT_FOUND"),
        ("missing_base", "BASE_REQUIRED"),
        ("base_v1", "BASE_REQUIRED"),
        ("pointer_bytes", "PREPARED_POINTER_INVALID"),
        ("wrong_base", "PREPARED_BASE_MISMATCH"),
        ("other_actor", "INTAKE_REQUIRED"),
        ("source_changed", "SOURCE_MISMATCH"),
        ("rights_changed", "RIGHTS_MISMATCH"),
        ("revoked", "PERMISSION_DENIED"),
        ("hash", "CHECKPOINT_POINTER_INVALID"),
        ("wrong_native_file", "BUNDLE_SCOPE_MISMATCH"),
    ),
)
def test_native_checkpoint_never_falls_back_or_ignores_authority(monkeypatch, fault, code):
    case = checkpoint_case(monkeypatch)
    actor, target = ACTOR, case.target
    if fault == "foreign_storage":
        case.artifacts.engine = object()
    elif fault == "retired":
        case.session.get = lambda *a, **k: None
    elif fault == "missing_base":
        case.source.prepared_artifact_id = None
    elif fault == "base_v1":
        monkeypatch.setattr(owner, "read_material_prepared", lambda *a, **k: object())
    elif fault == "pointer_bytes":
        target = owner._NativeVisualPreparedTarget(
            case.pointer.model_copy(update={"bytes": case.pointer.bytes + 1}), case.artifacts
        )
    elif fault == "wrong_base":
        changed = case.prepared.model_copy(
            update={
                "base_prepared": case.base_pointer.model_copy(
                    update={"sha256": "sha256:" + "f" * 64}
                )
            }
        )
        monkeypatch.setattr(
            owner,
            "read_material_prepared",
            lambda _a, p, **k: case.base if p == case.base_pointer else changed,
        )
    elif fault == "other_actor":
        altered = case.intake.model_copy(update={"requested_by": "operator_" + "0" * 32})
        monkeypatch.setattr(owner, "read_material_intake", lambda *a, **k: altered)
    elif fault == "source_changed":
        altered = deepcopy(case.base.model_dump(mode="json"))
        altered["sources"][0]["original"]["artifact_revision_id"] = "rev_" + "f" * 32
        changed_base = MaterialNativePreparedArtifact.model_validate(
            rehash(altered, "prepared_sha256")
        )
        # The real pure base comparison is separately tested; isolate this source join guard.
        monkeypatch.setattr(owner, "require_native_visual_prepared_base", lambda *a, **k: None)
        monkeypatch.setattr(
            owner,
            "read_material_prepared",
            lambda _a, p, **k: changed_base if p == case.base_pointer else case.prepared,
        )
    elif fault == "rights_changed":
        rights = case.rights.model_copy(update={"source_hashes": ("sha256:" + "f" * 64,)})
        monkeypatch.setattr(owner, "read_material_metadata", lambda *a, **k: rights)
    elif fault == "revoked":
        case.sources.resolve.side_effect = MaterialLearningSourceError(
            "MATERIAL_LEARNING_PERMISSION_DENIED"
        )
    elif fault == "wrong_native_file":
        scope = case.prepared.question_visual_scopes[0]
        changed = case.prepared.model_copy(
            update={
                "question_visual_scopes": (
                    scope.model_copy(
                        update={
                            "question_document": scope.question_document.model_copy(
                                update={"artifact_revision_id": "rev_" + "0" * 32}
                            )
                        }
                    ),
                )
            }
        )
        monkeypatch.setattr(
            owner,
            "read_material_prepared",
            lambda _a, p, **k: case.base if p == case.base_pointer else changed,
        )
    else:

        def deny(*args, **kwargs):
            raise ValueError("MATERIAL_LEARNING_CHECKPOINT_POINTER_INVALID")

        monkeypatch.setattr(owner, "material_prepared_pointer", deny)
    with pytest.raises(ValueError, match=code):
        owner._native_visual_checkpoint(case.session, case.source, case.revision, actor, target)


def retry_case(monkeypatch):
    case = checkpoint_case(monkeypatch)
    now = datetime(2026, 11, 14, tzinfo=UTC)
    case.source.created_by, case.revision.created_by = ACTOR, ACTOR
    case.source.state, case.source.attempt, case.source.updated_at = (
        "COMPLETED_WITH_EXCEPTIONS",
        1,
        now,
    )
    tasks = tuple(
        MaterialLearningTaskRecord(
            task_id="materialtask_" + str(index) * 32,
            run_id=case.source.run_id,
            task_kind=kind,
            unit_key="unit-" + str(index),
            ordinal=index,
            attempt=1,
            state=state,
            execution_lane="MATERIAL_LEARNING",
            input_artifact_id=case.base_pointer.artifact_id,
            input_artifact_revision_id=case.base_pointer.artifact_revision_id,
            input_sha256=case.base_pointer.sha256,
            output_artifact_id=case.base_pointer.artifact_id if state == "COMPLETED" else None,
            output_artifact_revision_id=case.base_pointer.artifact_revision_id
            if state == "COMPLETED"
            else None,
            output_sha256=case.base_pointer.sha256 if state == "COMPLETED" else None,
            item_revision_id="itemrev_" + "b" * 32 if index == 2 else None,
            graph_snapshot_revision_id="graphrev_" + "c" * 32 if index == 2 else None,
            analysis_run_id="analysisrun_" + "d" * 32 if index == 2 else None,
            solution_analysis_run_id="analysisrun_" + "e" * 32 if index == 2 else None,
        )
        for index, kind, state in (
            (1, "PREPARE", "COMPLETED"),
            (2, "QUESTION", "COMPLETED"),
            (3, "QUESTION", "FAILED"),
        )
    )
    records, added, locks = {case.source.run_id: case.source}, [], []
    old_get = case.session.get
    case.session.get = lambda model, key, **kw: (
        records.get(key) if model is MaterialLearningRunRecord else old_get(model, key, **kw)
    )

    def scalar(query):
        entity, name = query.column_descriptions[0]["entity"], query.column_descriptions[0]["name"]
        if entity is LearningMaterialRevisionRecord:
            locks.append("revision")
            return case.revision
        if name == "run_id":
            return None
        locks.append("run")
        return case.source

    def add(record):
        added.append(record)
        if isinstance(record, MaterialLearningRunRecord):
            records[record.run_id] = record

    case.session.scalar, case.session.scalars = scalar, lambda query: tasks
    case.session.add, case.session.add_all = add, lambda values: added.extend(values)
    case.session.flush = lambda: None
    monkeypatch.setattr(owner, "append_material_event", Mock())
    monkeypatch.setattr(owner, "_native_visual_checkpoint", Mock(return_value=case.prepared))
    monkeypatch.setattr(owner, "_quiescent_failed_workflows", Mock(return_value={}))
    monkeypatch.setattr(
        owner,
        "read_material_task_histories",
        lambda _s, rows: {row.task_id: MaterialTaskHistory((row,)) for row in rows},
    )
    case.sessions = SimpleNamespace(begin=lambda: nullcontext(case.session))
    case.command = RetryMaterialLearningRunCommand(
        actor_id=ACTOR, run_id=case.source.run_id, expected_updated_at=now
    )
    case.records, case.added, case.locks, case.tasks = records, added, locks, tasks
    return case


def test_native_retry_pins_new_checkpoint_and_keeps_successful_history_and_replay(monkeypatch):
    case = retry_case(monkeypatch)
    result = owner.recover_native_material_visuals(
        case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
    )
    assert case.locks == ["revision", "run"]
    assert result.reused_tasks == 2 and result.retried_tasks == 1
    current = case.records[result.run_id]
    assert current.prepared_sha256 == case.pointer.sha256
    assert case.source.prepared_sha256 == case.base_pointer.sha256
    clones = [row for row in case.added if isinstance(row, MaterialLearningTaskRecord)]
    assert [row.state for row in clones] == ["COMPLETED", "COMPLETED", "PENDING"]
    assert clones[1].item_revision_id == case.tasks[1].item_revision_id
    assert clones[1].graph_snapshot_revision_id == case.tasks[1].graph_snapshot_revision_id
    assert clones[1].analysis_run_id is None and case.tasks[1].analysis_run_id is not None
    assert (
        clones[1].solution_analysis_run_id is None
        and case.tasks[1].solution_analysis_run_id is not None
    )
    assert [row.predecessor_task_id for row in clones] == [row.task_id for row in case.tasks]
    assert owner.recover_native_material_visuals(
        case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
    ).replayed
    assert len([row for row in case.added if isinstance(row, MaterialLearningRunRecord)]) == 1


def test_ordinary_retry_keeps_original_identity_and_prepared_pointer(monkeypatch):
    case = retry_case(monkeypatch)
    result = owner.retry_material_learning_run(case.sessions, case.command)
    assert (
        result.run_id
        == "materialrun_"
        + uuid5(
            NAMESPACE_URL,
            "eom:material-retry:" + content_sha256(case.command.model_dump(mode="json")),
        ).hex
    )
    assert case.records[result.run_id].prepared_sha256 == case.base_pointer.sha256
    owner._native_visual_checkpoint.assert_not_called()


@pytest.mark.parametrize("field", owner._VISUAL_FAILED_OUTPUT_FIELDS)
def test_native_visual_recovery_never_reuses_an_accepted_failed_result(monkeypatch, field):
    case = retry_case(monkeypatch)
    setattr(case.tasks[-1], field, "already-pinned-result")
    with pytest.raises(MaterialLearningSourceError, match="VISUAL_RECOVERY_PHASE_INVALID"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )
    assert not case.added


@pytest.mark.parametrize("kind", ("PREPARE", "DISCOVER", "EXPLANATION"))
def test_visual_recovery_only_retries_failed_questions(monkeypatch, kind):
    case = retry_case(monkeypatch)
    case.tasks[-1].task_kind = kind
    with pytest.raises(MaterialLearningSourceError, match="VISUAL_RECOVERY_PHASE_INVALID"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )
    assert not case.added


@pytest.mark.parametrize("fault", ("live_workflow", "other_actor"))
def test_native_retry_checks_completed_history_workflows_before_creating_run(monkeypatch, fault):
    case = retry_case(monkeypatch)
    guard = owner._quiescent_failed_workflows
    if fault == "live_workflow":
        guard.side_effect = MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
    else:
        guard.return_value = {"workflow": SimpleNamespace(created_actor_id="operator_" + "0" * 32)}
    with pytest.raises(MaterialLearningSourceError, match="RECONCILIATION_REQUIRED"):
        owner.recover_native_material_visuals(
            case.sessions, case.command, prepared=case.pointer, artifacts=case.artifacts
        )
    assert guard.call_args.args[1] == case.tasks
    assert not case.added


@pytest.mark.parametrize(
    "fault,code",
    (
        ("stale", "STATE_STALE"),
        ("running", "RETRY_PHASE_INVALID"),
        ("live_lease", "RECONCILIATION_REQUIRED"),
        ("live_task", "RECONCILIATION_REQUIRED"),
        ("actor", "RUN_NOT_FOUND"),
    ),
)
def test_native_retry_rejects_unsafe_source_before_creating_successor(monkeypatch, fault, code):
    case = retry_case(monkeypatch)
    command = case.command
    if fault == "stale":
        command = command.model_copy(
            update={"expected_updated_at": command.expected_updated_at + timedelta(seconds=1)}
        )
    elif fault == "running":
        case.source.state = "PROCESSING"
    elif fault == "live_lease":
        case.source.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    elif fault == "live_task":
        case.tasks[0].state = "PREPARING"
    else:
        command = command.model_copy(update={"actor_id": "operator_" + "0" * 32})
    with pytest.raises(MaterialLearningSourceError, match=code):
        owner.recover_native_material_visuals(
            case.sessions, command, prepared=case.pointer, artifacts=case.artifacts
        )
    assert not case.added
