"""Typed orchestration failures with stable external error codes."""

from __future__ import annotations

from eom_protocol import ErrorCode


class PlatformError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
