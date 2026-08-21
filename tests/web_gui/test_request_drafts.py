from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_web_gui.contracts import RequestDraftInput, RequestDraftUpdate
from eom_web_gui.request_drafts import (
    DEMO_REQUEST,
    normalize_request,
    quality_policy,
    update_draft,
    workflow_start_payload,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def test_demo_request_normalization_is_deterministic_and_structured() -> None:
    first = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="1" * 32
    )
    second = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="2" * 32
    )
    assert first.subject == second.subject == "물리학"
    assert first.topic == second.topic == "2차원 포물선 운동"
    assert first.task_type == "calculation"
    assert first.equation_required is True
    assert first.image_required is False
    assert first.choice_count == 5
    assert first.original_request_sha256 == second.original_request_sha256


def test_request_text_is_not_raw_workflow_prompt() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="3" * 32
    )
    payload = workflow_start_payload(draft)
    assert payload["request_name"] == "PLACEHOLDER_REQUEST"
    assert DEMO_REQUEST not in str(payload)
    assert "model" not in payload and "reasoning" not in payload


def test_quality_profile_is_closed_policy_mapping() -> None:
    assert quality_policy("fast")["policy_key"] == "economy"
    assert quality_policy("balanced")["policy_key"] == "balanced"
    assert quality_policy("deep")["policy_key"] == "thorough"
    with pytest.raises(ValueError):
        quality_policy("raw-model")


def test_draft_update_preserves_identity_and_source_hash() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="4" * 32
    )
    updated = update_draft(
        draft,
        RequestDraftUpdate(
            subject="물리학",
            topic="포물체 운동",
            task_type="calculation",
            difficulty="hard",
            choice_count=4,
            equation_required=True,
            image_required=True,
            quality_profile="deep",
        ),
        now=NOW,
    )
    assert updated.request_draft_id == draft.request_draft_id
    assert updated.original_request_sha256 == draft.original_request_sha256
    assert updated.topic == "포물체 운동"


def test_draft_validation_rejects_unbounded_choice_count() -> None:
    with pytest.raises(ValidationError):
        RequestDraftUpdate(
            subject="물리학",
            topic="운동",
            task_type="calculation",
            difficulty="medium",
            choice_count=20,
            equation_required=True,
            image_required=False,
            quality_profile="balanced",
        )
