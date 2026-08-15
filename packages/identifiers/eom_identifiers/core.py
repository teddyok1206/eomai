"""Identifier generation and deterministic JSON serialization."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_job_id() -> str:
    return f"job_{uuid4().hex}"


def new_logical_artifact_id() -> str:
    return f"artifact_{uuid4().hex}"


def new_revision_id() -> str:
    return f"rev_{uuid4().hex}"


def new_hwpx_template_id() -> str:
    return f"hwpxtpl_{uuid4().hex}"


def new_hwpx_template_revision_id() -> str:
    return f"hwpxrev_{uuid4().hex}"


def new_hwpx_build_id() -> str:
    return f"hwpxbuild_{uuid4().hex}"


def new_hwpx_validation_id() -> str:
    return f"hwpxval_{uuid4().hex}"


def _canonical_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not allowed in canonical EOM messages")
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def content_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
