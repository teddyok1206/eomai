"""Public input DTOs reuse the Catalog-owned bounded capture contract."""

from eom_catalog_contracts.kakao_capture_intake import (
    ConfirmKakaoManualCapture,
    KakaoManualCapturePage,
)

__all__ = ["ConfirmKakaoManualCapture", "KakaoManualCapturePage"]
