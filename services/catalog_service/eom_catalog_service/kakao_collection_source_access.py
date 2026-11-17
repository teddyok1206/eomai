"""One accepted capture's durable source authority, not authentication or worker input."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from eom_catalog_contracts.kakao_collection_attempt import KakaoCollectionAttempt
from eom_catalog_contracts.kakao_source import KakaoSourceAdmission
from eom_operator_identity import PermissionKey
from sqlalchemy.orm import Session

from .kakao_archive_authorization import KakaoArchiveError, read_owned_kakao_room_scope
from .kakao_room_models import KakaoRoomRecord

if TYPE_CHECKING:
    from .kakao_collection_attempt_service import KakaoCollectionAttemptService


@dataclass(frozen=True, slots=True)
class KakaoCollectionSourceAccess:
    service: KakaoCollectionAttemptService = field(repr=False, compare=False)
    attempt: KakaoCollectionAttempt
    owner_operator_id: str

    def authorize_operator(self, session: Session, permission: PermissionKey) -> str:
        return self.service.authorize_accepted_capture(session, self, permission)

    def authorize_room(
        self, session: Session, binding: str, room: str, permission: PermissionKey, *, lock: bool
    ) -> tuple[str, KakaoRoomRecord]:
        if (binding, room) != (self.attempt.source_binding_id, self.attempt.room_id):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
        owner = self.authorize_operator(session, permission)
        return owner, read_owned_kakao_room_scope(session, owner, binding, room, lock=lock)

    def authorize_capture(self, session: Session, admission: KakaoSourceAdmission) -> None:
        self.service.authorize_accepted_source(session, self, admission)
