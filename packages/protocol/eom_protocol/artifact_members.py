"""Storage-neutral immutable Artifact member references."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import Field, field_validator

from eom_protocol.models import ArtifactId, ProtocolModel, RevisionId, Sha256


class ArtifactMemberPointer(ProtocolModel):
    artifact_id: ArtifactId
    artifact_revision_id: RevisionId
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: Sha256

    @field_validator("member_path")
    @classmethod
    def safe_member(cls, value: str) -> str:
        if (
            "\\" in value
            or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("unsafe Artifact member")
        return value
