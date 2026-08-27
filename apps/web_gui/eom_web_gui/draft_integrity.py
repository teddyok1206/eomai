"""Canonical normalization and integrity helpers for short-lived Request Drafts.

The guidance representation mirrors the Application API wire contract without importing the
broader Catalog distribution into the isolated Scientific Studio runtime.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from typing import Any

REQUEST_DRAFT_EDITABLE_FIELDS = (
    "subject",
    "topic",
    "item_format",
    "task_type",
    "difficulty",
    "choice_count",
    "equation_required",
    "image_required",
    "quality_profile",
    "source_intake_batch_id",
    "authoring_guidance",
    "knowledge_grounding",
    "curriculum_selected_unit_key",
)


def normalize_authoring_guidance(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("authoring guidance contains a forbidden Unicode character")
    return " ".join(normalized.split())


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def authoring_guidance_sha256(value: str) -> str:
    return f"sha256:{text_sha256(value)}"


def draft_spec_sha256(
    *,
    editable: Mapping[str, object],
    original_request_sha256: str,
) -> str:
    """Hash all reviewed semantics using canonical JSON serialization."""
    canonical: dict[str, Any] = {
        **editable,
        "original_request_sha256": original_request_sha256,
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
