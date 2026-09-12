from __future__ import annotations

from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.application_runner import (
    _legacy_automation_batch_ids,
    _legacy_automation_graph_batch_size,
    _legacy_automation_preset_pin,
    _legacy_automation_retry_analysis_run_ids,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_item_automation_service import (
    LegacyItemAutomaticLearningService,
    _LearningCandidate,
)
from eom_catalog_service.legacy_item_graph_learning_service import LegacyItemGraphCandidate
from eom_catalog_service.legacy_item_learning_service import LegacyItemLearningPresetPin
from sqlalchemy import Engine, create_engine, text


def _candidate() -> _LearningCandidate:
    return _LearningCandidate(
        acceptance_id="itemacceptance_" + "1" * 32,
        acceptance_sha256="sha256:" + "2" * 64,
        item_proposal_id="itemproposal_" + "3" * 32,
        item_number=7,
        requested_by="operator_batch_owner",
    )


def _without_graph(service: LegacyItemAutomaticLearningService) -> None:
    service.graph = None
    service.graph_batch_size = 16


def _pin() -> LegacyItemLearningPresetPin:
    return LegacyItemLearningPresetPin(
        preset_id="execpreset_" + "1" * 32,
        preset_revision_id="execpresetrev_" + "2" * 32,
        preset_content_sha256="sha256:" + "3" * 64,
        capacity_policy_id="capacity_" + "4" * 32,
        capacity_policy_revision_id="capacityrev_" + "5" * 32,
        capacity_policy_content_sha256="sha256:" + "6" * 64,
        capacity_current_revision_id="capacityrev_" + "7" * 32,
        capacity_current_content_sha256="sha256:" + "8" * 64,
    )


def _guard(service: LegacyItemAutomaticLearningService) -> None:
    if not hasattr(service, "learning"):
        service.learning = Mock()
    service.preset_pin = _pin()
    service.learning.preset_pin_guard.return_value = nullcontext()
    service._terminal_analysis = cast(Any, lambda: None)
    if "_solution_candidate" not in service.__dict__:
        service._solution_candidate = cast(Any, lambda: None)


def _query_backed_service(
    retry_analysis_run_ids: tuple[str, ...],
) -> tuple[Engine, LegacyItemAutomaticLearningService]:
    """Use real terminal/retry selectors over the smallest relational fixture they need."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE knowledge_analysis_runs (
                analysis_run_id TEXT PRIMARY KEY,
                predecessor_analysis_run_id TEXT,
                source_revision_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                state TEXT NOT NULL,
                created_by_operator_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE item_revisions (
                item_revision_id TEXT PRIMARY KEY,
                registration_key TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE legacy_item_extraction_decisions (
                acceptance_id TEXT NOT NULL,
                item_proposal_id TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE legacy_item_extraction_batch_work_units (
                acceptance_id TEXT NOT NULL,
                extraction_batch_id TEXT NOT NULL
            )
            """
        )
    learning = Mock()
    learning.preset_pin_guard.return_value = nullcontext()
    service = LegacyItemAutomaticLearningService(
        engine,
        extraction_batch_ids=("legacybatch_" + "1" * 32,),
        retry_analysis_run_ids=retry_analysis_run_ids,
        content_pack_release_id="packrel_" + "2" * 32,
        risk_policy_revision_id="analysisriskrev_" + "3" * 32,
        preset_pin=_pin(),
        graph=None,
        learning=learning,
        analyses=Mock(),
    )
    # These branches are outside the selector-order invariant under test.  Terminal and retry
    # selection remain the real service implementations backed by the relational fixture.
    service._active_analyses = cast(Any, tuple)
    service._solution_candidate = cast(Any, lambda: None)
    service._candidate = Mock()
    return engine, service


def _insert_terminal(
    engine: Engine,
    *,
    ordinal: int,
    analysis_run_id: str,
    state: str = "FAILED",
) -> None:
    acceptance_id = f"acceptance-{ordinal}"
    item_proposal_id = f"proposal-{ordinal}"
    item_revision_id = f"item-revision-{ordinal}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO item_revisions (item_revision_id, registration_key)
                VALUES (:item_revision_id, :registration_key)
                """
            ),
            {
                "item_revision_id": item_revision_id,
                "registration_key": (f"legacy-item-promotion:{acceptance_id}:{item_proposal_id}"),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_decisions
                    (acceptance_id, item_proposal_id)
                VALUES (:acceptance_id, :item_proposal_id)
                """
            ),
            {"acceptance_id": acceptance_id, "item_proposal_id": item_proposal_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batch_work_units
                    (acceptance_id, extraction_batch_id)
                VALUES (:acceptance_id, :batch_id)
                """
            ),
            {"acceptance_id": acceptance_id, "batch_id": "legacybatch_" + "1" * 32},
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_analysis_runs (
                    analysis_run_id, predecessor_analysis_run_id, source_revision_id,
                    source_kind, state, created_by_operator_id, created_at
                ) VALUES (
                    :analysis_run_id, NULL, :source_revision_id,
                    'APPROVED_ITEM_REVISION', :state, :operator_id, :created_at
                )
                """
            ),
            {
                "analysis_run_id": analysis_run_id,
                "source_revision_id": item_revision_id,
                "state": state,
                "operator_id": f"operator-{ordinal}",
                # Reverse chronological order proves the explicit allowlist CASE wins.
                "created_at": f"2026-09-{30 - ordinal:02d}T00:00:00+00:00",
            },
        )


def test_automatic_learning_reconciles_two_active_runs_before_refilling() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service._active_analyses = cast(
        Any,
        lambda: (
            ("analysisrun_" + "4" * 32, "operator_owner", "RUNNING"),
            ("analysisrun_" + "5" * 32, "operator_sibling", "QUEUED"),
        ),
    )
    service._candidate = cast(Any, lambda: None)
    _guard(service)

    assert service.advance_once() is True

    commands = tuple(call.args[0] for call in service.analyses.reconcile.call_args_list)
    assert tuple(command.analysis_run_id for command in commands) == (
        "analysisrun_" + "4" * 32,
        "analysisrun_" + "5" * 32,
    )
    assert tuple(command.requested_by for command in commands) == (
        "operator_owner",
        "operator_sibling",
    )
    service.learning.promote_and_schedule.assert_not_called()


def test_automatic_learning_refills_second_position_while_first_is_running() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service.content_pack_release_id = "packrel_" + "5" * 32
    service.risk_policy_revision_id = "analysisriskrev_" + "6" * 32
    _without_graph(service)
    service._active_analyses = cast(
        Any,
        lambda: (("analysisrun_" + "4" * 32, "operator_owner", "RUNNING"),),
    )
    service._retryable_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, _candidate)
    _guard(service)

    assert service.advance_once() is True

    command = service.analyses.reconcile.call_args.args[0]
    assert command.analysis_run_id == "analysisrun_" + "4" * 32
    service.learning.promote_and_schedule.assert_called_once()


def test_automatic_learning_schedules_additive_report_before_graph_or_new_source() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service.graph = Mock()
    service.graph_batch_size = 16
    service._active_analyses = cast(Any, tuple)
    service._solution_candidate = cast(
        Any,
        lambda: ("analysisrun_" + "4" * 32, "operator_owner"),
    )
    service._retryable_analysis = Mock()
    service._candidate = Mock()
    _guard(service)

    assert service.advance_once() is True

    command = service.analyses.create_solution.call_args.args[0]
    assert command.base_analysis_run_id == "analysisrun_" + "4" * 32
    assert command.requested_by == "operator_owner"
    assert command.idempotency_key == "legacy-item-solution:" + "analysisrun_" + "4" * 32
    service.graph.pending_candidates.assert_not_called()
    service.learning.retry_failed_analysis.assert_not_called()
    service._candidate.assert_not_called()


def test_duplicate_batch_membership_reconciles_once_and_refills_second_position() -> None:
    engine, service = _query_backed_service(())
    try:
        run_id = "analysisrun_" + "4" * 32
        _insert_terminal(engine, ordinal=1, analysis_run_id=run_id, state="RUNNING")
        second_batch_id = "legacybatch_" + "2" * 32
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO legacy_item_extraction_batch_work_units
                        (acceptance_id, extraction_batch_id)
                    VALUES (:acceptance_id, :batch_id)
                    """
                ),
                {"acceptance_id": "acceptance-1", "batch_id": second_batch_id},
            )
        service.extraction_batch_ids = ("legacybatch_" + "1" * 32, second_batch_id)
        delattr(service, "_active_analyses")
        service._retryable_analysis = cast(Any, lambda: None)
        service._candidate = cast(Any, _candidate)
        _guard(service)

        assert service.advance_once() is True

        service.analyses.reconcile.assert_called_once()
        command = service.analyses.reconcile.call_args.args[0]
        assert command.analysis_run_id == run_id
        service.learning.promote_and_schedule.assert_called_once()
    finally:
        engine.dispose()


def test_automatic_learning_accepts_validated_review_state_without_human_record() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    _without_graph(service)
    service._active_analyses = cast(
        Any,
        lambda: (("analysisrun_" + "4" * 32, "operator_owner", "NEEDS_REVIEW"),),
    )
    service._retryable_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, lambda: None)
    _guard(service)

    assert service.advance_once() is True

    service.analyses.accept_validated_without_review.assert_called_once_with(
        analysis_run_id="analysisrun_" + "4" * 32,
        requested_by="operator_owner",
    )
    service.analyses.reconcile.assert_not_called()
    service.learning.promote_and_schedule.assert_not_called()


def test_validated_review_override_uses_system_policy_without_review_pointer() -> None:
    service = object.__new__(KnowledgeAnalysisApplicationService)
    service._accept = Mock(return_value="accepted")  # type: ignore[method-assign]

    assert (
        service.accept_validated_without_review(
            analysis_run_id="analysisrun_" + "4" * 32,
            requested_by="operator_owner",
        )
        == "accepted"
    )
    service._accept.assert_called_once_with(
        "analysisrun_" + "4" * 32,
        acceptance_mode="AUTO_POLICY",
        review_pointer=None,
        actor_id="operator_owner",
        auto_policy_review_override=True,
    )


def test_automatic_learning_builds_replay_stable_promotion_and_pins_policy() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service.content_pack_release_id = "packrel_" + "5" * 32
    service.risk_policy_revision_id = "analysisriskrev_" + "6" * 32
    _without_graph(service)
    service._active_analyses = cast(Any, tuple)
    service._retryable_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, _candidate)
    _guard(service)

    assert service.advance_once() is True

    command = service.learning.promote_and_schedule.call_args.args[0]
    assert command.acceptance_id == "itemacceptance_" + "1" * 32
    assert command.item_proposal_id == "itemproposal_" + "3" * 32
    assert command.item_number == 7
    assert command.content_pack_release_id == "packrel_" + "5" * 32
    assert command.primary_taxonomy_ref is None
    assert command.difficulty_band is None
    assert service.learning.promote_and_schedule.call_args.kwargs == {
        "risk_policy_revision_id": "analysisriskrev_" + "6" * 32,
        "preset_pin": _pin(),
    }
    replay = LegacyItemAutomaticLearningService._promotion_request(
        _candidate(),
        content_pack_release_id="packrel_" + "5" * 32,
    )
    assert command == replay


def test_automatic_learning_creates_one_fresh_successor_before_new_items() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    _without_graph(service)
    service._active_analyses = cast(Any, tuple)
    service._retryable_analysis = cast(
        Any,
        lambda: ("analysisrun_" + "4" * 32, "operator_owner"),
    )
    service._candidate = Mock()
    _guard(service)

    assert service.advance_once() is True

    service.learning.retry_failed_analysis.assert_called_once_with(
        predecessor_analysis_run_id="analysisrun_" + "4" * 32,
        requested_by="operator_owner",
    )
    service._candidate.assert_not_called()


def test_allowlisted_terminal_reaches_real_retry_selector_in_explicit_order() -> None:
    first = "analysisrun_" + "1" * 32
    second = "analysisrun_" + "2" * 32
    engine, service = _query_backed_service((second, first))
    try:
        _insert_terminal(engine, ordinal=1, analysis_run_id=first)
        _insert_terminal(engine, ordinal=2, analysis_run_id=second)

        assert service.advance_once() is True

        service.learning.retry_failed_analysis.assert_called_once_with(
            predecessor_analysis_run_id=second,
            requested_by="operator-2",
        )
        service._candidate.assert_not_called()
    finally:
        engine.dispose()


def test_unallowlisted_terminal_real_selector_fail_stops_without_side_effect() -> None:
    allowed = "analysisrun_" + "1" * 32
    unexpected = "analysisrun_" + "9" * 32
    engine, service = _query_backed_service((allowed,))
    try:
        _insert_terminal(engine, ordinal=9, analysis_run_id=unexpected, state="REJECTED")

        with pytest.raises(RuntimeError, match="terminal leaf analysis"):
            service.advance_once()

        service.learning.retry_failed_analysis.assert_not_called()
        service.learning.promote_and_schedule.assert_not_called()
        service.analyses.reconcile.assert_not_called()
        service.analyses.accept_validated_without_review.assert_not_called()
        service._candidate.assert_not_called()
    finally:
        engine.dispose()


def test_service_rejects_duplicate_retry_allowlist_before_query_or_side_effect() -> None:
    duplicate = "analysisrun_" + "1" * 32
    with pytest.raises(ValueError, match="retry identities must be unique"):
        LegacyItemAutomaticLearningService(
            Mock(),
            extraction_batch_ids=("legacybatch_" + "1" * 32,),
            retry_analysis_run_ids=(duplicate, duplicate),
            content_pack_release_id="packrel_" + "2" * 32,
            risk_policy_revision_id="analysisriskrev_" + "3" * 32,
            preset_pin=_pin(),
            graph=None,
            learning=Mock(),
            analyses=Mock(),
        )


def test_automatic_learning_is_idle_without_active_or_unlearned_work() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    _without_graph(service)
    service._active_analyses = cast(Any, tuple)
    service._retryable_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, lambda: None)
    _guard(service)

    assert service.advance_once() is False


def test_automatic_learning_publishes_one_full_graph_batch_before_more_source_work() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service.graph_batch_size = 2
    candidates = (
        LegacyItemGraphCandidate(
            "analysisrun_" + "1" * 32, "operator_owner", "graphrev_" + "1" * 32
        ),
        LegacyItemGraphCandidate(
            "analysisrun_" + "2" * 32, "operator_owner", "graphrev_" + "1" * 32
        ),
    )
    service.graph = Mock()
    service.graph.pending_candidates.return_value = candidates
    service._active_analyses = cast(Any, tuple)
    service._retryable_analysis = Mock()
    service._candidate = Mock()
    _guard(service)

    assert service.advance_once() is True

    service.graph.pending_candidates.assert_called_once_with(limit=2)
    service.graph.publish.assert_called_once_with(candidates)
    service._retryable_analysis.assert_not_called()
    service._candidate.assert_not_called()


def test_automatic_learning_flushes_partial_graph_batch_only_after_source_completion() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service.graph_batch_size = 16
    candidates = (
        LegacyItemGraphCandidate(
            "analysisrun_" + "1" * 32, "operator_owner", "graphrev_" + "1" * 32
        ),
    )
    service.graph = Mock()
    service.graph.pending_candidates.return_value = candidates
    service._active_analyses = cast(Any, tuple)
    service._retryable_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, lambda: None)
    service._source_work_remaining = cast(Any, lambda: False)
    _guard(service)

    assert service.advance_once() is True

    service.graph.publish.assert_called_once_with(candidates)


def test_automation_batch_ids_support_an_explicit_ordered_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "legacybatch_" + "1" * 32
    second = "legacybatch_" + "2" * 32
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS", f"{first},{second}")
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_BATCH_ID", "legacybatch_" + "3" * 32)

    assert _legacy_automation_batch_ids() == (first, second)


def test_automation_batch_ids_reject_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_id = "legacybatch_" + "1" * 32
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS", f"{batch_id},{batch_id}")

    assert _legacy_automation_batch_ids() == ()


def test_retry_analysis_ids_are_an_explicit_ordered_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "analysisrun_" + "1" * 32
    second = "analysisrun_" + "2" * 32
    monkeypatch.setenv(
        "EOM_LEGACY_ITEM_AUTOMATION_RETRY_ANALYSIS_RUN_IDS",
        f"{first},{second}",
    )

    assert _legacy_automation_retry_analysis_run_ids() == (first, second)


def test_retry_analysis_ids_reject_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis_run_id = "analysisrun_" + "1" * 32
    monkeypatch.setenv(
        "EOM_LEGACY_ITEM_AUTOMATION_RETRY_ANALYSIS_RUN_IDS",
        f"{analysis_run_id},{analysis_run_id}",
    )

    assert _legacy_automation_retry_analysis_run_ids() == ()


def test_retry_analysis_ids_share_the_stage_c_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    bounded = tuple(f"analysisrun_{index:032x}" for index in range(32))
    monkeypatch.setenv(
        "EOM_LEGACY_ITEM_AUTOMATION_RETRY_ANALYSIS_RUN_IDS",
        ",".join(bounded),
    )
    assert _legacy_automation_retry_analysis_run_ids() == bounded

    monkeypatch.setenv(
        "EOM_LEGACY_ITEM_AUTOMATION_RETRY_ANALYSIS_RUN_IDS",
        ",".join((*bounded, "analysisrun_" + "f" * 32)),
    )
    assert _legacy_automation_retry_analysis_run_ids() == ()


@pytest.mark.parametrize(("configured", "expected"), [("1", 1), ("8", 8), ("16", 16)])
def test_graph_batch_size_accepts_bounded_values(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
    expected: int,
) -> None:
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_GRAPH_BATCH_SIZE", configured)
    assert _legacy_automation_graph_batch_size() == expected


@pytest.mark.parametrize("configured", ["0", "17", "not-an-integer"])
def test_graph_batch_size_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_GRAPH_BATCH_SIZE", configured)
    assert _legacy_automation_graph_batch_size() is None


def test_automation_preset_pin_requires_every_exact_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "EOM_LEGACY_ITEM_AUTOMATION_PRESET_ID": "execpreset_" + "1" * 32,
        "EOM_LEGACY_ITEM_AUTOMATION_PRESET_REVISION_ID": "execpresetrev_" + "2" * 32,
        "EOM_LEGACY_ITEM_AUTOMATION_PRESET_SHA256": "sha256:" + "3" * 64,
        "EOM_LEGACY_ITEM_AUTOMATION_CAPACITY_POLICY_ID": "capacity_" + "4" * 32,
        "EOM_LEGACY_ITEM_AUTOMATION_CAPACITY_POLICY_REVISION_ID": ("capacityrev_" + "5" * 32),
        "EOM_LEGACY_ITEM_AUTOMATION_CAPACITY_POLICY_SHA256": "sha256:" + "6" * 64,
        "EOM_LEGACY_ITEM_AUTOMATION_CAPACITY_CURRENT_REVISION_ID": ("capacityrev_" + "7" * 32),
        "EOM_LEGACY_ITEM_AUTOMATION_CAPACITY_CURRENT_SHA256": "sha256:" + "8" * 64,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    assert _legacy_automation_preset_pin() == _pin()
    monkeypatch.delenv("EOM_LEGACY_ITEM_AUTOMATION_PRESET_SHA256")
    assert _legacy_automation_preset_pin() is None


def test_terminal_leaf_stops_before_reconcile_graph_retry_or_promotion() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.learning = Mock()
    service.analyses = Mock()
    service.graph = Mock()
    service._terminal_analysis = cast(Any, lambda: ("analysisrun_" + "9" * 32, "FAILED"))
    service._active_analyses = Mock()
    service._retryable_analysis = Mock()
    service._candidate = Mock()
    service.preset_pin = _pin()
    service.learning.preset_pin_guard.return_value = nullcontext()

    with pytest.raises(RuntimeError, match="terminal leaf analysis"):
        service.advance_once()

    service._active_analyses.assert_not_called()
    service.graph.pending_candidates.assert_not_called()
    service._retryable_analysis.assert_not_called()
    service._candidate.assert_not_called()
