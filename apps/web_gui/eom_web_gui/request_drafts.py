"""Deterministic, closed-vocabulary Request Draft normalization."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Literal

from eom_web_gui.contracts import (
    QualityProfile,
    RequestDraft,
    RequestDraftInput,
    RequestDraftUpdate,
)
from eom_web_gui.draft_integrity import (
    authoring_guidance_sha256,
    draft_spec_sha256,
    normalize_authoring_guidance,
    text_sha256,
)

DEMO_REQUEST = "물리학에서 2차원 포물선 운동에 관한 계산 문항을 출제해줘."
STANDARD_EXECUTION_PRESET_KEY = "standard-item"
KNOWLEDGE_EXECUTION_PRESET_KEY = "knowledge-grounded-item"
QUALITY_POLICY = {
    "fast": {"label": "빠름", "policy_key": "economy"},
    "balanced": {"label": "균형", "policy_key": "balanced"},
    "deep": {"label": "심층", "policy_key": "thorough"},
}


def _compact(value: str) -> str:
    return normalize_authoring_guidance(re.sub(r"\s+", " ", value))


def normalize_request(
    value: RequestDraftInput, *, now: datetime | None = None, token: str | None = None
) -> RequestDraft:
    text = _compact(value.original_request_text)
    if len(text) < 10:
        raise ValueError("request text is too short after normalization")
    lowered = text.casefold()
    subject = "물리학" if "물리" in lowered else "일반 과학"
    topic = "2차원 포물선 운동" if "포물선" in lowered else _topic_from_request(text)
    task_type: Literal["calculation", "conceptual"] = (
        "calculation" if any(word in lowered for word in ("계산", "구하", "값")) else "conceptual"
    )
    current = now or datetime.now(UTC)
    guidance_sha256 = authoring_guidance_sha256(text)
    editable: dict[str, object] = {
        "subject": subject,
        "topic": topic,
        "item_format": "multiple_choice",
        "task_type": task_type,
        "difficulty": "medium",
        "choice_count": 5,
        "equation_required": True,
        "image_required": True,
        "quality_profile": QualityProfile.BALANCED,
        "source_intake_batch_id": None,
        "authoring_guidance": text,
        "knowledge_grounding": False,
        "curriculum_selected_unit_key": None,
    }
    original_sha256 = text_sha256(text)
    return RequestDraft.model_validate(
        {
            **editable,
            "request_draft_id": f"requestdraft_{token or secrets.token_hex(16)}",
            "original_request_text": text,
            "original_request_sha256": original_sha256,
            "authoring_guidance_sha256": guidance_sha256,
            "draft_spec_sha256": draft_spec_sha256(
                editable=editable,
                original_request_sha256=original_sha256,
            ),
            "created_at": current,
            "updated_at": current,
        }
    )


def update_draft(draft: RequestDraft, value: RequestDraftUpdate, *, now: datetime) -> RequestDraft:
    editable = value.model_dump()
    guidance_sha256 = authoring_guidance_sha256(value.authoring_guidance)
    return RequestDraft.model_validate(
        {
            **editable,
            "request_draft_id": draft.request_draft_id,
            "original_request_text": draft.original_request_text,
            "original_request_sha256": draft.original_request_sha256,
            "authoring_guidance_sha256": guidance_sha256,
            "draft_spec_sha256": draft_spec_sha256(
                editable=editable,
                original_request_sha256=draft.original_request_sha256,
            ),
            "created_at": draft.created_at,
            "updated_at": now,
        }
    )


def quality_policy(profile: str) -> dict[str, str]:
    try:
        return dict(QUALITY_POLICY[profile])
    except KeyError as exc:
        raise ValueError("unknown quality profile") from exc


def workflow_start_payload(
    draft: RequestDraft, *, graph_corpus_key: str | None = None
) -> dict[str, object]:
    """Map a reviewed draft to the source-optional knowledge-item workflow contract."""
    payload: dict[str, object] = {
        "definition_key": "generic-item-development",
        "definition_version": "1.8.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "execution_preset_key": (
            KNOWLEDGE_EXECUTION_PRESET_KEY
            if draft.knowledge_grounding
            else STANDARD_EXECUTION_PRESET_KEY
        ),
        "environment": "development",
        "source_intake_batch_ids": [],
        "registry_mode": "CREATE_ITEM",
        "item_id": None,
        "base_revision_id": None,
        "item_brief": {
            "schema_version": "3.0",
            "subject": draft.subject,
            "topic": draft.topic,
            "task_type": draft.task_type,
            "difficulty": draft.difficulty,
            "original_request_sha256": draft.original_request_sha256,
            "authoring_guidance": draft.authoring_guidance,
            "authoring_guidance_sha256": draft.authoring_guidance_sha256,
            "curriculum_selected_unit_key": draft.curriculum_selected_unit_key,
        },
        "stimulus_asset_key": None,
    }
    if draft.knowledge_grounding:
        assert draft.curriculum_selected_unit_key is not None
        if (
            graph_corpus_key is None
            or re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", graph_corpus_key) is None
        ):
            raise ValueError("Graph grounding requires the API-verified production corpus")
        payload["educational_retrieval"] = {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": graph_corpus_key,
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": None,
            "topic_keys": [],
            "required_item_elements": ["choice"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        }
    return payload


def _topic_from_request(text: str) -> str:
    cleaned = re.sub(r"(문항|문제).*$", "", text).strip(" .,?!")
    return cleaned[-160:] or "일반 과학"
