"""Source authorization adapter boundary, never a worker/public permission DTO."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.kakao_source import KakaoSourceAdmission
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy.orm import Session

from .kakao_archive_authorization import authorize_kakao_actor, authorize_kakao_room_scope

SourceAdmissionAuthorizer = Callable[[Session, ActorContext, KakaoSourceAdmission], None]


class KakaoSourceAuthorization(Protocol):
    """Trusted composition port: actual API authentication or a scoped accepted run."""

    def authorize_operator(self, session: Session, permission: PermissionKey) -> str: ...

    def authorize_room(
        self, session: Session, binding: str, room: str, permission: PermissionKey, *, lock: bool
    ) -> str: ...

    def authorize_capture(self, session: Session, admission: KakaoSourceAdmission) -> None: ...


type KakaoSourcePrincipal = ActorContext | KakaoSourceAuthorization


@dataclass(frozen=True, slots=True)
class ApiKakaoSourceAuthorization:
    actor: ActorContext
    capture_authorizer: SourceAdmissionAuthorizer

    def authorize_operator(self, session: Session, permission: PermissionKey) -> str:
        return authorize_kakao_actor(session, self.actor, permission, now=datetime.now(UTC))

    def authorize_room(
        self, session: Session, binding: str, room: str, permission: PermissionKey, *, lock: bool
    ) -> str:
        owner, _ = authorize_kakao_room_scope(
            session, self.actor, binding, room, permission, lock=lock
        )
        return owner

    def authorize_capture(self, session: Session, admission: KakaoSourceAdmission) -> None:
        self.capture_authorizer(session, self.actor, admission)


def source_authorization(
    principal: KakaoSourcePrincipal, capture_authorizer: SourceAdmissionAuthorizer
) -> KakaoSourceAuthorization:
    if isinstance(principal, ActorContext):
        return ApiKakaoSourceAuthorization(principal, capture_authorizer)
    return principal
