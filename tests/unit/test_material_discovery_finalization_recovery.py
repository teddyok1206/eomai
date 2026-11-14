"""Closed finalization recovery admission with explicit synthetic read ports."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_discovery_finalization_recovery import (
    RecoverNativeMaterialDiscoveryFinalizationCommand,
)
from eom_catalog_service import material_discovery_finalization_recovery as owner
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_task_history import MaterialTaskHistory

ACTOR = "operator_" + "1" * 32
RUN = "materialrun_" + "2" * 32
REVISION = "materialrev_" + "3" * 32
MATERIAL = "material_" + "4" * 32
HASH = "sha256:" + "5" * 64


def command():
    return RecoverNativeMaterialDiscoveryFinalizationCommand(
        actor_id=ACTOR,
        run_id=RUN,
        expected_updated_at=datetime(2026, 11, 14, tzinfo=UTC),
        expected_prepared_sha256=HASH,
        target_source_commit="a" * 40,
    )


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("actor", "RUN_NOT_FOUND"),
        ("withdrawn", "RUN_NOT_FOUND"),
        ("current", "RUN_NOT_FOUND"),
        ("stale", "STATE_STALE"),
        ("state", "PHASE_INVALID"),
        ("error", "PHASE_INVALID"),
        ("prepared", "PHASE_INVALID"),
        ("lease", "LIVE_LEASE"),
    ],
)
def test_source_scope_cannot_be_broadened_by_a_recovery_command(monkeypatch, fault, expected):
    cmd = command()
    source = SimpleNamespace(
        created_by=ACTOR,
        material_revision_id=REVISION,
        updated_at=cmd.expected_updated_at,
        state="FAILED",
        error_code="MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID",
        prepared_artifact_id="artifact_" + "6" * 32,
        prepared_artifact_revision_id="rev_" + "7" * 32,
        prepared_sha256=HASH,
        lease_expires_at=None,
    )
    revision = SimpleNamespace(
        material_id=MATERIAL, material_revision_id=REVISION, created_by=ACTOR
    )
    material = SimpleNamespace(
        created_by=ACTOR, lifecycle_state="ACTIVE", current_revision_id=REVISION
    )
    if fault == "actor":
        source.created_by = "operator_" + "0" * 32
    if fault == "withdrawn":
        material.lifecycle_state = "WITHDRAWN"
    if fault == "current":
        material.current_revision_id = "materialrev_" + "0" * 32
    if fault == "stale":
        source.updated_at -= timedelta(seconds=1)
    if fault == "state":
        source.state = "DISCOVERING"
    if fault == "error":
        source.error_code = "MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH"
    if fault == "prepared":
        source.prepared_sha256 = "sha256:" + "0" * 64
    if fault == "lease":
        source.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    values = {
        MaterialLearningRunRecord: source,
        LearningMaterialRevisionRecord: revision,
        LearningMaterialRecord: material,
    }
    session = SimpleNamespace(get=lambda model, identity, **kwargs: values[model])
    monkeypatch.setattr(owner, "authorize_material_learning", lambda *args: None)
    with pytest.raises(ValueError, match=expected):
        owner.NativeMaterialDiscoveryFinalizationRecoveryService._source(session, cmd)


def tasks():
    result = []
    for ordinal, kind in enumerate(("PREPARE", "DISCOVER"), 1):
        result.append(
            MaterialLearningTaskRecord(
                task_id="materialtask_" + str(ordinal) * 32,
                run_id=RUN,
                task_kind=kind,
                unit_key="source-preparation" if ordinal == 1 else "window-main",
                ordinal=ordinal,
                attempt=1,
                state="COMPLETED",
                execution_lane="MATERIAL_LEARNING",
                workflow_id=None if ordinal == 1 else "workflow_" + "8" * 32,
                input_artifact_id="artifact_" + "6" * 32,
                input_artifact_revision_id="rev_" + "7" * 32,
                input_sha256=HASH,
                output_artifact_id="artifact_" + "6" * 32,
                output_artifact_revision_id="rev_" + "7" * 32,
                output_sha256=HASH,
            )
        )
    return tuple(result)


@pytest.mark.parametrize(
    "fault", ["question", "explanation", "pending", "output", "analysis", "lane", "ordinal"]
)
def test_only_completed_prepare_and_discovery_can_be_inherited(fault):
    rows = tasks()
    if fault in {"question", "explanation"}:
        rows[1].task_kind = fault.upper()
    if fault == "pending":
        rows[1].state = "PENDING"
    if fault == "output":
        rows[1].output_sha256 = None
    if fault == "analysis":
        rows[1].analysis_run_id = "analysisrun_" + "9" * 32
    if fault == "lane":
        rows[1].execution_lane = "OTHER"
    if fault == "ordinal":
        rows[1].ordinal = 3
    session = SimpleNamespace(scalars=lambda query: rows)
    with pytest.raises(ValueError, match="FINALIZATION_TASKS_INVALID"):
        owner.NativeMaterialDiscoveryFinalizationRecoveryService._tasks(
            session, SimpleNamespace(run_id=RUN), ACTOR
        )


@pytest.mark.parametrize("workflow_state,lease", [("RUNNING", None), ("COMPLETED", "held")])
def test_complete_task_labels_do_not_override_a_live_child(monkeypatch, workflow_state, lease):
    rows = tasks()
    workflow = SimpleNamespace(
        workflow_id=rows[1].workflow_id, state=workflow_state, created_actor_id=ACTOR
    )
    reads = iter((rows, (workflow,)))
    session = SimpleNamespace(scalars=lambda query: next(reads), scalar=lambda query: lease)
    monkeypatch.setattr(
        owner,
        "read_material_task_histories",
        lambda *args: {row.task_id: MaterialTaskHistory((row,)) for row in rows},
    )
    with pytest.raises(ValueError, match="RECONCILIATION_REQUIRED"):
        owner.NativeMaterialDiscoveryFinalizationRecoveryService._tasks(
            session, SimpleNamespace(run_id=RUN), ACTOR
        )


def test_target_source_must_be_the_trusted_installed_source_before_any_reads():
    service = object.__new__(owner.NativeMaterialDiscoveryFinalizationRecoveryService)
    service.source_commit = "b" * 40
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        service.recover(command())
