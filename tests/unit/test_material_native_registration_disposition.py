"""An explicit metadata-update request must not kill the resident material owner."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import material_learning_processing as owner
from eom_catalog_service.material_learning_processing import MaterialLearningProcessingService


@pytest.mark.parametrize(
    "code",
    [
        "MATERIAL_ITEM_SOURCE_UNREADABLE",
        "MATERIAL_NATIVE_METADATA_UPDATE_REQUIRED",
        "MATERIAL_NATIVE_BINDING_HASH_INVALID",
    ],
)
def test_only_explicit_source_exceptions_are_recorded_without_new_item_or_analysis(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    service = object.__new__(MaterialLearningProcessingService)
    task = SimpleNamespace(task_id="synthetic-task", state="RESULT_READY")
    claim = SimpleNamespace(run_id="synthetic-run")
    context = SimpleNamespace(operator_id="synthetic-operator")
    session = SimpleNamespace(get=lambda *_args: task)

    @contextmanager
    def begin():
        yield session

    service.sessions = SimpleNamespace(begin=begin)
    service.registration = SimpleNamespace(register_completed=Mock(side_effect=ValueError(code)))
    service.graph = Mock()
    service._set_state = Mock(side_effect=AssertionError("must not create registration success"))
    transition = Mock()
    monkeypatch.setattr(owner, "lock_material_run", lambda *_args, **_kwargs: claim)
    monkeypatch.setattr(owner, "transition_material_task", transition)
    if code in owner._REGISTRATION_SOURCE_EXCEPTIONS:
        result = service._question(claim, context, None, task)
        assert result.phase == "EXCEPTION"
        assert transition.call_args.kwargs["error_code"] == code
        assert transition.call_args.args[3].value == "EXCEPTION"
    else:
        with pytest.raises(ValueError, match=code):
            service._question(claim, context, None, task)
        transition.assert_not_called()
    service._set_state.assert_not_called()
    assert not service.graph.mock_calls
