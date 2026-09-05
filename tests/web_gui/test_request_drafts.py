from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_web_gui.contracts import DraftSubmission, RequestDraftInput, RequestDraftUpdate
from eom_web_gui.request_drafts import (
    DEMO_REQUEST,
    normalize_request,
    quality_policy,
    update_draft,
    workflow_start_payload,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
INTAKE_ID = "intake_00000000000000000000000000000001"


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
    assert first.image_required is True
    assert first.choice_count == 5
    assert first.knowledge_grounding is False
    assert first.curriculum_selected_unit_key is None
    assert first.authoring_guidance == DEMO_REQUEST
    assert first.authoring_guidance_sha256 == f"sha256:{first.original_request_sha256}"
    assert first.original_request_sha256 == second.original_request_sha256
    assert first.draft_spec_sha256 == second.draft_spec_sha256


def test_request_text_becomes_reviewed_bounded_authoring_guidance() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="3" * 32
    )
    payload = workflow_start_payload(draft)
    assert payload["request_name"] == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
    assert payload["definition_version"] == "1.8.0"
    assert payload["image_mode"] == "required"
    assert payload["pack_key"] == "generated-knowledge-item"
    assert payload["execution_preset_key"] == "standard-item"
    assert payload["source_intake_batch_ids"] == []
    brief = payload["item_brief"]
    assert isinstance(brief, dict)
    assert brief["schema_version"] == "3.0"
    assert brief["authoring_guidance"] == DEMO_REQUEST
    assert brief["authoring_guidance_sha256"] == draft.authoring_guidance_sha256
    assert {
        "choice_count",
        "equation_required",
        "image_required",
        "quality_profile",
    }.isdisjoint(brief)
    assert "model" not in payload and "reasoning" not in payload and "slot" not in payload


def test_grounded_content_team_request_does_not_add_visual_or_equation_requirements() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="9" * 32
    )
    grounded = RequestDraftUpdate.model_validate(
        {
            **{
                name: getattr(draft, name)
                for name in RequestDraftUpdate.model_fields
                if name not in {"knowledge_grounding", "curriculum_selected_unit_key"}
            },
            "knowledge_grounding": True,
            "curriculum_selected_unit_key": "eom.is.middle.1-1",
        }
    )
    payload = workflow_start_payload(
        update_draft(draft, grounded, now=NOW),
        graph_corpus_key="integrated-science-textbooks",
    )

    retrieval = payload["educational_retrieval"]
    assert isinstance(retrieval, dict)
    assert retrieval["required_item_elements"] == ["choice"]
    assert payload["image_mode"] == "required"
    brief = payload["item_brief"]
    assert isinstance(brief, dict)
    assert {
        "choice_count",
        "equation_required",
        "image_required",
        "quality_profile",
    }.isdisjoint(brief)


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
            choice_count=5,
            equation_required=True,
            image_required=True,
            quality_profile="deep",
            source_intake_batch_id=INTAKE_ID,
            authoring_guidance="포물체의 수평·수직 운동을 함께 해석하도록 출제한다.",
            knowledge_grounding=False,
            curriculum_selected_unit_key=None,
        ),
        now=NOW,
    )
    assert updated.request_draft_id == draft.request_draft_id
    assert updated.original_request_sha256 == draft.original_request_sha256
    assert updated.topic == "포물체 운동"
    assert updated.source_intake_batch_id == INTAKE_ID
    assert updated.draft_spec_sha256 != draft.draft_spec_sha256


def test_request_draft_rejects_stale_composite_spec_hash() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="7" * 32
    )
    with pytest.raises(ValidationError, match="draft spec SHA-256"):
        type(draft).model_validate(draft.model_dump() | {"topic": "변조된 주제"})


def test_curriculum_selection_changes_composite_spec_hash() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="8" * 32
    )
    values = {
        "subject": draft.subject,
        "topic": draft.topic,
        "task_type": draft.task_type,
        "difficulty": draft.difficulty,
        "quality_profile": draft.quality_profile,
        "authoring_guidance": draft.authoring_guidance,
        "knowledge_grounding": False,
    }
    large = update_draft(
        draft,
        RequestDraftUpdate(**values, curriculum_selected_unit_key="eom.is.large.3"),
        now=NOW,
    )
    middle = update_draft(
        draft,
        RequestDraftUpdate(**values, curriculum_selected_unit_key="eom.is.middle.3-2"),
        now=NOW,
    )
    assert len({draft.draft_spec_sha256, large.draft_spec_sha256, middle.draft_spec_sha256}) == 3


def test_full_spec_hash_fits_submission_idempotency_contract() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="9" * 32
    )
    key = f"studio:{draft.request_draft_id}:{draft.draft_spec_sha256}"
    assert len(key) <= 128
    assert DraftSubmission(idempotency_key=key).idempotency_key == key


def test_workflow_payload_allows_source_free_general_knowledge() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="5" * 32
    )
    payload = workflow_start_payload(draft)
    assert payload["source_intake_batch_ids"] == []
    assert payload["stimulus_asset_key"] is None
    assert "educational_retrieval" not in payload


def test_workflow_payload_exposes_only_bounded_educational_requirement() -> None:
    draft = normalize_request(
        RequestDraftInput(original_request_text=DEMO_REQUEST), now=NOW, token="6" * 32
    )
    draft = update_draft(
        draft,
        RequestDraftUpdate(
            subject="통합과학",
            topic="판구조론과 지각 변동",
            task_type="data_interpretation",
            difficulty="hard",
            quality_profile="deep",
            authoring_guidance="판 경계 자료를 해석하고 지각 변동을 추론하는 문항을 출제한다.",
            knowledge_grounding=True,
            curriculum_selected_unit_key="eom.is.middle.3-2",
        ),
        now=NOW,
    )
    payload = workflow_start_payload(draft, graph_corpus_key="integrated-science-textbooks")
    assert payload["educational_retrieval"] == {
        "schema_version": "educational-retrieval-requirement/1.0",
        "corpus_key": "integrated-science-textbooks",
        "query_kind": "ITEM_PREPARATION",
        "curriculum_root_key": None,
        "topic_keys": [],
        "required_item_elements": ["choice"],
        "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
    }
    assert payload["execution_preset_key"] == "knowledge-grounded-item"
    brief = payload["item_brief"]
    assert isinstance(brief, dict)
    assert brief["curriculum_selected_unit_key"] == "eom.is.middle.3-2"
    serialized = str(payload)
    assert "graph_snapshot_revision_id" not in serialized
    assert "access_policy_revision_id" not in serialized
    assert "storage" not in serialized and "path" not in serialized


def test_draft_grounding_requires_one_reviewed_curriculum_selection() -> None:
    base = {
        "subject": "물리학",
        "topic": "운동",
        "task_type": "calculation",
        "difficulty": "medium",
        "choice_count": 5,
        "equation_required": True,
        "image_required": True,
        "quality_profile": "balanced",
        "authoring_guidance": "운동을 해석하는 계산 문항을 출제한다.",
    }
    with pytest.raises(ValidationError, match="selected curriculum unit"):
        RequestDraftUpdate.model_validate(base | {"knowledge_grounding": True})
    selected = RequestDraftUpdate.model_validate(
        base
        | {
            "knowledge_grounding": False,
            "curriculum_selected_unit_key": "eom.is.middle.3-3",
        }
    )
    assert selected.curriculum_selected_unit_key == "eom.is.middle.3-3"


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
            authoring_guidance="운동을 해석하는 계산 문항을 출제한다.",
        )
