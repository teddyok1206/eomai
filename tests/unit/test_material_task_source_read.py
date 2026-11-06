"""Source-location reads reuse the original discovered plan, not guessed pages."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import material_task_source_read as owner
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_workflow.material_learning_plan import plan_material_learning_units

from tests.unit.test_material_learning_plan import discovered


def case(monkeypatch):
    unit = next(
        row for row in plan_material_learning_units((discovered(),)) if row.unit.kind == "QUESTION"
    )
    task = SimpleNamespace(
        task_id="materialtask_" + "1" * 32,
        run_id="materialrun_" + "2" * 32,
        task_kind="QUESTION",
        input_artifact_revision_id=None,
        unit_key=unit.unit_key,
    )
    run = SimpleNamespace(
        run_id=task.run_id,
        created_by="operator_" + "3" * 32,
        material_revision_id="materialrev_" + "4" * 32,
    )
    revision = SimpleNamespace(material_revision_id=run.material_revision_id)
    read = Mock(return_value=SimpleNamespace(by_unit={unit.unit_key: unit}))
    monkeypatch.setattr(owner, "read_material_discovery_plan", read)
    return task, run, revision, read


def test_exception_before_extraction_still_shows_real_discovered_page(monkeypatch):
    task, run, revision, read = case(monkeypatch)
    artifacts = Mock()
    result = owner.read_material_task_source(
        Mock(),
        artifacts,
        run=run,
        revision=revision,
        task=task,
        operator_id=run.created_by,
        history=None,
    )
    assert result.printed_label == "1" and result.section_path == ("1장",)
    assert [page.physical_page for page in result.source_pages] == [1]
    assert result.source_pages[0].source_role == "MAIN"
    read.assert_called_once()
    artifacts.read_member.assert_not_called()


def test_missing_unit_or_wrong_actor_does_not_invent_location(monkeypatch):
    task, run, revision, read = case(monkeypatch)
    read.return_value = SimpleNamespace(by_unit={})
    with pytest.raises(MaterialLearningSourceError, match="SOURCE_MISSING"):
        owner.read_material_task_source(
            Mock(),
            Mock(),
            run=run,
            revision=revision,
            task=task,
            operator_id=run.created_by,
            history=None,
        )
    read.reset_mock()
    with pytest.raises(MaterialLearningSourceError, match="TASK_NOT_FOUND"):
        owner.read_material_task_source(
            Mock(),
            Mock(),
            run=run,
            revision=revision,
            task=task,
            operator_id="operator_" + "f" * 32,
            history=None,
        )
    read.assert_not_called()
