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


def test_automatic_learning_reconciles_existing_run_before_scheduling_another() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service._active_analysis = cast(
        Any,
        lambda: ("analysisrun_" + "4" * 32, "operator_owner", "RUNNING"),
    )
    service._candidate = cast(Any, lambda: None)
    _guard(service)

    assert service.advance_once() is True

    command = service.analyses.reconcile.call_args.args[0]
    assert command.analysis_run_id == "analysisrun_" + "4" * 32
    assert command.requested_by == "operator_owner"
    service.learning.promote_and_schedule.assert_not_called()


def test_automatic_learning_accepts_validated_review_state_without_human_record() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service._active_analysis = cast(
        Any,
        lambda: ("analysisrun_" + "4" * 32, "operator_owner", "NEEDS_REVIEW"),
    )
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
    service._active_analysis = cast(Any, lambda: None)
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
    service._active_analysis = cast(Any, lambda: None)
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


def test_automatic_learning_is_idle_without_active_or_unlearned_work() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    _without_graph(service)
    service._active_analysis = cast(Any, lambda: None)
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
    service._active_analysis = cast(Any, lambda: None)
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
    service._active_analysis = cast(Any, lambda: None)
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
    service._active_analysis = Mock()
    service._retryable_analysis = Mock()
    service._candidate = Mock()
    service.preset_pin = _pin()
    service.learning.preset_pin_guard.return_value = nullcontext()

    with pytest.raises(RuntimeError, match="terminal leaf analysis"):
        service.advance_once()

    service._active_analysis.assert_not_called()
    service.graph.pending_candidates.assert_not_called()
    service._retryable_analysis.assert_not_called()
    service._candidate.assert_not_called()
