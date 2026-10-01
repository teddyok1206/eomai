"""Opaque pagination values shared by read-only Application API projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from eom_api.errors import ApiError


@dataclass(frozen=True)
class PageResult[ViewT]:
    data: tuple[ViewT, ...]
    next_cursor: str | None
    has_more: bool


class CursorCodec:
    """Authenticate bounded cursor values without exposing database pagination details."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def encode(self, resource: str, created_at: datetime, resource_id: str) -> str:
        payload = json.dumps(
            {"r": resource, "t": created_at.isoformat(), "i": resource_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return self._b64(payload + signature)

    def decode(self, cursor: str, resource: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if value["r"] != resource or not isinstance(value["i"], str):
                raise ValueError
            timestamp = datetime.fromisoformat(value["t"])
            if timestamp.tzinfo is None:
                raise ValueError
            return timestamp, value["i"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The pagination cursor is invalid for this resource.",
            ) from exc

    def encode_ordinal(self, resource: str, aggregate_id: str, ordinal: int) -> str:
        payload = json.dumps(
            {"r": resource, "a": aggregate_id, "o": ordinal},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return self._b64(payload + signature)

    def decode_ordinal(self, cursor: str, resource: str, aggregate_id: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            ordinal = value["o"]
            if (
                value["r"] != resource
                or value["a"] != aggregate_id
                or not isinstance(ordinal, int)
                or isinstance(ordinal, bool)
                or ordinal < 0
            ):
                raise ValueError
            return ordinal
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The pagination cursor is invalid for this resource.",
            ) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
