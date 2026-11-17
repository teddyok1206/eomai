"""Existing shared-workflow continuation, bounded ticks and no inferred authority or model retry."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import kakao_concept_continuation as module
from eom_catalog_service import kakao_concept_workflow_submission as submission
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_kakao_archive_contracts.concepts import ConceptPlan


def coordinator(monkeypatch, *, status="PLANNED", candidates=None):
    session = Mock()
    session.execute.return_value.first.side_effect = candidates or [
        ("task-first", "actual-owner"),
        None,
    ]
    service = Mock()
    service.sessions = Mock(return_value=nullcontext(session))
    authority = service.accepted_source_authority.return_value
    output = ConceptPlan(
        status=status,
        focus_summary="합성 개념",
        queries=({"concept": "개념", "query": "검색어", "reason": "기초 개념 연결"},)
        if status == "PLANNED"
        else (),
        limitations=(),
    )
    completed = SimpleNamespace(result=SimpleNamespace(output=SimpleNamespace(output=output)))
    reader = Mock(return_value=completed)
    monkeypatch.setattr(module, "read_kakao_concept_phase_result", reader)
    definition, preset = SimpleNamespace(definition_hash="same-definition"), object()
    runtime = Mock(return_value=(definition, preset))
    monkeypatch.setattr(module, "read_kakao_concept_submission_runtime", runtime)
    submitted = Mock(return_value=SimpleNamespace(workflow_id="same-child-workflow"))
    monkeypatch.setattr(module, "submit_accepted_kakao_concept_phase", submitted)
    return module.KakaoConceptCoordinator(service), session, authority, reader, runtime, submitted


def test_one_tick_continues_the_saved_owner_and_uses_existing_submission(monkeypatch):
    owner, _session, authority, reader, runtime, submitted = coordinator(monkeypatch)
    result = owner.advance_once()
    assert (result.state, result.task_id, result.workflow_id) == (
        "SUBMITTED",
        "task-first",
        "same-child-workflow",
    )
    owner.service.accepted_source_authority.assert_called_once_with(
        task_id="task-first", operator_id="actual-owner"
    )
    reader.assert_called_once_with(authority, "PLAN")
    owner.service.prepare_accepted_compose.assert_called_once_with(authority)
    assert submitted.call_args.args == (authority,)
    assert runtime.call_args_list[0].kwargs == {"authority": authority}
    assert runtime.call_args_list[1].kwargs == {}
    assert owner.advance_once().state == "IDLE"
    submitted.assert_called_once()


def test_more_input_never_triggers_another_model_or_knowledge_retrieval(monkeypatch):
    owner, _session, _authority, _reader, runtime, submitted = coordinator(
        monkeypatch, status="NEEDS_INPUT"
    )
    assert owner.advance_once().state == "NEEDS_INPUT"
    runtime.assert_not_called()
    owner.service.prepare_accepted_compose.assert_not_called()
    submitted.assert_not_called()


def test_changed_current_preset_does_not_silently_change_an_accepted_task(monkeypatch):
    owner, _session, _authority, _reader, runtime, submitted = coordinator(monkeypatch)
    definition = SimpleNamespace(definition_hash="same-definition")
    runtime.side_effect = [(definition, "old-preset"), (definition, "new-preset")]
    result = owner.advance_once()
    assert result.state == "ERROR" and result.error_code == "CONTROL_PRESET_POINTER_STALE"
    owner.service.prepare_accepted_compose.assert_not_called()
    submitted.assert_not_called()


def test_source_error_advances_cursor_and_does_not_starve_another_task(monkeypatch):
    owner, session, _authority, _reader, _runtime, submitted = coordinator(
        monkeypatch,
        candidates=[("task-first", "actual-owner"), ("task-next", "actual-owner"), None],
    )
    owner.service.accepted_source_authority.side_effect = [
        KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED"),
        Mock(),
    ]
    assert owner.advance_once().error_code == "KAKAO_ARCHIVE_PERMISSION_DENIED"
    assert owner.advance_once().task_id == "task-next"
    assert session.execute.call_args_list[1].args[0].compile().params["task_id_1"] == "task-first"
    assert owner.advance_once().state == "IDLE"
    submitted.assert_called_once()


def test_tick_lock_does_not_create_or_run_a_parallel_workflow(monkeypatch):
    owner, session, *_ = coordinator(monkeypatch)
    owner._tick.acquire()
    try:
        assert owner.advance_once().state == "WAITING"
        session.execute.assert_not_called()
    finally:
        owner._tick.release()
    assert owner.advance_once().state == "SUBMITTED"


def test_unexpected_io_failure_is_content_safe_and_keeps_work_recoverable(monkeypatch):
    owner, _session, _authority, _reader, _runtime, submitted = coordinator(monkeypatch)
    owner.service.prepare_accepted_compose.side_effect = RuntimeError(
        "PRIVATE INPUT MUST NOT BE RETURNED"
    )
    result = owner.advance_once()
    assert result.state == "ERROR" and result.error_code == "KAKAO_CONCEPT_CONTINUATION_FAILED"
    assert "PRIVATE" not in repr(result)
    submitted.assert_not_called()
    assert owner.advance_once().state == "IDLE"


def test_missing_published_definition_is_explicit_not_generic_support_fallback(monkeypatch):
    service, session = Mock(), Mock()
    service.sessions.begin.return_value = nullcontext(session)
    monkeypatch.setattr(submission, "admitted_workflow_definition", Mock(return_value=None))
    with pytest.raises(KakaoArchiveError, match="KAKAO_CONCEPT_RUNTIME_UNAVAILABLE"):
        submission.read_kakao_concept_submission_runtime(service)
    service.prepare_plan.assert_not_called()


def test_source_runtime_mode_is_closed_and_disabled_by_default(monkeypatch):
    from eom_catalog_service import kakao_question_composition as composition

    for name in (
        "CatalogArtifactService",
        "KakaoSourceService",
        "KakaoQuestionService",
        "KakaoConceptKnowledgeReader",
        "KakaoQuestionReads",
        "KakaoQuestionComposeService",
        "KakaoConceptTaskService",
    ):
        monkeypatch.setattr(composition, name, Mock())
    assert composition.build_kakao_question_application(Mock()).concept_coordinator is None
    enabled = composition.build_kakao_question_application(Mock(), concept_mode="SHARED")
    assert enabled.concept_coordinator.service is enabled.concepts
    with pytest.raises(ValueError, match="KAKAO_CONCEPT_MODE_INVALID"):
        composition.build_kakao_question_application(Mock(), concept_mode="AUTO_GUESSED")


def test_catalog_early_exit_stops_optional_continuations_before_engine_disposal(monkeypatch):
    from eom_catalog_service import application_runner as runner

    engine, event = Mock(), Mock()
    monkeypatch.setattr(runner, "build_engine", Mock(return_value=engine))
    monkeypatch.setattr(runner, "threading", SimpleNamespace(Event=lambda: event))
    monkeypatch.setattr(runner, "signal", SimpleNamespace(SIGTERM=15, SIGINT=2, signal=Mock()))
    monkeypatch.setattr(runner, "catalog_runtime_privileges_ready", Mock(return_value=False))
    engine.dispose.side_effect = lambda: event.set.assert_called_once()
    assert runner.serve() == 1
    event.set.assert_called_once()
    engine.dispose.assert_called_once()


def test_concept_source_owner_does_not_gain_preset_mutation_privileges():
    from eom_catalog_service.runtime_privileges import (
        COLUMN_PRIVILEGES,
        READ_TABLES,
        UPDATE_TABLES,
    )

    assert "execution_presets" in READ_TABLES
    assert "execution_presets" not in UPDATE_TABLES
    assert not any(
        privilege == "UPDATE" and table == "execution_presets"
        for privilege, table, _columns in COLUMN_PRIVILEGES
    )
