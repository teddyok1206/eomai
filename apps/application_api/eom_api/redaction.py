"""Non-reversible request fingerprints and defensive text redaction."""

from __future__ import annotations

import hashlib
import hmac
import re

TOKEN = re.compile(r"eom_(?:at|rt)_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
SECRET_FIELD = re.compile(r"(?i)(password|authorization|token|idempotency[-_ ]?key)")


def fingerprint(key: bytes, value: str | None) -> str | None:
    if not value:
        return None
    return "sha256:" + hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def redact_text(value: str) -> str:
    sanitized = TOKEN.sub("[REDACTED_TOKEN]", value)
    return "[REDACTED]" if SECRET_FIELD.search(sanitized) else sanitized[:1000]
