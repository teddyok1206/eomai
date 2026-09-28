from eom_workflow_runner.engine import _is_retryable_precommit_agent_failure


def test_route_unavailable_visual_reference_failure_remains_retryable() -> None:
    assert _is_retryable_precommit_agent_failure(
        error_code="WORKER_UNAVAILABLE",
        error_detail="VISUAL_REFERENCE_ROUTE_UNAVAILABLE",
    )


def test_deterministic_visual_reference_failure_is_terminal() -> None:
    for detail in (
        "VISUAL_REFERENCE_DISCOVERY_INVALID",
        "VISUAL_REFERENCE_HANDOFF_INVALID",
        "VISUAL_REFERENCE_IMAGE_INVALID",
        "VISUAL_REFERENCE_INPUT_INVALID",
        "VISUAL_REFERENCE_LICENSE_REJECTED",
        "VISUAL_REFERENCE_OUTPUT_INVALID",
        "VISUAL_REFERENCE_ROUTE_UNDEPLOYED",
        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
        "VISUAL_REFERENCE_SOURCE_REJECTED",
    ):
        assert not _is_retryable_precommit_agent_failure(
            error_code="WORKER_UNAVAILABLE",
            error_detail=detail,
        )


def test_deterministic_evidence_pointer_failure_is_terminal() -> None:
    for detail in (
        "EVIDENCE_DRAFT_POINTER_INVALID",
        "EVIDENCE_DRAFT_POINTER_MISSING",
        "EVIDENCE_DRAFT_POINTER_NOT_LEAF",
        "EVIDENCE_REVIEW_TARGET_SOURCE_INVALID",
        "EVIDENCE_REVIEW_TARGET_SOURCE_MISSING",
    ):
        assert not _is_retryable_precommit_agent_failure(
            error_code="WORKER_RESULT_INVALID",
            error_detail=detail,
        )


def test_non_retryable_worker_code_stays_terminal() -> None:
    assert not _is_retryable_precommit_agent_failure(
        error_code="WORKFLOW_INPUT_INVALID",
        error_detail=None,
    )
