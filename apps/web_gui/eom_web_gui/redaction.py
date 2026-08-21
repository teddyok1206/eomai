"""Output sanitization for operator-visible summaries and logs."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(?:password|secret|token|authorization|database_url|cookie|prompt|result_body|chain.of.thought)",
    re.IGNORECASE,
)
TOKEN_VALUE = re.compile(r"(?:eom_(?:at|rt)_[A-Za-z0-9._-]+|Bearer\s+\S+)", re.IGNORECASE)
SAFE_SCALAR = str | int | float | bool | None


def sanitize_text(value: str, *, maximum: int = 500) -> str:
    return TOKEN_VALUE.sub("[REDACTED]", value)[:maximum]


def sanitize_mapping(value: dict[str, Any]) -> dict[str, SAFE_SCALAR]:
    result: dict[str, SAFE_SCALAR] = {}
    for key, item in value.items():
        if SENSITIVE_KEY.search(str(key)):
            continue
        if isinstance(item, str):
            result[str(key)] = sanitize_text(item)
        elif item is None or isinstance(item, (bool, int, float)):
            result[str(key)] = item
    return result
