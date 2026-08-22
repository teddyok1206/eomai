"""Deterministic, closed-vocabulary Request Draft normalization."""

from __future__ import annotations

import hashlib
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

DEMO_REQUEST = "물리학에서 2차원 포물선 운동에 관한 계산 문항을 출제해줘."
QUALITY_POLICY = {
    "fast": {"label": "빠름", "policy_key": "economy"},
    "balanced": {"label": "균형", "policy_key": "balanced"},
    "deep": {"label": "심층", "policy_key": "thorough"},
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
    return RequestDraft(
        request_draft_id=f"requestdraft_{token or secrets.token_hex(16)}",
        subject=subject,
        topic=topic,
        item_format="multiple_choice",
        task_type=task_type,
        difficulty="medium",
        choice_count=5,
        equation_required=True,
        image_required=True,
        quality_profile=QualityProfile.BALANCED,
        original_request_text=text,
        original_request_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        created_at=current,
        updated_at=current,
    )


def update_draft(draft: RequestDraft, value: RequestDraftUpdate, *, now: datetime) -> RequestDraft:
    return RequestDraft(
        **value.model_dump(),
        request_draft_id=draft.request_draft_id,
        original_request_text=draft.original_request_text,
        original_request_sha256=draft.original_request_sha256,
        created_at=draft.created_at,
        updated_at=now,
    )


def quality_policy(profile: str) -> dict[str, str]:
    try:
        return dict(QUALITY_POLICY[profile])
    except KeyError as exc:
        raise ValueError("unknown quality profile") from exc


def workflow_start_payload(draft: RequestDraft) -> dict[str, object]:
    """Map a reviewed draft to the source-optional knowledge-item workflow contract."""
    return {
        "definition_key": "generic-item-development",
        "definition_version": "1.4.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "environment": "development",
        "source_intake_batch_ids": [],
        "registry_mode": "CREATE_ITEM",
        "item_id": None,
        "base_revision_id": None,
        "item_brief": {
            "subject": draft.subject,
            "topic": draft.topic,
            "task_type": draft.task_type,
            "difficulty": draft.difficulty,
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": draft.quality_profile,
            "original_request_sha256": draft.original_request_sha256,
        },
        "stimulus_asset_key": None,
    }


def _topic_from_request(text: str) -> str:
    cleaned = re.sub(r"(문항|문제).*$", "", text).strip(" .,?!")
    return cleaned[-160:] or "일반 과학"
