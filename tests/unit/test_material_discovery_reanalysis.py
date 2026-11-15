"""Closed native source admission and unchanged task copies; no runtime/model IO."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_catalog_service import material_discovery_reanalysis as owner
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
)
from eom_catalog_service.material_learning_recovery import clone_material_retry_task
from eom_catalog_service.material_task_history import MaterialTaskHistory
from eom_identifiers import content_sha256

from tests.unit.test_material_discovery_finalization_recovery import tasks

ACTOR = "operator_" + "1" * 32
RUN = "materialrun_" + "2" * 32
REVISION = "materialrev_" + "3" * 32
MATERIAL = "material_" + "4" * 32
SUCCESSOR = "materialrun_" + "9" * 32
NOW = datetime(2026, 11, 15, tzinfo=UTC)


def command():
    return owner.RetryMaterialLearningRunCommand(
        actor_id=ACTOR, run_id=RUN, expected_updated_at=NOW
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("actor", "RUN_NOT_FOUND"),
        ("material_actor", "RUN_NOT_FOUND"),
        ("retired", "RUN_NOT_FOUND"),
        ("current", "RUN_NOT_FOUND"),
        ("stale", "STATE_STALE"),
        ("state", "PHASE_INVALID"),
        ("error", "PHASE_INVALID"),
        ("lease", "RECONCILIATION_REQUIRED"),
    ],
)
def test_reanalysis_never_broadens_actor_source_phase_or_lease(monkeypatch, fault, code):
    source = SimpleNamespace(
        created_by=ACTOR,
        material_revision_id=REVISION,
        updated_at=NOW,
        state="FAILED",
        error_code=owner._ERROR,
        lease_expires_at=None,
    )
    revision = SimpleNamespace(
        created_by=ACTOR, material_id=MATERIAL, material_revision_id=REVISION
    )
    material = SimpleNamespace(
        created_by=ACTOR, lifecycle_state="ACTIVE", current_revision_id=REVISION
    )
    if fault == "actor":
        source.created_by = "operator_" + "0" * 32
    elif fault == "material_actor":
        material.created_by = "operator_" + "0" * 32
    elif fault == "retired":
        material.lifecycle_state = "WITHDRAWN"
    elif fault == "current":
        material.current_revision_id = "materialrev_" + "0" * 32
    elif fault == "stale":
        source.updated_at -= timedelta(seconds=1)
    elif fault == "state":
        source.state = "DISCOVERING"
    elif fault == "error":
        source.error_code = "MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH"
    elif fault == "lease":
        source.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    values = {
        MaterialLearningRunRecord: source,
        LearningMaterialRevisionRecord: revision,
        LearningMaterialRecord: material,
    }
    session = SimpleNamespace(get=lambda model, identity, **kwargs: values[model])
    monkeypatch.setattr(owner, "authorize_material_learning", lambda *args: None)
    with pytest.raises(ValueError, match=code):
        owner.NativeMaterialDiscoveryReanalysisService._source(session, command())


@pytest.mark.parametrize(
    "fault", ["pending", "failed", "question", "input", "output", "registered", "ordinal", "lane"]
)
def test_only_complete_discovery_before_any_registration_is_eligible(fault):
    rows = tasks()
    row = rows[1]
    if fault == "pending":
        row.state = "PENDING"
    elif fault == "failed":
        row.state = "FAILED"
    elif fault == "question":
        row.task_kind = "QUESTION"
    elif fault == "input":
        row.input_sha256 = None
    elif fault == "output":
        row.output_artifact_revision_id = None
    elif fault == "registered":
        row.item_revision_id = "itemrev_" + "0" * 32
    elif fault == "ordinal":
        row.ordinal = 4
    else:
        row.execution_lane = "OTHER"
    session = SimpleNamespace(scalars=lambda query: rows)
    with pytest.raises(ValueError, match="REANALYSIS_TASKS_INVALID"):
        owner.NativeMaterialDiscoveryReanalysisService._tasks(session, SimpleNamespace(run_id=RUN))


def test_inherited_copy_reuses_exact_pointers_and_selected_copy_has_no_old_input_or_result():
    row = tasks()[1]
    before = owner._task_signature((row,))
    inherited = clone_material_retry_task(row, run_id=SUCCESSOR, now=NOW, checkpoint_state=None)
    selected = clone_material_retry_task(row, run_id=SUCCESSOR, now=NOW, checkpoint_state="PENDING")
    assert inherited.task_id == selected.task_id != row.task_id
    assert inherited.state == "COMPLETED" and selected.state == "PENDING"
    assert inherited.predecessor_task_id == selected.predecessor_task_id == row.task_id
    assert inherited.workflow_id is None and selected.workflow_id is None
    for field in (
        "input_artifact_id",
        "input_artifact_revision_id",
        "input_sha256",
        "output_artifact_id",
        "output_artifact_revision_id",
        "output_sha256",
    ):
        assert getattr(inherited, field) == getattr(row, field)
        assert getattr(selected, field) is None
    assert owner._task_signature((row,)) == before


@pytest.mark.parametrize("fault", [None, "running", "foreign_actor", "missing"])
def test_inherited_result_maps_the_original_producer_to_current_task(monkeypatch, fault):
    original = tasks()
    inherited = tuple(
        clone_material_retry_task(row, run_id=SUCCESSOR, now=NOW, checkpoint_state=None)
        for row in original
    )
    histories = {
        current.task_id: MaterialTaskHistory((current, previous))
        for current, previous in zip(inherited, original, strict=True)
    }
    workflow = SimpleNamespace(
        state="RUNNING" if fault == "running" else "COMPLETED",
        created_actor_id="operator_" + "0" * 32 if fault == "foreign_actor" else ACTOR,
    )
    monkeypatch.setattr(owner, "read_material_task_histories", lambda *_args: histories)
    monkeypatch.setattr(
        owner,
        "quiescent_material_task_workflows",
        lambda *_args: {} if fault == "missing" else {original[1].workflow_id: workflow},
    )
    if fault is None:
        assert owner.NativeMaterialDiscoveryReanalysisService._owners(None, inherited, ACTOR) == {
            original[1].task_id: inherited[1].task_id,
        }
    else:
        with pytest.raises(ValueError, match="RECONCILIATION_REQUIRED"):
            owner.NativeMaterialDiscoveryReanalysisService._owners(None, inherited, ACTOR)


@pytest.mark.parametrize("fault", [None, "withdrawn", "manifest", "missing", "duplicate"])
def test_artifact_metadata_fence_is_one_bounded_query_and_rejects_stale_values(fault):
    manifest = {"primary_file": "result.json", "files": []}
    artifact = SimpleNamespace(
        logical_artifact_id="artifact_" + "1" * 32,
        approved=True,
        artifact_type="workflow_support",
        job_id="job_" + "3" * 32,
    )
    revision = SimpleNamespace(
        revision_id="rev_" + "2" * 32,
        approved=True,
        content_hash="sha256:" + "4" * 64,
        content_bytes=10,
        manifest=manifest,
        manifest_hash=content_sha256(manifest),
        job_id=artifact.job_id,
    )
    keys = frozenset({(artifact.logical_artifact_id, revision.revision_id)})
    rows = [(artifact, revision)]
    if fault == "withdrawn":
        revision.approved = False
    elif fault == "manifest":
        revision.manifest = {"primary_file": "other.json"}
    elif fault == "missing":
        rows = []
    elif fault == "duplicate":
        rows *= 2
    calls = []
    session = SimpleNamespace(
        execute=lambda query: calls.append(query) or SimpleNamespace(all=lambda: rows)
    )
    if fault is None:
        assert len(owner._artifact_signature(session, keys)) == 1
    else:
        with pytest.raises(ValueError, match="ARTIFACT_CHANGED"):
            owner._artifact_signature(session, keys)
    assert len(calls) == 1


def test_replay_checks_inherited_pointers_and_cannot_relabel_an_old_result_as_reanalysis():
    rows = tasks()
    selected = frozenset({rows[1].task_id})
    snapshot = SimpleNamespace(selected_task_ids=selected)
    successor = SimpleNamespace(run_id=SUCCESSOR, created_at=NOW)
    clones = tuple(
        clone_material_retry_task(
            row,
            run_id=SUCCESSOR,
            now=NOW,
            checkpoint_state="PENDING" if row.task_id in selected else None,
        )
        for row in rows
    )
    session = SimpleNamespace(scalars=lambda query: clones)
    owner.NativeMaterialDiscoveryReanalysisService._require_replay_tasks(
        session, successor, rows, snapshot
    )
    clones[1].output_artifact_revision_id = rows[1].output_artifact_revision_id
    with pytest.raises(ValueError, match="RETRY_IDENTITY_INVALID"):
        owner.NativeMaterialDiscoveryReanalysisService._require_replay_tasks(
            session, successor, rows, snapshot
        )
    clones[1].output_artifact_revision_id = None
    clones[0].input_sha256 = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="RETRY_IDENTITY_INVALID"):
        owner.NativeMaterialDiscoveryReanalysisService._require_replay_tasks(
            session, successor, rows, snapshot
        )
