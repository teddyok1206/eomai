"""Known source-visual failures must close one run, not stop the resident service.

Real Coordinator.prepare/visual enrichment/scope validation run over the existing
synthetic artifact and parser ports. Only persistence, claim and PDF preparation
are in-memory ports; no PostgreSQL, NAS, systemd, model or live source is used.
"""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_native_intake import MaterialNativePreparationInput
from eom_catalog_service import material_learning_coordinator as coordinator_owner
from eom_catalog_service import material_learning_processing as processing_owner
from eom_catalog_service import material_native_visual_preparation as visual_owner
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_pages import MaterialPreparationOutcome
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_learning_store import MaterialRunClaim
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.office_picture_use_extraction import ExtractedOfficePictureUses

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_intake import native_preparation
from tests.unit.test_material_native_visual_preparation_service import PREPARED_TYPE, _case


class MemorySession:
    def __init__(self, run, task):
        self.run, self.task = run, task

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, model, identity):
        if model is MaterialLearningRunRecord and identity == self.run.run_id:
            return self.run
        if model is MaterialLearningTaskRecord and identity == self.task.task_id:
            return self.task
        raise AssertionError("Unexpected persistence read in preparation failure")

    def scalar(self, statement):
        assert "material_learning_tasks" in str(statement)
        return self.task


class MemorySessions:
    def __init__(self, run, task):
        self.run, self.task = run, task

    def __call__(self):
        return MemorySession(self.run, self.task)

    begin = __call__


def preparation_case(monkeypatch, tmp_path, *, ambiguous=False, unsupported=False):
    case = _case(monkeypatch, tmp_path, fixed=True, ambiguous=ambiguous)
    data = native_preparation()
    data.update(
        material_id=case.intake.material_id,
        material_revision_id=case.intake.material_revision_id,
        native_bundle=case.intake.native_bundle.model_dump(mode="json"),
        intake_manifest=case.base.intake_manifest.model_dump(mode="json"),
    )
    work = MaterialNativePreparationInput.model_validate(rehash(data))
    run = SimpleNamespace(run_id="materialrun_" + "9" * 32, state="PREPARING", error_code=None)
    task = SimpleNamespace(
        task_id=work.task_id,
        state="PREPARING",
        input_artifact_id=case.base_pointer.artifact_id,
        input_artifact_revision_id=case.base_pointer.artifact_revision_id,
        input_sha256=case.base_pointer.sha256,
        error_code=None,
    )
    claim = MaterialRunClaim(
        run.run_id,
        "synthetic-material-owner",
        "synthetic-lease-token",
        datetime.now(UTC) + timedelta(minutes=1),
    )
    coordinator = coordinator_owner.MaterialLearningCoordinator.__new__(
        coordinator_owner.MaterialLearningCoordinator
    )
    coordinator.sessions = MemorySessions(run, task)
    coordinator.artifacts = case.artifacts
    coordinator.claim = Mock(side_effect=[claim, None])
    coordinator.release = Mock()
    coordinator.authorize = Mock(side_effect=lambda _: case.authorize())
    coordinator.intake = Mock(return_value=(case.intake, case.base.intake_manifest))
    coordinator.maintain_claim = Mock(side_effect=lambda _: nullcontext())
    coordinator.preparation = SimpleNamespace(
        prepare=Mock(return_value=MaterialPreparationOutcome(case.base, case.base_pointer))
    )
    coordinator.native_visuals = case.service
    monkeypatch.setattr(coordinator_owner, "lock_material_run", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(processing_owner, "lock_material_run", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(coordinator_owner, "material_preparation_task", lambda *_: (task, False))
    monkeypatch.setattr(
        coordinator_owner, "material_preparation_pointer", lambda *_a, **_k: case.base_pointer
    )
    monkeypatch.setattr(coordinator_owner, "read_material_preparation", lambda *_a, **_k: work)

    def transition_task(_session, _run, observed, state, **fields):
        observed.state, observed.error_code = state.value, fields.get("error_code")

    def transition_run(_session, observed, state, **fields):
        observed.state, observed.error_code = state.value, fields.get("error_code")

    monkeypatch.setattr(processing_owner, "transition_material_task", transition_task)
    monkeypatch.setattr(processing_owner, "transition_material_run", transition_run)
    if unsupported:
        extract = visual_owner.extract_office_picture_use_input

        def unsupported_body(*args, **kwargs):
            observed = extract(*args, **kwargs)
            value = observed.catalog.model_dump(mode="json")
            value["picture_uses"][0]["unresolved_reasons"] = ["IMAGE_EFFECT_UNSUPPORTED"]
            value["rendered_uses"] = []
            catalog = OfficePictureUseCatalog.model_validate(rehash(value, "manifest_sha256"))
            return ExtractedOfficePictureUses(catalog, observed.workspace, observed.members)

        monkeypatch.setattr(visual_owner, "extract_office_picture_use_input", unsupported_body)
    processing = processing_owner.MaterialLearningProcessingService(
        coordinator, registration=Mock(), graph=Mock()
    )
    return SimpleNamespace(**locals())


@pytest.mark.parametrize(
    "failure,expected_code",
    [
        ("unsupported", "MATERIAL_NATIVE_VISUAL_QUESTION_USE_UNRESOLVED"),
        ("ambiguous", "MATERIAL_NATIVE_VISUAL_SOURCE_USE_AMBIGUOUS"),
    ],
)
def test_known_native_source_visual_failure_closes_only_its_run(
    monkeypatch, tmp_path, failure, expected_code
):
    case = preparation_case(monkeypatch, tmp_path, **{failure: True})
    progress = case.processing.advance_once()
    assert progress.phase == "FAILED"
    assert case.run.state == case.task.state == "FAILED"
    assert case.run.error_code == case.task.error_code == expected_code
    assert not case.case.publisher.calls
    case.coordinator.release.assert_called_once_with(case.claim)
    assert case.processing.advance_once().phase == "IDLE"


@pytest.mark.parametrize(
    "failure", ["publication", "hash", "profile", "permission", "pointer", "tool"]
)
def test_infrastructure_hash_and_stale_profile_remain_hard_failures(monkeypatch, tmp_path, failure):
    case = preparation_case(monkeypatch, tmp_path)
    if failure == "publication":
        case.case.publisher.fail_type = PREPARED_TYPE
        error, code = ControlPlaneError, "CONTROL_FILE_SET_INCOMPLETE"
    elif failure == "hash":
        file = case.case.bundle.items[0].question.document
        key = file.artifact_id, file.artifact_revision_id, file.member_path
        pointer, raw = case.case.artifacts.values[key]
        case.case.artifacts.values[key] = pointer, raw + b"changed"
        error, code = ValueError, "TEST_CANONICAL_HASH_MISMATCH"
    elif failure == "profile":
        code = "MATERIAL_LEARNING_PREPARATION_PROFILE_STALE"
        case.coordinator.preparation.prepare.side_effect = MaterialLearningSourceError(code)
        error = MaterialLearningSourceError
    elif failure == "permission":
        code = "MATERIAL_LEARNING_PERMISSION_DENIED"
        case.case.service.sources.resolve = Mock(side_effect=MaterialLearningSourceError(code))
        error = MaterialLearningSourceError
    elif failure == "pointer":
        code = "MATERIAL_NATIVE_VISUAL_SOURCE_CATALOG_MISMATCH"
        case.case.service._catalog = Mock(side_effect=ValueError(code))
        error = ValueError
    else:
        code = "MATERIAL_NATIVE_TOOL_UNAVAILABLE"
        case.case.service.sources.resolve = Mock(side_effect=OSError(code))
        error = OSError
    with pytest.raises(error) as observed:
        case.processing.advance_once()
    assert getattr(observed.value, "code", str(observed.value)) == code
    assert case.run.state == case.task.state == "PREPARING"
    case.coordinator.release.assert_called_once_with(case.claim)
