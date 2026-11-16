"""Public binding values reuse the authoritative small immutable Catalog contract.

The HTTP layer adds its existing authentication, envelope and ETag headers. It does
not duplicate binding rules or accept a browser-supplied operator/profile identity.
"""

from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCommand,
    KakaoBindingCreate,
    KakaoBindingMutation,
    KakaoBindingPage,
    KakaoSourceBinding,
)

__all__ = [
    "KakaoBindingCommand",
    "KakaoBindingCreate",
    "KakaoBindingMutation",
    "KakaoBindingPage",
    "KakaoSourceBinding",
]
