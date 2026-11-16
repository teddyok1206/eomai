"""Shared current-owner and exact-pin checks for accepted collection preparation."""

from eom_catalog_contracts.kakao_capability import CAPABILITY_VERIFICATION_REF
from eom_operator_identity import PermissionKey
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_current_operator
from .kakao_archive_models import KakaoChannelBindingRecord, KakaoCollectionPolicyRevisionRecord
from .kakao_capability_models import KakaoCapabilityAcceptanceRecord
from .kakao_collection_models import KakaoCollectionRunRecord
from .kakao_room_models import KakaoRoomRecord
from .kakao_source_pointers import validate_source_pointer_metadata_batch


def validate_kakao_collection_pins(
    session: Session, row: KakaoCollectionRunRecord
) -> ArtifactMemberPointer:
    capability = session.get(KakaoCapabilityAcceptanceRecord, row.capability_revision_id)
    policy = session.get(KakaoCollectionPolicyRevisionRecord, row.policy_revision_id)
    if (
        capability is None
        or capability.owner_operator_id != row.owner_operator_id
        or capability.source_binding_id != row.source_binding_id
        or capability.room_id != row.anchor_room_id
        or capability.adapter_release_sha256 != row.adapter_release_sha256
        or policy is None
        or policy.source_binding_id != row.source_binding_id
        or policy.sha256 != row.policy_sha256
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_PIN_INVALID")
    pointer = ArtifactMemberPointer(
        artifact_id=capability.manifest_artifact_id,
        artifact_revision_id=capability.manifest_artifact_revision_id,
        member_path="verification.json",
        schema_ref=CAPABILITY_VERIFICATION_REF,
        media_type="application/json",
        sha256=capability.manifest_sha256,
    )
    validate_source_pointer_metadata_batch(session, (pointer,))
    return pointer


def authorize_kakao_collection_preparation(
    session: Session, row: KakaoCollectionRunRecord, *, adapter_release_sha256: str
) -> ArtifactMemberPointer:
    """Owner is read from an accepted row; this is not actual capture/source authority."""
    for permission in (PermissionKey.KAKAO_ARCHIVE_READ, PermissionKey.KAKAO_ARCHIVE_COLLECT):
        authorize_kakao_current_operator(
            session, operator_id=row.owner_operator_id, permission=permission, admin_only=True
        )
    binding = session.get(KakaoChannelBindingRecord, row.source_binding_id)
    if binding is None or binding.owner_operator_id != row.owner_operator_id:
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    if binding.state == "RETIRED":
        raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
    if row.state in {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}:
        raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_TERMINAL")
    if binding.current_policy_revision_id != row.policy_revision_id:
        raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_POLICY_CHANGED")
    if row.adapter_release_sha256 != adapter_release_sha256:
        raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_ADAPTER_CHANGED")
    pointer = validate_kakao_collection_pins(session, row)
    room = session.get(KakaoRoomRecord, row.anchor_room_id)
    if (
        room is None
        or room.owner_operator_id != row.owner_operator_id
        or room.source_binding_id != row.source_binding_id
        or room.state != "ACTIVE"
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
    return pointer
