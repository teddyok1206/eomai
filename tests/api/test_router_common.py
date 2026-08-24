from __future__ import annotations

from enum import StrEnum

from eom_api.routers.common import _domain_error_code


class _Code(StrEnum):
    POINTER_STALE = "POINTER_STALE"


class _DomainError(RuntimeError):
    def __init__(self, code: str | _Code | None = None, error_code: str | None = None) -> None:
        super().__init__("bounded test failure")
        self.code = code
        self.error_code = error_code


def test_domain_error_code_preserves_string_and_enum_codes() -> None:
    assert _domain_error_code(_DomainError("KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH")) == (
        "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH"
    )
    assert _domain_error_code(_DomainError(_Code.POINTER_STALE)) == "POINTER_STALE"


def test_domain_error_code_uses_bounded_fallback() -> None:
    assert _domain_error_code(_DomainError(error_code="CATALOG_UNAVAILABLE")) == (
        "CATALOG_UNAVAILABLE"
    )
    assert _domain_error_code(RuntimeError("unclassified")) == "DOMAIN_COMMAND_FAILED"
