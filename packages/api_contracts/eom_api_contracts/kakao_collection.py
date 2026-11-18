"""Public selection and view: no provider keys, runtime pins or source content."""

from eom_catalog_contracts.kakao_archive_binding import KakaoPolicyRevisionId
from eom_catalog_contracts.kakao_capability import ConfirmKakaoCapability
from eom_catalog_contracts.kakao_collection import KakaoCollectionStatus
from eom_catalog_contracts.models import FrozenModel


class KakaoRoomCollectionSelection(FrozenModel):
    selection: ConfirmKakaoCapability
    expected_policy_revision_id: KakaoPolicyRevisionId


__all__ = ["KakaoCollectionStatus", "KakaoRoomCollectionSelection"]
