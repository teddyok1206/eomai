"""Immutable manual capability evidence; neither a browser action nor AUTO activation."""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId
from .kakao_archive_binding import KakaoResourceVersion
from .kakao_room_intake import MANUAL_ROOM_EVIDENCE_REF
from .kakao_rooms import ROOM_OBSERVATION_REF
from .models import FrozenModel, Sha256
from .validation import validate_contract

CAPABILITY_VERIFICATION_REF = "eom://schemas/kakao-archive/capability-verification-v1/1.0"


class ConfirmKakaoCapability(FrozenModel):
    schema_version: Literal["kakao-capability-confirmation/1.0"] = (
        "kakao-capability-confirmation/1.0"
    )
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    expected_binding_version: KakaoResourceVersion

    @model_validator(mode="after")
    def closed_request(self) -> Self:
        validate_contract("kakao-capability-verification-v1", self.model_dump(mode="json"))
        return self


class KakaoCapabilityVerification(FrozenModel):
    schema_version: Literal["kakao-capability-verification/1.0"] = (
        "kakao-capability-verification/1.0"
    )
    request: ConfirmKakaoCapability
    request_sha256: Sha256
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    capability_revision_id: str = Field(pattern=r"^kakaocapabilityrev_[0-9a-f]{32}$")
    adapter_release_sha256: Sha256
    room_observation: ArtifactMemberPointer
    manual_proof: ArtifactMemberPointer
    capability_sha256: Sha256

    @model_validator(mode="after")
    def exact_evidence(self) -> Self:
        if self.request_sha256 != sha256_bytes(
            canonical_json_bytes(self.request.model_dump(mode="json"))
        ) or any(
            pointer.schema_ref != schema or pointer.media_type != "application/json"
            for pointer, schema in (
                (self.room_observation, ROOM_OBSERVATION_REF),
                (self.manual_proof, MANUAL_ROOM_EVIDENCE_REF),
            )
        ):
            raise ValueError("KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID")
        validate_contract("kakao-capability-verification-v1", self.model_dump(mode="json"))
        return self
