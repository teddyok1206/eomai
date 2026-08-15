"""Metadata-only projection of untrusted request, result, path, and error values."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePath
from typing import Any

from eom_observe.settings import PrivacySettings

SECRET_PATTERNS = (
    re.compile(r"(?i)(password|secret|token|authorization|cookie|credential)\s*[:=]\s*\S+"),
    re.compile(r"(?i)postgres(?:ql)?://\S+"),
)
SAFE_ENUM_KEYS = {
    "status",
    "protocol_version",
    "task_type",
    "request_name",
    "image_mode",
    "step_key",
    "attempt",
    "workflow_id",
    "step_run_id",
    "job_id",
    "result_schema",
    "schema_version",
    "logical_artifact_id",
    "revision_id",
}


def sanitize_error(value: str | None, max_length: int = 500) -> str | None:
    if value is None:
        return None
    sanitized = value.replace("\n", " ").replace("\r", " ")
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    sanitized = re.sub(r"/(?:home|root|srv|mnt|etc|var)/[^\s,;]+", "[PATH REDACTED]", sanitized)
    return sanitized[:max_length]


def logical_artifact_uri(artifact_id: str, revision_id: str) -> str:
    return f"nas://artifacts/{artifact_id}/{revision_id}"


def shortened_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def sanitize_path(value: str, *, expose: bool = False) -> str:
    if expose:
        return value
    path = PurePath(value)
    if "artifacts" in path.parts:
        index = path.parts.index("artifacts")
        suffix = path.parts[index + 1 : index + 3]
        if len(suffix) == 2:
            return logical_artifact_uri(suffix[0], suffix[1])
    return "[PATH HIDDEN]"


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def metadata_summary(
    value: Any, privacy: PrivacySettings
) -> dict[str, str | int | bool | list[str] | None]:
    size = _json_size(value)
    summary: dict[str, str | int | bool | list[str] | None] = {"payload_bytes": size}
    if size > privacy.max_preview_bytes:
        summary["content"] = f"[CONTENT HIDDEN, length={size}]"
        return summary
    if not isinstance(value, dict):
        summary["content"] = f"[CONTENT HIDDEN, length={size}]"
        return summary
    for key in sorted(SAFE_ENUM_KEYS):
        candidate = value.get(key)
        if isinstance(candidate, str | int | bool) or (candidate is None and key in value):
            text = candidate
            if (
                key == "request_name"
                and isinstance(text, str)
                and not text.startswith("PLACEHOLDER_")
            ):
                text = f"[CONTENT HIDDEN, length={len(text)}]"
            if isinstance(text, str) and len(text) > privacy.max_text_length:
                text = f"[CONTENT HIDDEN, length={len(text)}]"
            summary[key] = text
    idempotency_key = value.get("idempotency_key")
    if isinstance(idempotency_key, str) and idempotency_key:
        summary["idempotency_key_hash"] = shortened_hash(idempotency_key)
    artifact = value.get("artifact")
    if isinstance(artifact, dict):
        for key in ("logical_artifact_id", "revision_id"):
            if isinstance(artifact.get(key), str):
                summary[key] = artifact[key]
    upstream = value.get("upstream_artifacts")
    if isinstance(upstream, list):
        summary["upstream_artifacts"] = [
            str(item.get("logical_artifact_id"))
            for item in upstream[:12]
            if isinstance(item, dict) and item.get("logical_artifact_id")
        ]
    if len(summary) == 1 and size:
        summary["content"] = f"[CONTENT HIDDEN, length={size}]"
    return summary
