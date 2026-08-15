"""Secret and sensitive-path redaction for reports and rendered payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "***REDACTED***"
SLACK_WEBHOOK_ORIGIN = "https://" + "hooks.slack.com"
SENSITIVE_PATTERNS = (
    re.compile(r"https://hooks\.slack\.com/services/[^\s'\"<>]+", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"\bxapp-[A-Za-z0-9-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bOPENAI_API_KEY\s*=\s*[^\s]+", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----"),
    re.compile(r"/mnt/nas(?:/[^\s'\"<>]*)?"),
)


def redact_text(value: str, secrets: Sequence[str] = ()) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTED)
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_value(value: Any, secrets: Sequence[str] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    return value


def masked_webhook_url(configured: bool) -> str:
    return f"{SLACK_WEBHOOK_ORIGIN}/services/***REDACTED***" if configured else "not configured"
