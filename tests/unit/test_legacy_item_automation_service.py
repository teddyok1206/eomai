from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_item_automation_service import (
    LegacyItemAutomaticLearningService,
    _LearningCandidate,
)


def _candidate() -> _LearningCandidate:
    return _LearningCandidate(
        acceptance_id="itemacceptance_" + "1" * 32,
        acceptance_sha256="sha256:" + "2" * 64,
        item_proposal_id="itemproposal_" + "3" * 32,
        item_number=7,
        requested_by="operator_batch_owner",
    )


def test_automatic_learning_reconciles_existing_run_before_scheduling_another() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service.analyses = Mock()
    service.learning = Mock()
    service._active_analysis = cast(
        Any,
        lambda: ("analysisrun_" + "4" * 32, "operator_owner", "RUNNING"),
    )
    service._candidate = cast(Any, lambda: None)

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
    service._active_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, _candidate)

    assert service.advance_once() is True

    command = service.learning.promote_and_schedule.call_args.args[0]
    assert command.acceptance_id == "itemacceptance_" + "1" * 32
    assert command.item_proposal_id == "itemproposal_" + "3" * 32
    assert command.item_number == 7
    assert command.content_pack_release_id == "packrel_" + "5" * 32
    assert command.primary_taxonomy_ref is None
    assert command.difficulty_band is None
    assert service.learning.promote_and_schedule.call_args.kwargs == {
        "risk_policy_revision_id": "analysisriskrev_" + "6" * 32
    }
    replay = LegacyItemAutomaticLearningService._promotion_request(
        _candidate(),
        content_pack_release_id="packrel_" + "5" * 32,
    )
    assert command == replay


def test_automatic_learning_is_idle_without_active_or_unlearned_work() -> None:
    service = object.__new__(LegacyItemAutomaticLearningService)
    service._active_analysis = cast(Any, lambda: None)
    service._candidate = cast(Any, lambda: None)

    assert service.advance_once() is False
