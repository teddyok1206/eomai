"""Canonical normalization and hashing for reviewed natural-language guidance."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_MIN_GUIDANCE_LENGTH = 10
_MAX_GUIDANCE_LENGTH = 2_000


class ReviewedAuthoringGuidanceError(ValueError):
    """Raised when reviewed authoring guidance is unsafe or has stale provenance."""


@dataclass(frozen=True, slots=True)
class ReviewedAuthoringGuidance:
    """Normalized guidance paired with the hash of its exact UTF-8 representation."""

    text: str
    sha256: str


def normalize_reviewed_authoring_guidance(value: str) -> str:
    """Return the one canonical text representation used by every boundary."""

    if not isinstance(value, str):
        raise ReviewedAuthoringGuidanceError("authoring guidance must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ReviewedAuthoringGuidanceError(
            "authoring guidance contains a forbidden Unicode character"
        )
    collapsed = " ".join(normalized.split())
    if not _MIN_GUIDANCE_LENGTH <= len(collapsed) <= _MAX_GUIDANCE_LENGTH:
        raise ReviewedAuthoringGuidanceError(
            "authoring guidance must contain 10..2000 normalized characters"
        )
    return collapsed


def validate_reviewed_authoring_guidance(value: str, sha256: str) -> ReviewedAuthoringGuidance:
    """Normalize guidance and fail closed unless its caller-pinned hash matches."""

    normalized = normalize_reviewed_authoring_guidance(value)
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise ReviewedAuthoringGuidanceError("authoring guidance SHA-256 is malformed")
    actual_sha256 = "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual_sha256 != sha256:
        raise ReviewedAuthoringGuidanceError("authoring guidance SHA-256 mismatch")
    return ReviewedAuthoringGuidance(text=normalized, sha256=actual_sha256)
